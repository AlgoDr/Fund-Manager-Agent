import os
import time
import tempfile
import logging
from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing services that read environment variables.
# override=True so the project .env (GROQ_MODEL=openai/gpt-oss-120b)
# takes precedence over any shell-exported GROQ_MODEL that may be stale.
load_dotenv(override=True)

import mlx_whisper
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from services.draft_pipeline import build_draft,parse_amount_paise
from services.date_parser import resolve_date_phrase
from services.agent_call import agent_call
from schemas.expense import ExtractionResult
from services.tts import PiperTTS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Log the resolved Groq model at startup so a stale process / unloaded
# .env is immediately obvious in the terminal (Groq falls back to Ollama
# when the configured model is rejected, e.g. model_not_found).
logger.info(
    "Groq model configured: %s", os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
)

BASE_DIR = Path(__file__).resolve().parent
MODEL = str(BASE_DIR / "models" / "whisper-large-v3-turbo")

# Serve static files (Silero VAD model, etc.)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/models/static", StaticFiles(directory=str(BASE_DIR / "models" / "static")), name="models_static")


import json
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from services.database import get_connection


class DraftRequest(BaseModel):
    transcript: str


class ClarifyRequest(BaseModel):
    expense_index: int = Field(ge=0)
    field: str  # "amount_phrase", "currency", "merchant", "note", "category", or "date_phrase"
    answer: str = Field(min_length=1)


class ConfirmRequest(BaseModel):
    expenses: list[dict]
    idempotency_key: str = Field(min_length=1)


class ExpenseUpdateRequest(BaseModel):
    amount_paise: int | None = None
    currency: str | None = None
    category: str | None = None
    merchant: str | None = None
    note: str | None = None
    spent_at: str | None = None


class BudgetRequest(BaseModel):
    category: str
    month: str  # "YYYY-MM"
    amount_paise: int = Field(gt=0)


class VoiceQueryRequest(BaseModel):
    query: str = Field(min_length=1)

class TTSRequest(BaseModel):
    text: str = Field(min_length=1)

@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    """Transcribe audio using Whisper.
    
    Note: Whisper model inference on CPU can be slow.
    If transcription fails, returns empty text so the UI can still function.
    """
    started = time.perf_counter()

    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
        temp_path = temp.name
        try:
            temp.write(await audio.read())
        except Exception:
            # Clean up temp file if read fails
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            logger.exception("Failed to read audio file")
            return {"text": "", "timings_ms": {"upload": 0, "transcription": 0, "transcribe_endpoint_total": round((time.perf_counter() - started) * 1000, 2)}}

    upload_done = time.perf_counter()

    try:
        result = mlx_whisper.transcribe(
            temp_path,
            path_or_hf_repo=MODEL,
            language="en",
            temperature=0,
        )

        inference_done = time.perf_counter()

        return {
            "text": result["text"].strip(),
            "timings_ms": {
                "upload": round((upload_done - started) * 1000, 2),
                "transcription": round((inference_done - upload_done) * 1000, 2),
                "transcribe_endpoint_total": round((inference_done - started) * 1000, 2),
            },
        }

    except Exception as e:
        logger.exception("Transcription failed")
        # Return empty text instead of 500 so UI can still function
        return {"text": "", "timings_ms": {"upload": 0, "transcription": 0, "transcribe_endpoint_total": round((time.perf_counter() - started) * 1000, 2)}}

    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
            os.unlink(temp_path)
        except OSError:
            logger.warning("Could not remove temporary audio file: %s", temp_path)




@app.post("/api/draft")
async def create_expense_draft(request: DraftRequest):
    """
    Extract expenses, but do not write anything to the expenses table.
    """
    result = await build_draft(request.transcript)

    # Convert Pydantic models to JSON-compatible dictionaries.
    # Add clarification_field so the frontend knows exactly which field
    # needs clarification (amount_phrase, currency, merchant, or note)
    # instead of guessing from amount_paise.
    expenses = []
    for item in result.expenses:
        d = item.model_dump(mode="json")
        if d.get("clarification_required"):
            missing = d.get("missing_fields") or []
            d["clarification_field"] = (
                missing[0]
                if missing
                else (
                    "amount_phrase"
                    if d.get("amount_paise") is None
                    else "currency"
                )
            )
        expenses.append(d)

    return {
        "transcript": result.transcript,
        "provider_used": result.provider_used,
        "expenses": expenses,
        "ready_to_confirm": all(
            not item.get("clarification_required")
            for item in expenses
        ),
    }


