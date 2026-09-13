"""Build a draft golden set by sampling diverse (CV, job) pairs from the live corpus.

    python -m evals.curate --cv 1                     # write an UNLABELED draft template
    python -m evals.curate --apply-labels _labels.json  # merge human/agent tier labels

Sampling is stratified over the cosine ranking so the set is not trivially separable:
the truly-relevant jobs are NOT all at the top and the irrelevant ones are NOT all at
the bottom (otherwise every ranking metric is a perfect 1.0 and measures nothing).
Strata: the head of the shortlist, a mid band, the tail, a random sample, and titles
that score high on cosine but are usually off-target (senior / ML-research / sales),
i.e. the retrieve stage's known false positives.

The template it writes has `label_tier: null`; fill those in (that is the human
judgement the whole harness rests on), then run --apply-labels to produce a set that
`load_golden_set` will accept. Requires the database, so run it inside Docker against
the compose Postgres (see evals/README.md).
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

from app.ai.matching import rank_jobs
from app.db import SessionLocal
from app.models import Cv, Job
from evals.golden_set import CV_PLACEHOLDER, GOLDEN_SET_PATH, LOCAL_CVS_PATH, GoldenSet

_MAX_DESC_CHARS = 6000
_SEED = 20260822  # fixed so re-running curate reproduces the same sample

# Titles that overlap the AI/full-stack CV in embedding space but are usually a weak
# fit for a junior EU-remote search (see the project's pool-cleaning notes). Included
# deliberately as hard negatives so the ranking metrics have something to get wrong.
_OFF_TARGET = re.compile(
    r"\b(senior|staff|principal|lead|head of|director|vp|manager|"
    r"machine learning|ml engineer|research scientist|data scientist|"
    r"sales|account executive|marketing|social media|recruiter|designer)\b",
    re.IGNORECASE,
)


def _write_local_cv(cv_id: int, content: str, path: Path = LOCAL_CVS_PATH) -> None:
    """Merge one CV's real text into the gitignored local overrides file."""
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    existing[str(cv_id)] = content
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")


def _snapshot(job: Job, cosine_rank: int) -> dict:
    return {
        "id": f"j{job.id}",
        "cv_id": None,  # filled per CV below
        "label_tier": None,  # <-- fill this in
        "rationale": "",
        "reviewed": False,
        "cosine_rank": cosine_rank,
        "job": {
            "source": job.source,
            "source_id": job.source_id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "is_remote": job.is_remote,
            "description": (job.description or "")[:_MAX_DESC_CHARS],
            "seniority": job.seniority,
            "role_family": job.role_family,
            "required_languages": list(job.required_languages or []),
            "min_years_experience": job.min_years_experience,
            "url": job.url,
        },
    }


def _select_indices(n: int, ranked: list, rng: random.Random) -> dict[int, str]:
    """Map a selected cosine-rank index -> the stratum it was picked for."""
    chosen: dict[int, str] = {}

    def take(indices, stratum):
        for i in indices:
            if 0 <= i < n and i not in chosen:
                chosen[i] = stratum

    take(range(0, 18), "head")  # top of the shortlist
    mid = n // 2
    take(range(mid, mid + 8), "mid")
    take(range(max(0, n - 6), n), "tail")

    # High-cosine off-target titles: hard negatives from the top of the ranking.
    off_target = [i for i in range(0, min(200, n)) if _OFF_TARGET.search(ranked[i][0].title or "")]
    take(off_target[:8], "off_target")

    # Random spread across the rest, for coverage the strata miss.
    remaining = [i for i in range(n) if i not in chosen]
    rng.shuffle(remaining)
    take(remaining[:8], "random")
    return chosen


