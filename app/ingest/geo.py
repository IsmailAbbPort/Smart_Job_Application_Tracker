"""Location resolution backed by the geonamescache dataset (offline, ~28k cities).

Turns a free-text location into a canonical (city, country, is_european) triple,
so every spelling/format variant of the same place collapses:
    "Munich" / "München" / "Munich, Germany" / "Munich, Bavaria, DE"  ->  Munich, Germany
    "Warszawa, Masovian Voivodeship, Poland"                          ->  Warsaw, Poland

`country` is the actual resolved country (any continent); `is_european` flags the
European ones for the EU-remote search. `city` is only set for European cities
(the app's focus); non-European and unknown locations leave it None.

This replaces a hand-maintained city list: coverage is now the full dataset, not
whatever we remembered to type. Ambiguous bare names resolve to the highest-
population match (so "Berlin" -> Berlin, DE, not Berlin, US), and an explicit
country in the string pins the city to that country.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import geonamescache

_gc = geonamescache.GeonamesCache()
_COUNTRIES = _gc.get_countries()  # ISO2 -> {"name", ...}
_CITIES = _gc.get_cities()  # id -> {"name", "countrycode", "population", "alternatenames"}

# Broad "European" country set: EU27 + EFTA + UK + microstates + a few neighbours.
EUROPEAN_CC = {
    "AT",
    "BE",
    "BG",
    "HR",
    "CY",
    "CZ",
    "DK",
    "EE",
    "FI",
    "FR",
    "DE",
    "GR",
    "HU",
    "IE",
    "IT",
    "LV",
    "LT",
    "LU",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SK",
    "SI",
    "ES",
    "SE",
    "GB",
    "IS",
    "NO",
    "LI",
    "CH",
    "MC",
    "AD",
    "SM",
    "VA",
    "RS",
    "UA",
    "AL",
    "MK",
    "ME",
    "BA",
    "MD",
    "XK",
}

_REGION_TOKENS = {"europe", "emea", "eea", "european union", "eurozone"}

# Non-place words that must never be treated as a city candidate.
_STOPWORDS = {
    "remote",
    "hybrid",
    "onsite",
    "office",
    "anywhere",
    "worldwide",
    "global",
    "home",
    "based",
    "all",
    "other",
    "various",
    "multiple",
    "greater",
    "central",
    "area",
    "region",
    "distributed",
    "flexible",
    "new",
    "the",
    "or",
    "in",
    "and",
}


def _norm(text: str) -> str:
    """Lowercase and strip accents so München and Munchen key the same."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().strip()


# country name / alias -> ISO2
_COUNTRY_BY_NAME: dict[str, str] = {_norm(c["name"]): cc for cc, c in _COUNTRIES.items()}
_COUNTRY_BY_NAME.update(
    {
        "usa": "US",
        "us": "US",
        "u.s.": "US",
        "u.s.a.": "US",
        "united states of america": "US",
        "uk": "GB",
        "u.k.": "GB",
        "britain": "GB",
        "great britain": "GB",
        "england": "GB",
        "scotland": "GB",
        "wales": "GB",
        "czech republic": "CZ",
        "the netherlands": "NL",
        "holland": "NL",
        "republic of ireland": "IE",
    }
)

# Short forms that must only match in upper case, so the pronoun "us" in "join us in
# Berlin" is never read as the United States.
_CASED_ALIASES = {"US", "USA", "U.S.", "U.S.A.", "UK", "U.K.", "EU", "EEA", "EMEA"}

# city name / alternate name -> list of (canonical name, ISO2, population)
_CITY_INDEX: dict[str, list[tuple[str, str, int]]] = {}
for _c in _CITIES.values():
    _entry = (_c["name"], _c["countrycode"], _c.get("population", 0) or 0)
    for _nm in (_c["name"], *(_c.get("alternatenames") or [])):
        _key = _norm(_nm)
        if _key:
            _CITY_INDEX.setdefault(_key, []).append(_entry)

_SPLIT_RE = re.compile(r"[;,/|()\-]| or | in ")

# Names matched case-insensitively (on normalized text), longest first so "united states"
# wins over "united"; the cased short forms are matched separately on the raw text.
_MENTION_RE = re.compile(
    r"\b(?:"
    + "|".join(
        re.escape(name)
        for name in sorted(_COUNTRY_BY_NAME, key=len, reverse=True)
        if name.upper() not in _CASED_ALIASES and len(name) > 3
    )
    + r")\b"
)
_CASED_RE = re.compile(
    r"(?<![A-Za-z])(?:"
    + "|".join(re.escape(alias) for alias in sorted(_CASED_ALIASES, key=len, reverse=True))
    + r")(?![A-Za-z])"
)


def _segments(location: str) -> list[str]:
    """Top-level location parts (comma/dash/semicolon separated), in order."""
    return [s.strip() for s in _SPLIT_RE.split(_norm(location)) if s.strip()]


def _phrases(segments: list[str]) -> list[str]:
    """Ordered, de-duplicated phrases (segments + their 1..3-word n-grams)."""
    ordered: list[str] = []
    seen: set[str] = set()

    def add(phrase: str) -> None:
        if phrase and phrase not in seen:
            seen.add(phrase)
            ordered.append(phrase)

    for seg in segments:
        add(seg)
        words = seg.split()
        for n in (3, 2, 1):
            for i in range(len(words) - n + 1):
                add(" ".join(words[i : i + n]))
    return ordered


