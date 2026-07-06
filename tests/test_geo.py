"""Unit tests for European country resolution."""

from __future__ import annotations

import pytest

from app.ingest.geo import is_european, location_identity, resolve_city, resolve_country


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Remote, Germany", "Germany"),
        ("Berlin, Germany; Helsinki, Finland", "Germany"),  # first hit wins
        ("Paris", "France"),  # city -> country
        ("London", "United Kingdom"),
        ("Amsterdam", "Netherlands"),
        ("Europe", "Europe"),  # region token
        ("EMEA", "Europe"),
        ("Remote - UK", "United Kingdom"),
    ],
)
def test_resolve_country_european(location, expected):
    assert resolve_country(location) == expected


@pytest.mark.parametrize(
    "location",
    [
        "Aurora, IL, United States",
        "Remote, US",
        "Worldwide",
        "Remote",
        "Anywhere",
        "San Francisco, CA",
        "Toronto, Ontario, Canada",
        "Singapore",
        None,
        "",
    ],
)
def test_non_european_not_flagged(location):
    # country may resolve (e.g. United States), but is_european must be False.
    assert is_european(location) is False
    assert resolve_city(location) is None  # city is European-only


@pytest.mark.parametrize(
    ("location", "expected_country"),
    [
        ("Aurora, IL, United States", "United States"),
        ("Remote, US", "United States"),
        ("Toronto, Ontario, Canada", "Canada"),
        ("Worldwide", None),
        ("Remote", None),
    ],
)
def test_resolve_country_non_european_value(location, expected_country):
    assert resolve_country(location) == expected_country


def test_is_european_true():
    assert is_european("Remote, Spain") is True


def test_country_needs_full_segment_not_fragment():
    # "wales" inside "New South Wales" must NOT resolve to the UK.
    assert resolve_country("Sydney, New South Wales, Australia") == "Australia"
    assert is_european("Sydney, New South Wales, Australia") is False
    # But "Wales" as its own segment still resolves to the UK.
    assert resolve_country("Cardiff, Wales") == "United Kingdom"


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Munich", "Munich"),
        ("Munich, Germany", "Munich"),
        ("München", "Munich"),
        ("München, Bavaria, Germany", "Munich"),
        ("Augsburg, Germany; Munich, Germany", "Munich"),  # first known city wins
        ("Paris", "Paris"),
        ("Remote, Germany", None),  # country only, no known city
        ("Aurora, IL, United States", None),
        (None, None),
    ],
)
def test_resolve_city(location, expected):
    assert resolve_city(location) == expected


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Munich", "Munich, Germany"),
        ("Munich, Germany", "Munich, Germany"),
        ("München", "Munich, Germany"),
        ("Remote, Germany", "Germany"),  # country only
        ("Worldwide", ""),  # unknown -> empty (caller falls back to raw)
        ("Austin, TX", "United States"),  # US city: country resolves, city stays None
    ],
)
def test_location_identity(location, expected):
    assert location_identity(location) == expected
