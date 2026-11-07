# Voice Spend Manager --- Handoff Summary

**Project:** `FUND_MANAGER_VOICE_AI`\
**Purpose:** Voice-first expense tracker POC. User speaks expenses,
reviews an editable draft, then confirms before persistence.

## Architecture and requirements

-   FastAPI backend, HTML/JavaScript frontend, local MLX Whisper Large
    V3 Turbo transcription.
-   LLM extraction: Groq primary, Ollama fallback.
-   SQLite; amounts stored as integer paise, currency separately.
-   Categories: Food, Groceries, Transport, Shopping, Utilities,
    Entertainment, Health, Travel, Education, Other.
-   Extract amount/currency/category/merchant/date/note; support
    multiple expenses, number words/shorthand, relative dates,
    corrections, and clarification for missing/ambiguous fields.
-   Draft endpoint must not persist. Confirmation writes transactionally
    with an idempotency key.
-   Tables are user-scoped; current local implementation uses
    `user_id="local-user"`.
-   Assignment also calls for history/edit/delete, voice queries,
    category budgets with 80%/100% warnings, README/design note, 30+
    labelled utterances and evaluation script, parser tests, and a 3--5
    minute demo.

## Implemented code/API

-   `POST /api/draft`: runs extraction/draft pipeline; returns
    transcript, provider, expenses, and `ready_to_confirm`.
-   `POST /api/draft/clarify`: handles clarification answers.
-   `POST /api/confirm`: validates and saves expenses with per-item
    idempotency keys.
-   `GET /api/expenses/today`: returns today's expenses and totals for
    `local-user`.
-   `/` serves the frontend.
-   SQLite schema includes expenses and budgets. `services/database.py`
    connection issue was fixed; a temporary insert and today endpoint
    were tested.
-   `services/draft_pipeline.py` parses amount phrases to paise,
    resolves dates deterministically in IST, and flags
    missing/unsupported currency or amount for clarification.
-   Provider implementation/logging is in `services/agent_call.py`; logs
    provider attempts, failures, and raw extraction payloads.

## Provider configuration and evidence

The user's Groq model list included `openai/gpt-oss-120b`,
`openai/gpt-oss-20b`, and `qwen/qwen3.8-27b`. A direct chat-completions
curl using `openai/gpt-oss-120b` succeeded and returned three
expenses: - 350 rupees --- Uber --- Transport - 40 rupees --- Samosa Pao
--- Food - 200 rupees --- lunch --- Food

The `jq` parse error in that test was only because `curl -w` appended
`HTTP_STATUS=...` after the JSON; the Groq response itself succeeded.

Earlier app logs showed Groq being called with
`llama-3.3-70b-versatile`, which Groq rejected with `model_not_found`;
the app then fell back to Ollama. The user has not yet confirmed that
the running app loads the updated `GROQ_MODEL` value.

## Direct API test: successful

The user tested `/api/draft` directly with:

``` bash
curl -sS -X POST http://127.0.0.1:8000/api/draft \
  -H "Content-Type: application/json" \
  -d '{
    "transcript": "Today I spent 350 rupees for Uber, 40 rupees for Samosa Pao, and 200 rupees for lunch."
  }' | jq .
```

Observed: - HTTP 200 - `provider_used: "ollama"` -
`ready_to_confirm: true` - Three expenses: - Uber:
`amount_paise: 35000`, category `Transport` - Samosa Pao:
`amount_paise: 4000`, category `Shopping` (likely wrong; should be
Food) - Lunch: `amount_paise: 20000`, category `Food` - Dates resolved
to `2026-11-04`.

This establishes that the API/draft pipeline can return expense drafts.
It does not establish that Groq is being used or that the browser
renders the returned expenses.

## Current issues — STATUS UPDATE (Nov 4, 2026 session)

### 1. App falling back to Ollama — RESOLVED

-   Root cause: stale shell variable `GROQ_MODEL=llama-3.3-70b-versatile` took
    precedence over `.env` because `load_dotenv()` defaulted to `override=False`.
    Groq rejected the old model with `model_not_found` (HTTP 404) and fell back
    to Ollama.
-   Fixes applied:
    - `server.py` line 10: `load_dotenv()` → `load_dotenv(override=True)` so the
      project `.env` (`GROQ_MODEL=openai/gpt-oss-120b`) wins over shell vars.
    - `server.py` lines 24–29: added startup log `Groq model configured: <model>`.
-   Verification: after restart, terminal shows
    `INFO:server:Groq model configured: openai/gpt-oss-120b` and
    `INFO:services.agent_call:Extraction payload from groq: {...}` with HTTP 200.

