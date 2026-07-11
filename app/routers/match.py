"""/match - embed jobs and shortlist them against the CV (retrieve stage)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.embedder import Embedder, build_job_document, get_embedder
from app.ai.matching import rank_jobs
from app.db import get_session
from app.models import Cv, Job
from app.schemas import JobOut, ShortlistItem, ShortlistResponse

router = APIRouter(prefix="/match", tags=["match"])


@router.post("/embed-jobs")
def embed_jobs(
    session: Session = Depends(get_session),
    embedder: Embedder = Depends(get_embedder),
    force: bool = Query(default=False, description="Re-embed all jobs, not just missing ones"),
    limit: int = Query(default=5000, ge=1, le=10000, description="Max jobs to embed this call"),
) -> dict:
    """Embed jobs that lack an embedding (or all, with force)."""
    stmt = select(Job)
    if not force:
        stmt = stmt.where(Job.embedding.is_(None))
    jobs = session.scalars(stmt.limit(limit)).all()

    if jobs:
        vectors = embedder.embed([build_job_document(j) for j in jobs])
        for job, vector in zip(jobs, vectors, strict=True):
            job.embedding = vector
        session.commit()

    remaining = session.scalar(select(func.count()).select_from(Job).where(Job.embedding.is_(None)))
    return {"embedded": len(jobs), "remaining_unembedded": remaining or 0}


@router.get("/shortlist", response_model=ShortlistResponse)
def shortlist(
    session: Session = Depends(get_session),
    cv_id: int | None = Query(default=None, description="CV to match; defaults to the latest"),
    limit: int = Query(default=25, ge=1, le=100),
    is_remote: bool | None = Query(default=None),
    europe: bool | None = Query(default=None),
    country: str | None = Query(default=None),
) -> ShortlistResponse:
    """Cosine-rank embedded jobs against the CV. The cheap retrieve stage."""
    cv = (
        session.get(Cv, cv_id)
        if cv_id
        else session.scalar(select(Cv).order_by(Cv.created_at.desc()).limit(1))
    )
    if cv is None:
        raise HTTPException(status_code=404, detail="no CV found; POST /cv first")
    if cv.embedding is None:
        raise HTTPException(status_code=409, detail="CV has no embedding")

    filters = []
    if is_remote is not None:
        filters.append(Job.is_remote == is_remote)
    if europe is not None:
        filters.append(Job.is_european == europe)
    if country is not None:
        filters.append(func.lower(Job.country) == country.lower())

    ranked = rank_jobs(session, list(cv.embedding), filters=filters, limit=limit)
    items = [
        ShortlistItem(**JobOut.model_validate(job).model_dump(), similarity=round(score, 4))
        for job, score in ranked
    ]
    return ShortlistResponse(cv_id=cv.id, count=len(items), items=items)
