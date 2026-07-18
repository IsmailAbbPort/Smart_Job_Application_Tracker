"""Eligibility signals: can the candidate actually take this job?

Distinct from *fit* (how well the CV matches) - these are the gates that make a
great match worthless if they fail:

- `detect_visa_sponsorship`: does the posting offer / refuse visa sponsorship?
- `detect_remote_region`: is a "remote" role secretly locked to a region (US-only)?
- `extract_required_utc_offsets`: which working-hours timezone(s) it demands, as
  UTC offsets, so overlap with the candidate's timezone can be scored.

All best-effort regex over the posting text; conservative on purpose (better to
leave a signal null and let the judge read the nuance than to wrongly gate a job).
"""

from __future__ import annotations

import re

# --- visa sponsorship -------------------------------------------------------

_SPONSOR_YES = re.compile(
    r"visa sponsorship (?:is )?(?:available|offered|provided)|"
    r"we (?:can |will )?sponsor|sponsorship provided|will provide sponsorship|"
    r"relocation and visa|visa support (?:available|provided)",
    re.IGNORECASE,
)
_SPONSOR_NO = re.compile(
    r"no (?:visa )?sponsorship|not (?:able to|be able to) sponsor|"
    r"cannot sponsor|unable to sponsor|do(?:es)? not (?:offer|provide) (?:visa )?sponsorship|"
    r"without (?:visa )?sponsorship|no relocation or visa|"
    r"must (?:already )?be (?:legally )?authorized to work|"
    r"must have (?:the )?right to work",
    re.IGNORECASE,
)


def detect_visa_sponsorship(text: str | None) -> bool | None:
    """True if sponsorship is offered, False if explicitly refused, None if unstated.

    A refusal wins over an offer when both appear (postings hedge, but "we don't
    sponsor" is the operative constraint).
    """
    if not text:
        return None
    if _SPONSOR_NO.search(text):
        return False
    if _SPONSOR_YES.search(text):
        return True
    return None


# --- remote region lock -----------------------------------------------------

# Region code -> phrases that lock a remote role to it. Matched only near a
# remote/based/located cue so a passing mention of a country doesn't trigger.
_REGION_PHRASES: dict[str, tuple[str, ...]] = {
    "us": ("united states", "u.s.", "usa", "us-based", "us only", "us-only"),
    "uk": ("united kingdom", "uk-based", "uk only"),
    "eu": ("european union", "eu-based", "within europe", "europe only", "emea"),
    "canada": ("canada", "canadian"),
    "apac": ("apac", "asia-pacific", "asia pacific"),
}
_REMOTE_CUE = re.compile(
    r"remote|based|located|resid|work from|eligible to work|authorized to work", re.IGNORECASE
)


def detect_remote_region(text: str | None, *, is_remote: bool) -> str | None:
    """Region a remote role is restricted to (us/uk/eu/...), else None.

    Only meaningful for remote roles; on-site roles carry their location elsewhere.
    """
    if not text or not is_remote:
        return None
    lower = text.lower()
    for code, phrases in _REGION_PHRASES.items():
        for phrase in phrases:
            idx = lower.find(phrase)
            while idx != -1:
                window = lower[max(0, idx - 40) : idx + len(phrase) + 40]
                if _REMOTE_CUE.search(window):
                    return code
                idx = lower.find(phrase, idx + 1)
    return None


# --- timezone requirement ---------------------------------------------------

# Timezone ABBREVIATIONS -> representative UTC offset. Matched CASE-SENSITIVELY on
# the original text: real postings write "CET"/"EST" in uppercase, whereas the
# lowercase forms collide with common non-English words ("ist" = German "is",
# "est"/"cet" = French), which produced large false-positive rates in the corpus.
_TZ_ABBR: dict[str, int] = {
    "CET": 1,
    "CEST": 1,
    "EET": 2,
    "EEST": 2,
    "GMT": 0,
    "UTC": 0,
    "BST": 0,
    "WET": 0,
    "EST": -5,
    "EDT": -5,
    "CST": -6,
    "CDT": -6,
    "MST": -7,
    "MDT": -7,
    "PST": -8,
    "PDT": -8,
    "IST": 5,
}
# Multi-word timezone PHRASES are unambiguous, so matched case-insensitively.
_TZ_PHRASE: dict[str, int] = {
    "central european": 1,
    "eastern european": 2,
    "eastern time": -5,
    "central time": -6,
    "mountain time": -7,
    "pacific time": -8,
    "uk time": 0,
}


def extract_required_utc_offsets(text: str | None) -> list[int]:
    """UTC offsets the posting's working-hours requirement implies (sorted, unique)."""
    if not text:
        return []
    offsets: set[int] = set()
    for abbr, offset in _TZ_ABBR.items():
        if re.search(rf"\b{abbr}\b", text):  # case-sensitive on the original text
            offsets.add(offset)
    lower = text.lower()
    for phrase, offset in _TZ_PHRASE.items():
        if phrase in lower:
            offsets.add(offset)
    return sorted(offsets)


def timezone_overlap_hours(
    required_offsets: list[int] | None, user_offset: int | None
) -> int | None:
    """Best overlapping working hours between the job's timezone and the user's.

    Assumes a standard 8h day (roughly 9-17 local): overlap = max(0, 8 - |Δoffset|),
    taken as the best over all required offsets. None when either side is unknown,
    so the signal never penalizes missing data.
    """
    if user_offset is None or not required_offsets:
        return None
    return max(max(0, 8 - abs(offset - user_offset)) for offset in required_offsets)
