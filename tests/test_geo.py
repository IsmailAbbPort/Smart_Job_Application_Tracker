"""Unit tests for European country resolution."""

from __future__ import annotations

import pytest

from app.ingest.geo import is_european, resolve_country


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
