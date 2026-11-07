"""Orchestrates extraction and deterministic parsing into a UI-ready draft."""
import logging
import re
from schemas.expense import DraftExpense, DraftResult
from services.agent_call import agent_call
from services.amount_parser import parse_amount_paise
from services.date_parser import resolve_date_phrase

logger = logging.getLogger(__name__)

WORD_TO_DIGIT = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
}


def _convert_word_to_digits(transcript: str) -> str:
    result = transcript
    for word, digit in WORD_TO_DIGIT.items():
        result = re.sub(r"\b" + word + r"\b", digit, result, flags=re.IGNORECASE)
    return result


def _extract_amount_phrase(transcript: str) -> str:
    transcript_digits = _convert_word_to_digits(transcript)
    amount_match = re.search(r"[\u20b9]?\s*([0-9,]+\.?[0-9]*)", transcript_digits)
    amount_phrase = amount_match.group(1).replace(",", "") if amount_match else None
    if not amount_phrase:
        amount_match = re.search(r"[\u20b9]?\s*([0-9,]+\.?[0-9]*)", transcript)
        amount_phrase = amount_match.group(1).replace(",", "") if amount_match else None
    return amount_phrase


def _deterministic_draft(transcript: str) -> DraftResult:
    expenses = []
    transcript_lower = transcript.lower()

    amount_phrase = _extract_amount_phrase(transcript)

    date_phrase = None
    for word in ["today", "yesterday", "this week", "last week",
                 "january", "february", "march", "april", "may", "june",
                 "july", "august", "september", "october", "november", "december"]:
        if word in transcript_lower:
            date_phrase = word
            break

    merchant = None
    for pattern in [r"at\s+([a-zA-Z\s]+)", r"from\s+([a-zA-Z\s]+)"]:
        m = re.search(pattern, transcript_lower)
        if m:
            merchant = m.group(1).strip()
            break

    category = "Other"
    if any(w in transcript_lower for w in ["food", "restaurant", "hotel", "cafe", "mess"]):
        category = "Food"
    elif any(w in transcript_lower for w in ["transport", "auto", "taxi", "uber", "bus", "fuel"]):
        category = "Transport"
    elif any(w in transcript_lower for w in ["shopping", "store", "market", "mall"]):
        category = "Shopping"
    elif any(w in transcript_lower for w in ["utilities", "bill", "electricity", "water"]):
        category = "Utilities"

    amount_paise = 0
    if amount_phrase:
        try:
            amount_float = float(amount_phrase)
            amount_paise = int(amount_float * 100)
        except ValueError:
            amount_paise = 0

    if amount_phrase or merchant:
        expenses.append({
            "amount_paise": amount_paise,
            "currency": "INR",
            "category": category,
            "merchant": merchant or "Unknown",
            "note": transcript,
            "date_phrase": date_phrase or "unknown",
            "clarification_required": False,
        })

    draft_expenses = []
    for expense in expenses:
        de = DraftExpense.model_validate(expense)
        item = de.model_dump()
        item["resolved_date"] = resolve_date_phrase(item.get("date_phrase"))
        if item.get("amount_paise") is None and not item.get("clarification_question"):
            item["clarification_required"] = True
            item["clarification_question"] = "What was the amount in rupees?"
        draft_expenses.append(item)

    return DraftResult(transcript=transcript, expenses=draft_expenses, provider_used="deterministic")


async def build_draft(transcript: str) -> DraftResult:
    try:
        extraction, provider = await agent_call(transcript)
    except Exception as exc:
        logger.exception("LLM extraction failed; falling back to deterministic parser: %s", exc)
        return _deterministic_draft(transcript)

    draft_expenses = []
    for exp in extraction.expenses:
        amount_paise = parse_amount_paise(exp.amount_phrase)

        currency = exp.currency or "INR"
        missing = list(exp.missing_fields or [])
        clarification_required = bool(exp.clarification_required)

        if currency.upper() not in {"INR", "RS", "RUPEE", "RUPEES", "\u20b9"}:
            clarification_required = True
            if "currency" not in missing:
                missing.append("currency")

        if amount_paise is None:
            clarification_required = True
            if "amount_phrase" not in missing:
                missing.append("amount_phrase")

        # Drop noisy missing_fields when no clarification is required.
        if not clarification_required:
            missing = []

        resolved_date = resolve_date_phrase(exp.date_phrase)

        merchant = exp.merchant if exp.merchant is not None else "Unknown"
        category = exp.category if exp.category is not None else "Other"
        note = exp.note if exp.note is not None else transcript

        clarification_question = exp.clarification_question
        if clarification_required and not clarification_question:
            if "amount_phrase" in missing:
                clarification_question = "What was the amount in rupees?"
            elif "currency" in missing:
                clarification_question = "Please state the amount in INR/rupees."
            else:
                clarification_question = "Could you clarify?"

        de = DraftExpense.model_validate({
            "amount_phrase": exp.amount_phrase,
            "currency": currency,
            "category": category,
            "merchant": merchant,
            "date_phrase": exp.date_phrase,
            "note": note,
            "missing_fields": missing,
            "clarification_required": clarification_required,
            "clarification_question": clarification_question,
            "amount_paise": amount_paise,
            "resolved_date": resolved_date,
        })
        item = de.model_dump()
        item["resolved_date"] = resolved_date
        draft_expenses.append(item)

    return DraftResult(transcript=transcript, expenses=draft_expenses, provider_used=provider)
