"""Map a continent/region slug to the set of country names it contains.

Backs the "Region" filter (frontend point 4). Job rows store a free-text country
name, so we resolve a region to the lowercased country names in it (via
geonamescache) and filter Job.country against that set. Best-effort: Latin America
is split out of the Americas by a curated list, since continent codes alone put
Mexico/Central America under North America.
"""

from __future__ import annotations

from functools import lru_cache

# geonamescache continent codes.
_CONTINENT = {
    "africa": {"AF"},
    "asia": {"AS"},
    "europe": {"EU"},
    "oceania": {"OC"},
    # The Americas are code NA (North) + SA (South); we split Latin America out below.
    "north_america": {"NA"},
    "latin_america": {"SA"},
}

# Latin American countries that geonamescache files under North America (NA).
# These move from "North America" into "Latin America".
_LATIN_IN_NA = {
    "Mexico",
    "Guatemala",
    "Belize",
    "Honduras",
    "El Salvador",
    "Nicaragua",
    "Costa Rica",
    "Panama",
    "Cuba",
    "Dominican Republic",
    "Haiti",
    "Puerto Rico",
}


@lru_cache
def _name_by_continent() -> dict[str, set[str]]:
    from geonamescache import GeonamesCache

    out: dict[str, set[str]] = {}
    for c in GeonamesCache().get_countries().values():
        out.setdefault(c["continentcode"], set()).add(c["name"])
    return out


@lru_cache
def region_country_names(region: str) -> frozenset[str]:
    """Lowercased country names in a region slug; empty for an unknown slug."""
    codes = _CONTINENT.get(region.strip().lower())
    if not codes:
        return frozenset()
    by_continent = _name_by_continent()
    names: set[str] = set()
    for code in codes:
        names |= by_continent.get(code, set())
    if region == "north_america":
        names -= _LATIN_IN_NA
    elif region == "latin_america":
        names |= _LATIN_IN_NA
    return frozenset(n.lower() for n in names)
