"""Ingest runner: upsert idempotency, cross-source dedup, throttle, error handling."""

from __future__ import annotations

from sqlalchemy import func, select

from app.ingest import runner
from app.models import Job
from tests.conftest import BrokenSource, FakeSource, make_canonical

_DUMMY_CLIENT = object()  # FakeSource.fetch ignores the client


def _count(session) -> int:
    return session.scalar(select(func.count()).select_from(Job)) or 0


def test_registry_has_all_five_sources():
    assert set(runner.SOURCES) == {"greenhouse", "lever", "ashby", "arbeitnow", "remotive"}


def test_insert_then_reingest_updates(session, monkeypatch):
    jobs = [make_canonical(source_id="1"), make_canonical(source_id="2", title="Frontend Engineer")]
    monkeypatch.setitem(runner.SOURCES, "fake", FakeSource("fake", jobs))

    first = runner.ingest_source(session, "fake", force=True, client=_DUMMY_CLIENT)
    assert (first.inserted, first.updated, first.deduped) == (2, 0, 0)
    assert _count(session) == 2

    # Re-poll: same (source, source_id) pairs -> updates, no new rows.
    second = runner.ingest_source(session, "fake", force=True, client=_DUMMY_CLIENT)
    assert (second.inserted, second.updated) == (0, 2)
    assert _count(session) == 2


def test_reingest_applies_field_changes(session, monkeypatch):
    monkeypatch.setitem(runner.SOURCES, "fake", FakeSource("fake", [make_canonical(source_id="1")]))
    runner.ingest_source(session, "fake", force=True, client=_DUMMY_CLIENT)

    updated_job = make_canonical(source_id="1", title="Staff Engineer", is_remote=False)
    monkeypatch.setitem(runner.SOURCES, "fake", FakeSource("fake", [updated_job]))
    runner.ingest_source(session, "fake", force=True, client=_DUMMY_CLIENT)

    row = session.scalar(select(Job).where(Job.source == "fake", Job.source_id == "1"))
    assert row.title == "Staff Engineer"
    assert row.is_remote is False
    assert row.title_norm == "staff engineer"


def test_cross_source_dedup(session, monkeypatch):
    same = dict(title="Senior Backend Engineer", company="GitLab", location="Remote, Germany")
    monkeypatch.setitem(
        runner.SOURCES, "srca", FakeSource("srca", [make_canonical(source_id="a1", **same)])
    )
    monkeypatch.setitem(
        runner.SOURCES, "srcb", FakeSource("srcb", [make_canonical(source_id="b1", **same)])
    )

    runner.ingest_source(session, "srca", force=True, client=_DUMMY_CLIENT)
    stats_b = runner.ingest_source(session, "srcb", force=True, client=_DUMMY_CLIENT)

    # The same real role from a second source is dropped, not stored twice.
    assert stats_b.deduped == 1
    assert stats_b.inserted == 0
    assert _count(session) == 1


def test_throttle_skips_second_run(session, monkeypatch):
    monkeypatch.setitem(runner.SOURCES, "fake", FakeSource("fake", [make_canonical(source_id="1")]))

    first = runner.ingest_source(session, "fake", client=_DUMMY_CLIENT)  # force defaults to False
    assert first.inserted == 1
    assert first.skipped_throttled is False

    # Immediately again, within TTL -> throttled, no fetch.
    second = runner.ingest_source(session, "fake", client=_DUMMY_CLIENT)
    assert second.skipped_throttled is True
    assert second.fetched == 0
    assert _count(session) == 1


def test_force_bypasses_throttle(session, monkeypatch):
    monkeypatch.setitem(runner.SOURCES, "fake", FakeSource("fake", [make_canonical(source_id="1")]))
    runner.ingest_source(session, "fake", client=_DUMMY_CLIENT)
    forced = runner.ingest_source(session, "fake", force=True, client=_DUMMY_CLIENT)
    assert forced.skipped_throttled is False


def test_error_is_captured_not_raised(session, monkeypatch):
    monkeypatch.setitem(runner.SOURCES, "broken", BrokenSource())
    stats = runner.ingest_source(session, "broken", force=True, client=_DUMMY_CLIENT)
    assert stats.error is not None
    assert "boom" in stats.error
    assert _count(session) == 0


def test_geo_derived_on_ingest(session, monkeypatch):
    jobs = [
        make_canonical(source_id="eu", location="Remote, Germany"),
        make_canonical(source_id="muc", location="München"),
        make_canonical(source_id="us", location="Aurora, IL, United States"),
        make_canonical(source_id="ww", location="Worldwide"),
    ]
    monkeypatch.setitem(runner.SOURCES, "fake", FakeSource("fake", jobs))
    runner.ingest_source(session, "fake", force=True, client=_DUMMY_CLIENT)

    by_id = {j.source_id: j for j in session.scalars(select(Job)).all()}
    assert by_id["eu"].country == "Germany" and by_id["eu"].is_european is True
    assert by_id["eu"].city is None  # country only, no known city
    assert by_id["muc"].city == "Munich" and by_id["muc"].country == "Germany"
    # US country resolves, but it is not European and has no (European) city.
    assert by_id["us"].country == "United States"
    assert by_id["us"].is_european is False and by_id["us"].city is None
    assert by_id["ww"].is_european is False  # "Worldwide" is not treated as European


def test_unknown_source_raises(session):
    try:
        runner.ingest_source(session, "does-not-exist", force=True)
    except KeyError:
        return
    raise AssertionError("expected KeyError for unknown source")
