"""Extract the minimum years of experience a posting requires.

Best-effort, like the other ingest signals. We take the *smallest* stated
requirement (the entry bar): a "5-8 years" role is entered at 5, and taking the
minimum keeps the signal conservative so a soft experience filter under-flags
rather than wrongly hiding reachable jobs. Returns None when nothing is stated.
"""

from __future__ import annotations

import re

_MAX_SANE_YEARS = 30  # anything larger is almost certainly not an experience bar

# "N years ... experience" within a short span (of/in optional), e.g.
# "5 years of experience", "3+ years' engineering experience", or the reverse
# "experience: 5+ years". The window (35 chars) covers "years of <domain> experience".
_EXP_NEAR = re.compile(
    r"(\d{1,2})\s*(?:\+|-|–|to)?\s*(?:\d{1,2})?\s*years?['’]?\s*"
    r"(?:of\s+|in\s+)?[\w/&,. -]{0,35}?experience"
    r"|experience[\w/&,.:'’ -]{0,20}?(\d{1,2})\s*\+?\s*years?",
    re.IGNORECASE,
)
# "N+ years" - the explicit plus signals a requirement even without "experience".
_EXP_PLUS = re.compile(r"(\d{1,2})\s*\+\s*years?", re.IGNORECASE)
_AGO = re.compile(r"\bago\b", re.IGNORECASE)


def extract_min_years_experience(text: str | None) -> int | None:
    """Smallest stated years-of-experience requirement, or None if unstated."""
    if not text:
        return None
    years: list[int] = []
    for pattern in (_EXP_NEAR, _EXP_PLUS):
        for match in pattern.finditer(text):
            # Skip "10 years ago" style mentions (company history, not a requirement).
            if _AGO.search(text[match.end() : match.end() + 6]):
                continue
            # _EXP_NEAR has two alternatives (forward / reverse) -> take whichever grouped.
            digits = next((g for g in match.groups() if g), None)
            if digits is None:
                continue
            n = int(digits)
            if 1 <= n <= _MAX_SANE_YEARS:
                years.append(n)
    return min(years) if years else None
