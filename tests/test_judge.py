"""LLM-judge tests: the FakeJudge, the get_judge gate, and the /match/{id} routes."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.ai.judge import FakeJudge, get_judge
from app.config import Settings
from app.models import Cv, Job
from app.schemas import MatchVerdict


def _seed(
    session_factory, *, cv_content="Python FastAPI Postgres Docker engineer"
) -> tuple[int, int]:
    with session_factory() as s:
        cv = Cv(label="CV", content=cv_content, embedding=None)
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


# --- FakeJudge / gate (unit) ---


def test_fake_judge_returns_valid_verdict():
    verdict = FakeJudge().judge("Python FastAPI engineer", "Python FastAPI role")
    assert isinstance(verdict, MatchVerdict)
    assert 0 <= verdict.overall_score <= 100
    assert verdict.matched_requirements  # some overlap surfaced


def test_fake_judge_monotonic_in_overlap():
    high = (
        FakeJudge()
        .judge("python fastapi postgres docker", "python fastapi postgres docker")
        .overall_score
    )
    low = (
        FakeJudge().judge("python fastapi postgres docker", "rust embedded firmware").overall_score
    )
    assert high > low


def test_get_judge_requires_key():
    with pytest.raises(HTTPException) as exc:
        get_judge(Settings(anthropic_api_key=None))
    assert exc.value.status_code == 503


# --- routes ---


def test_judge_persists_and_caches(judge_client, session_factory):
    cv_id, job_id = _seed(session_factory)
    resp = judge_client.post(f"/match/{job_id}", params={"cv_id": cv_id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id and body["cv_id"] == cv_id
    assert body["model"] == "fake-judge"
    assert 0 <= body["overall_score"] <= 100
    assert set(body["dimension_scores"]) == {"skills", "seniority", "domain", "location_remote"}

    # GET returns the stored verdict.
    got = judge_client.get(f"/match/{job_id}", params={"cv_id": cv_id})
    assert got.status_code == 200
    assert got.json()["overall_score"] == body["overall_score"]


def test_judge_defaults_to_latest_cv(judge_client, session_factory):
    _cv_id, job_id = _seed(session_factory)
    resp = judge_client.post(f"/match/{job_id}")  # no cv_id -> latest
    assert resp.status_code == 200


def test_get_match_404_before_judged(judge_client, session_factory):
    cv_id, job_id = _seed(session_factory)
    assert judge_client.get(f"/match/{job_id}", params={"cv_id": cv_id}).status_code == 404


def test_judge_missing_job_404(judge_client, session_factory):
    cv_id, _job_id = _seed(session_factory)
    assert judge_client.post("/match/999999", params={"cv_id": cv_id}).status_code == 404


def test_judge_no_cv_404(judge_client):
    assert judge_client.post("/match/1").status_code == 404


# --- rerank (batch-judge + re-order) ---


def test_rerank_orders_by_judge_score(judge_client, session_factory):
    with session_factory() as s:
        s.add(Cv(label="cv", content="python fastapi postgres docker backend"))
        s.add_all(
            [
                Job(
                    source="t",
                    source_id="low",
                    title="Role",
                    company="Acme",
                    url="u1",
                    description="sales marketing manager",
                    is_remote=True,
                    is_european=True,
                ),
                Job(
                    source="t",
                    source_id="high",
                    title="Role",
                    company="Acme",
                    url="u2",
                    description="python fastapi postgres docker backend",
                    is_remote=True,
                    is_european=True,
                ),
            ]
        )
        s.commit()
        ids = {j.source_id: j.id for j in s.query(Job).all()}

    # Pass low-fit first; the judge score must re-order it below the high-fit job.
    resp = judge_client.post("/match/rerank", json={"job_ids": [ids["low"], ids["high"]]})
    assert resp.status_code == 200
    body = resp.json()
    assert [b["job_id"] for b in body] == [ids["high"], ids["low"]]
    assert body[0]["overall_score"] >= body[1]["overall_score"]


def test_rerank_requires_key(client):
    # No judge override -> real get_judge -> 503 without ANTHROPIC_API_KEY.
    assert client.post("/match/rerank", json={"job_ids": [1]}).status_code == 503
