"""Eligibility signals: can the candidate actually take this job?

Distinct from *fit* (how well the CV matches) - these are the gates that make a
great match worthless if they fail:

- `detect_visa_sponsorship`: does the posting offer / refuse visa sponsorship?
- `detect_remote_region`: is a "remote" role secretly locked to a region (US-only)?
- `extract_work_countries`: which countries the text says it hires in, if it says.
- `extract_required_utc_offsets`: which working-hours timezone(s) it demands, as
  UTC offsets, so overlap with the candidate's timezone can be scored.

All best-effort regex over the posting text; conservative on purpose (better to
leave a signal null and let the judge read the nuance than to wrongly gate a job).
"""

from __future__ import annotations

import re

from app.ingest.geo import country_codes_mentioned

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


# --- stated hiring countries ------------------------------------------------

# A sentence only states a hiring restriction if it pairs one of these with a country
# name. Each needs a modal or an eligibility noun, because the bare verb is far too
# common: "our customers are based in the US" and "if you are based in France, you will
# have a French contract" are not restrictions, and a plain "based in" would catch both.
_SCOPE_CUE = re.compile(
    r"(?:must|need(?:s)? to|required to|have to|should|can only|only)\s+"
    r"(?:be\s+|have\s+|already\s+)?(?:based|located|resid\w*|live|living|a resident)"
    r"|(?:candidates?|applicants?|experts?|those|anyone|people|team members)\s+"
    r"(?:who are\s+)?(?:located|based|resid\w*|living)\s+(?:anywhere\s+)?in"
    r"|(?:only|exclusively)\s+(?:open to|available (?:to|for)|hiring|considering|accepting)"
    r"|(?:can|able to|eligible to|allowed to)\s+hire\s+"
    r"(?:new )?(?:candidates?|people|team members|employees)?\s*(?:based|located)?\s*in"
    r"|available (?:for|to) candidates (?:located|based) in"
    r"|(?:looking for|hiring|recruiting|accepting)\s+"
    r"(?:candidates?|applicants?|people|team members)\s+(?:located |based )?in"
    r"|(?:right|authori[sz]ation|eligib\w+|permit|permission)\s+to work in"
    r"|(?:have )?resided in"
    r"|this (?:role|position) is (?:only )?(?:open|available) (?:to|for|in)",
    re.IGNORECASE,
)

# Greenhouse boilerplate: the restriction is the posting's own location field, named
# nowhere in the sentence, so the caller's resolved location codes are the answer.
_SCOPE_IS_LOCATION = re.compile(
    r"only available for remote work within the specified country", re.IGNORECASE
)

# A negated sentence states the opposite of a scope ("we are not able to hire in the US",
# "this role is not open to candidates based in the United States"), and reading it as an
# allowlist would hide every job the posting actually is open to. Any negation in the
# sentence drops it: losing a real restriction only lets noise through, while misreading
# one hides a job the user should have seen.
_SCOPE_NEGATION = re.compile(
    r"\b(?:not|cannot|can ?not|unable|aren't|isn't|won't|doesn't|don't|"
    r"no longer|except|other than|outside|rather than|instead of)\b|n't\b",
    re.IGNORECASE,
)

# "U.S." would otherwise be split mid-abbreviation by the sentence splitter below, which
# also made the dotted aliases unreachable from here.
_DOTTED_ALIASES = ((r"\bU\.S\.A\.", "USA"), (r"\bU\.S\.", "US"), (r"\bU\.K\.", "UK"))

_SENTENCE_SPLIT_RE = re.compile(r"[.;\n!?]+")


def extract_work_countries(text: str | None, location_codes: list[str] | None = None) -> list[str]:
    """Countries the posting states it hires in, as ISO2 codes (plus 'EU'), else [].

    Sentence-scoped on purpose: a country name only counts when the sentence it sits in
    also states a restriction, because a posting names plenty of countries it is not
    hiring in (customers, offices, funding). Empty means unstated, never "nowhere", so a
    caller must treat [] as "keep".

    Recall is deliberately partial. This catches the common recruiter phrasings and
    leaves everything subtler to the judge, which reads the whole text. Precision is
    what matters here, since the result hides jobs.
    """
    if not text:
        return []
    for pattern, replacement in _DOTTED_ALIASES:
        text = re.sub(pattern, replacement, text)
    found: set[str] = set()
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        if _SCOPE_NEGATION.search(sentence):
            continue
        if _SCOPE_IS_LOCATION.search(sentence):
            found.update(location_codes or ())
            continue
        if _SCOPE_CUE.search(sentence):
            found.update(country_codes_mentioned(sentence))
    return sorted(found)


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
