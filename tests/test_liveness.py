"""Dead-listing scan: conservative liveness check + safe pruning."""

from __future__ import annotations

import httpx

from app.ingest.liveness import check_alive, prune_dead_jobs
from app.models import MANUAL_SOURCE, Application, Job


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _status_handler(request: httpx.Request) -> httpx.Response:
    # URL path like /404 -> respond with that status code.
    return httpx.Response(int(request.url.path.strip("/") or "200"))


def _job(sid, url) -> Job:
    return Job(
        source="t",
        source_id=sid,
        title="x",
        company="c",
        url=url,
        is_remote=True,
        is_european=True,
    )


def test_check_alive_status_mapping():
    c = _client(_status_handler)
    assert check_alive(c, "http://x/404") is False
    assert check_alive(c, "http://x/410") is False
    assert check_alive(c, "http://x/200") is True
    assert check_alive(c, "http://x/403") is None  # unknown -> keep
    assert check_alive(c, "http://x/503") is None
    assert check_alive(c, "") is None


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

    stats = prune_dead_jobs(session, limit=10, apply=True, client=_client(_status_handler))
    assert stats["dead"] == 1  # tracked dead job is skipped before the check
    assert stats["deleted"] == 1
    remaining = {j.source_id for j in session.query(Job).all()}
    assert remaining == {"ok", "dead_tracked"}  # untracked dead gone; tracked kept


def test_prune_dry_run_deletes_nothing(session):
    session.add(_job("dead", "http://x/404"))
    session.commit()
    stats = prune_dead_jobs(session, limit=10, apply=False, client=_client(_status_handler))
    assert stats["dead"] == 1 and stats["deleted"] == 0
    assert session.query(Job).count() == 1  # dry run left it in place


def test_prune_never_touches_manual_jobs(session):
    manual = _job("m", "http://x/404")
    manual.source = MANUAL_SOURCE
    session.add_all([manual, _job("dead", "http://x/404")])
    session.commit()

    stats = prune_dead_jobs(session, limit=10, apply=True, client=_client(_status_handler))
    assert stats["checked"] == 1  # the manual job is not even scanned
    assert {j.source_id for j in session.query(Job).all()} == {"m"}
