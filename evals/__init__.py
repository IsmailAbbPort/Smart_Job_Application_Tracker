"""Eval harness for the two LLM subsystems: the embedding matcher (retrieve) and
the Claude judge (rerank), plus the cover-letter grounding metric.

The golden set (evals/golden_set.json) is the hand-labeled ground truth; evals.run
scores the current models against it and evals.metrics holds the pure scoring math.
See evals/README.md for how to run and the baseline table.
"""
