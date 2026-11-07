# Voice Spend Manager — extraction-to-draft pipeline

Drop `services/` and `schemas/` into your backend. This scaffold does not persist expenses:
your API should save only after the user explicitly confirms a draft.

## Install

```bash
pip install pydantic httpx python-dateutil
```

Set `GROQ_API_KEY` in your environment. Configure model names with environment variables if needed.

## Example

```python
from services.draft_pipeline import build_draft

draft = await build_draft("Spent two thousand rupees on groceries yesterday")
# Return `draft` to your UI. Do not write it to the database yet.
```

The default date resolver uses the machine's local date. Pass an explicit `today` and timezone-aware `now` in tests or adapt it to your app's IST policy.

## Notes

- Groq extraction is attempted first; Ollama Granite is the fallback.
- Model output is schema-validated. Amounts are parsed deterministically from the original phrase.
- Non-INR currency and missing/ambiguous required details are marked for clarification.
- No database code is included by design.
