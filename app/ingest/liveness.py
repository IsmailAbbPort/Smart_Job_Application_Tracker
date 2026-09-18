"""Dead-listing sweep: find and remove aggregator jobs whose posting is gone.

Scope: only rolling-window aggregator sources (Arbeitnow, Remotive). Full-catalogue
ATS boards are already pruned at ingest (see runner._sweep_stale), and nothing ever
removes an aggregator job otherwise, so expired Arbeitnow listings pile up. Both
aggregators answer an expired posting with a definitive 410/404.

Conservative on purpose. A listing is only treated as dead on a definitive HTTP
404/410 (or a known "posting gone" redirect); timeouts, 403s, and 5xx all mean
"unknown -> keep" so a flaky network never deletes real jobs. Jobs you are tracking
(have an Application) are never pruned: a dead one is marked source_gone_at instead.

Polite on purpose, because a block from the aggregator's CDN would also break its
ingest (same IP): requests are serialized process-wide with a minimum interval, a
run stops after several consecutive unknowns (a challenge wall), and each run is
capped. Callers: the nightly pipeline, the shortlist's on-view background check,
and the manual /ingest/prune-dead endpoint.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ingest.runner import SOURCES
from app.models import Application, Job

_USER_AGENT = "SmartJobTracker/0.1 (portfolio project; liveness check)"
_TIMEOUT = 15.0
_DEAD_STATUSES = {404, 410}
# This many unknowns in a row reads as being blocked (e.g. a challenge page): stop.
MAX_CONSECUTIVE_UNKNOWN = 5

# Rolling-window sources: nothing but this sweep removes their expired postings.
AGGREGATOR_SOURCES = sorted(
    name for name, src in SOURCES.items() if not getattr(src, "full_catalog", False)
)

# One sweep at a time per process, and one outbound request at a time across sweeps.
_sweep_lock = threading.Lock()
_request_lock = threading.Lock()
_last_request_at = 0.0


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

    Uses HEAD (status only, no page download), falling back to GET when the server
    refuses HEAD. Gone = a 404/410, or a redirect that lands on a board's "posting
    not found" page (see _is_dead_redirect). Everything else 2xx is alive;
    403/429/5xx stay unknown.
    """
    if not url:
        return None
    try:
        resp = client.head(url, follow_redirects=True)
        if resp.status_code in (405, 501):
            resp = client.get(url, follow_redirects=True)
    except httpx.HTTPError:
        return None  # network error / timeout -> unknown, keep the job
    if resp.status_code in _DEAD_STATUSES:
        return False
    if resp.status_code < 400:
        return False if _is_dead_redirect(url, str(resp.url)) else True
    return None  # 403/429/5xx etc. -> unknown, keep


def _make_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT)


def _throttle(min_interval: float) -> None:
    """Block until at least min_interval seconds have passed since the last request."""
    global _last_request_at
    with _request_lock:
        wait = _last_request_at + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def sweep_dead_jobs(
    session: Session,
    *,
    job_ids: Iterable[int] | None = None,
    recheck_after: timedelta | None = None,
    limit: int = 600,
    apply: bool = True,
    client: httpx.Client | None = None,
    min_interval: float | None = None,
    wait: bool = True,
) -> dict:
    """Check aggregator jobs and delete the dead ones (only when apply=True).

    A dead job you are tracking is marked source_gone_at instead of deleted; jobs
    already marked are not re-checked.

    job_ids restricts the sweep to those jobs; recheck_after skips jobs confirmed live
    more recently than that. Least-recently-checked first, at most `limit` checks.
    wait=False returns immediately (skipped_busy) if another sweep is running, so
    on-view checks never pile up threads behind a long nightly run.
    """
    stats = {
        "checked": 0,
        "alive": 0,
        "dead": 0,
        "deleted": 0,
        "marked_gone": 0,
        "unknown_kept": 0,
        "stopped_early": False,
        "skipped_busy": False,
        "applied": apply,
        "dead_sample": [],
    }
    if not _sweep_lock.acquire(blocking=wait):
        stats["skipped_busy"] = True
        return stats
    try:
        _sweep(session, stats, job_ids, recheck_after, limit, apply, client, min_interval)
    finally:
        _sweep_lock.release()
    return stats


def _sweep(session, stats, job_ids, recheck_after, limit, apply, client, min_interval) -> None:
    if min_interval is None:
        min_interval = get_settings().liveness_min_interval_seconds
    now = datetime.now(UTC)
    tracked = set(session.scalars(select(Application.job_id)))
    stmt = select(Job).where(Job.source.in_(AGGREGATOR_SOURCES), Job.source_gone_at.is_(None))
    if job_ids is not None:
        stmt = stmt.where(Job.id.in_(list(job_ids)))
    if recheck_after is not None:
        stmt = stmt.where(
            or_(Job.last_checked_at.is_(None), Job.last_checked_at < now - recheck_after)
        )
    stmt = stmt.order_by(Job.last_checked_at.is_not(None), Job.last_checked_at, Job.id)
    jobs = session.scalars(stmt.limit(limit)).all()

    if not jobs:
        return
    owns_client = client is None
    client = client or _make_client()
    dead: list[Job] = []
    gone: list[Job] = []
    unknown_run = 0
    try:
        for job in jobs:
            _throttle(min_interval)
            alive = check_alive(client, job.url)
            stats["checked"] += 1
            if alive is True:
                stats["alive"] += 1
                job.last_checked_at = datetime.now(UTC)
                unknown_run = 0
            elif alive is False:
                if job.id in tracked:
                    gone.append(job)
                else:
                    dead.append(job)
                unknown_run = 0
            else:
                stats["unknown_kept"] += 1
                unknown_run += 1
                if unknown_run >= MAX_CONSECUTIVE_UNKNOWN:
                    stats["stopped_early"] = True
                    break
    finally:
        if owns_client:
            client.close()

    stats["dead"] = len(dead)
    stats["dead_sample"] = [j.id for j in dead[:20]]
    if apply:
        for job in dead:
            session.delete(job)
        for job in gone:
            job.source_gone_at = datetime.now(UTC)
        stats["deleted"] = len(dead)
        stats["marked_gone"] = len(gone)
    session.commit()


def prune_dead_jobs(
    session: Session,
    *,
    limit: int = 200,
    apply: bool = False,
    client: httpx.Client | None = None,
    min_interval: float | None = None,
) -> dict:
    """Manual sweep of every aggregator job (dry run unless apply=True)."""
    return sweep_dead_jobs(
        session, limit=limit, apply=apply, client=client, min_interval=min_interval
    )