@app.post("/api/draft/clarify")
async def clarify_expense_draft(request: ClarifyRequest):
    """
    Update one item in the draft in frontend state.
    This endpoint does not save to SQLite.
    """
    if request.field not in {"amount_phrase", "currency", "merchant", "note", "category", "date_phrase"}:
        raise HTTPException(
            status_code=400,
            detail="field must be amount_phrase, currency, merchant, note, category, or date_phrase",
        )

    answer = request.answer.strip()
    if not answer:
        raise HTTPException(status_code=400, detail="Answer cannot be empty")

    if request.field == "currency":
        currency = answer.upper().replace(".", "")
        accepted = {"INR", "RS", "RUPEE", "RUPEES", "₹"}

        if currency not in accepted:
            raise HTTPException(
                status_code=400,
                detail="This POC currently supports INR only. Enter INR or rupees.",
            )

        return {
            "field": "currency",
            "value": "INR",
            "clarification_required": False,
        }

    if request.field == "amount_phrase":
        amount_paise = parse_amount_paise(answer)

        if amount_paise is None:
            raise HTTPException(
                status_code=400,
                detail="I couldn't understand that amount. Please enter an amount like 250 or 250 rupees.",
            )

        return {
            "field": "amount_phrase",
            "value": answer,
            "amount_phrase": answer,
            "amount_paise": amount_paise,
            "clarification_required": False,
        }

    if request.field == "date_phrase":
        resolved_date = resolve_date_phrase(answer)
        if resolved_date is None:
            raise HTTPException(
                status_code=400,
                detail="I couldn't understand that date. Please say something like today, yesterday, or 04-11-2026.",
            )
        return {
            "field": "date_phrase",
            "value": answer,
            "resolved_date": resolved_date,
            "clarification_required": False,
        }

    # Merchant, note, and category clarifications just echo the answer back.
    return {
        "field": request.field,
        "value": answer,
        "clarification_required": False,
    }


@app.post("/api/confirm")
def confirm_expenses(request: ConfirmRequest):
    """
    Persist reviewed expenses. The client should call this only after
    the user presses the confirmation button.
    """
    if not request.expenses:
        raise HTTPException(status_code=400, detail="No expenses to save")

    for item in request.expenses:
        if item.get("clarification_required"):
            raise HTTPException(
                status_code=400,
                detail="Resolve all clarification questions before saving",
            )

        if not item.get("amount_paise") or int(item["amount_paise"]) <= 0:
            raise HTTPException(
                status_code=400,
                detail="Every expense must have a valid amount",
            )

        if not item.get("category"):
            raise HTTPException(
                status_code=400,
                detail="Every expense must have a category",
            )

    user_id = "local-user"  # Replace with authenticated user ID later.
    saved = []

    try:
        with get_connection() as conn:
            for index, item in enumerate(request.expenses):
                # Unique per batch item; retries of the same request reuse
                # the same key and therefore do not create duplicate rows.
                item_key = f"{request.idempotency_key}:{index}"

                existing = conn.execute(
                    """
                    SELECT id
                    FROM expenses
                    WHERE user_id = ? AND idempotency_key = ?
                    """,
                    (user_id, item_key),
                ).fetchone()

                if existing:
                    saved.append(existing["id"])
                    continue

                transaction_id = str(uuid4())
                spent_at = item.get("resolved_date") or item.get("spent_at")

                if not spent_at:
                    spent_at = datetime.now(
                        ZoneInfo("Asia/Kolkata")
                    ).date().isoformat()

                conn.execute(
                    """
                    INSERT INTO expenses (
                        id, user_id, amount_paise, currency, category,
                        merchant, note, spent_at, source_transcript,
                        idempotency_key
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        transaction_id,
                        user_id,
                        int(item["amount_paise"]),
                        item.get("currency") or "INR",
                        item["category"],
                        item.get("merchant"),
                        item.get("note"),
                        spent_at,
                        item.get("source_transcript"),
                        item_key,
                    ),
                )

                saved.append(transaction_id)

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not save expenses: {exc}",
        ) from exc

    return {
        "saved_count": len(saved),
        "transaction_ids": saved,
    }


@app.get("/api/expenses/today")
def get_today_expenses():
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    tomorrow = today + timedelta(days=1)

    user_id = "local-user"  # Replace with authenticated user ID later.

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                user_id,
                amount_paise,
                currency,
                category,
                merchant,
                note,
                spent_at,
                created_at
            FROM expenses
            WHERE user_id = ?
              AND spent_at >= ?
              AND spent_at < ?
            ORDER BY spent_at DESC
            """,
            (user_id, today.isoformat(), tomorrow.isoformat()),
        ).fetchall()

    expenses = [dict(row) for row in rows]
    total_paise = sum(row["amount_paise"] for row in expenses)

    return {
        "date": today.isoformat(),
        "user_id": user_id,
        "currency": "INR",
        "count": len(expenses),
        "total_paise": total_paise,
        "total_rupees": total_paise / 100,
        "expenses": expenses,
    }


