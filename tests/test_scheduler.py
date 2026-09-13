"""Daily ingest scheduler wiring (app/scheduler.py)."""

from __future__ import annotations

from app import scheduler
from app.config import Settings


def test_start_scheduler_is_noop_when_disabled():
    # conftest sets INGEST_SCHEDULE_ENABLED=false for the whole test run.
    scheduler.stop_scheduler()
    scheduler.start_scheduler()
    assert scheduler._scheduler is None


def test_scheduler_registers_daily_job_when_enabled(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: Settings(ingest_schedule_enabled=True, ingest_hour_utc=3),
    )
    scheduler.stop_scheduler()
    scheduler.start_scheduler()
    try:
        assert scheduler._scheduler is not None
        job = scheduler._scheduler.get_job("daily_ingest")
        assert job is not None
        assert "hour='3'" in str(job.trigger)
    finally:
        scheduler.stop_scheduler()
    assert scheduler._scheduler is None


def test_start_scheduler_is_idempotent(monkeypatch):
    monkeypatch.setattr(scheduler, "get_settings", lambda: Settings(ingest_schedule_enabled=True))
    scheduler.stop_scheduler()
    scheduler.start_scheduler()
    first = scheduler._scheduler
    scheduler.start_scheduler()  # second call must not replace the running scheduler
    try:
        assert scheduler._scheduler is first
    finally:
        scheduler.stop_scheduler()