def _country_name(cc: str) -> str:
    name = _COUNTRIES[cc]["name"]
    return name[4:] if name.lower().startswith("the ") else name


@lru_cache(maxsize=8192)
def _resolve(location: str | None) -> tuple[str | None, str | None, bool]:
    """Return (city, country, is_european). Cached: locations repeat heavily."""
    if not location:
        return (None, None, False)
    segments = _segments(location)
    phrases = _phrases(segments)

    # Country only from whole segments: a bare fragment must not count (e.g. "wales"
    # inside "New South Wales" must not resolve Australia to the UK).
    country_cc = next((_COUNTRY_BY_NAME[s] for s in segments if s in _COUNTRY_BY_NAME), None)

    matches: list[tuple[str, str, int]] = []
    for p in phrases:
        if p not in _STOPWORDS and p in _CITY_INDEX:
            matches.extend(_CITY_INDEX[p])

    # With a known country, only accept a city in it (no cross-country fallback).
    # Otherwise take the most-populous match so bare "Berlin" -> Berlin, DE.
    pool = [m for m in matches if m[1] == country_cc] if country_cc else matches
    chosen_city, chosen_cc = (None, None)
    if pool:
        chosen_city, chosen_cc, _pop = max(pool, key=lambda m: m[2])

    cc = country_cc or chosen_cc
    if cc:
        country, is_eu = _country_name(cc), cc in EUROPEAN_CC
    elif any(t in phrases for t in _REGION_TOKENS):
        country, is_eu = "Europe", True
    else:
        country, is_eu = None, False

    city = chosen_city if (chosen_city and chosen_cc in EUROPEAN_CC) else None
    return (city, country, is_eu)


def _segment_codes(segments: list[str]) -> list[str]:
    """Country codes named by whole segments, retrying each without its stopwords.

    Whole segments only, as in `_resolve`, so "wales" inside "New South Wales" cannot
    resolve Australia to the UK. The stopword retry is what lets "all france (remote)"
    reach France, since the raw segment "all france" is not a country name.
    """
    codes: list[str] = []
    for seg in segments:
        if seg in _COUNTRY_BY_NAME:
            codes.append(_COUNTRY_BY_NAME[seg])
            continue
        trimmed = " ".join(w for w in seg.split() if w not in _STOPWORDS)
        if trimmed and trimmed != seg and trimmed in _COUNTRY_BY_NAME:
            codes.append(_COUNTRY_BY_NAME[trimmed])
    return codes


@lru_cache(maxsize=8192)
def _country_codes(location: str | None) -> tuple[str, ...]:
    """Every country a location names, not just the first. See resolve_country_codes."""
    if not location:
        return ()
    out: list[str] = []
    # Semicolons separate whole locations ("Remote, Canada; Remote, United States"), so
    # each part gets its own city fallback rather than one winner for the whole string.
    for part in _norm(location).split(";"):
        segments = [s.strip() for s in _SPLIT_RE.split(part) if s.strip()]
        if not segments:
            continue
        codes = _segment_codes(segments)
        if not codes:
            phrases = _phrases(segments)
            matches = [m for p in phrases if p not in _STOPWORDS for m in _CITY_INDEX.get(p, ())]
            if matches:
                codes = [max(matches, key=lambda m: m[2])[1]]
            elif any(t in phrases for t in _REGION_TOKENS):
                codes = ["EU"]
        out.extend(codes)
    return tuple(sorted(set(out)))


def resolve_country_codes(location: str | None) -> list[str]:
    """Every country the location names, as ISO2 codes, with 'EU' for a region token.

    `resolve_country` answers "which country is this", picking one; this answers "which
    countries does this allow", which is the question an eligibility filter asks. Empty
    when the location names no place ("Remote", "Worldwide", "Anywhere").
    """
    return list(_country_codes(location))


def country_codes_mentioned(text: str) -> list[str]:
    """Country codes named anywhere in a short piece of text, as ISO2 plus 'EU'.

    For reading a sentence that states where a role may be done. Deliberately looser
    than `resolve_country_codes` (it matches names mid-sentence), so callers must only
    hand it text they have already established is about eligibility: run over a whole
    posting it would match every country the marketing copy happens to name.
    """
    out: set[str] = set()
    for match in _MENTION_RE.finditer(_norm(text)):
        out.add(_COUNTRY_BY_NAME[match.group(0)])
    for match in _CASED_RE.finditer(text):
        token = match.group(0)
        out.add("EU" if token in ("EU", "EEA", "EMEA") else _COUNTRY_BY_NAME[_norm(token)])
    if any(t in _norm(text) for t in _REGION_TOKENS):
        out.add("EU")
    return sorted(out)


def resolve_city(location: str | None) -> str | None:
    """Canonical European city for the location, else None."""
    return _resolve(location)[0]


def resolve_country(location: str | None) -> str | None:
    """Resolved country (any continent), else None."""
    return _resolve(location)[1]


def is_european(location: str | None) -> bool:
    return _resolve(location)[2]


def location_identity(location: str | None) -> str:
    """Canonical location string for dedup: "City, Country" | "Country" | "".

    Empty when the location is unknown, so callers fall back to the raw string.
    """
    city, country, _is_eu = _resolve(location)
    return ", ".join(p for p in (city, country) if p)
