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
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal

log = logging.getLogger("app.scheduler")

_scheduler: BackgroundScheduler | None = None

# One pipeline at a time across BOTH job ids AND the manual route. Non-reentrant and
# always released in a finally: a leaked lock would make every later run skip, write
# no run row and notify nothing, which is indistinguishable from a dead stack.
# Acquire it through `pipeline_slot()` rather than directly, so every entry point
# gets the same release guarantee.
_RUN_LOCK = threading.Lock()

# How long after the catch-up job is registered before it fires, so the API is
# serving before a long pipeline starts competing for the process.
_CATCHUP_DELAY_SECONDS = 60

# A missed one-shot is dropped without this. The catch-up exists to recover a day
# the laptop slept through, so it of all jobs must survive arriving late.
_MISFIRE_GRACE_SECONDS = 3600


@contextmanager
def pipeline_slot() -> Iterator[bool]:
    """Hold the one-pipeline-at-a-time slot. Yields whether it was acquired.

    A contextmanager rather than a bare lock because the lock has to be shared with
    POST /ingest: a manual trigger during the nightly run used to put a second
    ingest through the same tables, and the guard that was supposed to prevent that
    only covered the scheduled entry points.
    """
    acquired = _RUN_LOCK.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            _RUN_LOCK.release()


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
    with pipeline_slot() as acquired:
        if not acquired:
            log.warning("daily pipeline already running; %s trigger skipped", trigger)
            return {"skipped": "already running"}
        return _run_pipeline(session_factory, trigger)


def _run_pipeline(session_factory, trigger: str) -> dict:
    from app import shortlist
    from app.ai import role_family
    from app.ai.embedder import OpenAIEmbedder, build_job_document
    from app.ingest import runner
    from app.models import MANUAL_SOURCE, Job
    from app.notify.problems import AI_SCOPE, INTERNET_SCOPE, RUN_SCOPE

    settings = get_settings()
    summary: dict = {"embedded": 0, "classified": 0}
    ai_failures: list[Exception] = []
    embedding_skipped = not settings.openai_api_key
    # What this run genuinely re-examined, so the notifier can tell a fixed problem
    # from one whose source simply was not fetched this time. Added to as each step
    # actually happens, never up front.
    checked: set[str] = set()
    run_id = _open_run(session_factory, trigger)
    try:
        with session_factory() as session:
            # Keep the whole summary, not just totals: the per-source `error` lives in
            # ["sources"], and without it a partial run is indistinguishable from a
            # clean one and the notifier cannot name the source that broke.
            ingested = runner.ingest_all(session).as_dict()
            summary["ingest"] = ingested["totals"]
            summary["sources"] = ingested.get("sources", [])
            for src in summary["sources"]:
                name = src.get("source")
                # Guarded because `checked` is sorted on the way out, and one None
                # in the set would raise there rather than here.
                if name and not src.get("skipped_throttled"):
                    checked.add(name)
                if src.get("fetched"):
                    # Something answered, so the network is not the problem.
                    checked.add(INTERNET_SCOPE)

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
                    # The call is about to happen either way, so OpenAI counts as
                    # re-checked whether it answers or fails.
                    checked.update({"openai", AI_SCOPE})
                    try:
                        vectors = embedder.embed([build_job_document(j) for j in jobs])
                    except Exception as exc:  # noqa: BLE001 - enrichment fails soft
                        # An exhausted balance or a rejected key must not cost the
                        # ingest that already committed or the liveness sweep still
                        # to come; the next run backfills the embeddings. Keeping the
                        # live exception (rather than letting it flatten to a string
                        # on the failure path) is also what lets the taxonomy name
                        # the provider and so the actual remedy.
                        session.rollback()
                        ai_failures.append(exc)
                        log.warning("daily pipeline: embedding failed", exc_info=True)
                        # The same credentials back the fallback classifier, so there
                        # is nothing to gain from trying it with a broken embedder.
                        embedder = None
                    else:
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
                        checked.update({"anthropic", AI_SCOPE})
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
        # The same counts as the success path, not zeroes: the steps that completed
        # before the failure really did insert those jobs, and a row claiming
        # otherwise under-reports real work in /ops/runs and in the message.
        totals, sources, inserted = _counts(summary)
        _close_run(
            session_factory,
            run_id,
            status="failed",
            error=error,
            inserted=inserted,
            updated=totals.get("updated", 0),
            removed_stale=totals.get("removed_stale", 0),
            embedded=summary["embedded"],
            classified=summary["classified"],
            sources={"sources": sources},
            # No RUN_SCOPE here: the pipeline did not get to the end, so it is not
            # evidence that a previous run-level failure is behind us.
            checked=sorted(checked),
            problems=_problem_dicts(
                status="failed",
                error=error,
                sources=sources,
                inserted=inserted,
                ai_failures=ai_failures,
                embedding_skipped=embedding_skipped,
            ),
        )
        log.exception("daily pipeline failed")
        _notify(session_factory, run_id, settings)
        raise
    else:
        totals, sources, inserted = _counts(summary)
        failed_sources = [s for s in sources if s.get("error")]
        status = "partial" if failed_sources else "ok"
        checked.add(RUN_SCOPE)
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
            checked=sorted(checked),
            problems=_problem_dicts(
                status=status,
                error=None,
                sources=sources,
                inserted=inserted,
                ai_failures=ai_failures,
                embedding_skipped=embedding_skipped,
            ),
        )
        _notify(session_factory, run_id, settings)

    log.info("daily pipeline complete: %s", summary)
    return summary


