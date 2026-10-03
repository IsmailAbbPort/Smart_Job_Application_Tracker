"""Score the current models against the golden set and print a metrics table.

    python -m evals.run                 # real OpenAI + Claude Haiku (reads .env keys)
    python -m evals.run --model claude-sonnet-4-6   # A/B a different judge model
    python -m evals.run --offline       # deterministic fakes, no network (smoke test)
    python -m evals.run --stages matcher,judge --no-letters

The pipeline is three provider-injected stages (evaluate_matcher / evaluate_judge /
evaluate_letters) reused verbatim by the CI test with the Fake providers, so what CI
gates is the same code that produces the real baseline. Judge and letter verdicts are
cached per (model, cv, pair) under evals/.cache so re-runs and A/Bs do not re-spend;
pass --refresh to recompute. The runner calls the AI modules directly, so it bypasses
the app's HTTP rate limiter: keep the golden set small and mind the API spend.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from app.ai.cover_letter import (
    LETTER_PROMPT_VERSION,
    AnthropicDrafter,
    Drafter,
    FakeDrafter,
)
from app.ai.decide import CandidateRules, decide
from app.ai.embedder import (
    Embedder,
    FakeEmbedder,
    OpenAIEmbedder,
    build_cv_document,
    build_job_document,
)
from app.ai.judge import FACTS_VERSION, AnthropicJudge, FakeJudge, Judge, build_job_text
from app.ai.matching import cosine_similarity
from app.config import get_settings
from app.schemas import CoverLetterResult, JudgeFacts, MatchTier
from evals import metrics
from evals.golden_set import GoldenCv, GoldenPair, GoldenSet, load_golden_set
from evals.quality import AnthropicQualityJudge, FakeQualityJudge, LetterQuality, QualityJudge

_QUALITY_DIMS = ("overall", "specificity", "relevance", "authenticity", "no_cliche")

DEFAULT_KS = (1, 3, 5, 10)
TIERS = [MatchTier.strong.value, MatchTier.medium.value, MatchTier.weak.value]
_CACHE_DIR = Path(__file__).parent / ".cache"
_RESULTS_DIR = Path(__file__).parent / "results"


class JsonCache:
    """A tiny file-backed key->JSON cache. path=None keeps it in memory only."""

    def __init__(self, path: Path | None):
        self._path = path
        self._data: dict = {}
        if path and path.exists():
            self._data = json.loads(path.read_text(encoding="utf-8"))

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def set(self, key: str, value: dict) -> None:
        self._data[key] = value
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")


# --- Stages --------------------------------------------------------------------


def evaluate_matcher(
    cv: GoldenCv, pairs: list[GoldenPair], embedder: Embedder, ks: Iterable[int]
) -> dict:
    """Embed the CV + each job snapshot, rank by cosine, and score the ranking against
    the labels. This is the retrieve stage in isolation (pure cosine over the labeled
    pool), so it answers 'does the matcher put the truly-relevant jobs on top?'."""
    ks = list(ks)
    cv_vector = embedder.embed([build_cv_document(cv.content)])[0]
    job_vectors = embedder.embed([build_job_document(p.job) for p in pairs])
    # Score each pair once, then sort (not cosine-in-the-sort-key, which recomputes it).
    scored = sorted(
        ((p, cosine_similarity(cv_vector, vec)) for p, vec in zip(pairs, job_vectors, strict=True)),
        key=lambda ps: ps[1],
        reverse=True,
    )
    ranked_pairs = [p for p, _ in scored]
    relevances = [p.relevant for p in ranked_pairs]
    gains = [p.gain for p in ranked_pairs]
    total_relevant = sum(1 for p in pairs if p.relevant)
    return {
        "n": len(pairs),
        "n_relevant": total_relevant,
        "precision_at_k": {k: metrics.precision_at_k(relevances, k) for k in ks},
        "recall_at_k": {k: metrics.recall_at_k(relevances, k, total_relevant) for k in ks},
        "mrr": metrics.reciprocal_rank(relevances),
        "ndcg_at_k": {k: metrics.ndcg_at_k(gains, k) for k in ks},
    }


def evaluate_judge(
    cv_id: int,
    cv: GoldenCv,
    pairs: list[GoldenPair],
    judge: Judge,
    cache: JsonCache,
    refresh: bool,
    rules: CandidateRules | None = None,
    sample: int = 0,
) -> dict:
    """Extract facts for every pair, grade them under the golden set's rules, then score
    the tiers against the labels (classification) and the 0-100 scores against relevance
    (calibration). Facts are cached, so a rule change re-scores for free; `sample` > 0
    caches a separate extraction to measure run-to-run variance."""
    model = getattr(judge, "model", "unknown")
    rules = rules or CandidateRules()
    y_true: list[str] = []
    y_pred: list[str] = []
    probs: list[float] = []
    outcomes: list[bool] = []
    for pair in pairs:
        key = f"facts-v{FACTS_VERSION}:{model}:{cv_id}:{pair.id}" + (f"#{sample}" if sample else "")
        cached = None if refresh else cache.get(key)
        if cached is None:
            facts = judge.judge(cv.content, build_job_text(pair.job))
            cached = facts.model_dump(mode="json")
            cache.set(key, cached)
        verdict = decide(JudgeFacts.model_validate(cached), rules, pair.job.is_remote)
        y_true.append(pair.label_tier.value)
        y_pred.append(verdict.verdict.value)
        probs.append(verdict.overall_score / 100.0)
        outcomes.append(pair.relevant)

    prf = metrics.precision_recall_f1(y_true, y_pred, TIERS)
    return {
        "model": model,
        "n": len(pairs),
        "accuracy": metrics.accuracy(y_true, y_pred),
        "kappa": metrics.cohens_kappa(y_true, y_pred, TIERS),
        "kappa_quadratic": metrics.cohens_kappa(y_true, y_pred, TIERS, weights="quadratic"),
        "ac1": metrics.gwet_ac1(y_true, y_pred, TIERS),
        "per_label": prf["per_label"],
        "macro": prf["macro"],
        "confusion": metrics.confusion_matrix(y_true, y_pred, TIERS),
        "auroc": metrics.auroc(probs, outcomes),
        "ece": metrics.expected_calibration_error(probs, outcomes),
        "calibration_bins": metrics.calibration_bins(probs, outcomes),
    }


def evaluate_letters(
    cv_id: int,
    cv: GoldenCv,
    pairs: list[GoldenPair],
    drafter: Drafter,
    cache: JsonCache,
    refresh: bool,
    limit: int | None,
    quality_judge: QualityJudge | None = None,
    quality_cache: JsonCache | None = None,
) -> dict:
    """Draft + audit a cover letter for each pair and aggregate the grounding metric
    (fraction of claims the CV supports). When a quality judge is given, also grade each
    letter on the G-Eval rubric (specificity/relevance/authenticity/no-cliche/overall)."""
    model = getattr(drafter, "model", "unknown")
    quality_cache = quality_cache if quality_cache is not None else JsonCache(None)
    chosen = [p for p in pairs if p.relevant] or pairs
    if limit is not None:
        chosen = chosen[:limit]
    ratios: list[float] = []
    unsupported: list[int] = []
    qualities: list[LetterQuality] = []
    for pair in chosen:
        key = f"letter-v{LETTER_PROMPT_VERSION}:{model}:{cv_id}:{pair.id}"
        cached = None if refresh else cache.get(key)
        if cached is None:
            result = drafter.write(cv.content, build_job_text(pair.job))
            cached = result.model_dump(mode="json")
            cache.set(key, cached)
        result = CoverLetterResult.model_validate(cached)
        ratios.append(result.fabrication.grounded_ratio)
        unsupported.append(result.fabrication.unsupported_count)

        if quality_judge is not None:
            qmodel = getattr(quality_judge, "model", "unknown")
            qkey = f"letter-v{LETTER_PROMPT_VERSION}:{qmodel}:{cv_id}:{pair.id}"
            qcached = None if refresh else quality_cache.get(qkey)
            if qcached is None:
                score = quality_judge.score(build_job_text(pair.job), result.body)
                qcached = score.model_dump(mode="json")
                quality_cache.set(qkey, qcached)
            qualities.append(LetterQuality.model_validate(qcached))

    out = {
        "model": model,
        "n": len(chosen),
        "mean_grounded_ratio": metrics.mean(ratios),
        "mean_unsupported": metrics.mean([float(u) for u in unsupported]),
        "pct_with_unsupported": metrics.mean([1.0 if u else 0.0 for u in unsupported]),
    }
    if quality_judge is not None:
        means = {
            f"mean_{d}": metrics.mean([getattr(q, d) for q in qualities]) for d in _QUALITY_DIMS
        }
        out["quality"] = {"model": getattr(quality_judge, "model", "unknown"), **means}
    return out


def run_eval(
    golden: GoldenSet,
    *,
    embedder: Embedder,
    judge: Judge,
    drafter: Drafter,
    ks: Iterable[int] = DEFAULT_KS,
    stages: Iterable[str] = ("matcher", "judge", "letter"),
    cv_ids: Iterable[int] | None = None,
    judge_cache: JsonCache | None = None,
    letter_cache: JsonCache | None = None,
    quality_judge: QualityJudge | None = None,
    quality_cache: JsonCache | None = None,
    refresh: bool = False,
    letter_limit: int | None = None,
    split: str | None = None,
    sample: int = 0,
) -> dict:
    """Run the selected stages over the golden set and return a results dict.

    Providers are injected (the Embedder/Judge/Drafter protocols), so the same code
    runs the real baseline and the mocked CI gate. Metrics are averaged across CVs.
    """
    stages = set(stages)
    ks = list(ks)
    judge_cache = judge_cache if judge_cache is not None else JsonCache(None)
    letter_cache = letter_cache if letter_cache is not None else JsonCache(None)
    quality_cache = quality_cache if quality_cache is not None else JsonCache(None)
    cv_ids = list(cv_ids) if cv_ids is not None else golden.cv_ids

    per_cv: dict[int, dict] = {}
    for cv_id in cv_ids:
        cv = golden.cv_for(cv_id)
        pairs = [p for p in golden.pairs_for(cv_id) if split is None or p.split == split]
        if not pairs:
            continue
        result: dict = {"n_pairs": len(pairs)}
        if "matcher" in stages:
            result["matcher"] = evaluate_matcher(cv, pairs, embedder, ks)
        if "judge" in stages:
            rules = CandidateRules(**golden.rules.model_dump())
            result["judge"] = evaluate_judge(
                cv_id, cv, pairs, judge, judge_cache, refresh, rules, sample
            )
        if "letter" in stages:
            result["letter"] = evaluate_letters(
                cv_id,
                cv,
                pairs,
                drafter,
                letter_cache,
                refresh,
                letter_limit,
                quality_judge=quality_judge,
                quality_cache=quality_cache,
            )
        per_cv[cv_id] = result

    return {
        "golden": {
            "status": golden.status,
            "n_pairs": len(golden.pairs),
            "n_relevant": sum(1 for p in golden.pairs if p.relevant),
            "cv_ids": cv_ids,
        },
        "stages": sorted(stages),
        "ks": ks,
        "per_cv": per_cv,
        "aggregate": _aggregate(per_cv, ks, stages),
    }


def _aggregate(per_cv: dict[int, dict], ks: list[int], stages: set[str]) -> dict:
    """Mean each headline metric across CVs (the golden set has one CV today, but the
    harness is written for several)."""
    cvs = list(per_cv.values())
    agg: dict = {}

    def per_k(metric_key: str) -> dict[int, float]:
        return {k: metrics.mean([c["matcher"][metric_key][k] for c in cvs]) for k in ks}

    if "matcher" in stages and cvs:
        agg["matcher"] = {
            "precision_at_k": per_k("precision_at_k"),
            "recall_at_k": per_k("recall_at_k"),
            "mrr": metrics.mean([c["matcher"]["mrr"] for c in cvs]),
            "ndcg_at_k": per_k("ndcg_at_k"),
        }
    if "judge" in stages and cvs:
        agg["judge"] = {
            "accuracy": metrics.mean([c["judge"]["accuracy"] for c in cvs]),
            "kappa": metrics.mean([c["judge"]["kappa"] for c in cvs]),
            "kappa_quadratic": metrics.mean([c["judge"]["kappa_quadratic"] for c in cvs]),
            "ac1": metrics.mean([c["judge"]["ac1"] for c in cvs]),
            "strong_recall": metrics.mean(
                [c["judge"]["per_label"]["strong"]["recall"] for c in cvs]
            ),
            "strong_precision": metrics.mean(
                [c["judge"]["per_label"]["strong"]["precision"] for c in cvs]
            ),
            "macro_f1": metrics.mean([c["judge"]["macro"]["f1"] for c in cvs]),
            "auroc": metrics.mean([c["judge"]["auroc"] for c in cvs]),
            "ece": metrics.mean([c["judge"]["ece"] for c in cvs]),
        }
    if "letter" in stages and cvs:
        agg["letter"] = {
            "mean_grounded_ratio": metrics.mean([c["letter"]["mean_grounded_ratio"] for c in cvs]),
            "pct_with_unsupported": metrics.mean(
                [c["letter"]["pct_with_unsupported"] for c in cvs]
            ),
        }
        graded = [c["letter"]["quality"] for c in cvs if c["letter"].get("quality")]
        if graded:
            agg["letter"]["quality"] = {
                f"mean_{d}": metrics.mean([q[f"mean_{d}"] for q in graded]) for d in _QUALITY_DIMS
            }
    return agg


# --- CLI -----------------------------------------------------------------------


def _build_providers(args) -> tuple[Embedder, Judge, Drafter, QualityJudge | None]:
    if args.offline:
        quality = None if args.no_quality else FakeQualityJudge()
        return FakeEmbedder(), FakeJudge(), FakeDrafter(), quality
    settings = get_settings()
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY not set; use --offline or add the key to .env")
    if not settings.anthropic_api_key:
        raise SystemExit("ANTHROPIC_API_KEY not set; use --offline or add the key to .env")
    embedder = OpenAIEmbedder(
        settings.openai_api_key,
        model=args.embed_model or settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    judge = AnthropicJudge(settings.anthropic_api_key, model=args.model or settings.judge_model)
    drafter = AnthropicDrafter(
        settings.anthropic_api_key,
        model=args.letter_model or settings.letter_model,
        audit_model=args.letter_audit_model or settings.letter_audit_model,
    )
    quality = (
        None
        if args.no_quality
        else AnthropicQualityJudge(
            settings.anthropic_api_key, model=args.quality_model or settings.letter_model
        )
    )
    return embedder, judge, drafter, quality


def _fmt(value: float) -> str:
    return f"{value:.3f}"


def _print_report(results: dict) -> None:
    g = results["golden"]
    print(f"\nGolden set: {g['n_pairs']} pairs ({g['n_relevant']} relevant), status={g['status']}")
    print(f"Stages: {', '.join(results['stages'])}   CVs: {g['cv_ids']}\n")
    agg = results["aggregate"]
    ks = results["ks"]

    if "matcher" in agg:
        m = agg["matcher"]
        print("MATCHER (retrieve / ranking)")
        print("  k        " + "  ".join(f"{k:>6}" for k in ks))
        print("  P@k      " + "  ".join(f"{_fmt(m['precision_at_k'][k]):>6}" for k in ks))
        print("  R@k      " + "  ".join(f"{_fmt(m['recall_at_k'][k]):>6}" for k in ks))
        print("  nDCG@k   " + "  ".join(f"{_fmt(m['ndcg_at_k'][k]):>6}" for k in ks))
        print(f"  MRR      {_fmt(m['mrr'])}\n")

    if "judge" in agg:
        j = agg["judge"]
        print("JUDGE (rerank / classification + calibration)")
        print(f"  accuracy         {_fmt(j['accuracy'])}")
        print(f"  macro F1         {_fmt(j['macro_f1'])}")
        print(f"  Cohen's kappa    {_fmt(j['kappa'])}  (quadratic {_fmt(j['kappa_quadratic'])})")
        print(f"  Gwet's AC1       {_fmt(j['ac1'])}")
        print(f"  strong recall    {_fmt(j['strong_recall'])}")
        print(f"  strong precision {_fmt(j['strong_precision'])}")
        print(f"  AUROC            {_fmt(j['auroc'])}")
        print(f"  ECE              {_fmt(j['ece'])}")
        first = next(iter(results["per_cv"].values()), {})
        if "judge" in first:
            print("  confusion (rows=true, cols=pred):")
            cm = first["judge"]["confusion"]
            print("            " + "  ".join(f"{t:>6}" for t in TIERS))
            for t in TIERS:
                print(f"    {t:>6}  " + "  ".join(f"{cm[t][p]:>6}" for p in TIERS))
        print()

    if "letter" in agg:
        letter = agg["letter"]
        print("COVER LETTER (grounding)")
        print(f"  mean grounded ratio    {_fmt(letter['mean_grounded_ratio'])}")
        print(f"  % with unsupported     {_fmt(letter['pct_with_unsupported'])}")
        if "quality" in letter:
            q = letter["quality"]
            print("  quality rubric (0-100):")
            for dim in _QUALITY_DIMS:
                print(f"    {dim:<13} {q['mean_' + dim]:.1f}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the golden-set eval harness.")
    parser.add_argument("--model", help="Judge model override (the A/B knob)")
    parser.add_argument("--letter-model", help="Cover-letter draft model override")
    parser.add_argument("--letter-audit-model", help="Cover-letter audit model override (A/B)")
    parser.add_argument("--quality-model", help="Letter-quality judge model override")
    parser.add_argument("--no-quality", action="store_true", help="Skip the letter-quality rubric")
    parser.add_argument("--embed-model", help="Embedding model override")
    parser.add_argument("--offline", action="store_true", help="Deterministic fakes, no network")
    parser.add_argument("--stages", default="matcher,judge,letter", help="Comma list of stages")
    parser.add_argument("--no-letters", action="store_true", help="Skip the pricier letter stage")
    parser.add_argument("--cv", type=int, action="append", help="CV id to score (repeatable)")
    parser.add_argument("--k", default=",".join(str(k) for k in DEFAULT_KS), help="Comma list of k")
    parser.add_argument("--letter-limit", type=int, help="Cap the number of letters drafted")
    parser.add_argument("--refresh", action="store_true", help="Ignore the verdict cache")
    parser.add_argument("--golden", help="Path to the golden set JSON")
    parser.add_argument("--split", choices=["tune", "test"], help="Score only this split")
    parser.add_argument("--sample", type=int, default=0, help="Judge re-run index (variance)")
    parser.add_argument("--out", help="Write the full results JSON here (default evals/results/)")
    args = parser.parse_args()

    golden = load_golden_set(args.golden) if args.golden else load_golden_set()
    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    if args.no_letters and "letter" in stages:
        stages.remove("letter")
    ks = [int(k) for k in args.k.split(",") if k.strip()]

    embedder, judge, drafter, quality_judge = _build_providers(args)
    judge_cache = JsonCache(None if args.offline else _CACHE_DIR / "judge.json")
    letter_cache = JsonCache(None if args.offline else _CACHE_DIR / "letter.json")
    quality_cache = JsonCache(None if args.offline else _CACHE_DIR / "quality.json")

    results = run_eval(
        golden,
        embedder=embedder,
        judge=judge,
        drafter=drafter,
        ks=ks,
        stages=stages,
        cv_ids=args.cv,
        judge_cache=judge_cache,
        letter_cache=letter_cache,
        quality_judge=quality_judge,
        quality_cache=quality_cache,
        refresh=args.refresh,
        letter_limit=args.letter_limit,
        split=args.split,
        sample=args.sample,
    )
    results["meta"] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "offline": args.offline,
        "judge_model": getattr(judge, "model", "unknown"),
        "embed_model": getattr(embedder, "_model", "fake"),
        "letter_model": getattr(drafter, "model", "unknown"),
        "quality_model": getattr(quality_judge, "model", None),
    }
    _print_report(results)

    suffix = (f"-{args.split}" if args.split else "") + (f"-s{args.sample}" if args.sample else "")
    default_out = _RESULTS_DIR / f"{results['meta']['judge_model']}{suffix}.json"
    out = Path(args.out) if args.out else default_out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
