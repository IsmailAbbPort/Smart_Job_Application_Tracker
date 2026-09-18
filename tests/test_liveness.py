"""Dead-listing scan: conservative liveness check + safe, throttled sweeping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app.ingest import liveness
from app.ingest.liveness import check_alive, prune_dead_jobs, sweep_dead_jobs
from app.models import MANUAL_SOURCE, Application, Job


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _status_handler(request: httpx.Request) -> httpx.Response:
    # URL path like /404 -> respond with that status code.
    return httpx.Response(int(request.url.path.strip("/").split("/")[0] or "200"))


def _job(sid, url, *, source="arbeitnow", last_checked_at=None) -> Job:
    return Job(
        source=source,
        source_id=sid,
        title="x",
        company="c",
        url=url,
        is_remote=True,
        is_european=True,
        last_checked_at=last_checked_at,
    )


def _ids(session) -> set[str]:
    return {j.source_id for j in session.query(Job).all()}


def test_check_alive_status_mapping():
    c = _client(_status_handler)
    assert check_alive(c, "http://x/404") is False
    assert check_alive(c, "http://x/410") is False
    assert check_alive(c, "http://x/200") is True
    assert check_alive(c, "http://x/403") is None  # unknown -> keep
    assert check_alive(c, "http://x/503") is None
    assert check_alive(c, "") is None


def test_check_alive_uses_head_and_falls_back_to_get_on_405():
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(405)
        return httpx.Response(410)

    assert check_alive(_client(handler), "http://x/job") is False
    assert methods == ["HEAD", "GET"]


def _greenhouse_handler(request: httpx.Request) -> httpx.Response:
    """Mimic Greenhouse: a pulled job 302s to the board root tagged ?error=true;
    a live job path (with /jobs/<id>) returns 200."""
    url = str(request.url)
    if url.endswith("/jobs/dead"):
        return httpx.Response(
            302, headers={"Location": "https://job-boards.greenhouse.io/acme?error=true"}
        )
    return httpx.Response(200, text="ok")


def test_check_alive_detects_redirect_to_error_board():
    # Regression: a deleted Greenhouse listing 302s to <board>?error=true and lands
    # on a 200, which the old status-only check wrongly treated as alive.
    c = _client(_greenhouse_handler)
    assert check_alive(c, "https://job-boards.greenhouse.io/acme/jobs/dead") is False
    assert check_alive(c, "https://job-boards.greenhouse.io/acme/jobs/live") is True


def test_check_alive_network_error_is_unknown():
    def boom(request):
        raise httpx.ConnectError("down")

    assert check_alive(_client(boom), "http://x/1") is None


# --- sweep ---


def test_sweep_only_touches_aggregator_sources(session):
    # Full-catalogue ATS jobs are pruned at ingest; checking their pages would only add
    # load. Only rolling-window aggregators (Arbeitnow, Remotive) are swept.
    session.add_all(
        [
            _job("an", "http://x/410/an"),
            _job("rm", "http://x/404/rm", source="remotive"),
            _job("gh", "http://x/404/gh", source="greenhouse"),
        ]
    )
    session.commit()
    stats = sweep_dead_jobs(session, client=_client(_status_handler), min_interval=0)
    assert stats["checked"] == 2 and stats["deleted"] == 2
    assert _ids(session) == {"gh"}


def test_sweep_skips_recently_checked_and_stamps_alive(session):
    now = datetime.now(UTC)
    session.add_all(
        [
            _job("fresh_dead", "http://x/410/a", last_checked_at=now - timedelta(hours=1)),
            _job("stale_alive", "http://x/200/b", last_checked_at=now - timedelta(days=2)),
            _job("unknown", "http://x/503/c"),
        ]
    )
    session.commit()
    stats = sweep_dead_jobs(
        session,
        recheck_after=timedelta(hours=6),
        client=_client(_status_handler),
        min_interval=0,
    )
    assert stats["checked"] == 2  # fresh_dead was checked an hour ago -> skipped
    assert _ids(session) == {"fresh_dead", "stale_alive", "unknown"}
    rows = {j.source_id: j for j in session.query(Job).all()}
    assert rows["stale_alive"].last_checked_at.replace(tzinfo=UTC) >= now
    assert rows["unknown"].last_checked_at is None  # unknown is retried next time


def test_sweep_restricts_to_given_ids(session):
    session.add_all([_job("a", "http://x/410/a"), _job("b", "http://x/410/b")])
    session.commit()
    a = session.query(Job).filter_by(source_id="a").one()
    sweep_dead_jobs(session, job_ids=[a.id], client=_client(_status_handler), min_interval=0)
    assert _ids(session) == {"b"}


def test_sweep_marks_tracked_dead_expired_instead_of_deleting(session):
    session.add(_job("tracked", "http://x/410/t"))
    session.commit()
    job = session.query(Job).one()
    session.add(Application(job_id=job.id, status="applied"))
    session.commit()
    stats = sweep_dead_jobs(session, client=_client(_status_handler), min_interval=0)
    assert stats["checked"] == 1 and stats["deleted"] == 0 and stats["marked_gone"] == 1
    assert _ids(session) == {"tracked"}
    assert job.source_gone_at is not None


def test_sweep_skips_jobs_already_marked_expired(session):
    session.add(_job("gone", "http://x/410/g"))
    session.commit()
    job = session.query(Job).one()
    job.source_gone_at = datetime.now(UTC)
    session.add(Application(job_id=job.id, status="applied"))
    session.commit()
    stats = sweep_dead_jobs(session, client=_client(_status_handler), min_interval=0)
    assert stats["checked"] == 0


def test_sweep_stops_after_consecutive_unknowns(session):
    # A Cloudflare challenge (403) on every page means we're being blocked: stop
    # instead of hammering the site and getting the ingest IP banned too.
    session.add_all([_job(f"j{i}", f"http://x/403/{i}") for i in range(10)])
    session.commit()
    stats = sweep_dead_jobs(session, client=_client(_status_handler), min_interval=0)
    assert stats["stopped_early"] is True
    assert stats["checked"] == liveness.MAX_CONSECUTIVE_UNKNOWN


def test_sweep_respects_limit(session):
    session.add_all([_job(f"j{i}", f"http://x/200/{i}") for i in range(5)])
    session.commit()
    stats = sweep_dead_jobs(session, limit=2, client=_client(_status_handler), min_interval=0)
    assert stats["checked"] == 2


def test_sweep_throttles_requests(session, monkeypatch):
    session.add_all([_job(f"j{i}", f"http://x/200/{i}") for i in range(3)])
    session.commit()
    clock = [100.0]
    slept: list[float] = []

    def fake_sleep(seconds):
        slept.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(liveness.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(liveness.time, "sleep", fake_sleep)
    monkeypatch.setattr(liveness, "_last_request_at", 0.0)
    sweep_dead_jobs(session, client=_client(_status_handler), min_interval=1.0)
    assert len(slept) == 2 and all(abs(s - 1.0) < 1e-9 for s in slept)


def test_non_waiting_sweep_skips_when_another_is_running(session):
    session.add(_job("a", "http://x/410/a"))
    session.commit()
    with liveness._sweep_lock:
        stats = sweep_dead_jobs(
            session, client=_client(_status_handler), min_interval=0, wait=False
        )
    assert stats["skipped_busy"] is True and stats["checked"] == 0
    assert _ids(session) == {"a"}


def test_sweep_lock_released_after_run(session):
    sweep_dead_jobs(session, client=_client(_status_handler), min_interval=0)
    assert liveness._sweep_lock.acquire(blocking=False)
    liveness._sweep_lock.release()


# --- manual prune ---


def test_prune_deletes_untracked_dead_keeps_tracked(session):
    session.add_all(
        [
            _job("ok", "http://x/200"),
            _job("dead", "http://x/404"),
            _job("dead_tracked", "http://x/404"),
        ]
    )
    session.commit()
    tracked = session.query(Job).filter_by(source_id="dead_tracked").one()
    session.add(Application(job_id=tracked.id, status="applied"))
    session.commit()

    stats = prune_dead_jobs(
        session, limit=10, apply=True, client=_client(_status_handler), min_interval=0
    )
    assert stats["dead"] == 1  # only untracked dead jobs count toward deletion
    assert stats["deleted"] == 1
    assert _ids(session) == {"ok", "dead_tracked"}  # untracked dead gone; tracked kept
    assert tracked.source_gone_at is not None


def test_prune_dry_run_deletes_nothing(session):
    session.add(_job("dead", "http://x/404"))
    session.commit()
    stats = prune_dead_jobs(
        session, limit=10, apply=False, client=_client(_status_handler), min_interval=0
    )
    assert stats["dead"] == 1 and stats["deleted"] == 0
    assert session.query(Job).count() == 1  # dry run left it in place


def test_prune_never_touches_manual_jobs(session):
    manual = _job("m", "http://x/404")
    manual.source = MANUAL_SOURCE
    session.add_all([manual, _job("dead", "http://x/404")])
    session.commit()

    stats = prune_dead_jobs(
        session, limit=10, apply=True, client=_client(_status_handler), min_interval=0
    )
    assert stats["checked"] == 1  # the manual job is not even scanned
    assert {j.source_id for j in session.query(Job).all()} == {"m"}
