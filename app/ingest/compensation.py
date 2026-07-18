"""Compensation + application-effort signals from a posting.

- `extract_salary`: a (min, max, currency) range, only when currency-anchored so
  random numbers ("401k", "50 employees") don't get read as pay.
- `extract_effort_signals`: what applying costs (cover letter, coding challenge,
  portfolio), so a high-effort ask can lower priority for a marginal fit.

Best-effort, like the other ingest signals: unclear -> null/empty, never a guess.
"""

from __future__ import annotations

import re

_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP", "usd": "USD", "eur": "EUR", "gbp": "GBP"}

# A currency-anchored amount, optionally a range: "$120,000 - $150,000", "€60k-80k",
# "£50,000 to 65,000", "USD 100000". The first amount must carry a currency; the
# second (range end) may omit it.
_NUM = r"\d{1,3}(?:[,\s]?\d{3})*(?:\.\d+)?"
_SALARY_RE = re.compile(
    rf"(?P<cur>[$€£]|\busd\b|\beur\b|\bgbp\b)\s?(?P<n1>{_NUM})\s?(?P<k1>k)?"
    rf"(?:\s?(?:-|to|–|—)\s?[$€£]?\s?(?P<n2>{_NUM})\s?(?P<k2>k)?)?",
    re.IGNORECASE,
)

_MIN_PLAUSIBLE_SALARY = 1000  # below this it's an hourly rate or noise, not a salary
# A magnitude suffix right after the amount means it's funding/valuation, not pay
# (e.g. "$781M raised", "$11B valuation"), so that match is skipped.
_MAGNITUDE = re.compile(r"^\s*(?:m|bn|b|k?m|million|billion)\b", re.IGNORECASE)


def _to_int(number: str, is_k: bool) -> int:
    value = float(number.replace(",", "").replace(" ", ""))
    if is_k:
        value *= 1000
    return int(value)


def extract_salary(text: str | None) -> tuple[int | None, int | None, str | None]:
    """Return (salary_min, salary_max, currency), or (None, None, None) if unclear.

    Scans all currency-anchored amounts and returns the first *plausible* pay figure,
    skipping funding/valuation ("$781M") and hourly-rate ("$40") amounts. Scanning
    (not just the first match) matters: postings often mention funding before pay.
    """
    if not text:
        return None, None, None
    for match in _SALARY_RE.finditer(text):
        if _MAGNITUDE.match(text[match.end() : match.end() + 12]):
            continue  # funding/valuation, not a salary
        low = _to_int(match["n1"], bool(match["k1"]))
        high = _to_int(match["n2"], bool(match["k2"])) if match["n2"] else low
        if high < low:
            low, high = high, low
        if high < _MIN_PLAUSIBLE_SALARY:  # hourly rate or noise
            continue
        cur = _CURRENCY.get(match["cur"].lower(), _CURRENCY.get(match["cur"]))
        return low, high, cur
    return None, None, None


_EFFORT_PATTERNS: dict[str, re.Pattern[str]] = {
    "cover_letter": re.compile(r"cover letter", re.IGNORECASE),
    "coding_challenge": re.compile(
        r"coding challenge|take[- ]home|technical assessment|coding test|code test|"
        r"hackerrank|codility",
        re.IGNORECASE,
    ),
    "portfolio": re.compile(
        r"portfolio (?:is )?(?:required|link)|link to (?:your )?portfolio|share your portfolio",
        re.IGNORECASE,
    ),
}


def extract_effort_signals(text: str | None) -> list[str]:
    """Which application-effort asks the posting states (sorted, de-duplicated)."""
    if not text:
        return []
    return sorted(key for key, pattern in _EFFORT_PATTERNS.items() if pattern.search(text))
