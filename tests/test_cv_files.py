"""CV file storage: original kept, served for preview, relabelable, owner-scoped."""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.routers.cv import MAX_CV_BYTES

FIXTURES = Path(__file__).parent / "fixtures"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _upload(client, label="cv", filename="cv.txt", data=b"Python engineer."):
    return client.post(
        "/cv/upload",
        json={"label": label, "filename": filename, "content_base64": _b64(data)},
    )


# --- storage + metadata ---


def test_upload_text_stores_metadata(embed_client):
    body = _upload(embed_client, data=b"Python engineer.").json()
    assert body["filename"] == "cv.txt"
    assert body["content_type"] == "text/plain"
    assert body["size_bytes"] == len(b"Python engineer.")


def test_upload_pdf_stores_as_pdf(embed_client):
    pdf = (FIXTURES / "sample_cv.pdf").read_bytes()
    body = _upload(embed_client, filename="cv.pdf", data=pdf).json()
    assert body["content_type"] == "application/pdf"
    assert body["size_bytes"] == len(pdf)


def test_detail_includes_file_fields(embed_client):
    cv = _upload(embed_client).json()
    detail = embed_client.get(f"/cv/{cv['id']}").json()
    assert detail["filename"] == "cv.txt"
    assert detail["content_type"] == "text/plain"
    assert "content" in detail


def test_text_cv_via_post_has_no_file(embed_client):
    # POST /cv (text only) stores no original file, so preview 404s.
    cv = embed_client.post("/cv", json={"label": "typed", "content": "hello"}).json()
    assert cv["filename"] is None
    assert embed_client.get(f"/cv/{cv['id']}/file").status_code == 404


# --- file preview endpoint ---


def test_file_endpoint_serves_original_inline(embed_client):
    cv = _upload(embed_client, data=b"hello world").json()
    resp = embed_client.get(f"/cv/{cv['id']}/file")
    assert resp.status_code == 200
    assert resp.content == b"hello world"
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.headers["content-disposition"].startswith("inline")


def test_file_endpoint_missing_cv_404(embed_client):
    assert embed_client.get("/cv/999999/file").status_code == 404


# --- limits ---


def test_upload_rejects_oversize_file(embed_client):
    big = b"x" * (MAX_CV_BYTES + 1)
    assert _upload(embed_client, filename="cv.txt", data=big).status_code == 413


def test_upload_rejects_unsupported_type(embed_client):
    assert _upload(embed_client, filename="cv.docx", data=b"not a cv").status_code == 422


def test_upload_rejects_bad_base64(embed_client):
    resp = embed_client.post(
        "/cv/upload", json={"label": "x", "filename": "cv.txt", "content_base64": "@@@not b64@@@"}
    )
    assert resp.status_code == 422


def test_upload_rejects_empty_extraction(embed_client):
    assert _upload(embed_client, data=b"   \n\t ").status_code == 422


# --- PATCH (relabel) ---


def test_patch_relabels(embed_client):
    cv = _upload(embed_client, label="old").json()
    resp = embed_client.patch(f"/cv/{cv['id']}", json={"label": "  new label  "})
    assert resp.status_code == 200
    assert resp.json()["label"] == "new label"  # trimmed


def test_patch_empty_label_rejected(embed_client):
    cv = _upload(embed_client).json()
    assert embed_client.patch(f"/cv/{cv['id']}", json={"label": "   "}).status_code == 422


def test_patch_missing_cv_404(embed_client):
    assert embed_client.patch("/cv/999999", json={"label": "x"}).status_code == 404


# --- DELETE ---


def test_delete_removes_cv(embed_client):
    cv = _upload(embed_client).json()
    assert embed_client.delete(f"/cv/{cv['id']}").status_code == 204
    assert embed_client.get(f"/cv/{cv['id']}").status_code == 404
    assert embed_client.get("/cv").json() == []


def test_delete_missing_cv_404(embed_client):
    assert embed_client.delete("/cv/999999").status_code == 404


def test_delete_is_owner_scoped(embed_client):
    guest_cv = _upload(embed_client, label="guest cv").json()
    with TestClient(fastapi_app) as user:
        user.post(
            "/auth/register",
            json={"name": "Ann", "email": "a@b.com", "password": "secret1!"},
        )
        # A user cannot delete the guest's CV.
        assert user.delete(f"/cv/{guest_cv['id']}").status_code == 404
    # Still there for the guest.
    assert embed_client.get(f"/cv/{guest_cv['id']}").status_code == 200


# --- owner scoping ---


def test_cv_is_owner_scoped(embed_client, session_factory):
    """A guest's CV is invisible to a signed-in user, and vice-versa, across
    list / detail / file / patch."""
    # Guest uploads a CV.
    guest_cv = _upload(embed_client, label="guest cv").json()

    # A registered user sees none of it and gets 404 on every per-CV route.
    with TestClient(fastapi_app) as user:
        user.post(
            "/auth/register",
            json={"name": "Ann", "email": "a@b.com", "password": "secret1!"},
        )
        assert user.get("/cv").json() == []
        assert user.get(f"/cv/{guest_cv['id']}").status_code == 404
        assert user.get(f"/cv/{guest_cv['id']}/file").status_code == 404
        assert user.patch(f"/cv/{guest_cv['id']}", json={"label": "hijack"}).status_code == 404

        # The user's own upload is separate and visible only to them.
        own = _upload(user, label="user cv").json()
        assert [c["id"] for c in user.get("/cv").json()] == [own["id"]]

    # Guest still sees only their own, unaffected.
    assert [c["id"] for c in embed_client.get("/cv").json()] == [guest_cv["id"]]
