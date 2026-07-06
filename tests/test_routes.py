"""API tests: GET /jobs (filters, pagination, detail) and POST /ingest."""

from __future__ import annotations

from datetime import UTC, datetime

from app.ingest import runner
from app.ingest.geo import resolve_city, resolve_country
from app.ingest.normalize import (
    dedup_key,
    normalize_company,
    normalize_location,
    normalize_title,
)
from app.models import Job
from tests.conftest import FakeSource, make_canonical


def _make_job(source, source_id, title, company, *, is_remote, location, posted_year=2026) -> Job:
    country = resolve_country(location)
    return Job(
        source=source,
        source_id=source_id,
        title=title,
        company=company,
        location=location,
        is_remote=is_remote,
        city=resolve_city(location),
        country=country,
        is_european=country is not None,
        description=f"{title} at {company}",
        url=f"https://example.com/{source_id}",
        posted_at=datetime(posted_year, 6, 1, tzinfo=UTC),
        company_norm=normalize_company(company),
        title_norm=normalize_title(title),
        location_norm=normalize_location(location),
        dedup_key=dedup_key(company, title, location),
    )


def _seed(session_factory) -> None:
    with session_factory() as s:
        s.add_all(
            [
                _make_job(
                    "greenhouse",
                    "gitlab:1",
                    "Senior Backend Engineer",
                    "GitLab",
                    is_remote=True,
                    location="Remote, Germany",
                    posted_year=2026,
                ),
                _make_job(
                    "remotive",
                    "100",
                    "Copywriter",
                    "Coalition Technologies",
                    is_remote=True,
                    location="Worldwide",
                    posted_year=2025,
                ),
                _make_job(
                    "lever",
                    "mistral:2",
                    "Data Scientist",
                    "Mistral AI",
                    is_remote=False,
                    location="Paris",
                    posted_year=2024,
                ),
            ]
        )
        s.commit()


def test_list_all(client, session_factory):
    _seed(session_factory)
    body = client.get("/jobs").json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    # Ordered by posted_at desc -> the 2026 GitLab role comes first.
    assert body["items"][0]["company"] == "GitLab"


def test_filter_by_source(client, session_factory):
    _seed(session_factory)
    body = client.get("/jobs", params={"source": "greenhouse"}).json()
    assert body["total"] == 1
    assert body["items"][0]["source"] == "greenhouse"


def test_filter_by_is_remote(client, session_factory):
    _seed(session_factory)
    body = client.get("/jobs", params={"is_remote": "true"}).json()
    assert body["total"] == 2
    assert all(item["is_remote"] for item in body["items"])


def test_filter_by_query(client, session_factory):
    _seed(session_factory)
    body = client.get("/jobs", params={"q": "engineer"}).json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Senior Backend Engineer"


def test_filter_by_company(client, session_factory):
    _seed(session_factory)
    body = client.get("/jobs", params={"company": "mistral"}).json()
    assert body["total"] == 1
    assert body["items"][0]["company"] == "Mistral AI"


def test_filter_by_europe(client, session_factory):
    _seed(session_factory)
    body = client.get("/jobs", params={"europe": "true"}).json()
    # GitLab (Germany) + Data Scientist (Paris); Copywriter (Worldwide) excluded.
    assert body["total"] == 2
    assert {i["company"] for i in body["items"]} == {"GitLab", "Mistral AI"}


def test_filter_remote_european(client, session_factory):
    _seed(session_factory)
    # The user's actual scope: remote AND located in Europe.
    body = client.get("/jobs", params={"is_remote": "true", "europe": "true"}).json()
    assert body["total"] == 1
    assert body["items"][0]["company"] == "GitLab"  # Paris role is not remote; Worldwide not EU


def test_filter_by_country(client, session_factory):
    _seed(session_factory)
    body = client.get("/jobs", params={"country": "france"}).json()
    assert body["total"] == 1
    assert body["items"][0]["company"] == "Mistral AI"


def test_filter_by_city(client, session_factory):
    _seed(session_factory)
    body = client.get("/jobs", params={"city": "paris"}).json()
    assert body["total"] == 1
    assert body["items"][0]["company"] == "Mistral AI"
    assert body["items"][0]["city"] == "Paris"


def test_pagination(client, session_factory):
    _seed(session_factory)
    body = client.get("/jobs", params={"limit": 1, "offset": 0}).json()
    assert body["total"] == 3
    assert len(body["items"]) == 1
    assert body["limit"] == 1


def test_get_job_detail_and_404(client, session_factory):
    _seed(session_factory)
    listed = client.get("/jobs").json()["items"]
    job_id = listed[0]["id"]

    detail = client.get(f"/jobs/{job_id}")
    assert detail.status_code == 200
    assert "description" in detail.json()

    assert client.get("/jobs/999999").status_code == 404


def test_list_sources(client):
    body = client.get("/ingest/sources").json()
    assert set(body) == {"greenhouse", "lever", "ashby", "arbeitnow", "remotive"}
    assert body["remotive"]["ttl_seconds"] > 0


def test_ingest_unknown_source_404(client):
    assert client.post("/ingest/nope").status_code == 404


def test_ingest_endpoint_with_fake_source(client, monkeypatch):
    jobs = [make_canonical(source_id="1"), make_canonical(source_id="2", title="SRE")]
    monkeypatch.setitem(runner.SOURCES, "fakeroute", FakeSource("fakeroute", jobs))

    resp = client.post("/ingest/fakeroute", params={"force": "true"})
    assert resp.status_code == 200
    assert resp.json()["inserted"] == 2

    # The ingested jobs are now listable.
    listed = client.get("/jobs", params={"source": "fakeroute"}).json()
    assert listed["total"] == 2