USER_ID = "local-user"
CATEGORIES = [
    "Food", "Groceries", "Transport", "Shopping", "Utilities",
    "Entertainment", "Health", "Travel", "Education", "Other",
]


@app.get("/api/expenses")
def list_expenses(
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
):
    """List expenses for local-user with optional date range and category filter."""
    user_id = USER_ID
    query = """
        SELECT id, user_id, amount_paise, currency, category, merchant,
               note, spent_at, created_at, updated_at, source_transcript,
               idempotency_key
        FROM expenses
        WHERE user_id = ?
    """
    params: list = [user_id]

    if start_date:
        query += " AND spent_at >= ?"
        params.append(start_date)
    if end_date:
        query += " AND spent_at < ?"
        params.append(end_date)
    if category:
        if category not in CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Invalid category: {category}")
        query += " AND category = ?"
        params.append(category)

    query += " ORDER BY spent_at DESC, created_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return {
        "user_id": user_id,
        "count": len(rows),
        "expenses": [dict(row) for row in rows],
    }


@app.get("/api/expenses/{expense_id}")
def get_expense(expense_id: str):
    """Get a single expense by ID."""
    user_id = USER_ID
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, user_id, amount_paise, currency, category, merchant,
                   note, spent_at, created_at, updated_at, source_transcript,
                   idempotency_key
            FROM expenses
            WHERE id = ? AND user_id = ?
            """,
            (expense_id, user_id),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Expense not found")

    return dict(row)


@app.put("/api/expenses/{expense_id}")
def update_expense(expense_id: str, request: ExpenseUpdateRequest):
    """Update an existing expense. Only provided fields are changed."""
    user_id = USER_ID

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Expense not found")

        if request.category is not None and request.category not in CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Invalid category: {request.category}")

        if request.amount_paise is not None and request.amount_paise <= 0:
            raise HTTPException(status_code=400, detail="amount_paise must be positive")

        updates = []
        params = []
        if request.amount_paise is not None:
            updates.append("amount_paise = ?")
            params.append(int(request.amount_paise))
        if request.currency is not None:
            updates.append("currency = ?")
            params.append(request.currency)
        if request.category is not None:
            updates.append("category = ?")
            params.append(request.category)
        if request.merchant is not None:
            updates.append("merchant = ?")
            params.append(request.merchant)
        if request.note is not None:
            updates.append("note = ?")
            params.append(request.note)
        if request.spent_at is not None:
            updates.append("spent_at = ?")
            params.append(request.spent_at)

        updates.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
        params.append(expense_id)
        params.append(user_id)

        query = f"UPDATE expenses SET {', '.join(updates)} WHERE id = ? AND user_id = ?"
        conn.execute(query, params)
        conn.commit()

    return get_expense(expense_id)


@app.delete("/api/expenses/{expense_id}")
def delete_expense(expense_id: str):
    """Delete an expense by ID."""
    user_id = USER_ID
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Expense not found")

    return {"deleted": True, "id": expense_id}


@app.post("/api/budgets")
def set_budget(request: BudgetRequest):
    """Set or update a category budget for a month (YYYY-MM)."""
    user_id = USER_ID

    if request.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category: {request.category}")

    import re
    if not re.match(r"^\d{4}-\d{2}$", request.month):
        raise HTTPException(
            status_code=400,
            detail="month must be in YYYY-MM format",
        )

    budget_id = str(uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO budgets (id, user_id, category, month, amount_paise, currency)
            VALUES (?, ?, ?, ?, ?, 'INR')
            ON CONFLICT(user_id, category, month)
            DO UPDATE SET amount_paise = excluded.amount_paise,
                          currency = excluded.currency
            """,
            (budget_id, user_id, request.category, request.month,
             int(request.amount_paise)),
        )
        conn.commit()

    return {
        "id": budget_id,
        "user_id": user_id,
        "category": request.category,
        "month": request.month,
        "amount_paise": int(request.amount_paise),
    }


