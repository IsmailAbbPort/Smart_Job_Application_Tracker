"""/cv endpoint tests (with a fake embedder)."""

from __future__ import annotations

import base64
from pathlib import Path

from app.models import Cv

FIXTURES = Path(__file__).parent / "fixtures"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


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


def test_upload_text_cv(embed_client, session_factory):
    payload = {
        "label": "text upload",
        "filename": "cv.txt",
        "content_base64": _b64(b"Backend engineer. Python, FastAPI, Postgres."),
    }
    resp = embed_client.post("/cv/upload", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["embedded"] is True

    with session_factory() as s:
        cv = s.get(Cv, body["id"])
        assert "FastAPI" in cv.content


def test_upload_pdf_cv_extracts_text(embed_client, session_factory):
    pdf_bytes = (FIXTURES / "sample_cv.pdf").read_bytes()
    payload = {"label": "pdf upload", "filename": "cv.pdf", "content_base64": _b64(pdf_bytes)}
    resp = embed_client.post("/cv/upload", json=payload)
    assert resp.status_code == 201

    with session_factory() as s:
        cv = s.get(Cv, resp.json()["id"])
        assert "FastAPI" in cv.content  # text pulled out of the PDF


def test_upload_rejects_bad_base64(embed_client):
    payload = {"label": "x", "filename": "cv.txt", "content_base64": "not valid base64 !!!"}
    assert embed_client.post("/cv/upload", json=payload).status_code == 422


def test_upload_rejects_empty_extraction(embed_client):
    payload = {"label": "x", "filename": "cv.txt", "content_base64": _b64(b"   ")}
    assert embed_client.post("/cv/upload", json=payload).status_code == 422
