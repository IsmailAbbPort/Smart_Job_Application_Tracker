"""Unit tests for normalization, dedup keys, HTML stripping, and date parsing."""

from __future__ import annotations

from datetime import UTC

import pytest

from app.ingest.normalize import (
    dedup_key,
    html_to_text,
    looks_remote,
    normalize_company,
    normalize_location,
    normalize_title,
    parse_dt,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GitLab", "gitlab"),
        ("Qonto SAS", "qonto"),
        ("Activate Media GmbH", "activate media"),
        ("Back Market, Inc.", "back market"),
        ("N26 GmbH", "n26"),
        ("  Wise   Ltd  ", "wise"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_company(raw, expected):
    assert normalize_company(raw) == expected


def test_normalize_title_keeps_seniority():
    assert normalize_title("Senior Backend Engineer (Remote!)") == "senior backend engineer remote"
    # Seniority is meaningful for dedup, so "Senior X" != "X".
    assert normalize_title("Senior Data Scientist") != normalize_title("Data Scientist")


def test_normalize_location():
    assert normalize_location("Remote, Germany") == "remote, germany"
    assert normalize_location(None) == ""


def test_dedup_key_is_stable_across_formatting():
    a = dedup_key("GitLab Inc.", "Senior  Backend Engineer", "Remote, Germany")
    b = dedup_key("gitlab", "senior backend engineer", "remote, germany")
    # Location resolves to the canonical country identity (Germany).
    assert a == b == "gitlab|senior backend engineer|germany"


def test_dedup_key_collapses_city_variants():
    keys = {
        dedup_key("Personio", "Backend Engineer", loc)
        for loc in ["Munich", "Munich, Germany", "München", "Munich, Bavaria, Germany"]
    }
    # Every Munich spelling/format collapses to one dedup key.
    assert keys == {"personio|backend engineer|munich, germany"}


def test_dedup_key_differs_on_title():
    assert dedup_key("GitLab", "Senior Engineer", "Remote") != dedup_key(
        "GitLab", "Junior Engineer", "Remote"
    )


def test_html_to_text_strips_tags_and_double_unescapes():
    # Greenhouse-style entity-escaped HTML with a nested &amp;amp; entity.
    raw = "&lt;div&gt;&lt;p&gt;Build &amp;amp; ship.&lt;/p&gt;&lt;/div&gt;"
    assert html_to_text(raw) == "Build & ship."


def test_html_to_text_plain_html():
    assert html_to_text("<p>Join our <strong>remote</strong> team</p>") == "Join our remote team"
    assert html_to_text("") == ""
    assert html_to_text(None) == ""


def test_looks_remote():
    assert looks_remote("Remote, Italy") is True
    assert looks_remote(None, "Fully Remote Engineer") is True
    assert looks_remote("Berlin", "Office Manager") is False


def test_parse_dt_epoch_seconds():
    dt = parse_dt(1751792400)
    assert dt is not None and dt.tzinfo == UTC and dt.year == 2025


def test_parse_dt_epoch_millis():
    dt = parse_dt(1753687796431)
    assert dt is not None and dt.tzinfo == UTC and dt.year == 2025


def test_parse_dt_iso_with_offset():
    dt = parse_dt("2026-04-20T20:17:19.177+00:00")
    assert dt is not None and dt.year == 2026 and dt.tzinfo is not None


def test_parse_dt_naive_iso_assumed_utc():
    dt = parse_dt("2026-07-02T20:01:13")
    assert dt is not None and dt.tzinfo == UTC and dt.month == 7


def test_parse_dt_digit_string():
    dt = parse_dt("1751792400")
    assert dt is not None and dt.year == 2025


@pytest.mark.parametrize("bad", [None, "", "not-a-date"])
def test_parse_dt_bad_values(bad):
    assert parse_dt(bad) is None
