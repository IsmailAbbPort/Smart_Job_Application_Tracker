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

# Major European cities: alias -> (canonical city, country). Aliases fold spelling
# variants (München -> Munich) so "Munich", "Munich, Germany", "München, Bayern"
# all resolve to the same canonical (Munich, Germany).
_CITY_ALIASES: dict[str, tuple[str, str]] = {
    "london": ("London", "United Kingdom"),
    "manchester": ("Manchester", "United Kingdom"),
    "edinburgh": ("Edinburgh", "United Kingdom"),
    "dublin": ("Dublin", "Ireland"),
    "cork": ("Cork", "Ireland"),
    "berlin": ("Berlin", "Germany"),
    "munich": ("Munich", "Germany"),
    "münchen": ("Munich", "Germany"),
    "muenchen": ("Munich", "Germany"),
    "hamburg": ("Hamburg", "Germany"),
    "cologne": ("Cologne", "Germany"),
    "köln": ("Cologne", "Germany"),
    "koeln": ("Cologne", "Germany"),
    "frankfurt": ("Frankfurt", "Germany"),
    "paris": ("Paris", "France"),
    "lyon": ("Lyon", "France"),
    "toulouse": ("Toulouse", "France"),
    "madrid": ("Madrid", "Spain"),
    "barcelona": ("Barcelona", "Spain"),
    "valencia": ("Valencia", "Spain"),
    "lisbon": ("Lisbon", "Portugal"),
    "porto": ("Porto", "Portugal"),
    "milan": ("Milan", "Italy"),
    "milano": ("Milan", "Italy"),
    "rome": ("Rome", "Italy"),
    "roma": ("Rome", "Italy"),
    "turin": ("Turin", "Italy"),
    "amsterdam": ("Amsterdam", "Netherlands"),
    "rotterdam": ("Rotterdam", "Netherlands"),
    "the hague": ("The Hague", "Netherlands"),
    "brussels": ("Brussels", "Belgium"),
    "antwerp": ("Antwerp", "Belgium"),
    "zurich": ("Zurich", "Switzerland"),
    "zürich": ("Zurich", "Switzerland"),
    "geneva": ("Geneva", "Switzerland"),
    "vienna": ("Vienna", "Austria"),
    "wien": ("Vienna", "Austria"),
    "warsaw": ("Warsaw", "Poland"),
    "krakow": ("Krakow", "Poland"),
    "kraków": ("Krakow", "Poland"),
    "prague": ("Prague", "Czechia"),
    "praha": ("Prague", "Czechia"),
    "bratislava": ("Bratislava", "Slovakia"),
    "ljubljana": ("Ljubljana", "Slovenia"),
    "budapest": ("Budapest", "Hungary"),
    "bucharest": ("Bucharest", "Romania"),
    "sofia": ("Sofia", "Bulgaria"),
    "athens": ("Athens", "Greece"),
    "zagreb": ("Zagreb", "Croatia"),
    "copenhagen": ("Copenhagen", "Denmark"),
    "stockholm": ("Stockholm", "Sweden"),
    "gothenburg": ("Gothenburg", "Sweden"),
    "helsinki": ("Helsinki", "Finland"),
    "espoo": ("Espoo", "Finland"),
    "oslo": ("Oslo", "Norway"),
    "reykjavik": ("Reykjavik", "Iceland"),
    "tallinn": ("Tallinn", "Estonia"),
    "riga": ("Riga", "Latvia"),
    "vilnius": ("Vilnius", "Lithuania"),
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
_CITY_COUNTRY_PATTERNS = _compile({a: country for a, (_c, country) in _CITY_ALIASES.items()})
_CITY_NAME_PATTERNS = _compile({a: city for a, (city, _country) in _CITY_ALIASES.items()})
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
    for patterns in (_COUNTRY_PATTERNS, _CITY_COUNTRY_PATTERNS, _REGION_PATTERNS):
        for pattern, canonical in patterns:
            if pattern.search(text):
                return canonical
    return None


def resolve_city(location: str | None) -> str | None:
    """Return the canonical city for a known European city, else None.

    Coverage is the curated set above (major EU hubs). Unknown/smaller towns
    return None and callers fall back to the raw location.
    """
    if not location:
        return None
    text = location.lower()
    for pattern, canonical in _CITY_NAME_PATTERNS:
        if pattern.search(text):
            return canonical
    return None


def location_identity(location: str | None) -> str:
    """Canonical location string for dedup: "City, Country" | "Country" | "".

    Collapses spelling/format variants of the same place. Returns "" when the
    location is unknown/non-European, so callers fall back to the raw location.
    """
    city = resolve_city(location)
    country = resolve_country(location)
    return ", ".join(p for p in (city, country) if p)


def is_european(location: str | None) -> bool:
    return resolve_country(location) is not None
