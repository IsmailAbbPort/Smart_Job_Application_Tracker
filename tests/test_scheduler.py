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


def _pipeline_stubs(monkeypatch, settings, calls):
    from app import shortlist
    from app.ai import role_family
    from app.ingest import runner

    class _Summary:
        def as_dict(self):
            return {"totals": {"inserted": 0}}

    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "ingest_all", lambda session: calls.append("ingest") or _Summary())
    monkeypatch.setattr(
        role_family,
        "get_role_classifier",
        lambda s: role_family.FakeRoleClassifier() if s.anthropic_api_key else None,
    )
    monkeypatch.setattr(
        shortlist,
        "sweep_saved_shortlists",
        lambda session: calls.append("sweep") or {"checked": 0, "deleted": 0},
    )


def test_pipeline_classifies_and_sweeps_without_openai_key(monkeypatch, session_factory):
    # Regression: the pipeline returned early without OPENAI_API_KEY, so classification
    # (now LLM-based) and the liveness sweep silently never ran.
    from app.models import Job

    with session_factory() as s:
        s.add(Job(source="t", source_id="1", title="Corporate Paralegal", company="c", url="u"))
        s.commit()
    calls: list[str] = []
    _pipeline_stubs(monkeypatch, Settings(openai_api_key=None, anthropic_api_key="k"), calls)

    summary = scheduler.run_daily_pipeline(session_factory)

    assert calls == ["ingest", "sweep"]
    assert summary["embedded"] == 0 and summary["classified"] == 1
    with session_factory() as s:
        assert s.query(Job).one().role_family == "legal"


def test_pipeline_sweeps_even_with_no_ai_keys(monkeypatch, session_factory):
    calls: list[str] = []
    _pipeline_stubs(monkeypatch, Settings(openai_api_key=None, anthropic_api_key=None), calls)
    summary = scheduler.run_daily_pipeline(session_factory)
    assert calls == ["ingest", "sweep"]
    assert summary["classified"] == 0


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
