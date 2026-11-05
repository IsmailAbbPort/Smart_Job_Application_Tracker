"""pipeline_run lifecycle + the startup catch-up decision (app/scheduler.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app import scheduler
from app.config import Settings
from app.models import PipelineRun

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


# --- should_catch_up: pure, no clock patching, no scheduler, no database --------


def test_catch_up_when_there_is_no_previous_run():
    assert scheduler.should_catch_up(None, NOW, 20) is True


def test_catch_up_when_the_last_run_is_stale():
    assert scheduler.should_catch_up(NOW - timedelta(hours=30), NOW, 20) is True


def test_no_catch_up_when_the_last_run_is_fresh():
    assert scheduler.should_catch_up(NOW - timedelta(hours=2), NOW, 20) is False


def test_threshold_boundary_is_not_stale():
    # Exactly at the threshold has not yet exceeded it; only older than it counts.
    assert scheduler.should_catch_up(NOW - timedelta(hours=20), NOW, 20) is False
    assert scheduler.should_catch_up(NOW - timedelta(hours=20, seconds=1), NOW, 20) is True


def test_naive_last_success_is_treated_as_utc():
    # SQLite hands back naive datetimes; comparing them to an aware `now` would raise.
    assert scheduler.should_catch_up(datetime(2026, 11, 5, 10, 0), NOW, 20) is False


# --- run row lifecycle ---------------------------------------------------------


def _stub_pipeline(monkeypatch, calls, *, sources=None, raises=None):
    """Stub ingest/classify/sweep so the run-row logic is what's under test."""
    from app import shortlist
    from app.ai import role_family
    from app.ingest import runner

    class _Summary:
        def as_dict(self):
            return {
                "totals": {"inserted": 3, "updated": 1, "removed_stale": 0},
                "sources": (
                    sources
                    if sources is not None
                    else [{"source": "greenhouse", "inserted": 3, "error": None}]
                ),
            }

    def _ingest(session):
        calls.append("ingest")
        if raises is not None:
            raise raises
        return _Summary()

    monkeypatch.setattr(runner, "ingest_all", _ingest)
    monkeypatch.setattr(role_family, "get_role_classifier", lambda s: None)
    monkeypatch.setattr(
        shortlist, "sweep_saved_shortlists", lambda session: {"checked": 0, "deleted": 0}
    )


def test_successful_run_closes_its_row_as_ok(monkeypatch, session_factory):
    monkeypatch.setattr(
        scheduler, "get_settings", lambda: Settings(openai_api_key=None, anthropic_api_key=None)
    )
    _stub_pipeline(monkeypatch, [])

    scheduler.run_daily_pipeline(session_factory)

    with session_factory() as s:
        row = s.query(PipelineRun).one()
    assert row.status == "ok"
    assert row.trigger == "schedule"
    assert row.inserted == 3
    assert row.finished_at is not None
    assert row.error is None


def test_a_source_error_closes_the_row_as_partial(monkeypatch, session_factory):
    monkeypatch.setattr(
        scheduler, "get_settings", lambda: Settings(openai_api_key=None, anthropic_api_key=None)
    )
    _stub_pipeline(
        monkeypatch,
        [],
        sources=[
            {"source": "greenhouse", "inserted": 3, "error": None},
            {"source": "remotive", "inserted": 0, "error": "ConnectError: boom"},
        ],
    )

    scheduler.run_daily_pipeline(session_factory)

    with session_factory() as s:
        row = s.query(PipelineRun).one()
    assert row.status == "partial"
    # The per-source error has to survive into the row, or the notifier cannot name it.
    assert any(src["error"] for src in row.sources["sources"])


def test_a_raising_pipeline_closes_its_row_as_failed(monkeypatch, session_factory):
    # Regression: without try/finally a crash left the row 'running' forever, which
    # the next startup would misread as "interrupted" on every single boot.
    monkeypatch.setattr(
        scheduler, "get_settings", lambda: Settings(openai_api_key=None, anthropic_api_key=None)
    )
    _stub_pipeline(monkeypatch, [], raises=RuntimeError("db exploded"))

    with pytest.raises(RuntimeError):
        scheduler.run_daily_pipeline(session_factory)

    with session_factory() as s:
        row = s.query(PipelineRun).one()
    assert row.status == "failed"
    assert row.finished_at is not None
    assert "db exploded" in row.error


