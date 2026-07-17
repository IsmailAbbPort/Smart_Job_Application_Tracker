"""Eligibility: sponsorship / remote-region / timezone detection + filters."""

from __future__ import annotations

from app.ingest.eligibility import (
    detect_remote_region,
    detect_visa_sponsorship,
    extract_required_utc_offsets,
    timezone_overlap_hours,
)
from app.models import Cv, Job


def _job(sid, *, embedding=None, visa=None, region=None, offsets=None, is_remote=True) -> Job:
    return Job(
        source="test",
        source_id=sid,
        title="Engineer",
        company="Acme",
        url=f"https://example.com/{sid}",
        is_remote=is_remote,
        is_european=True,
        embedding=embedding,
        visa_sponsorship=visa,
        remote_region=region,
        required_utc_offsets=offsets or [],
    )


# --- unit ---


def test_detect_visa_sponsorship():
    assert detect_visa_sponsorship("Visa sponsorship is available.") is True
    assert detect_visa_sponsorship("We are unable to sponsor visas.") is False
    assert detect_visa_sponsorship("You must already be authorized to work here.") is False
    assert detect_visa_sponsorship("Nothing about visas here.") is None


def test_detect_remote_region():
    assert detect_remote_region("Remote, US-based only.", is_remote=True) == "us"
    assert detect_remote_region("Remote within Europe.", is_remote=True) == "eu"
    assert detect_remote_region("We sell into the united states.", is_remote=True) is None
    assert detect_remote_region("US-based remote.", is_remote=False) is None  # on-site ignored


def test_timezone_extraction_and_overlap():
    assert extract_required_utc_offsets("Must work CET hours.") == [1]
    assert extract_required_utc_offsets("Overlap with PST.") == [-8]
    assert extract_required_utc_offsets("Distributed, async.") == []
    # Cairo (+2): great overlap with CET (+1), none with Pacific (-8).
    assert timezone_overlap_hours([1], 2) == 7
    assert timezone_overlap_hours([-8], 2) == 0
    assert timezone_overlap_hours([], 2) is None  # unknown requirement -> neutral


# --- filters ---


def test_require_sponsorship_filter(client, session_factory):
    with session_factory() as s:
        s.add_all([_job("yes", visa=True), _job("no", visa=False), _job("unknown", visa=None)])
        s.commit()
    client.put("/preferences", json={"require_sponsorship": True})
    ids = {i["source_id"] for i in client.get("/jobs").json()["items"]}
    assert ids == {"yes", "unknown"}  # explicit refusal dropped; unknown kept


def test_exclude_remote_regions_filter(client, session_factory):
    with session_factory() as s:
        s.add_all([_job("us", region="us"), _job("eu", region="eu"), _job("open", region=None)])
        s.commit()
    client.put("/preferences", json={"exclude_remote_regions": ["US"]})  # case-insensitive
    ids = {i["source_id"] for i in client.get("/jobs").json()["items"]}
    assert ids == {"eu", "open"}


def test_shortlist_timezone_overlap_gate(client, session_factory):
    with session_factory() as s:
        s.add(Cv(label="cv", content="x", embedding=[1.0, 0.0, 0.0]))
        s.add_all(
            [
                _job("cet", embedding=[1.0, 0.0, 0.0], offsets=[1]),  # +2 vs +1 -> 7h
                _job("pst", embedding=[1.0, 0.0, 0.0], offsets=[-8]),  # +2 vs -8 -> 0h
                _job("async", embedding=[1.0, 0.0, 0.0], offsets=[]),  # unknown -> kept
            ]
        )
        s.commit()
    client.put("/preferences", json={"user_utc_offset": 2, "min_timezone_overlap_hours": 4})
    items = client.get("/match/shortlist").json()["items"]
    ids = {i["source_id"] for i in items}
    assert ids == {"cet", "async"}  # PST dropped (0h < 4h); unknown kept
    cet = next(i for i in items if i["source_id"] == "cet")
    assert cet["timezone_overlap_hours"] == 7


def test_backfill_sets_eligibility(client, session_factory):
    with session_factory() as s:
        s.add(
            Job(
                source="test",
                source_id="j",
                title="Backend Engineer",
                company="Acme",
                url="https://example.com/j",
                is_remote=True,
                is_european=True,
                description=(
                    "Remote role, US-based only. We are unable to sponsor visas. "
                    "You must overlap with PST working hours. " * 3
                ),
            )
        )
        s.commit()
    client.post("/ingest/backfill")
    with session_factory() as s:
        job = s.query(Job).filter_by(source_id="j").one()
        assert job.visa_sponsorship is False
        assert job.remote_region == "us"
        assert job.required_utc_offsets == [-8]