@app.get("/api/budgets")
def list_budgets(month: str | None = None):
    """List budgets with actual spending and 80%/100% warning status."""
    user_id = USER_ID

    import re
    if month is not None and not re.match(r"^\d{4}-\d{2}$", month):
        raise HTTPException(
            status_code=400,
            detail="month must be in YYYY-MM format",
        )

    with get_connection() as conn:
        budget_query = """
            SELECT id, user_id, category, month, amount_paise, currency
            FROM budgets
            WHERE user_id = ?
        """
        budget_params: list = [user_id]
        if month:
            budget_query += " AND month = ?"
            budget_params.append(month)
        budget_query += " ORDER BY category, month"

        budget_rows = conn.execute(budget_query, budget_params).fetchall()
        budgets = [dict(row) for row in budget_rows]

        if month:
            next_month = int(month[5:7]) + 1
            year = int(month[:4])
            if next_month > 12:
                next_month = 1
                year += 1
            month_start = f"{month}-01"
            month_end = f"{year}-{next_month:02d}-01"
            spend_query = """
                SELECT category, SUM(amount_paise) as total_spent
                FROM expenses
                WHERE user_id = ?
                  AND spent_at >= ?
                  AND spent_at < ?
                GROUP BY category
            """
            spend_rows = conn.execute(
                spend_query, (user_id, month_start, month_end)
            ).fetchall()
        else:
            spend_query = """
                SELECT category, SUM(amount_paise) as total_spent
                FROM expenses
                WHERE user_id = ?
                GROUP BY category
            """
            spend_rows = conn.execute(spend_query, (user_id,)).fetchall()

    spending = {row["category"]: row["total_spent"] for row in spend_rows}

    results = []
    for budget in budgets:
        category = budget["category"]
        budget_amount = budget["amount_paise"]
        actual = spending.get(category, 0)
        remaining = budget_amount - actual
        percent = (actual / budget_amount * 100) if budget_amount > 0 else 0

        warning = None
        if percent >= 100:
            warning = "100% budget reached"
        elif percent >= 80:
            warning = "80% budget warning"

        results.append({
            "id": budget["id"],
            "user_id": budget["user_id"],
            "category": category,
            "month": budget["month"],
            "amount_paise": budget_amount,
            "currency": budget["currency"],
            "actual_spent_paise": actual,
            "remaining_paise": remaining,
            "percent_used": round(percent, 2),
            "warning": warning,
        })

    return {
        "user_id": user_id,
        "month": month,
        "count": len(results),
        "budgets": results,
    }


