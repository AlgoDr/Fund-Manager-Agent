"""Small deterministic relative-date resolver; extend with dateutil/parser as needed."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

def resolve_date_phrase(phrase: str | None, *, now: datetime | None = None,
                        timezone: str = "Asia/Kolkata") -> str | None:
    if not phrase or not phrase.strip():
        return None
    current = now or datetime.now(ZoneInfo(timezone))
    today = current.astimezone(ZoneInfo(timezone)).date() if current.tzinfo else current.date()
    value = phrase.lower().strip()
    if value in {"today", "this morning", "tonight"}:
        return today.isoformat()
    if value == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    if value == "day before yesterday":
        return (today - timedelta(days=2)).isoformat()
    if value == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None
