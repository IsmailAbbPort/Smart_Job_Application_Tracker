"""Cover letter: FakeDrafter, the drafter gate, and the /letters routes."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.ai.cover_letter import AnthropicDrafter, FakeDrafter, get_drafter
from app.config import Settings
from app.models import Cv, Job, Match, User
from app.schemas import (
    CoverLetterResult,
    DimensionScores,
    FabricationCheck,
    FabricationClaim,
    MatchedRequirement,
    MatchTier,
    MatchVerdict,
)


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


def _verdict(requirement: str = "FastAPI services") -> MatchVerdict:
    return MatchVerdict(
        overall_score=80,
        verdict=MatchTier.strong,
        one_line_verdict="strong fit",
        dimension_scores=DimensionScores(skills=80, seniority=70, domain=75, location_remote=90),
        matched_requirements=[
            MatchedRequirement(requirement=requirement, cv_evidence="Built a FastAPI service")
        ],
        gaps=[],
    )


def test_fake_drafter_leads_with_match_brief():
    result = FakeDrafter().write("Python FastAPI engineer", "FastAPI role", _verdict())
    assert "FastAPI services" in result.body  # led with the judge's evidenced requirement
    assert result.fabrication.grounded_ratio == 1.0


# --- AnthropicDrafter orchestration (network-free: draft/check/revise are stubbed) ---


def _check_with(*supported: bool) -> FabricationCheck:
    return FabricationCheck(
        claims=[FabricationClaim(claim=f"c{i}", supported=s) for i, s in enumerate(supported)],
        placeholders=[],
    )


def test_anthropic_drafter_revises_when_unsupported():
    drafter = AnthropicDrafter(api_key="test")
    calls = {"draft": 0, "revise": 0, "check": 0}
    checks = iter([_check_with(False), _check_with(True)])  # first audit dirty, second clean

    def draft(cv, job, verdict):
        calls["draft"] += 1
        return "v1"

    def check(cv, letter):
        calls["check"] += 1
        return next(checks)

    def revise(cv, letter, report):
        calls["revise"] += 1
        return "v2"

    drafter._draft, drafter._check, drafter._revise = draft, check, revise

    result = drafter.write("cv text", "job text")
    assert calls == {"draft": 1, "revise": 1, "check": 2}  # one revise, then re-audited
    assert result.body == "v2"
    assert result.fabrication.unsupported_count == 0


def test_anthropic_drafter_skips_revise_when_clean():
    drafter = AnthropicDrafter(api_key="test")
    revised = {"n": 0}

    def revise(cv, letter, report):
        revised["n"] += 1
        return "x"

    drafter._draft = lambda cv, job, verdict: "clean letter"  # noqa: E731 - test stub
    drafter._check = lambda cv, letter: _check_with(True)  # noqa: E731 - test stub
    drafter._revise = revise

    result = drafter.write("cv text", "job text")
    assert revised["n"] == 0  # nothing unsupported -> no revise pass
    assert result.body == "clean letter"


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


def test_draft_grounds_in_stored_match_verdict(letter_client, session_factory):
    # When a judge verdict exists for (cv, job), the drafter is handed it so the letter
    # is built around the evidenced matches (here surfaced via the FakeDrafter's lead).
    cv_id, job_id = _seed(session_factory)
    with session_factory() as s:
        s.add(
            Match(
                cv_id=cv_id,
                job_id=job_id,
                overall_score=82,
                verdict="strong",
                one_line_verdict="strong fit",
                dimension_scores={
                    "skills": 82,
                    "seniority": 70,
                    "domain": 75,
                    "location_remote": 90,
                },
                matched_requirements=[
                    {"requirement": "FastAPI services", "cv_evidence": "Built a FastAPI service"}
                ],
                gaps=[],
                model="fake-judge",
            )
        )
        s.commit()

    body = letter_client.post(f"/letters/{job_id}", params={"cv_id": cv_id}).json()
    assert "FastAPI services" in body["body"]


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


def test_letter_cannot_use_another_owners_cv(letter_client, session_factory):
    # Regression: _resolve_cv was not owner-scoped, so a signed-in user could draft
    # (and read/overwrite) a cover letter grounded in another account's CV. All three
    # routes must now treat another owner's CV as not found.
    with session_factory() as s:
        owner_b = User(name="Bee", email="b@b.com", password_hash="x")
        s.add(owner_b)
        s.flush()
        cv = Cv(owner_id=owner_b.id, label="B CV", content="Private resume text of user B")
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
        cv_id, job_id = cv.id, job.id

    # A is a different signed-in account (owner_id != B).
    letter_client.post(
        "/auth/register", json={"name": "Ann", "email": "a@b.com", "password": "secret1!"}
    )
    params = {"cv_id": cv_id}
    assert letter_client.post(f"/letters/{job_id}", params=params).status_code == 404
    assert letter_client.get(f"/letters/{job_id}", params=params).status_code == 404
    assert (
        letter_client.put(f"/letters/{job_id}", params=params, json={"body": "x"}).status_code
        == 404
    )