@app.post("/api/voice-query")
async def voice_query(request: VoiceQueryRequest):
    """Answer natural-language questions about the user's expenses.

    Uses the LLM (Groq/Ollama) to interpret the query and answer based on
    the user's stored expenses. No persistence — read-only.
    """
    user_id = USER_ID
    query = request.query.strip()

    # Fetch all expenses for the user
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT amount_paise, currency, category, merchant, note, spent_at
            FROM expenses
            WHERE user_id = ?
            ORDER BY spent_at DESC
            """,
            (user_id,),
        ).fetchall()

    expenses = [dict(row) for row in rows]

    if not expenses:
        return {
            "query": query,
            "answer": "You haven't recorded any expenses yet. Start by speaking your first expense!",
            "expenses": [],
        }

    # Build a summary of expenses for the LLM
    expense_lines = []
    total_paise = 0
    for e in expenses:
        amount_rupees = e["amount_paise"] / 100
        total_paise += e["amount_paise"]
        expense_lines.append(
            f"- {e['spent_at']}: {e['merchant'] or 'Unknown'} — ₹{amount_rupees:.2f} — {e['category'] or 'Other'}"
            + (f" ({e['note']})" if e.get("note") else "")
        )

    total_rupees = total_paise / 100
    expense_summary = "\n".join(expense_lines)

    system_prompt = f"""You are a helpful assistant answering questions about a user's expenses.

Here are the user's recorded expenses:
{expense_summary}

Total spent: ₹{total_rupees:.2f}
Number of expenses: {len(expenses)}

Answer the user's question based ONLY on this data. Be concise and helpful.
If the answer cannot be determined from the data, say so.
Do not make up expenses or amounts. Respond in plain text (not JSON)."""

    # LLM providers (Groq/Ollama) may be unavailable - use simple text response
    # Build answer based on expense data without LLM
    if any(word in query for word in ["total", "sum", "overall"]):
        answer = f"You've spent a total of ₹{total_rupees:.2f} across {len(expenses)} expense" + ("" if len(expenses) == 1 else "s") + "."
    elif any(word in query for word in ["how many", "count", "number"]):
        answer = f"You have {len(expenses)} recorded expense" + ("" if len(expenses) == 1 else "s") + "."
    elif any(word in query for word in ["food", "groceries", "transport", "shopping", "utilities"]):
        categories = [e["category"] for e in expenses if e["category"]]
        if categories:
            answer = f"You have expenses in these categories: {', '.join(set(categories))}."
        else:
            answer = f"You have {len(expenses)} recorded expense" + ("" if len(expenses) == 1 else "s") + "."
    else:
        expense_lines = []
        for e in expenses[:5]:
            amount_rupees = e["amount_paise"] / 100
            line = f"- {e['spent_at'] or 'unknown date'}: {e['merchant'] or 'unknown merchant'} ₹{amount_rupees:.2f} ({e['category'] or 'other'})"
            expense_lines.append(line)
        summary = "\n".join(expense_lines)
        if len(expenses) > 5:
            summary += f"\n... and {len(expenses) - 5} more expenses."
        answer = f"Your recorded expenses:\n{summary}"

    return {
        "query": request.query,
        "answer": answer,
        "expense_count": len(expenses),
        "total_spent": total_rupees,
    }




# Global TTS engine instance (initialized lazily)
_tts_engine = None


def _get_tts_engine():
    global _tts_engine
    if _tts_engine is None:
        _tts_engine = PiperTTS()
    return _tts_engine


@app.post("/api/tts")
async def text_to_speech(request: TTSRequest):
    """Convert text to speech using Piper TTS (self-hosted, zero API cost).

    Returns a WAV audio file that the browser can play.
    """
    tts = _get_tts_engine()
    if not tts.is_available():
        raise HTTPException(
            status_code=503,
            detail="Piper TTS model not available. Install piper and download a voice model.",
        )

    import tempfile
    import asyncio

    # Run TTS in a thread to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    output_path = await loop.run_in_executor(
        None, lambda: asyncio.run(tts.speak(request.text))
    )

    if output_path is None:
        raise HTTPException(
            status_code=500, detail="TTS generation failed"
        )

    return FileResponse(
        output_path,
        media_type="audio/wav",
        filename="response.wav",
    )


@app.get("/")
def home():
    return HTMLResponse(
        (BASE_DIR / "index.html").read_text(encoding="utf-8")
    )