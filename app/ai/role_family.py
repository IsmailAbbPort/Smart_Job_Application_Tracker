"""Role-family classification from the job title.

The retrieve stage's cosine sits in a narrow band (every job at a trendy AI lab
looks ~alike), so it can't tell a Backend Engineer from an IT Support role at the
same company. The blunt fix is a title keyword blocklist, but that is whack-a-mole.

Two classifiers, one stored signal (`Job.role_family`) that a positive preference
filter (`include_role_families`) gates on, upstream of the LLM judge:

- `AnthropicRoleClassifier` (production): Claude Haiku labels titles in batches.
  Measured against a 718-title labelled sample it was far more precise than the
  embedding centroids (which kept ~half non-engineering jobs under an engineering
  filter, and still ~12% after tuning), and it reads German/French titles and
  look-alikes ("Enterprise Solutions Engineer" is sales). ~$1 to label the corpus.
- `RoleClassifier` (fallback when there is no ANTHROPIC_API_KEY): embed the title
  and assign the nearest family centroid. Deterministic, no LLM, coarser.
"""

from __future__ import annotations

import logging
import math
from typing import Protocol

from fastapi import Depends

from app.config import Settings, get_settings

log = logging.getLogger("app.ai.role_family")

ROLE_MODEL = "claude-haiku-4-5-20251001"
_LABEL_TOOL = "submit_role_families"
_SUGGEST_TOOL = "submit_cv_role_families"
_MAX_CV_CHARS = 12000
_MAX_SUGGESTIONS = 3

# Every family a job can be assigned, with the definition the LLM classifies by.
# Order is stable (the UI lists families in this order). `other` exists so a title
# that fits nothing still gets a family and is filtered out, not null-kept.
FAMILY_DESCRIPTIONS: dict[str, str] = {
    "engineering": "builds software: software/backend/frontend/fullstack/mobile/web "
    "developers, DevOps, SRE, platform/infra/cloud, QA automation, systems "
    "administration, embedded/firmware software, forward-deployed software engineers, "
    "managers/directors of software engineering",
    "data_ml": "data engineering, data science, ML/AI engineering and research, "
    "analytics engineering, BI/data/product analysts",
    "security": "cybersecurity, security engineering, GRC",
    "product": "product management / product ownership",
    "design": "UX/UI/product/graphic design",
    "sales": "sales, account executives/managers, business development, partnerships, "
    "presales incl. solutions/sales/value engineers and solution consultants",
    "support": "customer support, customer success, IT helpdesk",
    "marketing": "marketing, growth, SEO, content marketing, copywriting, PR, "
    "communications (incl. internal comms), community",
    "people": "HR, recruiting, talent, learning & development",
    "finance_ops": "finance, accounting, tax, controlling, procurement, business/strategy "
    "operations, office/workplace/admin, executive assistants",
    "media_content": "media production, video, audio, voice, localization, journalism",
    "legal": "legal counsel, paralegals, compliance officers, data protection",
    "industrial_eng": "non-software engineering and technicians: mechanical, electrical, "
    "civil, construction, HVAC/building tech, manufacturing, quality, hardware/chip "
    "design, energy",
    "hospitality_retail": "hospitality, food, retail stores, warehouse, logistics, "
    "drivers, production-floor and shift roles, trades",
    "consulting_research": "management/strategy consulting, market research, "
    "expert-network gigs, academic/non-ML research",
    "other": "healthcare, education/teaching, anything else",
}

