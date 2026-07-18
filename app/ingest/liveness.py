"""Dead-listing scan: find (and optionally remove) jobs whose posting is gone.

Conservative on purpose. A listing is only treated as dead on a definitive HTTP
404/410; timeouts, 403s, redirects, and 5xx all mean "unknown -> keep" so a flaky
network never deletes real jobs. Jobs you are tracking (have an Application) are
never pruned, so a listing going down doesn't wipe your pipeline record.

This is a MANUAL capability (dry-run by default) and is NOT scheduled - wiring a
daily run belongs with the scheduled-ingest work, deliberately deferred.
"""

from __future__ import annotations

import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, Job

_USER_AGENT = "SmartJobTracker/0.1 (portfolio project; liveness check)"
_TIMEOUT = 15.0
_POLITE_DELAY = 0.1
_DEAD_STATUSES = {404, 410}


def check_alive(client: httpx.Client, url: str) -> bool | None:
    """True if the posting is up, False if definitively gone (404/410), None if unknown."""
    if not url:
        return None
    try:
        resp = client.get(url, follow_redirects=True)
    except httpx.HTTPError:
        return None  # network error / timeout -> unknown, keep the job
    if resp.status_code in _DEAD_STATUSES:
        return False
    if resp.status_code < 400:
        return True
    return None  # 403/429/5xx etc. -> unknown, keep


def prune_dead_jobs(
    session: Session,
    *,
    limit: int = 200,
    apply: bool = False,
    client: httpx.Client | None = None,
) -> dict:
    """Scan up to `limit` jobs for dead listings. Deletes them only when apply=True.

    Skips jobs that have a tracked Application (never removes your pipeline). Returns
    counts plus a sample of the dead job ids so a dry run is informative.
    """
    tracked = set(session.scalars(select(Application.job_id)))
    jobs = session.scalars(select(Job).order_by(Job.id).limit(limit)).all()

    owns_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT, follow_redirects=True
    )
    dead_ids: list[int] = []
    unknown = 0
    try:
        for job in jobs:
            if job.id in tracked:
                continue  # never prune a job you're tracking
            alive = check_alive(client, job.url)
            if alive is False:
                dead_ids.append(job.id)
            elif alive is None:
                unknown += 1
            time.sleep(_POLITE_DELAY)
    finally:
        if owns_client:
            client.close()

    deleted = 0
    if apply and dead_ids:
        for job in session.scalars(select(Job).where(Job.id.in_(dead_ids))):
            session.delete(job)
        session.commit()
        deleted = len(dead_ids)

    return {
        "checked": len(jobs),
        "dead": len(dead_ids),
        "deleted": deleted,
        "unknown_kept": unknown,
        "applied": apply,
        "dead_sample": dead_ids[:20],
    }
