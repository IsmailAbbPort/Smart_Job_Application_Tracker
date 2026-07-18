"""POST /ingest - manually trigger source ingestion.

Manual trigger first (per Phase 1 plan): you control exactly when rate-limited
sources are hit. `?force=true` bypasses the per-source TTL throttle.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.ingest.liveness import prune_dead_jobs
from app.ingest.runner import SOURCES, backfill_enrichment, ingest_all, ingest_source

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.get("/sources")
def list_sources() -> dict:
    """List registered sources and their throttle TTLs."""
    return {name: {"ttl_seconds": src.ttl_seconds} for name, src in SOURCES.items()}


@router.post("/backfill")
def trigger_backfill(
    session: Session = Depends(get_session),
    force: bool = Query(default=False, description="Recompute for all jobs, not just missing ones"),
    limit: int = Query(default=5000, ge=1, le=20000, description="Max jobs to process this call"),
) -> dict:
    """Recompute derived signals (language + eligibility) for pre-existing jobs."""
    return backfill_enrichment(session, limit=limit, force=force)


@router.post("/prune-dead")
def trigger_prune_dead(
    session: Session = Depends(get_session),
    apply: bool = Query(default=False, description="Actually delete dead jobs (default: dry run)"),
    limit: int = Query(default=200, ge=1, le=5000, description="Max jobs to check this call"),
) -> dict:
    """Check job URLs and report (or with apply=true, remove) dead 404/410 listings.

    Manual + dry-run by default. Tracked jobs (with an Application) are never pruned.
    Scheduling a daily run is deferred to the scheduled-ingest work.
    """
    return prune_dead_jobs(session, limit=limit, apply=apply)


@router.post("/{source}")
def trigger_ingest(
    source: str,
    session: Session = Depends(get_session),
    force: bool = Query(default=False, description="Bypass the per-source TTL throttle"),
) -> dict:
    """Ingest one source, or all of them with source='all'."""
    if source == "all":
        return ingest_all(session, force=force).as_dict()
    if source not in SOURCES:
        raise HTTPException(
            status_code=404,
            detail=f"unknown source '{source}'. Known: {', '.join(SOURCES)} (or 'all').",
        )
    return ingest_source(session, source, force=force).as_dict()