def _counts(summary: dict) -> tuple[dict, list, int]:
    """Ingest totals, per-source rows and the inserted count, from a partial summary.

    Shared by the success and failure paths so a failed run reports the work that
    did happen rather than zeroes.
    """
    totals = summary.get("ingest") or {}
    return totals, summary.get("sources") or [], totals.get("inserted", 0)


def _problem_dicts(**kwargs) -> list[dict]:
    from app.notify.problems import collect_problems

    return [p.as_dict() for p in collect_problems(**kwargs)]


def _notify(session_factory, run_id: int, settings=None) -> None:
    """Send the run's Telegram message. A notifier failure must cost nothing: the
    run row is already closed and the ingested jobs are already committed.

    `settings` is the pipeline's own, forwarded rather than re-read: letting the
    notifier call get_settings() itself meant it ignored the settings the run was
    given, so a caller that had deliberately configured an inert notifier (every
    test, for one) still reached the real bot.
    """
    try:
        from app.notify.telegram import notify_run

        notify_run(session_factory, run_id, settings=settings)
    except Exception:  # noqa: BLE001 - notification is never worth failing a run over
        log.warning("run notification failed", exc_info=True)


def _send_interrupted_notice() -> None:
    """Tell the phone the last run was cut short. Never raises: this runs as a job,
    and an unreachable bot must not show up as a scheduler error."""
    try:
        from app.notify.telegram import INTERRUPTED_LINE, send_message

        send_message(INTERRUPTED_LINE)
    except Exception:  # noqa: BLE001 - notification is never worth an error for
        log.warning("interrupted-run notification failed", exc_info=True)


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

    interrupted = False
    try:
        interrupted = recover_interrupted_run(SessionLocal)
        last_success = _last_successful_run_at(SessionLocal)
        due = should_catch_up(last_success, datetime.now(UTC), settings.ingest_catchup_after_hours)
    except Exception:  # noqa: BLE001 - a dead DB must not block startup
        log.warning("catch-up check failed (database unreachable?); skipping", exc_info=True)
        due = False

    if interrupted:
        # On the scheduler's thread, not here. send_message is a blocking 10s post,
        # and this runs in the FastAPI lifespan: on a sleeping network that was 10s
        # of an app not yet serving, and it shared the try/except above, so a slow
        # bot could swallow the catch-up decision as collateral damage.
        scheduler.add_job(
            _send_interrupted_notice,
            DateTrigger(run_date=datetime.now(UTC) + timedelta(seconds=1)),
            id="interrupted_notice",
            misfire_grace_time=_MISFIRE_GRACE_SECONDS,
        )

    if due:
        scheduler.add_job(
            run_daily_pipeline,
            DateTrigger(run_date=datetime.now(UTC) + timedelta(seconds=_CATCHUP_DELAY_SECONDS)),
            id="catchup_ingest",
            kwargs={"trigger": "catchup"},
            max_instances=1,
            coalesce=True,
            misfire_grace_time=_MISFIRE_GRACE_SECONDS,
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
