"""Helper for annotating job results with their pipeline status.

Kept separate from the /applications router so both /jobs and /match/shortlist can
tag results (the "already applied?" signal) with one extra query, no ORM joins.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MANUAL_SOURCE, Application, Job
from app.schemas import JobOut


def application_status_map(
    session: Session, job_ids: Iterable[int], owner_id: int | None = None
) -> dict[int, str]:
    """Map job_id -> pipeline status for the owner's tracked jobs among job_ids."""
    ids = list(job_ids)
    if not ids:
        return {}
    rows = session.execute(
        select(Application.job_id, Application.status).where(
            Application.job_id.in_(ids), Application.owner_id == owner_id
        )
    ).all()
    return {job_id: status for job_id, status in rows}


def annotate_application_status(
    session: Session, items: Sequence[JobOut], owner_id: int | None = None
) -> None:
    """Set application_status in place on each item that is being tracked by the owner."""
    statuses = application_status_map(session, (item.id for item in items), owner_id)
    for item in items:
        item.application_status = statuses.get(item.id)


def job_visible_to(session: Session, job: Job, owner_id: int | None = None) -> bool:
    """False for a manually added job the owner is not tracking.

    Manual jobs are private to the pipeline that created them, so routes treat
    another owner's manual job exactly like a missing one (404), never leaking it.
    """
    if job.source != MANUAL_SOURCE:
        return True
    tracked = session.scalar(
        select(Application.id).where(Application.job_id == job.id, Application.owner_id == owner_id)
    )
    return tracked is not None
