"""GET /jobs - list and read canonical jobs from the DB (never live-hits sources)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.applications import annotate_application_status, job_visible_to
from app.auth import get_current_user_optional
from app.db import get_session
from app.models import MANUAL_SOURCE, Job, SearchPreferences, User
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
    language: str | None = Query(
        default=None, description="Filter by posting language (ISO, e.g. en)"
    ),
    max_age_days: int | None = Query(
        default=None, ge=1, description="Drop postings older than this many days"
    ),
    min_salary: int | None = Query(
        default=None, ge=1, description="Drop jobs whose stated max pay is below this"
    ),
    min_salary_currency: str | None = Query(
        default=None, description="Currency for min_salary (e.g. EUR); only same-currency compared"
    ),
    require_salary: bool = Query(default=False, description="Also drop jobs with no stated salary"),
    max_experience_gap: int | None = Query(
        default=None, ge=0, description="Drop jobs needing >N years beyond your experience"
    ),
    q: str | None = Query(default=None, description="Substring match on title or company"),
    ignore_prefs: bool = Query(default=False, description="Ignore saved default filters"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JobList:
    prefs = SearchPreferences() if ignore_prefs else get_preferences(session)
    filters = preference_filters(
        prefs,
        is_remote=is_remote,
        europe=europe,
        country=country,
        language=language,
        max_age_days=max_age_days,
        min_salary=min_salary,
        min_salary_currency=min_salary_currency,
        require_salary=require_salary,
        max_experience_gap=max_experience_gap,
    )
    filters.append(Job.source != MANUAL_SOURCE)
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
    items = [JobOut.model_validate(r) for r in rows]
    annotate_application_status(session, items)
    return JobList(total=total, limit=limit, offset=offset, items=items)


@router.get("/languages")
def list_languages(session: Session = Depends(get_session)) -> list[dict]:
    """Posting languages present in the corpus, with counts (for the UI filter)."""
    rows = session.execute(
        select(Job.language, func.count())
        .where(Job.language.is_not(None), Job.source != MANUAL_SOURCE)
        .group_by(Job.language)
        .order_by(func.count().desc())
    ).all()
    return [{"code": code, "count": count} for code, count in rows]


@router.get("/cities")
def list_cities(session: Session = Depends(get_session)) -> list[dict]:
    """Resolved cities present in the corpus, with counts (for the UI filter)."""
    rows = session.execute(
        select(Job.city, func.count())
        .where(Job.city.is_not(None), Job.city != "", Job.source != MANUAL_SOURCE)
        .group_by(Job.city)
        .order_by(func.count().desc())
    ).all()
    return [{"name": name, "count": count} for name, count in rows]


@router.get("/countries")
def list_countries(session: Session = Depends(get_session)) -> list[dict]:
    """Resolved countries present in the corpus, with counts (for the UI filter)."""
    rows = session.execute(
        select(Job.country, func.count())
        .where(Job.country.is_not(None), Job.country != "", Job.source != MANUAL_SOURCE)
        .group_by(Job.country)
        .order_by(func.count().desc())
    ).all()
    return [{"name": name, "count": count} for name, count in rows]


@router.get("/{job_id}", response_model=JobDetail)
def get_job(
    job_id: int,
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> JobDetail:
    job = session.get(Job, job_id)
    if job is None or not job_visible_to(session, job, user.id if user else None):
        raise HTTPException(status_code=404, detail="job not found")
    return JobDetail.model_validate(job)
