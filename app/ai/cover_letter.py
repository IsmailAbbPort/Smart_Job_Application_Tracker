"""Cover-letter drafting with a fabrication guard.

Drafting a letter is easy; *not lying* is the engineering. An unguarded model will
happily invent "5 years of Kubernetes" you don't have - catastrophic in a real
application. So two stages:

1. Draft (Claude Sonnet): write the letter grounded ONLY in the CV. Anything the
   letter would need but the CV lacks becomes a "[NEEDS INPUT: ...]" placeholder,
   never a fabrication.
2. Fabrication check (second call, structured): extract every factual claim the
   letter makes about the candidate and verify each against the CV, flagging
   anything unsupported. The UI surfaces "Fabrication check: N unsupported claims".

Human-in-the-loop: the app drafts + audits; the user edits/approves before sending.
`AnthropicDrafter` runs in production; `FakeDrafter` keeps tests offline. `get_drafter`
503s without ANTHROPIC_API_KEY, exactly like the judge.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import Depends, HTTPException

from app.ai.tooluse import coerce_tool_input
from app.config import Settings, get_settings
from app.schemas import CoverLetterResult, FabricationCheck, FabricationClaim, FabricationReport

LETTER_MODEL = "claude-sonnet-4-6"
_CHECK_TOOL = "report_fabrication_check"

_MAX_CV_CHARS = 12000
_MAX_JOB_CHARS = 6000

_DRAFT_SYSTEM = (
    "You are helping a job-seeker draft a cover letter for THEIR OWN application. "
    "Use ONLY facts present in the candidate's CV. Never invent experience, skills, "
    "employers, dates, titles, or metrics that are not in the CV. If a stronger letter "
    "would need a specific detail the CV lacks, insert a placeholder in square brackets "
    "like '[NEEDS INPUT: quantified result for project X]' rather than fabricating it. "
    "Do not claim years of experience or proficiency levels beyond what the CV states. "
    "Write in the first person, specific and genuine, in the candidate's own voice - not "
    "generic filler. 3-4 short paragraphs. Output only the letter body (no header, "
    "address, or date)."
)
_CHECK_SYSTEM = (
    "You are a fabrication auditor for a cover letter the candidate is about to send. "
    "Extract EVERY factual claim the letter makes about the candidate: skills, tools, "
    "years of experience, employers, titles, education, and quantified achievements. For "
    "each claim decide whether the CV SUPPORTS it (quote the CV evidence) or it is "
    "UNSUPPORTED (not present in the CV). Be strict: a skill, number, or employer not in "
    "the CV is unsupported. Treat '[NEEDS INPUT: ...]' placeholders as placeholders, not "
    f"claims - list them separately. Always answer by calling the {_CHECK_TOOL} tool."
)


class Drafter(Protocol):
    """Writes a CV-grounded cover letter and audits it for fabrication."""

    def write(self, cv_text: str, job_text: str) -> CoverLetterResult: ...


def _report_from_check(check: FabricationCheck) -> FabricationReport:
    """Add the derived counts the UI shows to the model's raw claim list."""
    total = len(check.claims)
    unsupported = [c for c in check.claims if not c.supported]
    grounded = (total - len(unsupported)) / total if total else 1.0
    return FabricationReport(
        claims=check.claims,
        placeholders=check.placeholders,
        unsupported_count=len(unsupported),
        grounded_ratio=round(grounded, 3),
    )


def _draft_prompt(cv_text: str, job_text: str) -> str:
    return (
        "## CANDIDATE CV\n"
        f"{cv_text[:_MAX_CV_CHARS]}\n\n"
        "## JOB POSTING\n"
        f"{job_text[:_MAX_JOB_CHARS]}\n\n"
        "Write the cover letter body now."
    )


def _check_prompt(cv_text: str, letter: str) -> str:
    return (
        "## CANDIDATE CV\n"
        f"{cv_text[:_MAX_CV_CHARS]}\n\n"
        "## COVER LETTER TO AUDIT\n"
        f"{letter}\n\n"
        f"Audit the letter against the CV and call {_CHECK_TOOL}."
    )


class AnthropicDrafter:
    """Claude Sonnet drafter + a structured fabrication-check pass."""

    def __init__(self, api_key: str, model: str = LETTER_MODEL):
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self.model = model
        self._tool = {
            "name": _CHECK_TOOL,
            "description": "Report the letter's factual claims and whether the CV supports each.",
            "input_schema": FabricationCheck.model_json_schema(),
        }

    def _draft(self, cv_text: str, job_text: str) -> str:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=1200,
            system=_DRAFT_SYSTEM,
            messages=[{"role": "user", "content": _draft_prompt(cv_text, job_text)}],
        )
        return "".join(
            b.text for b in message.content if getattr(b, "type", None) == "text"
        ).strip()

    def _check(self, cv_text: str, letter: str) -> FabricationCheck:
        message = self._client.messages.create(
            model=self.model,
            # Headroom for the claims list; a tight cap can truncate it mid-array.
            max_tokens=4096,
            system=_CHECK_SYSTEM,
            tools=[self._tool],
            tool_choice={"type": "tool", "name": _CHECK_TOOL},
            messages=[{"role": "user", "content": _check_prompt(cv_text, letter)}],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == _CHECK_TOOL:
                return FabricationCheck.model_validate(
                    coerce_tool_input(FabricationCheck, block.input)
                )
        raise RuntimeError("fabrication check returned no tool_use result")

    def write(self, cv_text: str, job_text: str) -> CoverLetterResult:
        letter = self._draft(cv_text, job_text)
        report = _report_from_check(self._check(cv_text, letter))
        return CoverLetterResult(body=letter, fabrication=report)


class FakeDrafter:
    """Deterministic, network-free drafter for tests.

    Produces a short grounded letter that reuses only words shared between the CV
    and the job, and reports those as supported claims - so the fabrication plumbing
    is exercised without a real model.
    """

    model = "fake-drafter"

    def write(self, cv_text: str, job_text: str) -> CoverLetterResult:
        cv_words = {w.strip(".,").lower() for w in cv_text.split() if len(w) > 3}
        shared = [w for w in dict.fromkeys(job_text.split()) if w.strip(".,").lower() in cv_words]
        highlights = shared[:4] or ["my background"]
        body = (
            "Dear Hiring Team,\n\n"
            f"I am excited to apply. My experience with {', '.join(highlights)} "
            "aligns with what this role needs.\n\n"
            "[NEEDS INPUT: a specific achievement with a metric]\n\n"
            "Sincerely,\nThe Candidate"
        )
        claims = [
            FabricationClaim(
                claim=f"Experience with {h}", supported=True, evidence=f"CV mentions {h}"
            )
            for h in highlights
        ]
        report = _report_from_check(
            FabricationCheck(claims=claims, placeholders=["a specific achievement with a metric"])
        )
        return CoverLetterResult(body=body, fabrication=report)


def get_drafter(settings: Settings = Depends(get_settings)) -> Drafter:
    """FastAPI dependency. Real Anthropic drafter; 503 if the key is missing."""
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured; the cover-letter drafter is unavailable.",
        )
    return AnthropicDrafter(settings.anthropic_api_key, model=settings.letter_model)
