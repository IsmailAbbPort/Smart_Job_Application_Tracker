"""Daily ingest scheduler.

Runs the ingest -> embed -> classify -> liveness sweep pipeline once a day, in-process, via
APScheduler. A single-container deploy stays fresh with no extra infrastructure
(no cron container, no worker, no Redis). Every step it calls is idempotent, so a
missed run (downtime) or a repeated run is harmless.

Disabled in tests and wherever `ingest_schedule_enabled` is false. It is started
and stopped by the FastAPI lifespan (see app/main.py). One instance only: a single
uvicorn worker runs here; scaling to multiple workers would need this moved to a
dedicated scheduler process (noted in the deploy handoff).
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal

log = logging.getLogger("app.scheduler")

_scheduler: BackgroundScheduler | None = None


def run_daily_pipeline(session_factory=SessionLocal) -> dict:
    """Ingest -> embed -> classify -> liveness sweep. Idempotent.

    Embedding needs OPENAI_API_KEY; classification uses the LLM (ANTHROPIC_API_KEY)
    or falls back to the embedding classifier. Missing keys skip only the steps that
    need them (logged): ingest and the liveness sweep always run, and the skipped
    enrichment backfills once a key is present. The sweep goes last so it replays
    shortlists over freshly classified jobs.
    """
    from app import shortlist
    from app.ai import role_family
    from app.ai.embedder import OpenAIEmbedder, build_job_document
    from app.ingest import runner
    from app.models import MANUAL_SOURCE, Job

    settings = get_settings()
    summary: dict = {"embedded": 0, "classified": 0}
    with session_factory() as session:
        summary["ingest"] = runner.ingest_all(session).as_dict()["totals"]

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

    log.info("daily pipeline complete: %s", summary)
    return summary


def start_scheduler() -> None:
    """Start the daily job at ingest_hour_utc:00 UTC. No-op if disabled or running."""
    global _scheduler
    settings = get_settings()
    if not settings.ingest_schedule_enabled or _scheduler is not None:
        return
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_daily_pipeline,
        CronTrigger(hour=settings.ingest_hour_utc, minute=0),
        id="daily_ingest",
        max_instances=1,  # never overlap a still-running pipeline
        coalesce=True,  # collapse missed runs into one on recovery
        misfire_grace_time=3600,
    )
    scheduler.start()
    log.info("daily ingest scheduled for %02d:00 UTC", settings.ingest_hour_utc)
    _scheduler = scheduler


def stop_scheduler() -> None:
    """Stop the scheduler if running (called on app shutdown)."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
