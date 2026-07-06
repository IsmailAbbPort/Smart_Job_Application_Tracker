"""Normalization + dedup helpers.

Two jobs are "the same" across sources when their normalized (company, title,
location) match. These helpers produce those normalized forms and the composite
dedup key. Kept pure (no I/O) so they're cheap to unit-test exhaustively.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

from app.ingest import geo

# Legal-entity suffixes stripped from company names so "Qonto SAS" == "Qonto".
_COMPANY_SUFFIXES = {
    "inc",
    "llc",
    "ltd",
    "limited",
    "gmbh",
    "ag",
    "sas",
    "sa",
    "sarl",
    "srl",
    "bv",
    "nv",
    "ab",
    "oy",
    "plc",
    "co",
    "corp",
    "corporation",
    "company",
    "group",
    "holding",
    "holdings",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)


def _collapse(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def normalize_company(value: str | None) -> str:
    """Lowercase, strip punctuation + trailing legal suffixes, collapse space."""
    if not value:
        return ""
    text = _PUNCT_RE.sub(" ", value.lower())
    tokens = [t for t in _collapse(text).split(" ") if t]
    while tokens and tokens[-1] in _COMPANY_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_title(value: str | None) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Deliberately light: we keep seniority words (senior/junior) since they matter
    for dedup - a "Senior X" and "X" are genuinely different postings.
    """
    if not value:
        return ""
    return _collapse(_PUNCT_RE.sub(" ", value.lower()))


def normalize_location(value: str | None) -> str:
    """Lowercase + collapse. Remote markers stay; location dedup is coarse on purpose."""
    if not value:
        return ""
    return _collapse(value.lower())


def dedup_key(company: str | None, title: str | None, location: str | None) -> str:
    """Composite cross-source identity: normalized company|title|location.

    Location uses the canonical geo identity ("Munich, Germany" for every Munich
    spelling/format variant) so the same role from two sources collapses. Unknown
    locations fall back to the lightly-normalized raw string.
    """
    canonical_location = geo.location_identity(location) or normalize_location(location)
    return "|".join(
        (
            normalize_company(company),
            normalize_title(title),
            canonical_location.lower(),
        )
    )


def html_to_text(value: str | None) -> str:
    """Unescape HTML entities, strip tags, collapse whitespace.

    Greenhouse returns entity-escaped HTML (&lt;p&gt;...), Arbeitnow/Remotive return
    real HTML. Unescape first, then strip tags. Lever/Ashby already give plain text
    and pass through unchanged.
    """
    if not value:
        return ""
    # Unescape twice: Greenhouse double-encodes (&amp;lt; -> &lt; -> <).
    text = html.unescape(html.unescape(value))
    text = _TAG_RE.sub(" ", text)
    return _collapse(text)


def looks_remote(*fields: str | None) -> bool:
    """Heuristic: any field mentions 'remote'."""
    return any(f and "remote" in f.lower() for f in fields)


def parse_dt(value: object) -> datetime | None:
    """Parse a source timestamp into an aware UTC datetime.

    Handles: epoch seconds (Arbeitnow), epoch milliseconds (Lever), ISO-8601 with
    offset (Greenhouse/Ashby), and naive ISO (Remotive - assumed UTC).
    """
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        seconds = value / 1000 if value > 1e12 else value
        return datetime.fromtimestamp(seconds, tz=UTC)
    if isinstance(value, str):
        raw = value.strip()
        if raw.isdigit():
            return parse_dt(int(raw))
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    return None
