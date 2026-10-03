"""Eval harness: metric math (unit), golden-set integrity, and the CI regression gate.

The metric functions are pure, so each is checked against a hand-computed value. The
regression gate runs the real eval pipeline (evals.run.run_eval) with the deterministic
Fake providers over a tiny crafted golden set, so CI fails if the wiring or the fakes
regress without burning any API budget. A separate smoke test runs the pipeline over
the committed golden_set.json (still offline) to prove it loads and scores end to end.
"""

from __future__ import annotations

import math

import pytest

from app.ai.cover_letter import FakeDrafter
from app.ai.embedder import FakeEmbedder
from app.ai.judge import FakeJudge
from app.schemas import MatchTier
from evals import metrics
from evals.golden_set import GoldenCv, GoldenJob, GoldenPair, GoldenSet, load_golden_set
from evals.quality import FakeQualityJudge, LetterQuality
from evals.run import JsonCache, run_eval

TIERS = [MatchTier.strong.value, MatchTier.medium.value, MatchTier.weak.value]


# --- Ranking metrics -----------------------------------------------------------


def test_precision_at_k():
    rel = [True, False, True, False, True]
    assert metrics.precision_at_k(rel, 3) == pytest.approx(2 / 3)
    assert metrics.precision_at_k(rel, 100) == pytest.approx(3 / 5)  # k clamps to len
    assert metrics.precision_at_k(rel, 0) == 0.0


def test_recall_at_k():
    rel = [True, False, True, False, True]
    assert metrics.recall_at_k(rel, 3) == pytest.approx(2 / 3)
    assert metrics.recall_at_k(rel, 3, total_relevant=6) == pytest.approx(2 / 6)
    assert metrics.recall_at_k([False, False], 2) == 0.0  # no relevant -> 0, not error


def test_reciprocal_rank():
    assert metrics.reciprocal_rank([False, False, True]) == pytest.approx(1 / 3)
    assert metrics.reciprocal_rank([True, False]) == 1.0
    assert metrics.reciprocal_rank([False, False]) == 0.0


def test_ndcg_at_k():
    assert metrics.ndcg_at_k([2, 1, 0], 3) == 1.0  # already ideal order
    # gains [0,1,2]: DCG = 0 + 1/log2(3) + 2/log2(4); IDCG = 2 + 1/log2(3)
    dcg = 1 / math.log2(3) + 2 / math.log2(4)
    idcg = 2 / math.log2(2) + 1 / math.log2(3)
    assert metrics.ndcg_at_k([0, 1, 2], 3) == pytest.approx(dcg / idcg)
    assert metrics.ndcg_at_k([0, 0, 0], 3) == 0.0


# --- Classification metrics ----------------------------------------------------


def test_confusion_matrix_and_prf():
    y_true = ["a", "a", "b"]
    y_pred = ["a", "b", "b"]
    cm = metrics.confusion_matrix(y_true, y_pred, ["a", "b"])
    assert cm == {"a": {"a": 1, "b": 1}, "b": {"a": 0, "b": 1}}

    prf = metrics.precision_recall_f1(y_true, y_pred, ["a", "b"])
    assert prf["per_label"]["a"]["precision"] == pytest.approx(1.0)
    assert prf["per_label"]["a"]["recall"] == pytest.approx(0.5)
    assert prf["per_label"]["a"]["f1"] == pytest.approx(2 / 3)
    assert prf["per_label"]["b"]["precision"] == pytest.approx(0.5)
    assert prf["per_label"]["b"]["recall"] == pytest.approx(1.0)
    assert prf["macro"]["f1"] == pytest.approx(2 / 3)


def test_accuracy():
    assert metrics.accuracy(["a", "a", "b"], ["a", "b", "b"]) == pytest.approx(2 / 3)
    assert metrics.accuracy([], []) == 0.0


def test_cohens_kappa_unweighted():
    # po = 2/3, pe = 4/9 -> kappa = 0.4 (worked out by hand).
    assert metrics.cohens_kappa(["a", "a", "b"], ["a", "b", "b"], ["a", "b"]) == pytest.approx(0.4)
    # Perfect agreement -> 1.0.
    assert metrics.cohens_kappa(["a", "b"], ["a", "b"], ["a", "b"]) == pytest.approx(1.0)


