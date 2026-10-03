"""The rerank stage: an LLM judge that reads ONE (CV, job) pair and extracts facts.

Where the embedding retrieve stage is cheap and fuzzy, the judge is expensive
and precise, so it only ever runs on the shortlist. It returns structured facts,
never a grade: each posting requirement checked against the CV (with the CV line as
evidence) plus the posting's eligibility constraints. app/ai/decide.py turns those
facts into a score and tier under the user's rules, because a model asked for a tier
directly was severe and never rated a good fit "strong" (see evals/README.md).

`AnthropicJudge` (Claude Haiku 4.5) runs in production; `FakeJudge` keeps tests
offline and deterministic. `get_judge` is the FastAPI seam: it 503s when no
ANTHROPIC_API_KEY is set, exactly like `get_embedder` does for OpenAI. Output is
forced through strict tool use so the model must return schema-valid JSON.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import Depends, HTTPException

from app.ai.tooluse import coerce_tool_input
from app.config import Settings, get_settings
from app.schemas import (
    Importance,
    JudgeFacts,
    PostingConstraints,
    RequirementCheck,
    RequirementStatus,
    Seniority,
    Tristate,
    WorkMode,
)

JUDGE_MODEL = "claude-haiku-4-5-20251001"
# Bump when the JudgeFacts schema or the extraction prompt changes, so cached facts from an
# older extractor are not mixed into an eval run.
FACTS_VERSION = 4
_VERDICT_TOOL = "submit_match_facts"

_MAX_CV_CHARS = 12000
# Long enough for the whole posting (corpus p99 is about 12k chars) plus the title and
# location lines build_job_text prepends. At 6000 the cut landed mid-posting and the model
# never saw the eligibility paragraph, which is exactly where the work-rights facts live.
_MAX_JOB_CHARS = 15000

_SYSTEM_PROMPT = (
    "You are an experienced technical recruiter reading ONE candidate CV against ONE job "
    "posting. Your job is to report facts accurately, not to grade the candidate: a "
    "separate step decides the fit from what you report.\n\n"
    "Requirements: list every skill, tool, domain and responsibility requirement the "
    "posting states. For each, first copy the CV line that supports it (empty if none), "
    "then classify it:\n"
    "- importance: must_have unless the posting marks it optional ('a plus', 'bonus', "
    "'ideally', 'nice to have', 'preferred', 'familiarity with').\n"
    "- status: met when the CV shows it; partial when the CV shows adjacent or "
    "transferable evidence, the way a recruiter would credit it (Express for NestJS, "
    "PostgreSQL for MySQL, AWS for GCP, the same skill at smaller scale, a personal or "
    "thesis project); absent only when nothing related appears.\n"
    "- core: true for the 3 to 6 requirements the role is really about, the ones a "
    "recruiter would screen on. A long posting that lists a team's product areas, tools "
    "or responsibilities still has only a handful of core requirements; mark the rest "
    "false.\n"
    "Do not list location, work mode, spoken languages, citizenship, years of experience "
    "or seniority as requirements; report them as constraints.\n\n"
    "Constraints: report what the posting states, and what the CV states, without judging "
    "whether they match. Use unknown or an empty list whenever the text does not say. "
    "work_countries: the countries the role can be done from, e.g. ['US', 'CA'] for "
    "'Remote, United States; Remote, Canada', ['FR'] for an on-site Paris role, ['EU'] for "
    "'remote within the EU'. candidate_work_rights: where the CV says the candidate may "
    "legally work, e.g. ['EU'] for an EU work authorization. work_mode: remote only when "
    "the posting says so; an office location with no mention of remote work is unknown. "
    "seniority: the level the text asks for ('We are seeking a Senior ...' is senior even "
    "when the title is not). Only list a required language when the posting demands it "
    "(a level, 'fluent', 'native', 'required'); a CV written in English shows English.\n\n"
    f"Always answer by calling the {_VERDICT_TOOL} tool."
)


class Judge(Protocol):
    """Reads a CV against a job and returns structured facts."""

    def judge(self, cv_text: str, job_text: str) -> JudgeFacts: ...


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
        "Report the facts for this candidate and job.\n\n"
        "## CANDIDATE CV\n"
        f"{cv_text[:_MAX_CV_CHARS]}\n\n"
        "## JOB POSTING\n"
        f"{job_text[:_MAX_JOB_CHARS]}\n\n"
        f"Call {_VERDICT_TOOL} with every requirement and the constraints."
    )


class AnthropicJudge:
    """Claude Haiku 4.5 fact extractor with strict tool-use structured output."""

    def __init__(self, api_key: str, model: str = JUDGE_MODEL):
        from anthropic import Anthropic, transform_schema

        self._client = Anthropic(api_key=api_key)
        self.model = model
        # strict: the API guarantees the input matches the schema. Without it Sonnet
        # sometimes returns a nested object as malformed JSON text that coercion can't
        # repair. transform_schema makes the schema strict-compatible (no extra keys;
        # the unsupported 0-100 bounds move into descriptions, pydantic still checks them).
        self._tool = {
            "name": _VERDICT_TOOL,
            "description": "Return the requirements checked against the CV, and the constraints.",
            "strict": True,
            "input_schema": transform_schema(JudgeFacts),
        }

    def judge(self, cv_text: str, job_text: str) -> JudgeFacts:
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
                return JudgeFacts.model_validate(coerce_tool_input(JudgeFacts, block.input))
        raise RuntimeError("judge returned no tool_use facts")


class FakeJudge:
    """Deterministic, network-free judge for tests.

    Each posting word (longer than 2 chars, first 10) becomes a must-have requirement,
    met when the CV contains it; the first four are core. Not semantically meaningful,
    but monotonic (more shared words -> more met requirements) so tests can assert
    ordering, and always schema-valid so it exercises the same storage/response plumbing.
    """

    model = "fake-judge"

    def judge(self, cv_text: str, job_text: str) -> JudgeFacts:
        cv_words = {w for w in cv_text.lower().split() if len(w) > 2}
        job_words = list(dict.fromkeys(w for w in job_text.lower().split() if len(w) > 2))
        requirements = [
            RequirementCheck(
                requirement=w,
                importance=Importance.must_have,
                cv_evidence=f"CV mentions {w}" if w in cv_words else "",
                status=RequirementStatus.met if w in cv_words else RequirementStatus.absent,
                core=i < 4,
            )
            for i, w in enumerate(job_words[:10])
        ]
        shared = sum(1 for r in requirements if r.status == RequirementStatus.met)
        return JudgeFacts(
            requirements=requirements,
            constraints=PostingConstraints(
                work_mode=WorkMode.unknown,
                location="",
                work_countries=[],
                candidate_work_rights=[],
                citizenship_or_clearance="",
                citizenship_or_clearance_ok=Tristate.unknown,
                required_languages=[],
                candidate_languages=[],
                min_years_experience=None,
                candidate_years_experience=None,
                seniority=Seniority.unknown,
            ),
            summary=f"{shared} overlapping terms with the posting.",
        )


def get_judge(settings: Settings = Depends(get_settings)) -> Judge:
    """FastAPI dependency. Real Anthropic judge; 503 if the key is missing."""
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured; the match judge is unavailable.",
        )
    return AnthropicJudge(settings.anthropic_api_key, model=settings.judge_model)
