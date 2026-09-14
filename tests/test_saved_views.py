"""Saved views: CRUD on named filter presets, name validation, owner scoping."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app as fastapi_app


def _register(client, email, name="U", password="secret1!"):
    return client.post("/auth/register", json={"name": name, "email": email, "password": password})


def _create(client, name="Remote EU", filters=None):
    return client.post("/views", json={"name": name, "filters": filters or {"remote": True}})


def test_create_and_list(client):
    resp = _create(client, name="  Remote EU  ", filters={"remote": True, "cities": ["Berlin"]})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Remote EU"  # trimmed
    assert body["filters"] == {"remote": True, "cities": ["Berlin"]}  # stored as-is
    assert body["created_at"] and body["updated_at"]

    assert [v["id"] for v in client.get("/views").json()] == [body["id"]]


def test_list_newest_first(client):
    first = _create(client, name="first").json()
    second = _create(client, name="second").json()
    assert [v["id"] for v in client.get("/views").json()] == [second["id"], first["id"]]


def test_create_empty_name_rejected(client):
    resp = _create(client, name="   ")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Name cannot be empty."


def test_patch_updates_name_and_filters(client):
    view = _create(client).json()

    renamed = client.patch(f"/views/{view['id']}", json={"name": " Renamed "})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed"
    assert renamed.json()["filters"] == view["filters"]  # untouched

    refiltered = client.patch(f"/views/{view['id']}", json={"filters": {"q": "python"}}).json()
    assert refiltered["name"] == "Renamed"
    assert refiltered["filters"] == {"q": "python"}


def test_patch_empty_name_rejected(client):
    view = _create(client).json()
    resp = client.patch(f"/views/{view['id']}", json={"name": ""})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Name cannot be empty."


def test_delete_removes_view(client):
    view = _create(client).json()
    assert client.delete(f"/views/{view['id']}").status_code == 204
    assert client.get("/views").json() == []


def test_missing_view_404(client):
    assert client.patch("/views/999999", json={"name": "x"}).status_code == 404
    assert client.delete("/views/999999").status_code == 404


def test_views_are_owner_scoped(client):
    guest_view = _create(client, name="guest").json()

    with TestClient(fastapi_app) as user:
        _register(user, "a@b.com")
        # A user sees none of the guest's views and cannot touch them.
        assert user.get("/views").json() == []
        resp = user.patch(f"/views/{guest_view['id']}", json={"name": "hijack"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "view not found"
        assert user.delete(f"/views/{guest_view['id']}").status_code == 404

        own = _create(user, name="mine").json()

        with TestClient(fastapi_app) as other:
            _register(other, "b@b.com")
            assert other.get("/views").json() == []
            assert other.delete(f"/views/{own['id']}").status_code == 404

        assert [v["id"] for v in user.get("/views").json()] == [own["id"]]

    # Guest still has exactly its own view, unmodified.
    views = client.get("/views").json()
    assert [(v["id"], v["name"]) for v in views] == [(guest_view["id"], "guest")]
