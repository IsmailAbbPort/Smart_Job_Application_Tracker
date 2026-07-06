"""Unit tests for the per-source fetch throttle (cache guard)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.ingest import cache

T0 = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)


def test_should_fetch_when_never_fetched(session):
    assert cache.should_fetch(session, "arbeitnow", 3600) is True


def test_should_not_fetch_within_ttl(session):
    cache.record_fetch(session, "remotive", status="ok", count=10, now=T0)
    session.commit()
    assert cache.should_fetch(session, "remotive", 3600, now=T0 + timedelta(minutes=30)) is False


def test_should_fetch_after_ttl(session):
    cache.record_fetch(session, "remotive", status="ok", count=10, now=T0)
    session.commit()
    assert cache.should_fetch(session, "remotive", 3600, now=T0 + timedelta(hours=2)) is True


def test_record_fetch_upserts(session):
    cache.record_fetch(session, "lever", status="ok", count=5, now=T0)
    session.commit()
    cache.record_fetch(session, "lever", status="error", count=0, now=T0 + timedelta(hours=1))
    session.commit()

    record = cache.last_fetch(session, "lever")
    assert record.last_status == "error"
    assert record.last_count == 0
    assert record.last_fetched_at.replace(tzinfo=UTC) == T0 + timedelta(hours=1)


def test_seconds_until_ready(session):
    cache.record_fetch(session, "ashby", status="ok", count=1, now=T0)
    session.commit()
    remaining = cache.seconds_until_ready(session, "ashby", 3600, now=T0 + timedelta(minutes=10))
    assert remaining == 3000


def test_seconds_until_ready_zero_when_never_fetched(session):
    assert cache.seconds_until_ready(session, "greenhouse", 3600) == 0
