"""Best-effort geographic resolution: map a free-text location to a European country.

This is the adjustable "definition of Europe" for the search. It is deliberately
data-driven (the sets below) so it can later move to the DB and be edited from the
UI. `resolve_country` returns a canonical country name (or "Europe" for region-only
strings like "EMEA"), and None when the location is non-European or unknown.

Policy (per the user's dogfooding scope): only *explicitly* European locations
count. "Remote"/"Worldwide"/"Anywhere" with no country resolve to None, so they are
NOT treated as European - we want jobs actually based in Europe, not merely
remote-eligible from Europe.
"""

from __future__ import annotations

import re

# Canonical European country -> its aliases as they appear in job locations.
_COUNTRY_ALIASES: dict[str, list[str]] = {
    "United Kingdom": [
        "united kingdom",
        "uk",
        "england",
        "scotland",
        "wales",
        "northern ireland",
        "great britain",
        "britain",
    ],
    "Ireland": ["ireland", "republic of ireland"],
    "Germany": ["germany", "deutschland"],
    "France": ["france"],
    "Spain": ["spain", "espana", "españa"],
    "Portugal": ["portugal"],
    "Italy": ["italy", "italia"],
    "Netherlands": ["netherlands", "the netherlands", "holland"],
    "Belgium": ["belgium"],
    "Luxembourg": ["luxembourg"],
    "Switzerland": ["switzerland"],
    "Austria": ["austria"],
    "Poland": ["poland"],
    "Czechia": ["czechia", "czech republic"],
    "Slovakia": ["slovakia"],
    "Slovenia": ["slovenia"],
    "Hungary": ["hungary"],
    "Romania": ["romania"],
    "Bulgaria": ["bulgaria"],
    "Greece": ["greece"],
    "Croatia": ["croatia"],
    "Denmark": ["denmark"],
    "Sweden": ["sweden"],
    "Finland": ["finland"],
    "Norway": ["norway"],
    "Iceland": ["iceland"],
    "Estonia": ["estonia"],
    "Latvia": ["latvia"],
    "Lithuania": ["lithuania"],
    "Malta": ["malta"],
    "Cyprus": ["cyprus"],
}

# Major European cities -> country, for locations that name only a city.
_CITY_TO_COUNTRY: dict[str, str] = {
    "london": "United Kingdom",
    "manchester": "United Kingdom",
    "edinburgh": "United Kingdom",
    "dublin": "Ireland",
    "cork": "Ireland",
    "berlin": "Germany",
    "munich": "Germany",
    "münchen": "Germany",
    "hamburg": "Germany",
    "cologne": "Germany",
    "köln": "Germany",
    "frankfurt": "Germany",
    "paris": "France",
    "lyon": "France",
    "toulouse": "France",
    "madrid": "Spain",
    "barcelona": "Spain",
    "valencia": "Spain",
    "lisbon": "Portugal",
    "porto": "Portugal",
    "milan": "Italy",
    "rome": "Italy",
    "roma": "Italy",
    "turin": "Italy",
    "amsterdam": "Netherlands",
    "rotterdam": "Netherlands",
    "the hague": "Netherlands",
    "brussels": "Belgium",
    "antwerp": "Belgium",
    "zurich": "Switzerland",
    "zürich": "Switzerland",
    "geneva": "Switzerland",
    "vienna": "Austria",
    "wien": "Austria",
    "warsaw": "Poland",
    "krakow": "Poland",
    "kraków": "Poland",
    "prague": "Czechia",
    "praha": "Czechia",
    "bratislava": "Slovakia",
    "ljubljana": "Slovenia",
    "budapest": "Hungary",
    "bucharest": "Romania",
    "sofia": "Bulgaria",
    "athens": "Greece",
    "zagreb": "Croatia",
    "copenhagen": "Denmark",
    "stockholm": "Sweden",
    "gothenburg": "Sweden",
    "helsinki": "Finland",
    "espoo": "Finland",
    "oslo": "Norway",
    "reykjavik": "Iceland",
    "tallinn": "Estonia",
    "riga": "Latvia",
    "vilnius": "Lithuania",
}

# Region-only tokens: European but no specific country.
_REGION_ALIASES = ["europe", "european union", "emea", "eea", "eurozone"]

_EUROPE = "Europe"


def _compile(aliases: dict[str, str]) -> list[tuple[re.Pattern[str], str]]:
    """Compile (word-boundary regex, canonical) pairs, longest alias first."""
    pairs: list[tuple[re.Pattern[str], str]] = []
    for alias, canonical in sorted(aliases.items(), key=lambda kv: -len(kv[0])):
        pairs.append((re.compile(rf"\b{re.escape(alias)}\b"), canonical))
    return pairs


# Flatten country aliases -> {alias: canonical} then compile.
_COUNTRY_PATTERNS = _compile(
    {alias: canonical for canonical, aliases in _COUNTRY_ALIASES.items() for alias in aliases}
)
_CITY_PATTERNS = _compile(_CITY_TO_COUNTRY)
_REGION_PATTERNS = _compile({alias: _EUROPE for alias in _REGION_ALIASES})


def resolve_country(location: str | None) -> str | None:
    """Return the canonical European country for a location, else None.

    Precedence: explicit country > known city > region token. Multi-location
    strings (e.g. "Berlin, Germany; Austin, TX") resolve on the first European
    hit, which is the desired behavior for an EU-focused search.
    """
    if not location:
        return None
    text = location.lower()
    for patterns in (_COUNTRY_PATTERNS, _CITY_PATTERNS, _REGION_PATTERNS):
        for pattern, canonical in patterns:
            if pattern.search(text):
                return canonical
    return None


def is_european(location: str | None) -> bool:
    return resolve_country(location) is not None
