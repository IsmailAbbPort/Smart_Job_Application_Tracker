"""Cover-letter drafting with a fabrication guard.

Drafting a letter is easy; *not lying* is the engineering. An unguarded model will
happily invent "5 years of Kubernetes" you don't have - catastrophic in a real
application. So the pipeline is grounded end to end:

1. Draft (Claude Sonnet): write the letter grounded ONLY in the CV. When a match
   verdict from the LLM judge is available, the letter is built around its evidenced
   requirements and steers clear of its gaps. Anything the letter would need but the
   CV lacks becomes a "[NEEDS INPUT: ...]" placeholder, never a fabrication.
2. Fabrication check (structured tool-use call): extract every factual claim the
   letter makes about the candidate and verify each against the CV.
3. Revise (only if the check found unsupported claims): rewrite to remove or
   placeholder them, then re-audit. So the audit is a guardrail, not just a warning.

Being *specific* is the other half. The draft prompt asks for a fixed shape (a hook only
a reader of this posting could write, then one paragraph per requirement bridging it to a
named CV project and its outcome) and shows examples of the target register, rather than
listing cliches to avoid: a list of banned phrases puts those phrases in the context and
makes them likelier, and the measured dimensions were specificity and relevance, which no
prohibition adds.

The CV is sent as a cached prefix so the repeated draft/audit/revise calls (and
repeat letters for the same CV) don't re-pay for it. `AnthropicDrafter` runs in
production; `FakeDrafter` keeps tests offline. `get_drafter` 503s without
ANTHROPIC_API_KEY, exactly like the judge.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import Depends, HTTPException

from app.ai.tooluse import coerce_tool_input
from app.config import Settings, get_settings
from app.schemas import (
    CoverLetterResult,
    FabricationCheck,
    FabricationClaim,
    FabricationReport,
    MatchVerdict,
)

LETTER_MODEL = "claude-sonnet-4-6"
# Bump when a drafting prompt changes, so an eval run re-drafts instead of scoring letters
# cached from the old prompt (the same job FACTS_VERSION does for the judge).
LETTER_PROMPT_VERSION = 2
_CHECK_TOOL = "report_fabrication_check"

_MAX_CV_CHARS = 12000
# The details worth opening a letter on (the product, the team's problem, the scale) are
# usually in the "about the team" prose late in a posting, so the whole posting is sent.
_MAX_JOB_CHARS = 15000
# A grounded letter needs few placeholders; more than this means the fit is weak, so
# the drafter is told to keep it short and honest rather than pad with placeholders.
_MAX_PLACEHOLDERS = 3

_DRAFT_SYSTEM = (
    "You are helping a job-seeker draft a cover letter for THEIR OWN application. "
    "Use ONLY facts present in the candidate's CV (given as <cv>). Never invent "
    "experience, skills, employers, dates, titles, or metrics that are not in the CV. "
    "If a match brief is provided, build the letter around its evidenced strengths and "
    "do NOT claim anything listed under its gaps. If a stronger letter would need a "
    "specific detail the CV lacks, insert a placeholder in square brackets like "
    "'[NEEDS INPUT: quantified result for project X]' rather than fabricating it, and "
    f"use at most {_MAX_PLACEHOLDERS} placeholders - if the letter would need more, the "
    "fit is weak, so keep it short and say so honestly instead of padding. "
    "Do not claim years of experience or proficiency levels beyond what the CV states.\n\n"
    "Follow this structure, which is what keeps a letter from reading like every other "
    "one:\n"
    "1. Open on something only someone who read THIS posting could write: the product, "
    "the team's stated problem, the stack, the scale they operate at. Pair it with the "
    "one fact from the CV that speaks to it. Do not state enthusiasm or an intent to "
    "apply; the letter is the application.\n"
    "2. Two middle paragraphs. Each takes ONE requirement from the posting and bridges "
    "it to a named thing in the CV: the project, employer or tool by name, what was "
    "built, and the outcome the CV records. One requirement per paragraph, the two that "
    "matter most for this role.\n"
    "3. Close in one or two sentences on what the candidate wants to work on here.\n\n"
    "Every paragraph must name at least one particular: a project, an employer, a tool, "
    "a number, or a detail from the posting. A sentence that could be pasted unchanged "
    "into an application for a different job is filler, so cut it or make it specific.\n"
    "Write in the first person, plain and declarative, in the candidate's own voice. "
    "These show the register and the level of detail to aim for (they are about other "
    "people, so take nothing factual from them):\n"
    "- 'I built the ingest pipeline at Kalea that pulls about 4,000 listings a night and "
    "dedupes them on a content hash.'\n"
    "- 'You need pgvector for semantic search; I moved Orbit's job search onto it from a "
    "LIKE query and cut p95 from 1.2s to 180ms.'\n"
    "- 'I have not run Kafka in production. The at-least-once handling you describe is "
    "what I wrote the retry queue in Meridian's payments worker for.'\n"
    "3 to 4 short paragraphs. Output only the letter body (no header, address, or date)."
)
_CHECK_SYSTEM = (
    "You are a fabrication auditor for a cover letter the candidate is about to send. "
    "Extract EVERY factual claim the letter makes about the candidate: skills, tools, "
    "years of experience, employers, titles, education, and quantified achievements. For "
    "each claim decide whether the CV (given as <cv>) SUPPORTS it (quote the CV evidence) "
    "or it is UNSUPPORTED (not present in the CV). Be strict: a skill, number, or employer "
    "not in the CV is unsupported. Treat '[NEEDS INPUT: ...]' placeholders as placeholders, "
    f"not claims - list them separately. Always answer by calling the {_CHECK_TOOL} tool."
)
_REVISE_SYSTEM = (
    "You are revising a cover letter to remove fabrication. You are given the CV (as "
    "<cv>), the current letter, and the claims an auditor flagged as NOT supported by the "
    "CV. Rewrite the letter so every remaining sentence is grounded in the CV: delete each "
    "unsupported claim, or replace it with a '[NEEDS INPUT: ...]' placeholder if the point "
    "is worth keeping. Change nothing else - keep the supported content, the voice, and the "
    "structure. Output only the revised letter body."
)


class Drafter(Protocol):
    """Writes a CV-grounded cover letter and audits it for fabrication."""

    def write(
        self, cv_text: str, job_text: str, verdict: MatchVerdict | None = None
    ) -> CoverLetterResult: ...


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


def _grounding_brief(verdict: MatchVerdict | None) -> str:
    """Turn the judge's verdict into a brief the drafter builds the letter around:
    lead with the evidenced matches, steer clear of the gaps. Empty if no verdict."""
    if verdict is None:
        return ""
    lines = ["## MATCH BRIEF (from the AI match judge - build the letter around this)"]
    if verdict.matched_requirements:
        lines.append("Evidenced strengths to lead with (requirement -> CV evidence):")
        lines += [f"- {r.requirement} -> {r.cv_evidence}" for r in verdict.matched_requirements]
    if verdict.gaps:
        lines.append("Gaps the CV does NOT evidence (do not claim these; omit or placeholder):")
        lines += [f"- {g}" for g in verdict.gaps]
    return "\n".join(lines)


def _system_blocks(system_text: str, cv_text: str) -> list[dict]:
    """System prompt + the CV as a cached prefix. The CV is the reused, stable part, so
    caching it keeps the repeated draft/audit/revise calls (and repeat letters for the
    same CV) from re-paying for it. Caching only triggers past the model's minimum
    prefix, so a short CV may not cache - it is correct either way."""
    return [
        {"type": "text", "text": system_text},
        {
            "type": "text",
            "text": f"<cv>\n{cv_text[:_MAX_CV_CHARS]}\n</cv>",
            "cache_control": {"type": "ephemeral"},
        },
    ]


def _draft_user(job_text: str, verdict: MatchVerdict | None) -> str:
    parts = [f"<job>\n{job_text[:_MAX_JOB_CHARS]}\n</job>"]
    brief = _grounding_brief(verdict)
    if brief:
        parts.append(brief)
    parts.append("Write the cover letter body now, grounded only in the <cv>.")
    return "\n\n".join(parts)


def _check_user(letter: str) -> str:
    return (
        f"<cover_letter>\n{letter}\n</cover_letter>\n\n"
        f"Audit the letter against the <cv> and call {_CHECK_TOOL}."
    )


def _revise_user(letter: str, report: FabricationReport) -> str:
    unsupported = "\n".join(f"- {c.claim}" for c in report.claims if not c.supported)
    return (
        f"<cover_letter>\n{letter}\n</cover_letter>\n\n"
        f"Claims the auditor flagged as unsupported by the CV:\n{unsupported}\n\n"
        "Rewrite the letter body to remove or placeholder each. Output only the body."
    )


class AnthropicDrafter:
    """Claude Sonnet drafter + a structured fabrication check + a revise pass.

    `audit_model` defaults to the draft model but can be a cheaper model (e.g. Haiku)
    for the classification-shaped audit; that trade is measurable via the eval harness.
    """

    def __init__(self, api_key: str, model: str = LETTER_MODEL, audit_model: str | None = None):
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self.model = model
        self.audit_model = audit_model or model
        self._tool = {
            "name": _CHECK_TOOL,
            "description": "Report the letter's factual claims and whether the CV supports each.",
            "input_schema": FabricationCheck.model_json_schema(),
        }

    def _draft(self, cv_text: str, job_text: str, verdict: MatchVerdict | None) -> str:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=1200,
            system=_system_blocks(_DRAFT_SYSTEM, cv_text),
            messages=[{"role": "user", "content": _draft_user(job_text, verdict)}],
        )
        return "".join(
            b.text for b in message.content if getattr(b, "type", None) == "text"
        ).strip()

    def _check(self, cv_text: str, letter: str) -> FabricationCheck:
        message = self._client.messages.create(
            model=self.audit_model,
            # Headroom for the claims list; a tight cap can truncate it mid-array.
            max_tokens=4096,
            system=_system_blocks(_CHECK_SYSTEM, cv_text),
            tools=[self._tool],
            tool_choice={"type": "tool", "name": _CHECK_TOOL},
            messages=[{"role": "user", "content": _check_user(letter)}],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == _CHECK_TOOL:
                return FabricationCheck.model_validate(
                    coerce_tool_input(FabricationCheck, block.input)
                )
        raise RuntimeError("fabrication check returned no tool_use result")

    def _revise(self, cv_text: str, letter: str, report: FabricationReport) -> str:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=1200,
            system=_system_blocks(_REVISE_SYSTEM, cv_text),
            messages=[{"role": "user", "content": _revise_user(letter, report)}],
        )
        return "".join(
            b.text for b in message.content if getattr(b, "type", None) == "text"
        ).strip()

    def write(
        self, cv_text: str, job_text: str, verdict: MatchVerdict | None = None
    ) -> CoverLetterResult:
        letter = self._draft(cv_text, job_text, verdict)
        report = _report_from_check(self._check(cv_text, letter))
        # One revise pass turns the audit from a warning into a guardrail: if anything
        # is unsupported, rewrite it out and re-audit. One pass keeps cost bounded.
        if report.unsupported_count > 0:
            letter = self._revise(cv_text, letter, report)
            report = _report_from_check(self._check(cv_text, letter))
        return CoverLetterResult(body=letter, fabrication=report)


class FakeDrafter:
    """Deterministic, network-free drafter for tests.

    Produces a short grounded letter that reuses only words shared between the CV and
    the job (and leads with the match brief's first evidenced requirement when given),
    reporting those as supported claims - so the fabrication plumbing is exercised
    without a real model.
    """

    model = "fake-drafter"

    def write(
        self, cv_text: str, job_text: str, verdict: MatchVerdict | None = None
    ) -> CoverLetterResult:
        cv_words = {w.strip(".,").lower() for w in cv_text.split() if len(w) > 3}
        shared = [w for w in dict.fromkeys(job_text.split()) if w.strip(".,").lower() in cv_words]
        highlights = shared[:4] or ["my background"]
        lead = ""
        if verdict is not None and verdict.matched_requirements:
            req = verdict.matched_requirements[0].requirement
            lead = f"My experience with {req} fits this role. "
        body = (
            "Dear Hiring Team,\n\n"
            f"{lead}I am excited to apply. My experience with {', '.join(highlights)} "
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
    return AnthropicDrafter(
        settings.anthropic_api_key,
        model=settings.letter_model,
        audit_model=settings.letter_audit_model,
    )
