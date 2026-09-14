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
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MANUAL_SOURCE, Application, Job

_USER_AGENT = "SmartJobTracker/0.1 (portfolio project; liveness check)"
_TIMEOUT = 15.0
_POLITE_DELAY = 0.1
_DEAD_STATUSES = {404, 410}


def _is_dead_redirect(original: str, final: str) -> bool:
    """True when a 2xx landing is actually a "posting gone" page reached by redirect.

    Some ATS boards (Greenhouse) don't 404 a pulled listing: they 302 the job URL to
    the board root tagged `?error=true`, so a naive status check sees 200 and keeps a
    dead job. Two high-precision signals: the explicit error marker, or a Greenhouse
    job path (/<org>/jobs/<id>) that collapsed to the bare board (lost its /jobs/).
    Deliberately narrow so a legitimate redirect to a live page is never flagged.
    """
    orig = urlparse(original)
    fin = urlparse(final)
    if parse_qs(fin.query).get("error") == ["true"]:
        return True
    if "greenhouse.io" in (fin.netloc or "") and "/jobs/" in orig.path and "/jobs/" not in fin.path:
        return True
    return False


def check_alive(client: httpx.Client, url: str) -> bool | None:
    """True if the posting is up, False if definitively gone, None if unknown.

    Gone = a 404/410, or a redirect that lands on a board's "posting not found" page
    (see _is_dead_redirect). Everything else 2xx is alive; 403/429/5xx stay unknown.
    """
    if not url:
        return None
    try:
        resp = client.get(url, follow_redirects=True)
    except httpx.HTTPError:
        return None  # network error / timeout -> unknown, keep the job
    if resp.status_code in _DEAD_STATUSES:
        return False
    if resp.status_code < 400:
        return False if _is_dead_redirect(url, str(resp.url)) else True
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
    # Manual jobs are the user's own record (often with no URL): never scanned or pruned.
    jobs = session.scalars(
        select(Job).where(Job.source != MANUAL_SOURCE).order_by(Job.id).limit(limit)
    ).all()

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
