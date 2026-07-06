"""POST /ingest - manually trigger source ingestion.

Manual trigger first (per Phase 1 plan): you control exactly when rate-limited
sources are hit. `?force=true` bypasses the per-source TTL throttle.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.ingest.runner import SOURCES, ingest_all, ingest_source

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.get("/sources")
def list_sources() -> dict:
    """List registered sources and their throttle TTLs."""
    return {name: {"ttl_seconds": src.ttl_seconds} for name, src in SOURCES.items()}


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