### 2. Browser shows "I couldn't identify an expense" — RESOLVED

-   Root cause: `index.html` assigned `currentDraft = draftResult.draft`, but
    `/api/draft` returns a flat object `{transcript, provider_used, expenses,
    ready_to_confirm}` — no nested `draft` key. So `currentDraft` was `undefined`
    and `renderDraft(undefined)` hit the empty fallback.
-   Fix applied: `index.html` line 374:
  `currentDraft = draftResult.draft` → `currentDraft = draftResult`.
-   Verification: after restart + refresh, expense cards render with amounts,
  categories, merchants, dates, parsed rupee amounts, and the "Save expenses"
  button.

### 3. Submit clarification button does nothing — RESOLVED

-   Root cause: Three problems:
    1. Frontend guessed the wrong field using `expense.amount_paise == null ? "amount_phrase" : "currency"`, so if amount was parsed but merchant was missing, it incorrectly sent `field: "currency"`.
    2. Backend `/api/draft/clarify` only accepted `amount_phrase` and `currency` — rejected `merchant`, `note`, `category`, `date_phrase`.
    3. No `clarification_field` in the API response, so the frontend couldn't know which field the LLM needed.
-   Fixes applied:
    1. `server.py` `/api/draft` endpoint: adds `clarification_field` to each expense needing clarification, derived from `missing_fields[0]` or fallback heuristic.
    2. `server.py` `/api/draft/clarify` endpoint: now accepts `amount_phrase`, `currency`, `merchant`, `note`, `category`, and `date_phrase`. For `date_phrase`, resolves via `resolve_date_phrase` and returns `resolved_date`.
    3. `index.html` clarification handler: uses `expense.clarification_field` (falling back to `missing_fields[0]`, then old heuristic) and handles responses for all six field types.
-   Verification: All six clarify field types return HTTP 200 via curl. Draft endpoint returns `clarification_field`.

### 4. Classification quality — EVALUATION SCRIPT CREATED

`tests/evaluation.py` contains 36 labelled utterances comparing Groq vs
Ollama on category, amount, merchant, date, clarification, and JSON
validity. Run with: `uv run python tests/evaluation.py`
Results saved to `evaluation_results.json`.

### 5. Environment warning

`uv run uvicorn server:app --reload` prints:

``` text
VIRTUAL_ENV=voice-env does not match the project environment path .venv and will be ignored
```

If dependency mismatches arise, use the project `.venv` consistently or
run `uv run --active ...` to target the active environment.

## Completed Work (this session)

### Issues resolved
1. **Groq falling back to Ollama** — `load_dotenv(override=True)` so `.env` wins over stale shell vars; startup model log added. Verified: `openai/gpt-oss-120b` returns HTTP 200.
2. **Empty draft UI** — `currentDraft = draftResult` (no nested `draft` key). Verified: expense cards render.
3. **Clarification submit broken** — Backend accepts 6 fields (`amount_phrase`, `currency`, `merchant`, `note`, `category`, `date_phrase`); frontend uses `clarification_field` from API response. Verified: all 6 return HTTP 200.

### Features implemented
- **CRUD endpoints**: GET/PUT/DELETE `/api/expenses/{id}`, GET `/api/expenses` with filters
- **Budget endpoints**: POST/GET `/api/budgets` with 80%/100% warnings
- **Parser tests**: 28 unit tests for amount_parser and date_parser (all passing)
- **Integration tests**: 21 API tests covering draft regression, CRUD, budgets (all passing)
- **Evaluation script**: 36 labelled utterances comparing Groq vs Ollama
- **Documentation**: README.md updated with API table, testing section, security

## Remaining work (per assignment requirements)

1. **Voice queries** — natural-language questions over existing expenses
2. **Frontend UI for CRUD + budgets** — history list, edit form, delete button, budget display in index.html
3. **3–5 minute demo** — prepare demo script

## Recommended next steps (updated)

1. Build frontend UI for expense history, edit, delete (consume new CRUD endpoints)
2. Build frontend UI for budget display with 80%/100% warnings
3. Implement voice queries endpoint
4. Prepare 3–5 minute demo script

## Useful commands

Check model setting without exposing the key:

``` bash
grep '^GROQ_MODEL=' .env
```

Restart after `.env` edits:

``` bash
# Ctrl+C, then:
uv run uvicorn server:app --reload
```

**Security:** Do not paste the Groq API key into logs, screenshots, or
handoff notes. It is not included here.
