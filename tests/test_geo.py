"""Unit tests for European country resolution."""

from __future__ import annotations

import pytest

from app.ingest.geo import (
    country_codes_mentioned,
    is_european,
    location_identity,
    resolve_city,
    resolve_country,
    resolve_country_codes,
)


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


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        # Every country, not just the first: a multi-country repost allows both.
        ("Remote, Canada; Remote, United States", ["CA", "US"]),
        ("Remote - United States", ["US"]),
        ("Sweden (Remote)", ["SE"]),
        ("Republic of Ireland (Remote)", ["IE"]),
        ("All France (remote)", ["FR"]),  # stopword-trimmed segment still resolves
        ("Remote-EMEA", ["EU"]),
        ("Remote, Bangalore", ["IN"]),
        ("Yerevan", ["AM"]),
        ("New South Wales, Australia", ["AU"]),
        # No place named: unknown, so callers keep the job.
        ("Remote", []),
        ("Worldwide", []),
        ("", []),
        (None, []),
    ],
)
def test_resolve_country_codes(location, expected):
    assert resolve_country_codes(location) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Must be located in France", ["FR"]),
        (
            "candidates in the UK, Germany, Spain, Ireland and Sweden",
            ["DE", "ES", "GB", "IE", "SE"],
        ),
        ("remote within the EU", ["EU"]),
        ("Are you located in the UK or Poland?", ["GB", "PL"]),
        # "us" as a pronoun must never read as the United States, so the short aliases
        # only match in upper case.
        ("join us in Berlin and help us grow", []),
        ("executed globally", []),
    ],
)
def test_country_codes_mentioned(text, expected):
    assert country_codes_mentioned(text) == expected
