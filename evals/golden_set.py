"""The golden set: hand-labeled (CV, job) pairs that ground every eval metric.

A pair carries a job-text snapshot (not a live DB id, which churns as the corpus is
re-ingested and stale rows are swept) plus the human label: a tier
(strong/medium/weak) from which the binary `relevant` flag and the graded nDCG gain
are derived. The runner re-embeds and re-judges these snapshots, so the set is
self-contained and reproducible without the database.

Build a draft set from the live corpus with `python -m evals.curate` (see that
module); this module only defines the schema and the loader the runner reads.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.schemas import MatchTier

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"
# Real CV text lives here, gitignored, so personal data is never committed. The
# committed golden set carries only a placeholder; load_golden_set merges the real
# content in when this file is present. Regenerate it with `python -m evals.curate`.
LOCAL_CVS_PATH = Path(__file__).parent / "cvs.local.json"

CV_PLACEHOLDER = (
    "[CV text is stored locally in evals/cvs.local.json (gitignored) and is not "
    "committed. Run `python -m evals.curate` to regenerate it from the database.]"
)

# Graded gains for nDCG and the relevance threshold. A "medium" fit is still worth
# surfacing, so it counts as relevant; only "weak" is treated as a non-match.
_TIER_GAIN: dict[MatchTier, float] = {
    MatchTier.strong: 2.0,
    MatchTier.medium: 1.0,
    MatchTier.weak: 0.0,
}


class GoldenJob(BaseModel):
    """Snapshot of a job: enough to rebuild its embedding + judge documents."""

    source: str = ""
    source_id: str = ""
    title: str
    company: str = ""
    location: str | None = None
    is_remote: bool = False
    description: str = ""
    seniority: str | None = None
    role_family: str | None = None
    required_languages: list[str] = Field(default_factory=list)
    min_years_experience: int | None = None
    url: str = ""
    # Set by the pre-filter stage from the snapshot's own text, not stored in the file,
    # so the eval exercises the live extractors rather than a frozen copy of their output.
    language: str | None = None
    work_countries: list[str] = Field(default_factory=list)


class GoldenPair(BaseModel):
    """One labeled (CV, job) pair. `label_tier` is the human ground truth."""

    id: str
    cv_id: int
    label_tier: MatchTier
    rationale: str = ""
    reviewed: bool = False
    cosine_rank: int | None = None  # rank in the live cosine shortlist when sampled
    # tune: may be looked at while iterating on the judge. test: held out, scored only.
    split: str = "tune"
    job: GoldenJob

    @property
    def gain(self) -> float:
        return _TIER_GAIN[self.label_tier]

    @property
    def relevant(self) -> bool:
        return self.gain >= 1.0


class GoldenCv(BaseModel):
    """A CV the pairs are labeled against, snapshotted by content."""

    label: str = ""
    content: str
    source: str = ""


class GoldenRules(BaseModel):
    """The candidate preferences the labels assume (fed to app/ai/decide.py)."""

    remote_only: bool = False
    known_languages: list[str] = Field(default_factory=list)
    work_rights: list[str] = Field(default_factory=list)
    years_experience: int | None = None
    max_experience_gap: int | None = None


class GoldenSet(BaseModel):
    """The whole labeled set: the CVs and every pair labeled against them."""

    version: int = 1
    status: str = "draft"  # draft (labels are my best guess) | reviewed (human-signed)
    notes: str = ""
    rules: GoldenRules = Field(default_factory=GoldenRules)
    cvs: dict[str, GoldenCv]
    pairs: list[GoldenPair]

    def cv_for(self, cv_id: int) -> GoldenCv:
        return self.cvs[str(cv_id)]

    def pairs_for(self, cv_id: int) -> list[GoldenPair]:
        return [p for p in self.pairs if p.cv_id == cv_id]

    @property
    def cv_ids(self) -> list[int]:
        return sorted({p.cv_id for p in self.pairs})


def _load_local_cv_overrides(path: Path | str = LOCAL_CVS_PATH) -> dict[str, str]:
    """{cv_id: content} from the gitignored local file, or {} if it is absent."""
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def load_golden_set(
    path: Path | str = GOLDEN_SET_PATH, cvs_path: Path | str = LOCAL_CVS_PATH
) -> GoldenSet:
    """Load and validate the golden set, merging real CV text from the gitignored
    local file over the committed placeholder when present.

    Raises if any pair is missing a tier label (an unlabeled draft template will not
    load, which is the intended guard). CI runs against the placeholder (fakes ignore
    CV content); a real run needs cvs.local.json for meaningful embedder/judge scores.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    overrides = _load_local_cv_overrides(cvs_path)
    for cv_id, cv in data.get("cvs", {}).items():
        if cv_id in overrides:
            cv["content"] = overrides[cv_id]
    return GoldenSet.model_validate(data)
