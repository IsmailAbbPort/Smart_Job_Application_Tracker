"""Role-family classification from the job title, in embedding space.

The retrieve stage's cosine sits in a narrow band (every job at a trendy AI lab
looks ~alike), so it can't tell a Backend Engineer from an IT Support role at the
same company. The blunt fix is a title keyword blocklist, but that is whack-a-mole.

This is the durable alternative: embed the *title* (which, unlike the body, has no
company boilerplate) and assign it to the nearest of a small set of canonical role
families by cosine to each family's prototype centroid. Deterministic, no LLM, and
it generalizes ("Deployment Strategist" lands near Sales without ever being named).

The family becomes a stored signal (`Job.role_family`) that a positive preference
filter (`include_role_families`) can gate on, upstream of the LLM judge.
"""

from __future__ import annotations

import math
from typing import Protocol

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
FAMILIES: list[str] = list(ROLE_PROTOTYPES)


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
