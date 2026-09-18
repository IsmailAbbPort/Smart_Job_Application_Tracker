"""LLM-judge tests: the FakeJudge, the get_judge gate, and the /match/{id} routes."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.ai.decide import CandidateRules, decide
from app.ai.judge import AnthropicJudge, FakeJudge, get_judge
from app.config import Settings, get_settings
from app.main import app as fastapi_app
from app.models import Cv, Job, Match
from app.schemas import JudgeFacts


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


def _objects(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from _objects(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _objects(value)


def test_anthropic_judge_tool_is_strict():
    # Regression: claude-sonnet-4-6 returned dimension_scores as malformed JSON text
    # ('{"skills": 2, "seniority": 10, "domain", 2, ...}'), which crashed the judge.
    # Strict tool use makes the API guarantee the input matches the schema.
    tool = AnthropicJudge(api_key="test")._tool
    assert tool["strict"] is True
    objects = list(_objects(tool["input_schema"]))
    assert objects and all(o.get("additionalProperties") is False for o in objects)
    assert "'maximum':" not in str(tool["input_schema"])  # unsupported in strict mode


def test_fake_judge_returns_valid_facts():
    facts = FakeJudge().judge("Python FastAPI engineer", "Python FastAPI role")
    assert isinstance(facts, JudgeFacts)
    assert any(r.status == "met" for r in facts.requirements)  # some overlap surfaced


def _score(cv: str, job: str) -> int:
    return decide(FakeJudge().judge(cv, job), CandidateRules()).overall_score


def test_fake_judge_monotonic_in_overlap():
    high = _score("python fastapi postgres docker", "python fastapi postgres docker")
    low = _score("python fastapi postgres docker", "rust embedded firmware")
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
    assert body["requirements"] and body["dealbreakers"] == []

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


def _legacy_row(session_factory, cv_id, job_id, facts=None):
    with session_factory() as s:
        s.add(
            Match(
                cv_id=cv_id,
                job_id=job_id,
                overall_score=40,
                verdict="medium",
                one_line_verdict="old",
                matched_requirements=[],
                gaps=[],
                facts=facts,
                model="old-judge",
            )
        )
        s.commit()


def test_pre_facts_row_counts_as_not_judged(judge_client, session_factory):
    cv_id, job_id = _seed(session_factory)
    _legacy_row(session_factory, cv_id, job_id)
    assert judge_client.get(f"/match/{job_id}", params={"cv_id": cv_id}).status_code == 404
    body = judge_client.post(f"/match/{job_id}", params={"cv_id": cv_id}).json()
    assert body["model"] == "fake-judge"  # re-judged, not served from the stale row


def test_verdict_regrades_when_preferences_change(judge_client, session_factory):
    # The tier is computed on read from stored facts, so switching to remote-only turns
    # an on-site role into a dealbreaker with no new judge call.
    cv_id, job_id = _seed(session_factory)
    facts = FakeJudge().judge("python fastapi", "python fastapi").model_dump(mode="json")
    facts["constraints"]["work_mode"] = "onsite"
    _legacy_row(session_factory, cv_id, job_id, facts=facts)

    before = judge_client.get(f"/match/{job_id}", params={"cv_id": cv_id}).json()
    assert before["verdict"] == "strong" and before["dealbreakers"] == []
    assert judge_client.put("/preferences", json={"remote_only": True}).status_code == 200
    after = judge_client.get(f"/match/{job_id}", params={"cv_id": cv_id}).json()
    assert after["verdict"] == "weak" and "remote only" in after["dealbreakers"][0]


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
    # Force keyless settings so the gate is exercised regardless of the ambient .env
    # (which now carries a real key). Real get_judge -> 503 without ANTHROPIC_API_KEY.
    fastapi_app.dependency_overrides[get_settings] = lambda: Settings(anthropic_api_key=None)
    try:
        assert client.post("/match/rerank", json={"job_ids": [1]}).status_code == 503
    finally:
        fastapi_app.dependency_overrides.pop(get_settings, None)
