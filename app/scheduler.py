"""Daily ingest scheduler.

Runs the ingest -> embed -> classify -> liveness sweep pipeline once a day, in-process, via
APScheduler. A single-container deploy stays fresh with no extra infrastructure
(no cron container, no worker, no Redis). Every step it calls is idempotent, so a
missed run (downtime) or a repeated run is harmless.

Two jobs, not one. `daily_ingest` is the cron job; `catchup_ingest` is a one-shot
registered at startup when the last recorded run is stale, because a laptop asleep
through `ingest_hour_utc` used to skip the day silently and nothing afterwards could
tell. `max_instances=1` is tracked per job id, so it does not stop those two from
overlapping - `_RUN_LOCK` is what actually guarantees one pipeline at a time.

Every run writes a `pipeline_run` row (opened `running`, closed in a `finally`), which
is what the catch-up decision reads on the next startup and what the notifier reports.

Disabled in tests and wherever `ingest_schedule_enabled` is false. It is started
and stopped by the FastAPI lifespan (see app/main.py). One instance only: a single
uvicorn worker runs here; scaling to multiple workers would need this moved to a
dedicated scheduler process (noted in the deploy handoff).
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal

log = logging.getLogger("app.scheduler")

_scheduler: BackgroundScheduler | None = None

# One pipeline at a time across BOTH job ids. Non-reentrant and always released in
# a finally: a leaked lock would make every later run skip, write no run row and
# notify nothing, which is indistinguishable from a dead stack.
_RUN_LOCK = threading.Lock()

# How long after the catch-up job is registered before it fires, so the API is
# serving before a long pipeline starts competing for the process.
_CATCHUP_DELAY_SECONDS = 60


def should_catch_up(last_success_at: datetime | None, now: datetime, threshold_hours: int) -> bool:
    """True when the last successful run is missing or older than the threshold.

    Pure on purpose: no clock patching, no scheduler, no database, so the decision
    this feature turns on is a plain unit test. A naive `last_success_at` is read as
    UTC, because SQLite hands datetimes back without a timezone.
    """
    if last_success_at is None:
        return True
    if last_success_at.tzinfo is None:
        last_success_at = last_success_at.replace(tzinfo=UTC)
    return now - last_success_at > timedelta(hours=threshold_hours)


def _last_successful_run_at(session_factory) -> datetime | None:
    """When the most recent run that got as far as finishing started."""
    from app.models import PipelineRun

    with session_factory() as session:
        return session.scalar(
            select(PipelineRun.started_at)
            .where(PipelineRun.status.in_(("ok", "partial")))
            .order_by(PipelineRun.started_at.desc())
            .limit(1)
        )


def recover_interrupted_run(session_factory) -> bool:
    """Close any leftover `running` row as failed. True when one was found.

    Nothing inside the container can report that the container stopped, so a row
    still open at startup is the only trace of a process killed mid-run (laptop
    sleep, Docker Desktop closing). Left alone it would also read as "a run is in
    flight" forever and the catch-up would never see a stale last success.
    """
    from app.models import PipelineRun

    with session_factory() as session:
        rows = session.scalars(select(PipelineRun).where(PipelineRun.status == "running")).all()
        if not rows:
            return False
        for row in rows:
            row.status = "failed"
            row.error = "interrupted: the process was killed mid-run"
            row.finished_at = datetime.now(UTC)
        session.commit()
        return True


def _open_run(session_factory, trigger: str) -> int:
    from app.models import PipelineRun

    with session_factory() as session:
        row = PipelineRun(trigger=trigger, status="running", started_at=datetime.now(UTC))
        session.add(row)
        session.commit()
        return row.id


def _close_run(session_factory, run_id: int, **fields) -> None:
    from app.models import PipelineRun

    with session_factory() as session:
        row = session.get(PipelineRun, run_id)
        if row is None:  # pragma: no cover - only if the row was deleted mid-run
            return
        for key, value in fields.items():
            setattr(row, key, value)
        row.finished_at = datetime.now(UTC)
        session.commit()


def run_daily_pipeline(session_factory=SessionLocal, trigger: str = "schedule") -> dict:
    """Ingest -> embed -> classify -> liveness sweep. Idempotent.

    Embedding needs OPENAI_API_KEY; classification uses the LLM (ANTHROPIC_API_KEY)
    or falls back to the embedding classifier. Missing keys skip only the steps that
    need them (logged): ingest and the liveness sweep always run, and the skipped
    enrichment backfills once a key is present. The sweep goes last so it replays
    shortlists over freshly classified jobs.

    Returns the skip marker without writing a run row if another pipeline holds the
    lock, so an overlapping cron firing during a long catch-up costs nothing.
    """
    if not _RUN_LOCK.acquire(blocking=False):
        log.warning("daily pipeline already running; %s trigger skipped", trigger)
        return {"skipped": "already running"}
    try:
        return _run_pipeline(session_factory, trigger)
    finally:
        _RUN_LOCK.release()


def _run_pipeline(session_factory, trigger: str) -> dict:
    from app import shortlist
    from app.ai import role_family
    from app.ai.embedder import OpenAIEmbedder, build_job_document
    from app.ingest import runner
    from app.models import MANUAL_SOURCE, Job

    settings = get_settings()
    summary: dict = {"embedded": 0, "classified": 0}
    ai_failures: list[Exception] = []
    embedding_skipped = not settings.openai_api_key
    run_id = _open_run(session_factory, trigger)
    try:
        with session_factory() as session:
            # Keep the whole summary, not just totals: the per-source `error` lives in
            # ["sources"], and without it a partial run is indistinguishable from a
            # clean one and the notifier cannot name the source that broke.
            ingested = runner.ingest_all(session).as_dict()
            summary["ingest"] = ingested["totals"]
            summary["sources"] = ingested.get("sources", [])

            embedder = None
            if settings.openai_api_key:
                embedder = OpenAIEmbedder(
                    settings.openai_api_key,
                    model=settings.embedding_model,
                    dimensions=settings.embedding_dimensions,
                )
                jobs = session.scalars(
                    select(Job)
                    .where(Job.embedding.is_(None), Job.source != MANUAL_SOURCE)
                    .limit(settings.ingest_embed_limit)
                ).all()
                if jobs:
                    vectors = embedder.embed([build_job_document(j) for j in jobs])
                    for job, vector in zip(jobs, vectors, strict=True):
                        job.embedding = vector
                    session.commit()
                summary["embedded"] = len(jobs)
            else:
                log.warning("daily pipeline: OPENAI_API_KEY missing; skipped embedding")

            llm = role_family.get_role_classifier(settings)
            if llm is None and embedder is None:
                log.warning("daily pipeline: no AI key; skipped role classification")
            else:
                unclassified = session.scalars(
                    select(Job)
                    .where(Job.role_family.is_(None), Job.source != MANUAL_SOURCE)
                    .limit(settings.ingest_classify_limit)
                ).all()
                if unclassified:
                    titles = [j.title for j in unclassified]
                    if llm is not None:
                        families = llm.classify_titles(titles)
                        # The classifier fails soft per batch; without this a rejected
                        # key or an empty balance looked like "nothing to classify".
                        ai_failures.extend(getattr(llm, "last_failures", None) or [])
                    else:
                        classifier = role_family.RoleClassifier.from_embedder(
                            embedder,
                            min_similarity=settings.role_min_similarity,
                            min_margin=settings.role_min_margin,
                        )
                        families = classifier.classify_titles(titles, embedder)
                    for job, family in zip(unclassified, families, strict=True):
                        job.role_family = family
                    session.commit()
                summary["classified"] = len(unclassified)

            summary["liveness"] = shortlist.sweep_saved_shortlists(session)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        _close_run(
            session_factory,
            run_id,
            status="failed",
            error=error,
            problems=_problem_dicts(
                status="failed",
                error=error,
                sources=summary.get("sources"),
                inserted=0,
                ai_failures=ai_failures,
                embedding_skipped=embedding_skipped,
            ),
        )
        log.exception("daily pipeline failed")
        _notify(session_factory, run_id)
        raise
    else:
        totals = summary.get("ingest") or {}
        sources = summary.get("sources") or []
        failed_sources = [s for s in sources if s.get("error")]
        status = "partial" if failed_sources else "ok"
        inserted = totals.get("inserted", 0)
        _close_run(
            session_factory,
            run_id,
            status=status,
            inserted=inserted,
            updated=totals.get("updated", 0),
            removed_stale=totals.get("removed_stale", 0),
            embedded=summary["embedded"],
            classified=summary["classified"],
            sources={"sources": sources},
            problems=_problem_dicts(
                status=status,
                error=None,
                sources=sources,
                inserted=inserted,
                ai_failures=ai_failures,
                embedding_skipped=embedding_skipped,
            ),
        )
        _notify(session_factory, run_id)

    log.info("daily pipeline complete: %s", summary)
    return summary


def _problem_dicts(**kwargs) -> list[dict]:
    from app.notify.problems import collect_problems

    return [p.as_dict() for p in collect_problems(**kwargs)]


def _notify(session_factory, run_id: int) -> None:
    """Send the run's Telegram message. A notifier failure must cost nothing: the
    run row is already closed and the ingested jobs are already committed."""
    try:
        from app.notify.telegram import notify_run

        notify_run(session_factory, run_id)
    except Exception:  # noqa: BLE001 - notification is never worth failing a run over
        log.warning("run notification failed", exc_info=True)


def start_scheduler() -> None:
    """Start the daily job at ingest_hour_utc:00 UTC. No-op if disabled or running.

    Also registers a one-shot catch-up when the last recorded run is stale. That
    query is best-effort: this runs in the FastAPI lifespan, and an unreachable
    database on laptop resume must not take the whole app down - exactly the case
    the catch-up exists to recover from.
    """
    global _scheduler
    settings = get_settings()
    if not settings.ingest_schedule_enabled or _scheduler is not None:
        return
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_daily_pipeline,
        CronTrigger(hour=settings.ingest_hour_utc, minute=0),
        id="daily_ingest",
        max_instances=1,  # never overlap a still-running pipeline (per job id)
        coalesce=True,  # collapse missed runs into one on recovery
        misfire_grace_time=3600,
    )

    try:
        if recover_interrupted_run(SessionLocal):
            from app.notify.telegram import INTERRUPTED_LINE, send_message

            send_message(INTERRUPTED_LINE)
        last_success = _last_successful_run_at(SessionLocal)
        due = should_catch_up(last_success, datetime.now(UTC), settings.ingest_catchup_after_hours)
    except Exception:  # noqa: BLE001 - a dead DB must not block startup
        log.warning("catch-up check failed (database unreachable?); skipping", exc_info=True)
        due = False

    if due:
        scheduler.add_job(
            run_daily_pipeline,
            DateTrigger(run_date=datetime.now(UTC) + timedelta(seconds=_CATCHUP_DELAY_SECONDS)),
            id="catchup_ingest",
            kwargs={"trigger": "catchup"},
            max_instances=1,
            coalesce=True,
        )
        log.info("last run stale; catch-up ingest in %ds", _CATCHUP_DELAY_SECONDS)

    scheduler.start()
    log.info("daily ingest scheduled for %02d:00 UTC", settings.ingest_hour_utc)
    _scheduler = scheduler


def stop_scheduler() -> None:
    """Stop the scheduler if running (called on app shutdown)."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
