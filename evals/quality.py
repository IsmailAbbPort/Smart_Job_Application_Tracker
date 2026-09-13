"""LLM-as-judge for cover-letter QUALITY (a G-Eval style rubric).

The fabrication check already measures faithfulness (is the letter true?); this
measures whether it is any *good* - specific, relevant to the role, authentic in
voice, and free of cover-letter cliches. It is an eval-only concern, so it lives in
`evals/` and never runs in the app.

`AnthropicQualityJudge` scores with a rubric via forced tool-use (structured, so the
scores are always parseable); `FakeQualityJudge` is deterministic for offline/CI.
Both implement the `QualityJudge` protocol so the runner can inject either.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

_QUALITY_TOOL = "report_letter_quality"
_MAX_JOB_CHARS = 4000
_MAX_LETTER_CHARS = 6000

# Cliches a good, specific letter avoids; the FakeQualityJudge penalizes these and the
# rubric names them so the two graders agree on what "generic" means.
_CLICHES = (
    "i am writing to express",
    "i am confident that",
    "keen interest",
    "perfect fit",
    "team player",
    "hit the ground running",
    "think outside the box",
    "proven track record",
    "to whom it may concern",
)

_SYSTEM_PROMPT = (
    "You are grading the QUALITY of a cover letter for a specific job (given as <job>). "
    "You are not checking whether its claims are true - only whether it is a strong, "
    "compelling letter. Score four dimensions 0-100, then an overall 0-100:\n"
    "- specificity: concrete, evidence-backed detail vs generic filler and unfilled "
    "[NEEDS INPUT] placeholders.\n"
    "- relevance: how directly it addresses THIS role and company's stated needs.\n"
    "- authenticity: a genuine first-person voice, not generic AI phrasing.\n"
    "- no_cliche: freedom from cover-letter cliches (higher = fewer cliches).\n"
    "Be calibrated: reserve high scores for genuinely strong letters. Always answer by "
    f"calling the {_QUALITY_TOOL} tool with a one-line rationale."
)


class LetterQuality(BaseModel):
    """Rubric scores for one cover letter. Doubles as the tool-use input schema."""

    specificity: int = Field(ge=0, le=100)
    relevance: int = Field(ge=0, le=100)
    authenticity: int = Field(ge=0, le=100)
    no_cliche: int = Field(ge=0, le=100, description="Higher means fewer cliches")
    overall: int = Field(ge=0, le=100, description="Holistic letter quality")
    rationale: str = Field(default="", description="One-line justification")


class QualityJudge(Protocol):
    """Scores a cover letter against a job on the quality rubric."""

    def score(self, job_text: str, letter: str) -> LetterQuality: ...


def _prompt(job_text: str, letter: str) -> str:
    return (
        f"<job>\n{job_text[:_MAX_JOB_CHARS]}\n</job>\n\n"
        f"<cover_letter>\n{letter[:_MAX_LETTER_CHARS]}\n</cover_letter>\n\n"
        f"Grade the letter's quality and call {_QUALITY_TOOL}."
    )


class AnthropicQualityJudge:
    """Claude quality grader with tool-use-enforced structured output."""

    def __init__(self, api_key: str, model: str):
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self.model = model
        self._tool = {
            "name": _QUALITY_TOOL,
            "description": "Return the cover letter's rubric quality scores.",
            "input_schema": LetterQuality.model_json_schema(),
        }

    def score(self, job_text: str, letter: str) -> LetterQuality:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            tools=[self._tool],
            tool_choice={"type": "tool", "name": _QUALITY_TOOL},
            messages=[{"role": "user", "content": _prompt(job_text, letter)}],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == _QUALITY_TOOL:
                return LetterQuality.model_validate(block.input)
        raise RuntimeError("quality judge returned no tool_use result")


class FakeQualityJudge:
    """Deterministic, network-free quality grader for tests.

    Heuristic but monotonic: unfilled placeholders and cliches lower the score, shared
    vocabulary with the job raises relevance. Not semantically meaningful, but enough to
    exercise the quality plumbing without a real model.
    """

    model = "fake-quality"

    def score(self, job_text: str, letter: str) -> LetterQuality:
        low = letter.lower()
        cliches = sum(1 for c in _CLICHES if c in low)
        placeholders = low.count("[needs input")
        letter_words = {w.strip(".,").lower() for w in letter.split() if len(w) > 3}
        job_words = {w.strip(".,").lower() for w in job_text.split() if len(w) > 3}
        shared = len(letter_words & job_words)

        specificity = max(0, min(100, len(letter_words) * 2 - placeholders * 20))
        relevance = min(100, shared * 10)
        no_cliche = max(0, 100 - cliches * 25)
        authenticity = max(0, 85 - cliches * 15)
        overall = round((specificity + relevance + no_cliche + authenticity) / 4)
        return LetterQuality(
            specificity=specificity,
            relevance=relevance,
            authenticity=authenticity,
            no_cliche=no_cliche,
            overall=overall,
            rationale=f"{cliches} cliche(s), {placeholders} placeholder(s), {shared} shared terms.",
        )
