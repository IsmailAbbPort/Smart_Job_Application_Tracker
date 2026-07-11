"""/cv endpoint tests (with a fake embedder)."""

from __future__ import annotations

from app.models import Cv


def test_create_cv_embeds_and_stores(embed_client, session_factory):
    resp = embed_client.post("/cv", json={"label": "My CV", "content": "Python engineer, FastAPI."})
    assert resp.status_code == 201
    body = resp.json()
    assert body["label"] == "My CV"
    assert body["embedded"] is True

    # Embedding actually persisted.
    with session_factory() as s:
        cv = s.get(Cv, body["id"])
        assert cv.embedding is not None and len(cv.embedding) == 8


def test_list_and_get_cv(embed_client):
    created = embed_client.post("/cv", json={"label": "CV1", "content": "content here"}).json()
    listing = embed_client.get("/cv").json()
    assert any(c["id"] == created["id"] for c in listing)

    detail = embed_client.get(f"/cv/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["content"] == "content here"


def test_get_missing_cv_404(embed_client):
    assert embed_client.get("/cv/999999").status_code == 404
