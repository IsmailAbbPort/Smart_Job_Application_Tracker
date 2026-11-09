"""pipeline_run lifecycle + the startup catch-up decision (app/scheduler.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
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


def _stub_pipeline(monkeypatch, calls, *, sources=None, raises=None, sweep_raises=None):
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

    def _sweep(session):
        if sweep_raises is not None:
            raise sweep_raises
        return {"checked": 0, "deleted": 0}

    monkeypatch.setattr(runner, "ingest_all", _ingest)
    monkeypatch.setattr(role_family, "get_role_classifier", lambda s: None)
    monkeypatch.setattr(shortlist, "sweep_saved_shortlists", _sweep)


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


def test_a_failure_after_ingest_still_records_what_was_ingested(monkeypatch, session_factory):
    # The failure path used to hardcode inserted=0 and write no counts or sources at
    # all, so a run that ingested 3 jobs and then died in the sweep was stored as
    # having done nothing. /ops/runs and the message then under-reported real work,
    # and the next run's "N new jobs" could not be read against it.
    monkeypatch.setattr(
        scheduler, "get_settings", lambda: Settings(openai_api_key=None, anthropic_api_key=None)
    )
    _stub_pipeline(monkeypatch, [], sweep_raises=RuntimeError("sweep exploded"))

    with pytest.raises(RuntimeError):
        scheduler.run_daily_pipeline(session_factory)

    with session_factory() as s:
        row = s.query(PipelineRun).one()
    assert row.status == "failed"
    assert "sweep exploded" in row.error
    assert row.inserted == 3
    assert row.updated == 1
    assert [src["source"] for src in row.sources["sources"]] == ["greenhouse"]


def test_an_embedding_failure_degrades_the_run_instead_of_killing_it(monkeypatch, session_factory):
    # The embed call had no try/except, so an exhausted OpenAI balance took the whole
    # run down: the liveness sweep never ran, and the exception reached the taxonomy
    # flattened to a string, where the provider (and so the real remedy) is invisible.
    import openai

    from app.ai import embedder as embedder_mod
    from app.models import Job

    quota = openai.RateLimitError(
        "You exceeded your current quota",
        response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com/v1")),
        body={"error": {"code": "insufficient_quota"}},
    )

    class _BrokenEmbedder:
        def __init__(self, *args, **kwargs):
            pass

        def embed(self, texts):
            raise quota

    with session_factory() as s:
        s.add(
            Job(
                source="greenhouse",
                source_id="1",
                title="Backend Engineer",
                company="Acme",
                url="https://example.com/1",
            )
        )
        s.commit()

    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: Settings(openai_api_key="sk-test", anthropic_api_key=None),
    )
    monkeypatch.setattr(embedder_mod, "OpenAIEmbedder", _BrokenEmbedder)
    _stub_pipeline(monkeypatch, [])

    summary = scheduler.run_daily_pipeline(session_factory)

    # The run finished, so the sweep ran and the ingest is reported.
    assert "liveness" in summary
    with session_factory() as s:
        row = s.query(PipelineRun).one()
    assert row.status == "ok"
    assert row.inserted == 3
    assert row.embedded == 0
    # Named as a credit problem, with the provider, because the live exception survived.
    assert [p["code"] for p in row.problems] == ["credits:openai"]


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


def test_the_catchup_job_tolerates_a_misfire(monkeypatch, session_factory):
    # The catch-up fires 60s after startup. Without a grace window, a laptop busy
    # with its own resume work (Docker starting, disks spinning up) could let that
    # one-shot slip past its run_date, and APScheduler then drops it silently - so
    # the job that exists to recover a missed day would itself be the missed day.
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
        assert scheduler._scheduler.get_job("catchup_ingest").misfire_grace_time == 3600
    finally:
        scheduler.stop_scheduler()


def test_the_interrupted_notice_is_not_sent_on_the_startup_thread(monkeypatch, session_factory):
    # send_message is a blocking 10s HTTP post. On the lifespan thread that is 10s
    # of an app that is not yet serving, and it shared a try/except with the catch-up
    # decision, so a slow bot could swallow the catch-up as collateral.
    sent: list[str] = []
    with session_factory() as s:
        s.add(PipelineRun(status="running", trigger="schedule", started_at=datetime.now(UTC)))
        s.commit()
    monkeypatch.setattr(scheduler, "get_settings", lambda: Settings(ingest_schedule_enabled=True))
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(
        "app.notify.telegram.send_message", lambda text, settings=None: sent.append(text) or True
    )

    scheduler.stop_scheduler()
    scheduler.start_scheduler()
    try:
        assert sent == []
        assert scheduler._scheduler.get_job("interrupted_notice") is not None
        # The leftover row is still closed synchronously: the catch-up decision
        # immediately below it reads that row.
        with session_factory() as s:
            assert s.query(PipelineRun).one().status == "failed"
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
