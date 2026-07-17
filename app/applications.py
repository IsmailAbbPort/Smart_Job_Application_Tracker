"""Helper for annotating job results with their pipeline status.

Kept separate from the /applications router so both /jobs and /match/shortlist can
tag results (the "already applied?" signal) with one extra query, no ORM joins.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application
from app.schemas import JobOut


def application_status_map(session: Session, job_ids: Iterable[int]) -> dict[int, str]:
    """Map job_id -> pipeline status for the tracked jobs among job_ids."""
    ids = list(job_ids)
    if not ids:
        return {}
    rows = session.execute(
        select(Application.job_id, Application.status).where(Application.job_id.in_(ids))
    ).all()
    return {job_id: status for job_id, status in rows}


def annotate_application_status(session: Session, items: Sequence[JobOut]) -> None:
    """Set application_status in place on each item that is being tracked."""
    statuses = application_status_map(session, (item.id for item in items))
    for item in items:
        item.application_status = statuses.get(item.id)
