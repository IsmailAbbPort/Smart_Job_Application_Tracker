"""Experience: extraction, soft de-ranking, and the optional hard cutoff."""

from __future__ import annotations

from app.ai.matching import experience_gap, experience_weight
from app.ingest.experience import extract_min_years_experience
from app.models import Cv, Job


def _job(sid, *, embedding=None, min_years=None) -> Job:
    return Job(
        source="test",
        source_id=sid,
        title="Engineer",
        company="Acme",
        url=f"https://example.com/{sid}",
        is_remote=True,
        is_european=True,
        embedding=embedding,
        min_years_experience=min_years,
    )


# --- unit ---


def test_extract_min_years_experience():
    assert extract_min_years_experience("5+ years of experience required") == 5
    assert extract_min_years_experience("We want 3-5 years experience") == 3
    assert extract_min_years_experience("8+ years building backend systems") == 8
    # Takes the minimum stated requirement (entry bar).
    assert extract_min_years_experience("2+ years support; 7+ years engineering experience") == 2
    # Reverse phrasing, en-dash ranges, and "years of <domain> experience".
    assert extract_min_years_experience("Experience: 6+ years in backend roles") == 6
    assert extract_min_years_experience("2–4 years of administrative experience") == 2
    assert extract_min_years_experience("5+ years of Product Management experience") == 5
    # Spelled out with a parenthetical numeral: "seven (7) years of experience".
    assert (
        extract_min_years_experience(
            "At least seven (7) years of experience as a software engineer"
        )
        == 7
    )
    # Not a requirement.
    assert extract_min_years_experience("Founded 10 years ago.") is None
    assert extract_min_years_experience("No experience required.") is None
    assert extract_min_years_experience("") is None


def test_experience_gap_and_weight():
    assert experience_gap(7, 3) == 4
    assert experience_gap(2, 5) == -3
    assert experience_gap(None, 3) is None
    assert experience_gap(5, None) is None
    # weight: meeting/under the bar or unknown is neutral; over is penalized + floored.
    assert experience_weight(None, penalty_per_year=0.1, floor=0.5) == 1.0
    assert experience_weight(-2, penalty_per_year=0.1, floor=0.5) == 1.0
    assert experience_weight(3, penalty_per_year=0.1, floor=0.5) == 0.7
    assert experience_weight(20, penalty_per_year=0.1, floor=0.5) == 0.5  # floored


# --- routes: soft de-ranking + hard cutoff ---


def _seed(session_factory):
    with session_factory() as s:
        s.add(Cv(label="cv", content="x", embedding=[1.0, 0.0, 0.0]))
        s.add_all(
            [
                _job("junior", embedding=[1.0, 0.0, 0.0], min_years=2),
                _job("senior", embedding=[1.0, 0.0, 0.0], min_years=12),
                _job("unstated", embedding=[1.0, 0.0, 0.0], min_years=None),
            ]
        )
        s.commit()


def test_experience_soft_deranks_but_keeps(client, session_factory):
    _seed(session_factory)
    client.put("/preferences", json={"years_experience": 3})
    items = client.get("/match/shortlist").json()["items"]
    ids = [i["source_id"] for i in items]
    # All three still present (soft), but the 12-year role is pushed below the others.
    assert set(ids) == {"junior", "senior", "unstated"}
    assert ids.index("senior") == len(ids) - 1
    senior = next(i for i in items if i["source_id"] == "senior")
    assert senior["experience_gap"] == 9  # 12 - 3


def test_experience_hard_cutoff_drops(client, session_factory):
    _seed(session_factory)
    client.put("/preferences", json={"years_experience": 3})
    ids = {
        i["source_id"]
        for i in client.get("/match/shortlist", params={"max_experience_gap": 3}).json()["items"]
    }
    # senior (gap 9 > 3) dropped; junior (gap -1) and unstated (unknown) kept.
    assert ids == {"junior", "unstated"}
