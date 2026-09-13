"""Daily ingest scheduler.

Runs the ingest -> embed -> classify pipeline once a day, in-process, via
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


def run_daily_pipeline() -> dict:
    """Ingest every source, then embed and classify any new jobs. Idempotent.

    Embedding + classification need OPENAI_API_KEY; without it, ingest still runs
    and the enrichment steps are skipped (logged), so the corpus stays current and
    the vectors backfill once a key is present.
    """
    from app.ai.embedder import OpenAIEmbedder, build_job_document
    from app.ai.role_family import RoleClassifier
    from app.ingest.runner import ingest_all
    from app.models import Job

    settings = get_settings()
    summary: dict = {}
    with SessionLocal() as session:
        summary["ingest"] = ingest_all(session).as_dict()["totals"]

        if not settings.openai_api_key:
            log.warning("daily pipeline: OPENAI_API_KEY missing; skipped embed + classify")
            summary["embedded"] = summary["classified"] = 0
            return summary

        embedder = OpenAIEmbedder(
            settings.openai_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )

        jobs = session.scalars(
            select(Job).where(Job.embedding.is_(None)).limit(settings.ingest_embed_limit)
        ).all()
        if jobs:
            vectors = embedder.embed([build_job_document(j) for j in jobs])
            for job, vector in zip(jobs, vectors, strict=True):
                job.embedding = vector
            session.commit()
        summary["embedded"] = len(jobs)

        unclassified = session.scalars(
            select(Job).where(Job.role_family.is_(None)).limit(settings.ingest_classify_limit)
        ).all()
        if unclassified:
            classifier = RoleClassifier.from_embedder(
                embedder,
                min_similarity=settings.role_min_similarity,
                min_margin=settings.role_min_margin,
            )
            families = classifier.classify_titles([j.title for j in unclassified], embedder)
            for job, family in zip(unclassified, families, strict=True):
                job.role_family = family
            session.commit()
        summary["classified"] = len(unclassified)

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
