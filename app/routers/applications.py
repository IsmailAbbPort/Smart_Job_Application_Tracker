"""/applications - track the application pipeline (one row per job).

Keyed by job_id for a single user: POST upserts (create or advance the status),
GET lists / reports pipeline stats, DELETE untracks. `applied_at` is stamped the
first time an application leaves the 'saved' stage.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user_optional
from app.db import get_session
from app.models import Application, Cv, Job, User
from app.schemas import ApplicationOut, ApplicationStatus, ApplicationUpsert, JobOut

router = APIRouter(prefix="/applications", tags=["applications"])


def _owner_id(user: User | None) -> int | None:
    return user.id if user else None


def _to_out(app: Application, job: Job) -> ApplicationOut:
    return ApplicationOut(
        id=app.id,
        job_id=app.job_id,
        cv_id=app.cv_id,
        status=app.status,
        notes=app.notes,
        applied_at=app.applied_at,
        created_at=app.created_at,
        updated_at=app.updated_at,
        job=JobOut.model_validate(job),
    )


@router.post("", response_model=ApplicationOut, status_code=201)
def upsert_application(
    payload: ApplicationUpsert,
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> ApplicationOut:
    """Start tracking a job or advance its status. Idempotent on (owner, job_id)."""
    owner_id = _owner_id(user)
    job = session.get(Job, payload.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if payload.cv_id is not None and session.get(Cv, payload.cv_id) is None:
        raise HTTPException(status_code=404, detail="cv not found")

    app = session.scalar(
        select(Application).where(
            Application.job_id == payload.job_id, Application.owner_id == owner_id
        )
    )
    if app is None:
        app = Application(job_id=payload.job_id, owner_id=owner_id)
        session.add(app)

    app.status = payload.status.value
    if payload.cv_id is not None:
        app.cv_id = payload.cv_id
    if payload.notes is not None:
        app.notes = payload.notes
    # Stamp applied_at when the pipeline first moves past 'saved'.
    if app.status != ApplicationStatus.saved.value and app.applied_at is None:
        app.applied_at = datetime.now(UTC)

    session.commit()
    session.refresh(app)
    return _to_out(app, job)


@router.get("", response_model=list[ApplicationOut])
def list_applications(
    session: Session = Depends(get_session),
    status: ApplicationStatus | None = Query(default=None, description="Filter by pipeline status"),
    user: User | None = Depends(get_current_user_optional),
) -> list[ApplicationOut]:
    stmt = (
        select(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .where(Application.owner_id == _owner_id(user))
    )
    if status is not None:
        stmt = stmt.where(Application.status == status.value)
    rows = session.execute(stmt.order_by(Application.updated_at.desc())).all()
    return [_to_out(app, job) for app, job in rows]


@router.get("/stats")
def application_stats(
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> dict:
    """Pipeline counts per status (zero-filled) plus the total."""
    rows = session.execute(
        select(Application.status, func.count())
        .where(Application.owner_id == _owner_id(user))
        .group_by(Application.status)
    ).all()
    counts = {s.value: 0 for s in ApplicationStatus}
    for status, count in rows:
        counts[status] = count
    return {"total": sum(counts.values()), "by_status": counts}


@router.get("/{job_id}", response_model=ApplicationOut)
def get_application(
    job_id: int,
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> ApplicationOut:
    app = session.scalar(
        select(Application).where(
            Application.job_id == job_id, Application.owner_id == _owner_id(user)
        )
    )
    if app is None:
        raise HTTPException(status_code=404, detail="not tracked; POST /applications first")
    return _to_out(app, session.get(Job, job_id))


@router.delete("/{job_id}", status_code=204)
def untrack_application(
    job_id: int,
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> None:
    app = session.scalar(
        select(Application).where(
            Application.job_id == job_id, Application.owner_id == _owner_id(user)
        )
    )
    if app is not None:
        session.delete(app)
        session.commit()
