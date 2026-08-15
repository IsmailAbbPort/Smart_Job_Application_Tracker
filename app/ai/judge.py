"""The rerank stage: an LLM judge that scores ONE (CV, job) pair.

Where the embedding retrieve stage is cheap and fuzzy, the judge is expensive
and precise, so it only ever runs on the shortlist. It returns a structured,
evidence-grounded verdict (score + dimension scores + matched requirements with
their CV receipts + gaps), never prose.

`AnthropicJudge` (Claude Haiku 4.5) runs in production; `FakeJudge` keeps tests
offline and deterministic. `get_judge` is the FastAPI seam: it 503s when no
ANTHROPIC_API_KEY is set, exactly like `get_embedder` does for OpenAI. Output is
forced through tool-use so the model must return schema-valid JSON.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import Depends, HTTPException

from app.ai.tooluse import coerce_tool_input
from app.config import Settings, get_settings
from app.schemas import DimensionScores, MatchedRequirement, MatchTier, MatchVerdict

JUDGE_MODEL = "claude-haiku-4-5-20251001"
_VERDICT_TOOL = "submit_match_verdict"

_MAX_CV_CHARS = 12000
_MAX_JOB_CHARS = 6000

_SYSTEM_PROMPT = (
    "You are a rigorous technical recruiter assessing how well ONE candidate CV "
    "fits ONE job posting. Score strictly on evidence present in the CV. Never "
    "credit experience the CV does not state. For every matched requirement, quote "
    "the exact CV line that supports it. List as gaps the requirements the CV does "
    "not evidence. "
    "Distinguish hard eligibility gates from ordinary skill gaps. A gate is a "
    "dealbreaker the candidate cannot satisfy by being talented: an unmet spoken- "
    "language requirement (e.g. 'fluent German', 'C1 French'), a work-authorization "
    "or visa-sponsorship constraint, a mandatory relocation or on-site presence, a "
    "hard minimum years/clearance/degree. When a gate is unmet, list it FIRST in "
    "gaps, say so in the one-line verdict, and cap the overall score low no matter "
    "how strong the skills fit. If such a requirement is only 'a plus', weigh it "
    "lightly. "
    "Be calibrated: reserve 'strong' and high scores for genuinely strong fits, "
    f"not merely plausible ones. Always answer by calling the {_VERDICT_TOOL} tool."
)


class Judge(Protocol):
    """Scores a CV against a job and returns a structured verdict."""

    def judge(self, cv_text: str, job_text: str) -> MatchVerdict: ...


def build_job_text(job) -> str:
    """The job text the judge reasons over (fuller than the embedding document)."""
    parts = [
        job.title or "",
        f"at {job.company}" if job.company else "",
        job.location or "",
        "Remote" if job.is_remote else "",
        job.description or "",
    ]
    return "\n".join(p for p in parts if p)


def _build_prompt(cv_text: str, job_text: str) -> str:
    return (
        "Assess how well this candidate fits this job.\n\n"
        "## CANDIDATE CV\n"
        f"{cv_text[:_MAX_CV_CHARS]}\n\n"
        "## JOB POSTING\n"
        f"{job_text[:_MAX_JOB_CHARS]}\n\n"
        f"Call {_VERDICT_TOOL} with your verdict. Populate matched_requirements and "
        "gaps as real JSON arrays (not strings), and always list the unmet or "
        "unevidenced requirements in gaps - leave it empty only if the CV meets every one."
    )


class AnthropicJudge:
    """Claude Haiku 4.5 judge with tool-use-enforced structured output."""

    def __init__(self, api_key: str, model: str = JUDGE_MODEL):
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self.model = model
        self._tool = {
            "name": _VERDICT_TOOL,
            "description": "Return the structured, evidence-grounded match verdict.",
            "input_schema": MatchVerdict.model_json_schema(),
        }

    def judge(self, cv_text: str, job_text: str) -> MatchVerdict:
        message = self._client.messages.create(
            model=self.model,
            # Generous ceiling: Haiku sometimes serializes the list fields as escaped
            # JSON strings, which roughly doubles the token count. A tight limit would
            # truncate that into unparseable JSON (see app/ai/tooluse.py), so leave
            # comfortable headroom and let the coercion repair the shape.
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            tools=[self._tool],
            tool_choice={"type": "tool", "name": _VERDICT_TOOL},
            messages=[{"role": "user", "content": _build_prompt(cv_text, job_text)}],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == _VERDICT_TOOL:
                return MatchVerdict.model_validate(coerce_tool_input(MatchVerdict, block.input))
        raise RuntimeError("judge returned no tool_use verdict")


class FakeJudge:
    """Deterministic, network-free judge for tests.

    Scores by word overlap between CV and job. Not semantically meaningful, but
    monotonic (more shared words -> higher score) so tests can assert ordering,
    and always schema-valid so it exercises the same storage/response plumbing.
    """

    model = "fake-judge"

    def judge(self, cv_text: str, job_text: str) -> MatchVerdict:
        cv_words = {w for w in cv_text.lower().split() if len(w) > 2}
        job_words = {w for w in job_text.lower().split() if len(w) > 2}
        shared = sorted(cv_words & job_words)
        missing = sorted(job_words - cv_words)
        score = min(100, len(shared) * 8)
        tier = (
            MatchTier.strong if score >= 70 else MatchTier.medium if score >= 40 else MatchTier.weak
        )
        return MatchVerdict(
            overall_score=score,
            verdict=tier,
            one_line_verdict=f"{len(shared)} overlapping terms with the posting.",
            dimension_scores=DimensionScores(
                skills=score, seniority=score, domain=score, location_remote=score
            ),
            matched_requirements=[
                MatchedRequirement(requirement=w, cv_evidence=f"CV mentions {w}")
                for w in shared[:5]
            ],
            gaps=missing[:5],
        )


def get_judge(settings: Settings = Depends(get_settings)) -> Judge:
    """FastAPI dependency. Real Anthropic judge; 503 if the key is missing."""
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured; the match judge is unavailable.",
        )
    return AnthropicJudge(settings.anthropic_api_key, model=settings.judge_model)
