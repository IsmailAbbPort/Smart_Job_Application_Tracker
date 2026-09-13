"""Region -> country mapping (app/geo_region.py) and the shortlist region filter."""

from __future__ import annotations

import pytest

from app.geo_region import region_country_names
from app.models import Cv, Job

# --- unit: region_country_names ---


@pytest.mark.parametrize(
    "region,expected",
    [
        ("europe", "germany"),
        ("asia", "japan"),
        ("africa", "nigeria"),
        ("oceania", "australia"),
        ("north_america", "united states"),
        ("latin_america", "brazil"),
    ],
)
def test_each_region_contains_a_known_country(region, expected):
    names = region_country_names(region)
    assert names, f"{region} resolved to no countries"
    assert expected in names


def test_names_are_lowercased():
    assert all(n == n.lower() for n in region_country_names("europe"))


def test_latin_america_split_from_north_america():
    # Mexico is a NA continent-code country, but curated into Latin America.
    assert "mexico" in region_country_names("latin_america")
    assert "mexico" not in region_country_names("north_america")
    # The US stays in North America and never leaks into Latin America.
    assert "united states" in region_country_names("north_america")
    assert "united states" not in region_country_names("latin_america")


def test_region_slug_is_case_insensitive_and_trimmed():
    assert region_country_names("  EUROPE ") == region_country_names("europe")


def test_unknown_region_is_empty():
    assert region_country_names("atlantis") == frozenset()
    assert region_country_names("") == frozenset()


# --- integration: /match/shortlist?region=... filters by country ---


def _job(sid, country):
    # Same (perfect) embedding for all, so ranking never hides a region mismatch.
    return Job(
        source="test",
        source_id=sid,
        title="Engineer",
        company="Acme",
        url=f"https://example.com/{sid}",
        is_remote=True,
        is_european=True,
        country=country,
        embedding=[1.0, 0.0, 0.0],
    )


def _seed(session_factory):
    with session_factory() as s:
        s.add(Cv(label="cv", content="x", embedding=[1.0, 0.0, 0.0]))
        s.add_all(
            [
                _job("de", "Germany"),
                _job("us", "United States"),
                _job("mx", "Mexico"),
                _job("jp", "Japan"),
            ]
        )
        s.commit()


def _ids(client, region):
    body = client.get("/match/shortlist", params={"region": region, "limit": 10}).json()
    return {i["source_id"] for i in body["items"]}


def test_region_europe_keeps_only_european_country(client, session_factory):
    _seed(session_factory)
    assert _ids(client, "europe") == {"de"}


def test_region_north_america_excludes_mexico(client, session_factory):
    _seed(session_factory)
    assert _ids(client, "north_america") == {"us"}


def test_region_latin_america_keeps_mexico_only(client, session_factory):
    _seed(session_factory)
    assert _ids(client, "latin_america") == {"mx"}


def test_region_case_insensitive_in_query(client, session_factory):
    _seed(session_factory)
    assert _ids(client, "ASIA") == {"jp"}


def test_unknown_region_does_not_filter(client, session_factory):
    _seed(session_factory)
    # Unknown region maps to no countries -> no condition added -> all kept.
    assert _ids(client, "narnia") == {"de", "us", "mx", "jp"}
