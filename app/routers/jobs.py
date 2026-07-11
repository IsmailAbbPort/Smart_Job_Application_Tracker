"""GET /jobs - list and read canonical jobs from the DB (never live-hits sources)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Job, SearchPreferences
from app.prefs import get_preferences, preference_filters
from app.schemas import JobDetail, JobList, JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=JobList)
def list_jobs(
    session: Session = Depends(get_session),
    source: str | None = Query(default=None, description="Filter by source"),
    company: str | None = Query(default=None, description="Substring match on company"),
    is_remote: bool | None = Query(default=None),
    europe: bool | None = Query(
        default=None, description="Only European-located jobs (true) or non-European (false)"
    ),
    country: str | None = Query(default=None, description="Filter by resolved country"),
    city: str | None = Query(default=None, description="Filter by resolved (canonical) city"),
    q: str | None = Query(default=None, description="Substring match on title or company"),
    ignore_prefs: bool = Query(default=False, description="Ignore saved default filters"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JobList:
    prefs = SearchPreferences() if ignore_prefs else get_preferences(session)
    filters = preference_filters(prefs, is_remote=is_remote, europe=europe, country=country)
    if source is not None:
        filters.append(Job.source == source)
    if city is not None:
        filters.append(func.lower(Job.city) == city.lower())
    if company is not None:
        filters.append(Job.company_norm.contains(company.lower()))
    if q is not None:
        like = f"%{q.lower()}%"
        filters.append(or_(func.lower(Job.title).like(like), func.lower(Job.company).like(like)))

    total = session.scalar(select(func.count()).select_from(Job).where(*filters)) or 0
    rows = session.scalars(
        select(Job)
        .where(*filters)
        .order_by(Job.posted_at.is_(None), Job.posted_at.desc(), Job.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return JobList(
        total=total,
        limit=limit,
        offset=offset,
        items=[JobOut.model_validate(r) for r in rows],
    )


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: int, session: Session = Depends(get_session)) -> JobDetail:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobDetail.model_validate(job)
