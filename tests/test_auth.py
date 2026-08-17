"""Auth flow (register/login/me/logout) and per-owner data isolation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.models import Job

GOOD_PW = "secret1!"


def _seed_job(session_factory, sid="j") -> int:
    with session_factory() as s:
        job = Job(
            source="test",
            source_id=sid,
            title="Engineer",
            company="Acme",
            url=f"https://example.com/{sid}",
            is_remote=True,
            is_european=True,
        )
        s.add(job)
        s.commit()
        return job.id


def _register(client, email="a@b.com", name="Ann", password=GOOD_PW):
    return client.post("/auth/register", json={"name": name, "email": email, "password": password})


def test_register_sets_session_and_me(client):
    resp = _register(client)
    assert resp.status_code == 201
    assert resp.json()["email"] == "a@b.com"
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["name"] == "Ann"


def test_me_is_null_for_guest(client):
    assert client.get("/auth/me").json() is None


def test_weak_password_rejected(client):
    # No number / special char -> 422, and no account is created.
    assert _register(client, password="abcdef").status_code == 422


def test_duplicate_email_conflict(client):
    assert _register(client).status_code == 201
    # A second client (fresh cookies) trying the same email.
    with TestClient(fastapi_app) as other:
        assert _register(other).status_code == 409


def test_login_and_wrong_password(client):
    _register(client)
    client.post("/auth/logout")
    assert client.get("/auth/me").json() is None
    ok = client.post("/auth/login", json={"email": "a@b.com", "password": GOOD_PW})
    assert ok.status_code == 200
    assert client.get("/auth/me").json()["email"] == "a@b.com"
    client.post("/auth/logout")
    bad = client.post("/auth/login", json={"email": "a@b.com", "password": "nope1!"})
    assert bad.status_code == 401


def test_applications_isolated_per_owner(client, session_factory):
    """A logged-in user's tracked jobs are invisible to a guest and to other users."""
    job_id = _seed_job(session_factory)

    # User A tracks the job.
    _register(client, email="a@b.com", name="Ann")
    assert client.post("/applications", json={"job_id": job_id, "status": "saved"}).status_code == 201
    assert len(client.get("/applications").json()) == 1

    # A guest (separate client, no cookies) sees nothing.
    with TestClient(fastapi_app) as guest:
        assert guest.get("/applications").json() == []
        assert guest.get("/applications/stats").json()["total"] == 0

    # User B sees nothing of A's, and can track the same job independently.
    with TestClient(fastapi_app) as other:
        _register(other, email="b@b.com", name="Bo")
        assert other.get("/applications").json() == []
        assert (
            other.post("/applications", json={"job_id": job_id, "status": "applied"}).status_code
            == 201
        )
        assert len(other.get("/applications").json()) == 1

    # A still has exactly one, unaffected by B.
    assert len(client.get("/applications").json()) == 1