def test_gwet_ac1():
    assert metrics.gwet_ac1(["a", "b"], ["a", "b"], ["a", "b"]) == pytest.approx(1.0)
    # po = 3/4; pi_a = 5/8, pi_b = 3/8; pe = 2 * (5/8 * 3/8) = 15/32 -> (24/32-15/32)/(17/32).
    y_true, y_pred = ["a", "a", "a", "b"], ["a", "a", "b", "b"]
    assert metrics.gwet_ac1(y_true, y_pred, ["a", "b"]) == pytest.approx(9 / 17)
    # Dominant class: kappa collapses toward 0, AC1 stays high.
    y_true = ["weak"] * 9 + ["strong"]
    y_pred = ["weak"] * 10
    assert metrics.gwet_ac1(y_true, y_pred, TIERS) > metrics.cohens_kappa(y_true, y_pred, TIERS)


def test_cohens_kappa_quadratic_rewards_near_misses():
    # An ordinal near-miss (strong vs medium) should score higher weighted than the
    # exact-match kappa, which treats it as a full error.
    y_true = ["strong", "strong", "weak"]
    y_pred = ["medium", "strong", "weak"]
    plain = metrics.cohens_kappa(y_true, y_pred, TIERS)
    quad = metrics.cohens_kappa(y_true, y_pred, TIERS, weights="quadratic")
    assert quad > plain


# --- Calibration metrics -------------------------------------------------------


def test_calibration_bins_and_ece():
    probs = [0.05, 0.15, 0.95]
    outcomes = [False, False, True]
    bins = metrics.calibration_bins(probs, outcomes, n_bins=10)
    assert len(bins) == 10
    assert bins[0]["count"] == 1 and bins[0]["frac_pos"] == 0.0
    assert bins[9]["count"] == 1 and bins[9]["frac_pos"] == 1.0
    # ECE = mean(|0.05-0|, |0.15-0|, |0.95-1|) = 0.25/3.
    assert metrics.expected_calibration_error(probs, outcomes) == pytest.approx(0.25 / 3)
    assert metrics.expected_calibration_error([], []) == 0.0


def test_auroc_ranks_relevant_pairs_above_irrelevant_ones():
    assert metrics.auroc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == 1.0
    assert metrics.auroc([0.9, 0.8, 0.2, 0.1], [False, False, True, True]) == 0.0
    # Rescaling the scores cannot change the ordering, so AUROC is unmoved (unlike ECE).
    assert metrics.auroc([0.45, 0.4, 0.1, 0.05], [True, True, False, False]) == 1.0
    # One relevant pair below one irrelevant pair: 3 of 4 cross-class pairs correct.
    assert metrics.auroc([0.9, 0.1, 0.5, 0.05], [True, True, False, False]) == 0.75
    # Every score tied means no separation at all: each cross-class pair counts a half.
    assert metrics.auroc([0.5] * 4, [True, True, False, False]) == 0.5
    # A tied block straddling the classes: the two clear pairs plus half of the tie.
    assert metrics.auroc([0.9, 0.5, 0.5, 0.1], [True, True, False, False]) == 0.875
    assert metrics.auroc([0.9, 0.8], [True, True]) == 0.5  # no negatives to separate from
    assert metrics.auroc([], []) == 0.5


# --- Golden-set integrity ------------------------------------------------------


def test_golden_set_loads_and_is_labeled():
    golden = load_golden_set()
    assert golden.pairs, "golden set is empty"
    assert golden.status in {"draft", "reviewed"}
    for cv_id in golden.cv_ids:
        assert golden.cv_for(cv_id).content.strip(), f"CV {cv_id} has no content"
    # Every pair carries a valid tier and at least one relevant + one non-relevant
    # exist (a ranking metric over an all-relevant set is meaningless).
    assert any(p.relevant for p in golden.pairs)
    assert any(not p.relevant for p in golden.pairs)


# --- The CI regression gate: real pipeline, fake providers, tiny crafted set ----


