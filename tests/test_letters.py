"""Cover letter: FakeDrafter, the drafter gate, and the /letters routes."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.ai.cover_letter import FakeDrafter, get_drafter
from app.config import Settings
from app.models import Cv, Job
from app.schemas import CoverLetterResult


def _seed(
    session_factory, *, cv_content="Python FastAPI Postgres Docker engineer"
) -> tuple[int, int]:
    with session_factory() as s:
        cv = Cv(label="CV", content=cv_content)
        job = Job(
            source="test",
            source_id="1",
            title="Backend Engineer",
            company="Acme",
            url="https://example.com/1",
            description="We need a Python FastAPI Postgres engineer.",
            is_remote=True,
            is_european=True,
        )
        s.add_all([cv, job])
        s.commit()
        return cv.id, job.id


# --- FakeDrafter / gate ---


def test_fake_drafter_grounded_and_audited():
    result = FakeDrafter().write("Python FastAPI Postgres engineer", "Python FastAPI role")
    assert isinstance(result, CoverLetterResult)
    assert result.body.strip()
    # Deterministic letter leaves a placeholder and reports grounded claims.
    assert result.fabrication.placeholders
    assert result.fabrication.grounded_ratio == 1.0
    assert result.fabrication.unsupported_count == 0


def test_get_drafter_requires_key():
    with pytest.raises(HTTPException) as exc:
        get_drafter(Settings(anthropic_api_key=None))
    assert exc.value.status_code == 503


# --- routes ---


def test_draft_persists_and_caches(letter_client, session_factory):
    cv_id, job_id = _seed(session_factory)
    resp = letter_client.post(f"/letters/{job_id}", params={"cv_id": cv_id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id and body["cv_id"] == cv_id
    assert body["model"] == "fake-drafter"
    assert body["edited"] is False
    assert "fabrication" in body and "grounded_ratio" in body["fabrication"]

    # GET returns the stored letter.
    got = letter_client.get(f"/letters/{job_id}", params={"cv_id": cv_id})
    assert got.status_code == 200
    assert got.json()["body"] == body["body"]


def test_save_edit_marks_edited(letter_client, session_factory):
    cv_id, job_id = _seed(session_factory)
    letter_client.post(f"/letters/{job_id}", params={"cv_id": cv_id})
    saved = letter_client.put(
        f"/letters/{job_id}", params={"cv_id": cv_id}, json={"body": "My own edited letter."}
    ).json()
    assert saved["edited"] is True
    assert saved["body"] == "My own edited letter."
    # Fabrication audit is retained across the edit.
    assert "grounded_ratio" in saved["fabrication"]


def test_get_missing_letter_404(letter_client, session_factory):
    _cv_id, job_id = _seed(session_factory)
    assert letter_client.get(f"/letters/{job_id}").status_code == 404


def test_draft_missing_job_404(letter_client, session_factory):
    cv_id, _job_id = _seed(session_factory)
    assert letter_client.post("/letters/999999", params={"cv_id": cv_id}).status_code == 404
