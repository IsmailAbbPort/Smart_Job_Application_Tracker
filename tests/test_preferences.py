"""Search preferences: CRUD, default application, blocklist, ignore_prefs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Cv, Job


def _job(
    sid,
    *,
    country=None,
    city=None,
    is_remote=True,
    is_european=True,
    embedding=None,
    posted_at=None,
) -> Job:
    return Job(
        source="test",
        source_id=sid,
        title="Engineer",
        company="Acme",
        url=f"https://example.com/{sid}",
        is_remote=is_remote,
        is_european=is_european,
        country=country,
        city=city,
        embedding=embedding,
        posted_at=posted_at,
    )


def test_get_creates_permissive_default(client):
    body = client.get("/preferences").json()
    assert body["remote_only"] is False
    assert body["require_european"] is False
    assert body["exclude_countries"] == []
    assert body["exclude_cities"] == []


def test_update_and_normalize(client):
    resp = client.put(
        "/preferences",
        json={
            "remote_only": True,
            "exclude_countries": ["United States", " united states ", "Canada"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["remote_only"] is True
    # Trimmed + de-duplicated (case-insensitive), order preserved.
    assert body["exclude_countries"] == ["United States", "Canada"]
    # Untouched field keeps its default.
    assert body["require_european"] is False


def test_jobs_apply_remote_default(client, session_factory):
    with session_factory() as s:
        s.add_all([_job("r", is_remote=True), _job("o", is_remote=False)])
        s.commit()
    client.put("/preferences", json={"remote_only": True})

    ids = [i["source_id"] for i in client.get("/jobs").json()["items"]]
    assert ids == ["r"]  # non-remote dropped by default
    # ignore_prefs brings the non-remote one back.
    ids_all = [
        i["source_id"] for i in client.get("/jobs", params={"ignore_prefs": "true"}).json()["items"]
    ]
    assert set(ids_all) == {"r", "o"}


def test_jobs_country_and_city_blocklist(client, session_factory):
    with session_factory() as s:
        s.add_all(
            [
                _job("de", country="Germany", city="Berlin"),
                _job("us", country="United States", city="Austin"),
                _job("uk_lon", country="United Kingdom", city="London"),
                _job("nocountry", country=None, city=None),
            ]
        )
        s.commit()
    client.put(
        "/preferences",
        json={"exclude_countries": ["United States"], "exclude_cities": ["London"]},
    )

    ids = {i["source_id"] for i in client.get("/jobs").json()["items"]}
    assert ids == {"de", "nocountry"}  # US excluded by country, London by city; null kept


def test_max_age_days_default_and_clear(client, session_factory):
    now = datetime.now(UTC)
    with session_factory() as s:
        s.add_all(
            [
                _job("new", posted_at=now - timedelta(days=5)),
                _job("old", posted_at=now - timedelta(days=200)),
                _job("undated", posted_at=None),
            ]
        )
        s.commit()
    client.put("/preferences", json={"max_age_days": 30})
    ids = {i["source_id"] for i in client.get("/jobs").json()["items"]}
    assert ids == {"new", "undated"}  # old dropped, null-dated kept

    # A non-positive value clears the cutoff.
    body = client.put("/preferences", json={"max_age_days": 0}).json()
    assert body["max_age_days"] is None
    ids_all = {i["source_id"] for i in client.get("/jobs").json()["items"]}
    assert ids_all == {"new", "old", "undated"}


def test_explicit_param_overrides_pref(client, session_factory):
    with session_factory() as s:
        s.add_all([_job("r", is_remote=True), _job("o", is_remote=False)])
        s.commit()
    client.put("/preferences", json={"remote_only": True})
    # Explicitly asking for non-remote overrides the remote_only default.
    ids = [
        i["source_id"] for i in client.get("/jobs", params={"is_remote": "false"}).json()["items"]
    ]
    assert ids == ["o"]


def test_shortlist_respects_blocklist(client, session_factory):
    with session_factory() as s:
        s.add(Cv(label="cv", content="x", embedding=[1.0, 0.0, 0.0]))
        s.add_all(
            [
                _job("de", country="Germany", embedding=[1.0, 0.0, 0.0]),
                _job("us", country="United States", embedding=[1.0, 0.0, 0.0]),
            ]
        )
        s.commit()
    client.put("/preferences", json={"exclude_countries": ["United States"]})

    ids = [i["source_id"] for i in client.get("/match/shortlist").json()["items"]]
    assert ids == ["de"]  # US excluded even though it is a perfect vector match