def _crafted_golden_set() -> GoldenSet:
    """A set the deterministic FakeJudge scores correctly: strong pairs share every
    posting word with the CV (each becomes a met requirement), weak pairs share none."""
    cv_text = (
        "full stack python fastapi postgres docker react typescript node redis kubernetes "
        "graphql backend frontend engineer"
    )
    strong_job = GoldenJob(
        title="Full Stack Engineer",
        description=(
            "python fastapi postgres docker react typescript node redis kubernetes graphql "
            "backend frontend engineer role"
        ),
    )
    weak_job = GoldenJob(
        title="Sales Executive",
        description="sales marketing account executive quota territory pipeline commission",
    )
    pairs = [
        GoldenPair(id="s1", cv_id=1, label_tier=MatchTier.strong, job=strong_job),
        GoldenPair(id="s2", cv_id=1, label_tier=MatchTier.strong, job=strong_job),
        GoldenPair(id="w1", cv_id=1, label_tier=MatchTier.weak, job=weak_job),
        GoldenPair(id="w2", cv_id=1, label_tier=MatchTier.weak, job=weak_job),
    ]
    return GoldenSet(cvs={"1": GoldenCv(content=cv_text)}, pairs=pairs)


def test_regression_gate_offline_thresholds():
    golden = _crafted_golden_set()
    results = run_eval(
        golden,
        embedder=FakeEmbedder(),
        judge=FakeJudge(),
        drafter=FakeDrafter(),
        judge_cache=JsonCache(None),
        letter_cache=JsonCache(None),
    )
    agg = results["aggregate"]
    # Judge (deterministic word-overlap) must classify the crafted set well.
    assert agg["judge"]["accuracy"] >= 0.75, agg["judge"]
    assert agg["judge"]["kappa"] > 0.0
    # Cover letters from the FakeDrafter are fully grounded by construction.
    assert agg["letter"]["mean_grounded_ratio"] == pytest.approx(1.0)
    # Matcher metrics are present and in range (FakeEmbedder ranking is arbitrary, so
    # only structure/bounds are gated here).
    for value in agg["matcher"]["precision_at_k"].values():
        assert 0.0 <= value <= 1.0


def test_fake_quality_judge_penalizes_generic_letters():
    judge = FakeQualityJudge()
    job = "Python FastAPI backend engineer building APIs"
    specific = "I built Python FastAPI backend APIs with Postgres and Docker in production."
    generic = (
        "I am writing to express my keen interest. " "I am a proven team player and a perfect fit."
    )
    good = judge.score(job, specific)
    bad = judge.score(job, generic)
    assert isinstance(good, LetterQuality)
    assert 0 <= good.overall <= 100 and 0 <= bad.overall <= 100
    assert good.no_cliche > bad.no_cliche  # the generic letter is full of cliches
    assert good.relevance >= bad.relevance


def test_run_eval_includes_letter_quality_offline():
    results = run_eval(
        _crafted_golden_set(),
        embedder=FakeEmbedder(),
        judge=FakeJudge(),
        drafter=FakeDrafter(),
        quality_judge=FakeQualityJudge(),
        judge_cache=JsonCache(None),
        letter_cache=JsonCache(None),
        quality_cache=JsonCache(None),
    )
    quality = results["aggregate"]["letter"]["quality"]
    assert set(quality) == {
        "mean_overall",
        "mean_specificity",
        "mean_relevance",
        "mean_authenticity",
        "mean_no_cliche",
    }
    assert all(0 <= v <= 100 for v in quality.values())


def test_pipeline_runs_over_committed_golden_set_offline():
    """Smoke: the real golden set scores end to end with fakes (no network)."""
    golden = load_golden_set()
    results = run_eval(
        golden,
        embedder=FakeEmbedder(),
        judge=FakeJudge(),
        drafter=FakeDrafter(),
        letter_limit=2,
        judge_cache=JsonCache(None),
        letter_cache=JsonCache(None),
    )
    agg = results["aggregate"]
    assert set(agg) == {"matcher", "judge", "letter"}
    assert 0.0 <= agg["judge"]["ece"] <= 1.0
    assert results["golden"]["n_pairs"] == len(golden.pairs)
