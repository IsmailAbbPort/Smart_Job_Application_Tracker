"""CV file storage: the original upload is kept, served for preview, and relabelable."""

from __future__ import annotations

import base64


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_upload_stores_file_and_metadata(embed_client):
    resp = embed_client.post(
        "/cv/upload",
        json={"label": "txt cv", "filename": "cv.txt", "content_base64": _b64(b"Python engineer.")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["filename"] == "cv.txt"
    assert body["content_type"] == "text/plain"
    assert body["size_bytes"] == len(b"Python engineer.")


def test_file_endpoint_serves_original(embed_client):
    cv = embed_client.post(
        "/cv/upload",
        json={"label": "cv", "filename": "cv.txt", "content_base64": _b64(b"hello world")},
    ).json()
    resp = embed_client.get(f"/cv/{cv['id']}/file")
    assert resp.status_code == 200
    assert resp.content == b"hello world"
    assert resp.headers["content-type"].startswith("text/plain")


def test_patch_relabels(embed_client):
    cv = embed_client.post(
        "/cv/upload",
        json={"label": "old", "filename": "cv.txt", "content_base64": _b64(b"x")},
    ).json()
    resp = embed_client.patch(f"/cv/{cv['id']}", json={"label": "new label"})
    assert resp.status_code == 200
    assert resp.json()["label"] == "new label"


def test_reject_unsupported_type(embed_client):
    resp = embed_client.post(
        "/cv/upload",
        json={"label": "bad", "filename": "cv.docx", "content_base64": _b64(b"not a cv")},
    )
    assert resp.status_code == 422
