"""Deterministic amount phrase parser. Output is integer paise; no LLM calls."""
import re

_SMALL = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS = {"twenty":20, "thirty":30, "forty":40, "fifty":50, "sixty":60,
         "seventy":70, "eighty":80, "ninety":90}

def _words_to_int(text: str) -> int:
    total = current = 0
    for word in re.findall(r"[a-z]+", text.lower()):
        if word in _SMALL:
            current += _SMALL[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word == "hundred":
            current = max(current, 1) * 100
        elif word == "thousand":
            total += max(current, 1) * 1000
            current = 0
        elif word == "lakh":
            total += max(current, 1) * 100_000
            current = 0
        elif word == "crore":
            total += max(current, 1) * 10_000_000
            current = 0
    return total + current

def parse_amount_paise(phrase: str | None) -> int | None:
    """Supports numeric amounts, k/lakh/crore shorthand, and common number words."""
    if not phrase:
        return None
    text = phrase.lower().replace(",", "").strip()
    # Numeric shorthand, e.g. 1.5k, 2 lakh, 1 crore
    match = re.search(r"(?<!\w)(\d+(?:\.\d+)?)\s*(k|thousand|lakh|lac|crore)?\b", text)
    if match:
        value = float(match.group(1))
        unit = match.group(2)
        multiplier = {"k": 1_000, "thousand": 1_000, "lakh": 100_000,
                      "lac": 100_000, "crore": 10_000_000}.get(unit, 1)
        rupees = value * multiplier
        return int(round(rupees * 100)) if round(rupees * 100) == rupees * 100 else None
    cleaned = re.sub(r"\b(rupees?|rs\.?|inr)\b", " ", text)
    # "two fifty" is commonly ₹250; "fifteen hundred" is ₹1500.
    if re.fullmatch(r"\s*(two)\s+(fifty)\s*", cleaned):
        return 25_000
    if re.fullmatch(r"\s*(fifteen)\s+hundred\s*", cleaned):
        return 150_000
    if "hundred" in cleaned or any(w in cleaned for w in ("thousand", "lakh", "lac", "crore")):
        return _words_to_int(cleaned) * 100
    words = re.findall(r"[a-z]+", cleaned)
    if words and all(w in _SMALL or w in _TENS or w == "and" for w in words):
        return _words_to_int(cleaned) * 100
    return None