def build_template(cv_id: int, out: Path) -> None:
    rng = random.Random(_SEED)
    with SessionLocal() as session:
        cv = session.get(Cv, cv_id)
        if cv is None or cv.embedding is None:
            raise SystemExit(f"CV {cv_id} not found or not embedded")
        ranked = rank_jobs(session, list(cv.embedding), filters=[], limit=6000)
        n = len(ranked)
        if n == 0:
            raise SystemExit("no embedded jobs in the corpus; embed jobs first")

        chosen = _select_indices(n, ranked, rng)
        pairs = []
        for idx in sorted(chosen):
            job, _sim = ranked[idx]
            pair = _snapshot(job, cosine_rank=idx + 1)
            pair["cv_id"] = cv_id
            pair["_stratum"] = chosen[idx]  # hint for labeling; dropped on --apply-labels
            pairs.append(pair)

        template = {
            "version": 1,
            "status": "draft-unlabeled",
            "notes": (
                "Draft golden set. Fill each pair's label_tier "
                "(strong|medium|weak), then run: python -m evals.curate --apply-labels."
            ),
            "cvs": {
                str(cv_id): {
                    "label": cv.label,
                    "content": CV_PLACEHOLDER,  # real text goes to the gitignored local file
                    "source": f"db:cv.id={cv_id}",
                }
            },
            "pairs": pairs,
        }
        # Real CV text is written to the gitignored local file, never the committed set.
        _write_local_cv(cv_id, cv.content)
    out.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {len(pairs)} candidate pairs to {out}")
    print("\nCompact summary for labeling (rank | stratum | seniority | role | langs | title):")
    for p in pairs:
        j = p["job"]
        langs = ",".join(j["required_languages"]) or "-"
        print(
            f"  {p['id']:>7}  #{p['cosine_rank']:<4} {p['_stratum']:<10} "
            f"{(j['seniority'] or '-'):<7} {(j['role_family'] or '-'):<12} {langs:<6} "
            f"{(j['title'] or '')[:48]:<48} @ {(j['company'] or '')[:22]}"
        )


def apply_labels(labels_path: Path, golden_path: Path) -> None:
    """Merge a {pair_id: tier | {tier, rationale}} map into the draft, drop the
    labeling hints, mark it status=draft, and validate it loads."""
    template = json.loads(golden_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    missing = []
    for pair in template["pairs"]:
        pair.pop("_stratum", None)
        entry = labels.get(pair["id"])
        if entry is None:
            missing.append(pair["id"])
            continue
        if isinstance(entry, str):
            pair["label_tier"] = entry
        else:
            pair["label_tier"] = entry["tier"]
            pair["rationale"] = entry.get("rationale", "")
    if missing:
        raise SystemExit(f"no label for {len(missing)} pairs: {', '.join(missing[:10])}")

    template["status"] = "draft"
    template["notes"] = (
        "DRAFT labels (my best judgement, not yet human-reviewed). Correct any tier and "
        "flip status to 'reviewed' once signed off. See evals/README.md."
    )
    GoldenSet.model_validate(template)  # fail loudly on a bad tier before writing
    golden_path.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Applied {len(template['pairs'])} labels -> {golden_path} (status=draft)")


def externalize_cvs(golden_path: Path) -> None:
    """Move CV text out of an already-built golden set into the gitignored local file,
    replacing the committed content with a placeholder. Safe to re-run (idempotent)."""
    data = json.loads(golden_path.read_text(encoding="utf-8"))
    moved = 0
    for cv_id, cv in data.get("cvs", {}).items():
        if cv.get("content") and cv["content"] != CV_PLACEHOLDER:
            _write_local_cv(int(cv_id), cv["content"])
            cv["content"] = CV_PLACEHOLDER
            moved += 1
    golden_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Externalized {moved} CV(s) to {LOCAL_CVS_PATH.name}; placeholder left in the set")


def main() -> None:
    parser = argparse.ArgumentParser(description="Curate / label the golden set.")
    parser.add_argument("--cv", type=int, default=1, help="CV id to sample against")
    parser.add_argument("--out", default=str(GOLDEN_SET_PATH), help="Template/golden output path")
    parser.add_argument("--apply-labels", help="Merge this labels JSON into the golden set")
    parser.add_argument(
        "--externalize-cvs",
        action="store_true",
        help="Move CV text out of the golden set into the gitignored local file",
    )
    args = parser.parse_args()

    out = Path(args.out)
    if args.externalize_cvs:
        externalize_cvs(out)
    elif args.apply_labels:
        apply_labels(Path(args.apply_labels), out)
    else:
        build_template(args.cv, out)


if __name__ == "__main__":
    main()
