"""Expired aggregator jobs are swept from the shortlist: on view, and nightly."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings, get_settings
from app.ingest import liveness
from app.main import app as fastapi_app
from app.models import Cv, Job, SearchPreferences
from app.shortlist import sweep_saved_shortlists


def _job(sid, *, source="arbeitnow", status=200, embedding=(1.0, 0.0, 0.0)) -> Job:
    return Job(
        source=source,
        source_id=sid,
        title="Backend Engineer",
        company="Acme",
        url=f"http://jobs.test/{status}/{sid}",
        is_remote=True,
        is_european=True,
        embedding=list(embedding),
    )


def _status_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(int(request.url.path.strip("/").split("/")[0]))

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def mock_http(monkeypatch):
    requested: list[str] = []

    def make_client():
        client = _status_client()
        original = client.head

        def head(url, **kwargs):
            requested.append(str(url))
            return original(url, **kwargs)

        client.head = head
        return client

    monkeypatch.setattr(liveness, "_make_client", make_client)
    return requested


@pytest.fixture
def fast_settings():
    fastapi_app.dependency_overrides[get_settings] = lambda: Settings(
        liveness_min_interval_seconds=0, liveness_view_max_checks=30
    )
    yield
    fastapi_app.dependency_overrides.pop(get_settings, None)


def _seed(session_factory, jobs) -> dict[str, int]:
    with session_factory() as s:
        s.add(Cv(label="cv", content="x", embedding=[1.0, 0.0, 0.0]))
        s.add_all(jobs)
        s.commit()
        return {j.source_id: j.id for j in s.query(Job).all()}


def test_viewing_shortlist_sweeps_expired_aggregator_jobs(
    client, session_factory, mock_http, fast_settings
):
    ids = _seed(
        session_factory,
        [
            _job("expired", status=410),
            _job("live", status=200),
            _job("ats_dead_url", source="greenhouse", status=404),
        ],
    )
    body = client.get("/match/shortlist").json()
    assert {i["source_id"] for i in body["items"]} == {"expired", "live", "ats_dead_url"}

    # The background check ran after the response: only aggregator jobs were requested.
    assert len(mock_http) == 2 and not any("ats_dead_url" in u for u in mock_http)
    existing = client.get("/jobs/existing", params={"ids": list(ids.values())}).json()["ids"]
    assert set(existing) == {ids["live"], ids["ats_dead_url"]}


def test_viewing_shortlist_skips_recently_confirmed_jobs(
    client, session_factory, mock_http, fast_settings
):
    _seed(session_factory, [_job("live", status=200)])
    client.get("/match/shortlist")
    client.get("/match/shortlist")  # confirmed live moments ago -> not re-checked
    assert len(mock_http) == 1


def test_view_check_is_capped(client, session_factory, mock_http):
    fastapi_app.dependency_overrides[get_settings] = lambda: Settings(
        liveness_min_interval_seconds=0, liveness_view_max_checks=2
    )
    try:
        _seed(session_factory, [_job(f"j{i}") for i in range(5)])
        client.get("/match/shortlist")
    finally:
        fastapi_app.dependency_overrides.pop(get_settings, None)
    assert len(mock_http) == 2


def test_shortlist_remembers_last_query(client, session_factory, mock_http, fast_settings):
    _seed(session_factory, [_job("live")])
    client.get("/match/shortlist", params={"limit": 7, "is_remote": "true", "cities": "Berlin"})
    with session_factory() as s:
        saved = s.query(SearchPreferences).filter_by(owner_id=None).one().last_shortlist_query
    assert saved["limit"] == 7 and saved["is_remote"] is True and saved["cities"] == ["Berlin"]


def test_existing_ids_endpoint_caps_input(client):
    resp = client.get("/jobs/existing", params={"ids": list(range(201))})
    assert resp.status_code == 422


def test_nightly_sweep_replays_saved_shortlists(session, mock_http, monkeypatch):
    monkeypatch.setattr(
        "app.shortlist.get_settings", lambda: Settings(liveness_min_interval_seconds=0)
    )
    session.add(Cv(label="cv", content="x", embedding=[1.0, 0.0, 0.0]))
    session.add_all(
        [
            _job("in_remote_list", status=410),
            _job("onsite_expired", status=410),
        ]
    )
    session.commit()
    onsite = session.query(Job).filter_by(source_id="onsite_expired").one()
    onsite.is_remote = False
    # The owner last viewed a remote-only shortlist; the nightly run replays exactly that.
    session.add(SearchPreferences(owner_id=None, last_shortlist_query={"is_remote": True}))
    session.commit()

    stats = sweep_saved_shortlists(session)
    assert stats["deleted"] == 1
    assert {j.source_id for j in session.query(Job).all()} == {"onsite_expired"}


def test_nightly_sweep_skips_owners_without_query_or_cv(session, mock_http, monkeypatch):
    monkeypatch.setattr(
        "app.shortlist.get_settings", lambda: Settings(liveness_min_interval_seconds=0)
    )
    session.add(_job("expired", status=410))
    session.add(SearchPreferences(owner_id=None, last_shortlist_query={}))  # no CV
    session.commit()
    assert sweep_saved_shortlists(session)["checked"] == 0
    assert mock_http == []