# Canonical families -> representative titles that define each centroid. Kept coarse
# on purpose: this separates domains (engineering vs sales vs support), not fit
# *within* a domain - that finer call is the CV-cosine + the LLM judge's job. A few
# prototypes per family average into a stable centroid.
ROLE_PROTOTYPES: dict[str, list[str]] = {
    "engineering": [
        "Software Engineer",
        "Software Developer",
        "Backend Engineer",
        "Frontend Engineer",
        "Full Stack Developer",
        "Web Developer",
        "iOS Developer",
        "Mobile Engineer (iOS / Android)",
        "DevOps Engineer",
        "Site Reliability Engineer",
        "Platform / Infrastructure Engineer",
        "QA Automation Engineer",
    ],
    "data_ml": [
        "Data Engineer",
        "Machine Learning Engineer",
        "Data Scientist",
        "Research Engineer",
        "MLOps Engineer",
        "Analytics Engineer",
    ],
    "security": [
        "Security Engineer",
        "Compliance Engineer",
        "GRC Analyst",
        "Penetration Tester",
        "Application Security Engineer",
    ],
    "product": [
        "Product Manager",
        "Technical Product Manager",
        "Product Owner",
    ],
    "design": [
        "Product Designer",
        "UX Designer",
        "UI Designer",
        "Design Lead",
    ],
    "sales": [
        "Account Executive",
        "Sales Development Representative",
        "Solutions Engineer",
        "Solutions Consultant",
        "Deployment Strategist",
        "Business Development Manager",
    ],
    "support": [
        "Customer Support Specialist",
        "Technical Support Engineer",
        "Customer Success Manager",
        "IT Support",
    ],
    "marketing": [
        "Marketing Manager",
        "Content Writer",
        "Editor",
        "Social Media Manager",
        "Growth Marketer",
    ],
    "people": [
        "Recruiter",
        "Talent Acquisition Partner",
        "People Operations Partner",
        "HR Manager",
    ],
    "finance_ops": [
        "Financial Analyst",
        "Accountant",
        "Accounts Payable Specialist",
        "Operations Manager",
        "Executive Assistant",
        "Buyer",
        "Procurement Specialist",
    ],
    "media_content": [
        "Dubbing Specialist",
        "Audiobook Narrator",
        "Voice Actor",
        "Localization Specialist",
        "Content Producer",
        "Video Editor",
        "Transcriptionist",
    ],
}

# The valid family keys, in a stable order (for the UI + validation).
FAMILIES: list[str] = list(FAMILY_DESCRIPTIONS)


