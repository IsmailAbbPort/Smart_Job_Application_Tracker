"""Pure metric functions for the eval harness.

No I/O, no DB, no model calls: every function here maps labels + predictions to a
number, so each is unit-tested with hand-computed cases (see tests/test_evals.py).
Three families:

- Ranking (retrieve stage): precision@k, recall@k, reciprocal rank, and graded-gain
  nDCG over a single ranked list. Answer: are the truly-relevant jobs near the top?
- Classification (judge stage): confusion matrix, per-class precision/recall/F1,
  accuracy, and Cohen's kappa (optionally ordinal-weighted for the tier scale).
- Calibration (judge scores): reliability bins + expected calibration error, i.e.
  does a score of 80 really mean ~80% good?

Kept dependency-free (pure Python) so the harness adds no runtime deps.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence


def mean(values: Sequence[float]) -> float:
    """Arithmetic mean, or 0.0 for an empty sequence."""
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0


# --- Ranking (retrieve stage) --------------------------------------------------
# Each takes `relevances`/`gains` already in ranked order (best first).


def precision_at_k(relevances: Sequence[bool], k: int) -> float:
    """Fraction of the top-k ranked items that are relevant. k>len clamps to len."""
    if k <= 0:
        return 0.0
    top = list(relevances[:k])
    if not top:
        return 0.0
    return sum(1 for r in top if r) / len(top)


def recall_at_k(relevances: Sequence[bool], k: int, total_relevant: int | None = None) -> float:
    """Fraction of all relevant items that appear in the top-k.

    total_relevant defaults to the number of relevant items in `relevances`; pass it
    explicitly when some relevant items live outside this ranked list.
    """
    total = total_relevant if total_relevant is not None else sum(1 for r in relevances if r)
    if total <= 0:
        return 0.0
    hit = sum(1 for r in relevances[:k] if r)
    return hit / total


def reciprocal_rank(relevances: Sequence[bool]) -> float:
    """1/(rank of the first relevant item), or 0.0 if none are relevant."""
    for i, r in enumerate(relevances):
        if r:
            return 1.0 / (i + 1)
    return 0.0


def dcg_at_k(gains: Sequence[float], k: int) -> float:
    """Discounted cumulative gain over the top-k (graded gains, log2 discount)."""
    return sum(g / math.log2(i + 2) for i, g in enumerate(list(gains)[:k]))


def ndcg_at_k(gains: Sequence[float], k: int) -> float:
    """nDCG with graded gains (e.g. strong=2, medium=1, weak=0). 0.0 if no gain."""
    ideal = dcg_at_k(sorted(gains, reverse=True), k)
    if ideal == 0:
        return 0.0
    return dcg_at_k(gains, k) / ideal


# --- Classification (judge stage) ----------------------------------------------


def confusion_matrix(
    y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str]
) -> dict[str, dict[str, int]]:
    """matrix[true][pred] = count, restricted to `labels` (other classes ignored)."""
    label_set = set(labels)
    matrix = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(y_true, y_pred, strict=True):
        if t in label_set and p in label_set:
            matrix[t][p] += 1
    return matrix


def precision_recall_f1(
    y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str]
) -> dict:
    """Per-label precision/recall/F1 (+ support) and macro averages."""
    cm = confusion_matrix(y_true, y_pred, labels)
    per_label: dict[str, dict[str, float]] = {}
    for label in labels:
        tp = cm[label][label]
        fp = sum(cm[t][label] for t in labels if t != label)
        fn = sum(cm[label][p] for p in labels if p != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_label[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": tp + fn,
        }
    macro = {
        metric: mean([per_label[label][metric] for label in labels])
        for metric in ("precision", "recall", "f1")
    }
    return {"per_label": per_label, "macro": macro}


def accuracy(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    """Fraction of exact-match predictions."""
    pairs = list(zip(y_true, y_pred, strict=True))
    if not pairs:
        return 0.0
    return sum(1 for t, p in pairs if t == p) / len(pairs)


def cohens_kappa(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    labels: Sequence[str] | None = None,
    weights: str | None = None,
) -> float:
    """Cohen's kappa: agreement corrected for chance, in (-inf, 1].

    weights=None gives standard (exact-match) kappa. weights in {"linear",
    "quadratic"} treat `labels` as an ordinal scale, so a strong/medium disagreement
    counts as a smaller error than strong/weak. The tier scale is ordinal, so the
    weighted variant is the honest agreement number to report for the judge.
    """
    pairs = list(zip(y_true, y_pred, strict=True))
    n = len(pairs)
    if n == 0:
        return 0.0
    if labels is None:
        labels = sorted({t for t, _ in pairs} | {p for _, p in pairs})
    index = {label: i for i, label in enumerate(labels)}
    k = len(labels)

    def agreement_weight(i: int, j: int) -> float:
        """1.0 = full agreement, 0.0 = full disagreement."""
        if weights is None:
            return 1.0 if i == j else 0.0
        if k <= 1:
            return 1.0
        distance = abs(i - j) / (k - 1)
        return 1.0 - (distance if weights == "linear" else distance * distance)

    row = Counter(index[t] for t, _ in pairs)  # true-label marginals
    col = Counter(index[p] for _, p in pairs)  # predicted-label marginals

    observed = mean([agreement_weight(index[t], index[p]) for t, p in pairs])
    expected = sum(agreement_weight(i, j) * row[i] * col[j] for i in range(k) for j in range(k)) / (
        n * n
    )
    if expected >= 1.0:  # degenerate (single class): no room to beat chance
        return 1.0 if observed >= 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


# --- Calibration (judge scores) ------------------------------------------------


def calibration_bins(
    probs: Sequence[float], outcomes: Sequence[bool], n_bins: int = 10
) -> list[dict]:
    """Reliability-curve bins over [0, 1]. Each bin reports its range, count, mean
    predicted probability, and observed positive fraction. Empty bins are kept so the
    curve has a fixed shape. The last bin is closed on the right so p==1.0 lands in it.
    """
    pairs = list(zip(probs, outcomes, strict=True))
    bins: list[dict] = []
    for b in range(n_bins):
        lo = b / n_bins
        hi = (b + 1) / n_bins
        in_bin = [(p, o) for p, o in pairs if (lo <= p < hi) or (b == n_bins - 1 and p == hi)]
        count = len(in_bin)
        bins.append(
            {
                "lo": lo,
                "hi": hi,
                "count": count,
                "mean_pred": mean([p for p, _ in in_bin]) if count else 0.0,
                "frac_pos": mean([1.0 if o else 0.0 for _, o in in_bin]) if count else 0.0,
            }
        )
    return bins


def expected_calibration_error(
    probs: Sequence[float], outcomes: Sequence[bool], n_bins: int = 10
) -> float:
    """ECE: the count-weighted average gap between predicted probability and observed
    positive frequency across bins. 0.0 is perfectly calibrated; higher is worse.
    """
    total = len(list(probs))
    if total == 0:
        return 0.0
    return sum(
        (bin_["count"] / total) * abs(bin_["mean_pred"] - bin_["frac_pos"])
        for bin_ in calibration_bins(probs, outcomes, n_bins)
        if bin_["count"]
    )
