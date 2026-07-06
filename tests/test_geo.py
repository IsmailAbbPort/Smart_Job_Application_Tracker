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
        None,
        "",
    ],
)
def test_resolve_country_non_european(location):
    assert resolve_country(location) is None
    assert is_european(location) is False


def test_is_european_true():
    assert is_european("Remote, Spain") is True


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
        ("Austin, TX", ""),
    ],
)
def test_location_identity(location, expected):
    assert location_identity(location) == expected