def test_catchup_trigger_is_recorded(monkeypatch, session_factory):
    monkeypatch.setattr(
        scheduler, "get_settings", lambda: Settings(openai_api_key=None, anthropic_api_key=None)
    )
    _stub_pipeline(monkeypatch, [])

    scheduler.run_daily_pipeline(session_factory, trigger="catchup")

    with session_factory() as s:
        assert s.query(PipelineRun).one().trigger == "catchup"


# --- re-entrancy ---------------------------------------------------------------


def test_second_concurrent_run_skips_and_writes_no_row(monkeypatch, session_factory):
    # max_instances=1 is per job id, so cron and catchup can overlap; the module
    # lock is what actually prevents two pipelines at once.
    monkeypatch.setattr(
        scheduler, "get_settings", lambda: Settings(openai_api_key=None, anthropic_api_key=None)
    )
    _stub_pipeline(monkeypatch, [])

    assert scheduler._RUN_LOCK.acquire(blocking=False)
    try:
        result = scheduler.run_daily_pipeline(session_factory)
    finally:
        scheduler._RUN_LOCK.release()

    assert result == {"skipped": "already running"}
    with session_factory() as s:
        assert s.query(PipelineRun).count() == 0


def test_the_lock_is_released_after_a_crash(monkeypatch, session_factory):
    # A leaked lock would make every later run skip, write no row, and notify
    # nothing - total silence, which is indistinguishable from a dead stack.
    monkeypatch.setattr(
        scheduler, "get_settings", lambda: Settings(openai_api_key=None, anthropic_api_key=None)
    )
    _stub_pipeline(monkeypatch, [], raises=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        scheduler.run_daily_pipeline(session_factory)

    assert scheduler._RUN_LOCK.acquire(blocking=False)
    scheduler._RUN_LOCK.release()


# --- startup wiring ------------------------------------------------------------


def test_start_scheduler_registers_catchup_when_the_last_run_is_stale(monkeypatch, session_factory):
    with session_factory() as s:
        s.add(
            PipelineRun(
                status="ok",
                trigger="schedule",
                started_at=datetime(2026, 11, 1, 3, 0, tzinfo=UTC),
                finished_at=datetime(2026, 11, 1, 3, 5, tzinfo=UTC),
            )
        )
        s.commit()
    monkeypatch.setattr(scheduler, "get_settings", lambda: Settings(ingest_schedule_enabled=True))
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)

    scheduler.stop_scheduler()
    scheduler.start_scheduler()
    try:
        assert scheduler._scheduler.get_job("catchup_ingest") is not None
    finally:
        scheduler.stop_scheduler()


def test_start_scheduler_skips_catchup_when_the_last_run_is_fresh(monkeypatch, session_factory):
    with session_factory() as s:
        s.add(
            PipelineRun(
                status="ok",
                trigger="schedule",
                started_at=datetime.now(UTC) - timedelta(hours=1),
                finished_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        s.commit()
    monkeypatch.setattr(scheduler, "get_settings", lambda: Settings(ingest_schedule_enabled=True))
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)

    scheduler.stop_scheduler()
    scheduler.start_scheduler()
    try:
        assert scheduler._scheduler.get_job("catchup_ingest") is None
        assert scheduler._scheduler.get_job("daily_ingest") is not None
    finally:
        scheduler.stop_scheduler()


def test_start_scheduler_survives_an_unreachable_database(monkeypatch):
    # start_scheduler() touches no DB today, so it cannot fail. Adding the catch-up
    # query must not make an unreachable DB at startup take the whole app down -
    # that is the laptop-resume case this feature exists for.
    def _explode():
        raise RuntimeError("could not connect to server")

    monkeypatch.setattr(scheduler, "get_settings", lambda: Settings(ingest_schedule_enabled=True))
    monkeypatch.setattr(scheduler, "SessionLocal", _explode)

    scheduler.stop_scheduler()
    scheduler.start_scheduler()
    try:
        assert scheduler._scheduler is not None
        assert scheduler._scheduler.get_job("daily_ingest") is not None
        assert scheduler._scheduler.get_job("catchup_ingest") is None
    finally:
        scheduler.stop_scheduler()
