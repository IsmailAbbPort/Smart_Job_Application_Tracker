"""Per-owner isolation of search preferences (guest vs users, and across users)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app as fastapi_app


def _register(client, email, name="U", password="secret1!"):
    return client.post("/auth/register", json={"name": name, "email": email, "password": password})


def test_preferences_default_per_owner(client):
    assert client.get("/preferences").json()["years_experience"] is None


def test_guest_and_user_preferences_are_separate(client):
    # Guest sets years_experience.
    client.put("/preferences", json={"years_experience": 5})
    assert client.get("/preferences").json()["years_experience"] == 5

    with TestClient(fastapi_app) as user:
        _register(user, "a@b.com")
        # A fresh account starts from the permissive default, not the guest's value.
        assert user.get("/preferences").json()["years_experience"] is None
        user.put("/preferences", json={"years_experience": 10})
        assert user.get("/preferences").json()["years_experience"] == 10

    # Guest value is untouched by the user's edit.
    assert client.get("/preferences").json()["years_experience"] == 5


def test_two_users_have_independent_preferences(client):
    _register(client, "a@b.com")
    client.put("/preferences", json={"include_role_families": ["engineering"]})

    with TestClient(fastapi_app) as other:
        _register(other, "b@b.com")
        other.put("/preferences", json={"include_role_families": ["design"]})
        assert other.get("/preferences").json()["include_role_families"] == ["design"]

    assert client.get("/preferences").json()["include_role_families"] == ["engineering"]


def test_preferences_persist_across_login(client):
    _register(client, "a@b.com")
    client.put("/preferences", json={"years_experience": 7})
    client.post("/auth/logout")
    # Guest scope again: does not see the user's saved value.
    assert client.get("/preferences").json()["years_experience"] is None
    client.post("/auth/login", json={"email": "a@b.com", "password": "secret1!"})
    assert client.get("/preferences").json()["years_experience"] == 7