class _Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine of two already-normalized vectors (a plain dot product)."""
    return sum(x * y for x, y in zip(a, b, strict=True))


def build_centroids(embedder: _Embedder) -> dict[str, list[float]]:
    """Embed every prototype once and average (then normalize) per family."""
    families = list(ROLE_PROTOTYPES)
    flat = [title for fam in families for title in ROLE_PROTOTYPES[fam]]
    vectors = embedder.embed(flat)
    centroids: dict[str, list[float]] = {}
    i = 0
    for fam in families:
        n = len(ROLE_PROTOTYPES[fam])
        group = vectors[i : i + n]
        i += n
        dim = len(group[0])
        mean = [sum(v[d] for v in group) / n for d in range(dim)]
        centroids[fam] = _normalize(mean)
    return centroids


def assign_family(
    vector: list[float],
    centroids: dict[str, list[float]],
    *,
    min_similarity: float,
    min_margin: float,
) -> str | None:
    """The nearest family, or None when the call is too weak/ambiguous to trust.

    None when the best cosine is below `min_similarity` (nothing fits) or within
    `min_margin` of the runner-up (a toss-up). Null-kept downstream: an unclassified
    job is never filtered out, matching the rest of the preference machinery.
    """
    unit = _normalize(vector)
    scored = sorted(((_cosine(unit, c), fam) for fam, c in centroids.items()), reverse=True)
    if not scored:
        return None
    top_sim, top_fam = scored[0]
    if top_sim < min_similarity:
        return None
    if len(scored) > 1 and top_sim - scored[1][0] < min_margin:
        return None
    return top_fam


class RoleClassifier:
    """Prototype centroids + thresholds; classifies titles into role families."""

    def __init__(
        self,
        centroids: dict[str, list[float]],
        *,
        min_similarity: float,
        min_margin: float,
    ):
        self._centroids = centroids
        self._min_similarity = min_similarity
        self._min_margin = min_margin

    @classmethod
    def from_embedder(
        cls, embedder: _Embedder, *, min_similarity: float, min_margin: float
    ) -> RoleClassifier:
        return cls(
            build_centroids(embedder),
            min_similarity=min_similarity,
            min_margin=min_margin,
        )

    def assign(self, vector: list[float]) -> str | None:
        return assign_family(
            vector,
            self._centroids,
            min_similarity=self._min_similarity,
            min_margin=self._min_margin,
        )

    def classify_titles(self, titles: list[str], embedder: _Embedder) -> list[str | None]:
        """Embed titles (boilerplate-free) and assign each a family."""
        if not titles:
            return []
        vectors = embedder.embed([t or " " for t in titles])
        return [self.assign(v) for v in vectors]


_FAMILY_GUIDE = "\n".join(f"- {fam}: {desc}" for fam, desc in FAMILY_DESCRIPTIONS.items())


class AnthropicRoleClassifier:
    """Claude Haiku labels job titles (and suggests families for a CV) via tool use.

    Fails soft: a batch the API errors on leaves its titles None (the pipeline only
    classifies null rows, so they are retried next run), and a failed CV suggestion
    returns [] rather than breaking the upload.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = ROLE_MODEL,
        *,
        client=None,
        batch_size: int = 60,
    ):
        if client is None:
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key)
        self._client = client
        self.model = model
        self._batch = batch_size

    def classify_titles(self, titles: list[str]) -> list[str | None]:
        out: list[str | None] = [None] * len(titles)
        for start in range(0, len(titles), self._batch):
            chunk = titles[start : start + self._batch]
            try:
                labels = self._label_batch(chunk)
            except Exception:  # noqa: BLE001 - one bad batch must not sink the run
                log.exception("role classification batch at %d failed", start)
                continue
            for idx, fam in labels.items():
                if 0 <= idx < len(chunk):
                    out[start + idx] = fam
        return out

    def _label_batch(self, titles: list[str]) -> dict[int, str]:
        listing = "\n".join(f"{i}\t{t}" for i, t in enumerate(titles))
        payload = self._call(
            _LABEL_TOOL,
            {
                "labels": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "family": {"type": "string", "enum": FAMILIES},
                        },
                        "required": ["index", "family"],
                    },
                }
            },
            system=(
                "Classify each job title into exactly one role family by the job's actual "
                "function, not by keywords (a 'Solutions Engineer' sells; a 'Bauleiter' "
                "runs construction sites). Titles may be German or French. Families:\n"
                + _FAMILY_GUIDE
            ),
            content=listing,
            max_tokens=4096,
        )
        labels: dict[int, str] = {}
        for item in payload.get("labels") or []:
            fam, idx = item.get("family"), item.get("index")
            if isinstance(idx, int) and fam in FAMILY_DESCRIPTIONS:
                labels[idx] = fam
        return labels

    def suggest_families(self, cv_text: str) -> list[str]:
        """The 1-3 families this CV's owner most plausibly targets, best first."""
        try:
            payload = self._call(
                _SUGGEST_TOOL,
                {"families": {"type": "array", "items": {"type": "string", "enum": FAMILIES}}},
                system=(
                    "From a candidate's CV, pick the 1-3 job role families they are best "
                    "qualified for or clearly moving toward, best first. Families:\n"
                    + _FAMILY_GUIDE
                ),
                content=cv_text[:_MAX_CV_CHARS],
                max_tokens=256,
            )
        except Exception:  # noqa: BLE001 - a suggestion is optional
            log.exception("CV role-family suggestion failed")
            return []
        picked: list[str] = []
        for fam in payload.get("families") or []:
            if fam in FAMILY_DESCRIPTIONS and fam != "other" and fam not in picked:
                picked.append(fam)
        return picked[:_MAX_SUGGESTIONS]

    def _call(self, tool: str, properties: dict, *, system: str, content: str, max_tokens: int):
        message = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            tools=[
                {
                    "name": tool,
                    "description": "Submit the role-family classification.",
                    "input_schema": {
                        "type": "object",
                        "properties": properties,
                        "required": list(properties),
                    },
                }
            ],
            tool_choice={"type": "tool", "name": tool},
            messages=[{"role": "user", "content": content}],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool:
                return block.input
        raise RuntimeError(f"{tool}: no tool_use in response")


class FakeRoleClassifier:
    """Deterministic, network-free classifier for tests: keyword rules over the title."""

    model = "fake-role-classifier"
    _RULES = (
        ("paralegal", "legal"),
        ("counsel", "legal"),
        ("account executive", "sales"),
        ("engineer", "engineering"),
        ("developer", "engineering"),
    )

    def __init__(self, suggestions: list[str] | None = None):
        self._suggestions = suggestions if suggestions is not None else ["engineering"]

    def classify_titles(self, titles: list[str]) -> list[str | None]:
        out: list[str | None] = []
        for title in titles:
            low = (title or "").lower()
            out.append(next((fam for kw, fam in self._RULES if kw in low), "other"))
        return out

    def suggest_families(self, cv_text: str) -> list[str]:
        return list(self._suggestions)


def get_role_classifier(
    settings: Settings = Depends(get_settings),
) -> AnthropicRoleClassifier | None:
    """The LLM classifier when ANTHROPIC_API_KEY is set, else None (use the fallback).

    Usable both as a FastAPI dependency and called directly with a Settings.
    """
    if not settings.anthropic_api_key:
        return None
    return AnthropicRoleClassifier(settings.anthropic_api_key, model=settings.role_model)
