"""Auth: register/login/me/logout, validation edge cases, JWT handling, isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import COOKIE_NAME, get_current_user, hash_password, verify_password
from app.config import INSECURE_JWT_DEFAULT, Settings, get_settings
from app.main import app as fastapi_app
from app.models import Job, User

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


# --- password hashing (unit) ---


def test_hash_roundtrip_and_wrong_password():
    h = hash_password(GOOD_PW)
    assert h != GOOD_PW  # never store plaintext
    assert verify_password(GOOD_PW, h)
    assert not verify_password("wrong", h)


def test_verify_tolerates_malformed_hash():
    assert verify_password(GOOD_PW, "not-a-bcrypt-hash") is False


def test_same_password_hashes_differ():
    # bcrypt salts each hash, so two hashes of the same password differ.
    assert hash_password(GOOD_PW) != hash_password(GOOD_PW)


# --- register / me ---


def test_register_sets_session_and_me(client):
    resp = _register(client)
    assert resp.status_code == 201
    assert resp.json()["email"] == "a@b.com"
    assert client.get("/auth/me").json()["name"] == "Ann"


def test_register_cookie_is_httponly(client):
    resp = _register(client)
    set_cookie = resp.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "Path=/" in set_cookie


def test_register_normalizes_email(client):
    _register(client, email="  Demo@Example.COM  ")
    assert client.get("/auth/me").json()["email"] == "demo@example.com"


def test_me_is_null_for_guest(client):
    assert client.get("/auth/me").json() is None


def test_register_requires_name(client):
    assert _register(client, name="   ").status_code == 422


def test_register_requires_valid_email(client):
    assert _register(client, email="not-an-email").status_code == 422


@pytest.mark.parametrize("password", ["short", "abcdef", "abcdefg", "123456", "!!!!!!"])
def test_register_rejects_weak_passwords(client, password):
    # Each fails at least one rule: length >=6, >=1 digit, >=1 special.
    assert _register(client, password=password).status_code == 422


@pytest.mark.parametrize("password", ["secret1!", "abc123#", "P@ssw0rd", "aaaa1_"])
def test_register_accepts_valid_passwords(client, password):
    assert _register(client, email=f"{len(password)}@b.com", password=password).status_code == 201


def test_duplicate_email_conflict_case_insensitive(client):
    assert _register(client, email="a@b.com").status_code == 201
    with TestClient(fastapi_app) as other:
        assert _register(other, email="A@B.COM").status_code == 409


# --- login / logout ---


def test_login_wrong_password_and_unknown_email(client):
    _register(client)
    client.post("/auth/logout")
    assert (
        client.post("/auth/login", json={"email": "a@b.com", "password": "nope1!"}).status_code
        == 401
    )
    assert (
        client.post("/auth/login", json={"email": "ghost@b.com", "password": GOOD_PW}).status_code
        == 401
    )


def test_login_is_case_insensitive_on_email(client):
    _register(client, email="a@b.com")
    client.post("/auth/logout")
    ok = client.post("/auth/login", json={"email": "A@B.COM", "password": GOOD_PW})
    assert ok.status_code == 200
    assert client.get("/auth/me").json()["email"] == "a@b.com"


def test_logout_clears_session(client):
    _register(client)
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").json() is None


def test_me_refreshes_session_cookie_when_authed(client):
    # Sliding session: /auth/me re-issues the cookie for a signed-in user so the
    # expiry counts from last activity (enables auto-login on return).
    _register(client)
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    assert "session=" in resp.headers.get("set-cookie", "")


def test_me_sets_no_cookie_for_guest(client):
    resp = client.get("/auth/me")
    assert resp.json() is None
    assert "session=" not in resp.headers.get("set-cookie", "")


# --- JWT session cookie handling ---


def _token(sub, *, secret=None, exp_delta=timedelta(days=1)):
    secret = secret or get_settings().jwt_secret
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": str(sub), "iat": now, "exp": now + exp_delta}, secret, algorithm="HS256"
    )


def test_garbage_cookie_is_guest(client):
    client.cookies.set(COOKIE_NAME, "not.a.jwt")
    assert client.get("/auth/me").json() is None


def test_expired_token_is_guest(client):
    resp = _register(client)
    uid = resp.json()["id"]
    client.cookies.set(COOKIE_NAME, _token(uid, exp_delta=timedelta(days=-1)))
    assert client.get("/auth/me").json() is None


def test_wrong_secret_token_is_guest(client):
    resp = _register(client)
    uid = resp.json()["id"]
    client.cookies.set(COOKIE_NAME, _token(uid, secret="a-different-secret-key-000000000000"))
    assert client.get("/auth/me").json() is None


def test_token_for_deleted_user_is_guest(client, session_factory):
    uid = _register(client).json()["id"]
    with session_factory() as s:
        s.delete(s.get(User, uid))
        s.commit()
    # Cookie is still a valid signed token, but the user no longer exists.
    assert client.get("/auth/me").json() is None


# --- get_current_user (required dependency) unit ---


def test_get_current_user_requires_auth():
    with pytest.raises(HTTPException) as exc:
        get_current_user(user=None)
    assert exc.value.status_code == 401


def test_get_current_user_passes_through_user():
    u = User(id=5, name="X", email="x@y.com", password_hash="h")
    assert get_current_user(user=u) is u


# --- production config guard ---


def test_production_rejects_default_jwt_secret():
    # Booting a real deploy with the source-visible default secret would let anyone
    # forge a session cookie, so the settings validator must refuse it.
    with pytest.raises(ValidationError):
        Settings(environment="production", cookie_secure=True, _env_file=None)


def test_production_requires_secure_cookie():
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            jwt_secret="a-strong-non-default-secret-value-000000",
            cookie_secure=False,
            _env_file=None,
        )


def test_production_with_real_secret_and_secure_cookie_is_valid():
    s = Settings(
        environment="production",
        jwt_secret="a-strong-non-default-secret-value-000000",
        cookie_secure=True,
        _env_file=None,
    )
    assert s.jwt_secret != INSECURE_JWT_DEFAULT


def test_development_keeps_permissive_defaults():
    # Local dev / tests need no configuration: defaults must not raise.
    s = Settings(environment="development", _env_file=None)
    assert s.jwt_secret == INSECURE_JWT_DEFAULT
    assert s.cookie_secure is False


# --- per-owner data isolation ---


def test_applications_isolated_per_owner(client, session_factory):
    job_id = _seed_job(session_factory)

    _register(client, email="a@b.com", name="Ann")
    assert (
        client.post("/applications", json={"job_id": job_id, "status": "saved"}).status_code == 201
    )
    assert len(client.get("/applications").json()) == 1

    with TestClient(fastapi_app) as guest:
        assert guest.get("/applications").json() == []
        assert guest.get("/applications/stats").json()["total"] == 0

    with TestClient(fastapi_app) as other:
        _register(other, email="b@b.com", name="Bo")
        assert other.get("/applications").json() == []
        assert (
            other.post("/applications", json={"job_id": job_id, "status": "applied"}).status_code
            == 201
        )
        assert len(other.get("/applications").json()) == 1

    assert len(client.get("/applications").json()) == 1  # A unaffected by B
