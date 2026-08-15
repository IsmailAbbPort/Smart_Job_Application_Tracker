"""Language signals for a job posting.

Two distinct things, don't conflate them:

- `detect_language`: what language the posting is *written in* (via py3langid,
  offline + deterministic). A strong-but-imperfect proxy for "you need to read
  this language", used as the cheap pre-filter over the whole feed.
- `extract_required_languages`: explicit *spoken-language requirements* stated in
  the text ("fluent German", "C1 French"). Best-effort regex, high-precision /
  modest-recall; the LLM judge does the nuanced reading on the shortlist.

Both return ISO 639-1 codes (en, de, fr, ...).
"""

from __future__ import annotations

import re

# English language names we look for -> ISO 639-1 code. Kept to the languages that
# actually show up in EU job postings.
_LANG_NAMES: dict[str, str] = {
    "english": "en",
    "german": "de",
    "french": "fr",
    "spanish": "es",
    "italian": "it",
    "dutch": "nl",
    "portuguese": "pt",
    "polish": "pl",
    "swedish": "sv",
    "danish": "da",
    "norwegian": "no",
    "finnish": "fi",
    "czech": "cs",
    "greek": "el",
    "romanian": "ro",
    "hungarian": "hu",
    "russian": "ru",
    "ukrainian": "uk",
    "turkish": "tr",
    "arabic": "ar",
}

# Cues that a language mention is a real requirement (incl. a couple of German
# ones, since German boards are a target). CEFR levels B2/C1/C2 count as required.
_REQUIRE_CUE = re.compile(
    r"fluen|nativ|proficien|mother tongue|business[- ]level|required|must |mandatory|"
    r"\bc1\b|\bc2\b|\bb2\b|verhandlungssicher|muttersprache",
    re.IGNORECASE,
)
# Cues that downgrade it to "nice to have" -> not a hard requirement.
_SOFT_CUE = re.compile(
    r"a plus|is a plus|nice to have|optional|bonus|beneficial|advantageous|desirable",
    re.IGNORECASE,
)

_MIN_DETECT_CHARS = 80

# A language named in the *title* is almost always a hard requirement (job boards
# tag "(German Speaking)" / "- French" roles that way). Two high-precision cues:
#   A. "<lang> speaking/speaker" (with optional space/hyphen): "German speaking".
#   B. a bare "<lang>" set off by a "-" or "(" qualifier: "- German", "(German)".
# Both rely on \b so "Germany" (a location) never matches "german". Titles like
# "... - Germany" (a place, not a language) are therefore left untouched.
_TITLE_LANG_NAMES = "|".join(re.escape(n) for n in _LANG_NAMES)
_TITLE_LANG_CUE = re.compile(
    rf"(?:\b(?P<a>{_TITLE_LANG_NAMES})[\s-]*(?:speaking|speaker)\b)"
    rf"|(?:[-(]\s*(?P<b>{_TITLE_LANG_NAMES})\b)",
    re.IGNORECASE,
)


def detect_language(*texts: str | None, min_chars: int = _MIN_DETECT_CHARS) -> str | None:
    """Detect the dominant language of the given texts. None if too short to trust."""
    text = " ".join(t for t in texts if t).strip()
    if len(text) < min_chars:
        return None
    import py3langid

    lang, _score = py3langid.classify(text)
    return lang


def extract_required_languages(text: str | None) -> list[str]:
    """Best-effort list of spoken languages the posting *requires* (ISO codes).

    A language name counts only when a requirement cue sits within ~60 chars and no
    softening cue ("a plus", "nice to have") does. Conservative on purpose: better
    to miss one and let the judge catch it than to wrongly filter a job out.
    """
    if not text:
        return []
    lower = text.lower()
    found: set[str] = set()
    for name, code in _LANG_NAMES.items():
        for match in re.finditer(rf"\b{name}\b", lower):
            window = lower[max(0, match.start() - 60) : match.end() + 60]
            if _REQUIRE_CUE.search(window) and not _SOFT_CUE.search(window):
                found.add(code)
                break
    return sorted(found)


def extract_required_languages_from_title(title: str | None) -> list[str]:
    """Spoken-language requirements stated in the *title* (ISO codes).

    Job boards encode a hard language requirement into the title itself
    ("Solutions Consultant (German Speaking)", "Support - German speaking"),
    which `extract_required_languages` misses because it reads the description.
    High-precision by design: only a "speaking/speaker" cue or a dash/paren-set-off
    bare language name counts, so a location like "- Germany" is never flagged.
    """
    if not title:
        return []
    found: set[str] = set()
    for match in _TITLE_LANG_CUE.finditer(title):
        name = (match.group("a") or match.group("b")).lower()
        found.add(_LANG_NAMES[name])
    return sorted(found)
