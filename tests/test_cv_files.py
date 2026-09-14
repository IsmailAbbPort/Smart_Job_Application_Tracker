"""CV file storage: original kept, served for preview, relabelable, owner-scoped."""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.models import CoverLetter, Cv, Job, Match
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


# --- PUT /{cv_id}/file (replace the file) ---


def _replace(client, cv_id, filename="new.txt", data=b"Go and Rust engineer."):
    return client.put(
        f"/cv/{cv_id}/file", json={"filename": filename, "content_base64": _b64(data)}
    )


def _seed_match_and_letter(session_factory, cv_id) -> None:
    with session_factory() as s:
        job = Job(
            source="test",
            source_id="1",
            title="Engineer",
            company="Acme",
            url="https://example.com/1",
            is_remote=True,
            is_european=True,
        )
        s.add(job)
        s.flush()
        s.add(
            Match(
                cv_id=cv_id,
                job_id=job.id,
                overall_score=80,
                verdict="strong",
                one_line_verdict="fit",
                model="fake-judge",
            )
        )
        s.add(CoverLetter(cv_id=cv_id, job_id=job.id, body="Dear Acme", model="fake-drafter"))
        s.commit()


def test_replace_file_reembeds_and_keeps_label(embed_client, session_factory):
    cv = _upload(embed_client, label="main", data=b"Python engineer.").json()
    with session_factory() as s:
        old_embedding = list(s.get(Cv, cv["id"]).embedding)

    resp = _replace(embed_client, cv["id"], filename="new.txt", data=b"Go and Rust engineer.")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == cv["id"]
    assert body["label"] == "main"  # kept
    assert body["filename"] == "new.txt"
    assert body["content_type"] == "text/plain"
    assert body["size_bytes"] == len(b"Go and Rust engineer.")
    assert body["embedded"] is True

    assert embed_client.get(f"/cv/{cv['id']}").json()["content"] == "Go and Rust engineer."
    assert embed_client.get(f"/cv/{cv['id']}/file").content == b"Go and Rust engineer."
    with session_factory() as s:
        assert list(s.get(Cv, cv["id"]).embedding) != old_embedding


def test_replace_file_accepts_pdf(embed_client):
    cv = _upload(embed_client).json()
    pdf = (FIXTURES / "sample_cv.pdf").read_bytes()
    body = _replace(embed_client, cv["id"], filename="cv.pdf", data=pdf).json()
    assert body["content_type"] == "application/pdf"
    assert body["size_bytes"] == len(pdf)


def test_replace_file_clears_matches_and_letters(embed_client, session_factory):
    cv = _upload(embed_client).json()
    _seed_match_and_letter(session_factory, cv["id"])

    assert _replace(embed_client, cv["id"]).status_code == 200

    # Verdicts and letters grounded in the old text are stale, so they are dropped.
    with session_factory() as s:
        assert s.query(Match).filter_by(cv_id=cv["id"]).count() == 0
        assert s.query(CoverLetter).filter_by(cv_id=cv["id"]).count() == 0


def test_replace_file_keeps_other_cvs_verdicts(embed_client, session_factory):
    cv = _upload(embed_client).json()
    other = _upload(embed_client, label="other").json()
    _seed_match_and_letter(session_factory, other["id"])

    assert _replace(embed_client, cv["id"]).status_code == 200

    with session_factory() as s:
        assert s.query(Match).filter_by(cv_id=other["id"]).count() == 1
        assert s.query(CoverLetter).filter_by(cv_id=other["id"]).count() == 1


def test_replace_file_rejects_bad_file(embed_client):
    cv = _upload(embed_client, data=b"Python engineer.").json()
    assert _replace(embed_client, cv["id"], filename="cv.docx", data=b"x").status_code == 422
    assert _replace(embed_client, cv["id"], data=b"   ").status_code == 422
    big = b"x" * (MAX_CV_BYTES + 1)
    assert _replace(embed_client, cv["id"], data=big).status_code == 413
    resp = embed_client.put(
        f"/cv/{cv['id']}/file", json={"filename": "cv.txt", "content_base64": "@@@"}
    )
    assert resp.status_code == 422
    # A rejected replace leaves the original file in place.
    assert embed_client.get(f"/cv/{cv['id']}/file").content == b"Python engineer."


def test_replace_file_missing_cv_404(embed_client):
    assert _replace(embed_client, 999999).status_code == 404


def test_replace_file_is_owner_scoped(embed_client):
    guest_cv = _upload(embed_client, data=b"Guest engineer.").json()
    with TestClient(fastapi_app) as user:
        user.post(
            "/auth/register",
            json={"name": "Ann", "email": "a@b.com", "password": "secret1!"},
        )
        assert _replace(user, guest_cv["id"]).status_code == 404
    assert embed_client.get(f"/cv/{guest_cv['id']}/file").content == b"Guest engineer."
