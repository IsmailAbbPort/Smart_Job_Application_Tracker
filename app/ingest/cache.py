"""Per-source fetch throttle - the durable cache guard that respects rate limits.

The database already caches jobs (the API never live-hits sources). This adds the
second layer: before an ingest run calls a source, we check when we last fetched it
and skip if we're within that source's TTL. State lives in the `source_fetch` table
so it survives restarts. No Redis.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import SourceFetch


def last_fetch(session: Session, source: str) -> SourceFetch | None:
    return session.get(SourceFetch, source)


def should_fetch(
    session: Session, source: str, ttl_seconds: int, *, now: datetime | None = None
) -> bool:
    """True if we've never fetched this source or the TTL has elapsed."""
    record = last_fetch(session, source)
    if record is None:
        return True
    now = now or datetime.now(UTC)
    last = record.last_fetched_at
    if last.tzinfo is None:  # SQLite may hand back naive datetimes
        last = last.replace(tzinfo=UTC)
    return (now - last).total_seconds() >= ttl_seconds


def record_fetch(
    session: Session,
    source: str,
    *,
    status: str,
    count: int,
    now: datetime | None = None,
) -> None:
    """Upsert the last-fetch record for a source."""
    now = now or datetime.now(UTC)
    record = session.get(SourceFetch, source)
    if record is None:
        record = SourceFetch(source=source)
        session.add(record)
    record.last_fetched_at = now
    record.last_status = status
    record.last_count = count


def seconds_until_ready(
    session: Session, source: str, ttl_seconds: int, *, now: datetime | None = None
) -> int:
    """How long until this source may be fetched again (0 if ready now)."""
    record = last_fetch(session, source)
    if record is None:
        return 0
    now = now or datetime.now(UTC)
    last = record.last_fetched_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    remaining = ttl_seconds - (now - last).total_seconds()
    return max(0, int(remaining))
