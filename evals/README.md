# Evals: measuring the two LLM subsystems

The app trusts two LLM subsystems that are otherwise judged "by feel". This harness
makes their quality measurable against a hand-labeled golden set, so a prompt or model
change is decided from data, not vibes.

- **Matcher** (retrieve stage, `app/ai/matching.py` + `app/ai/embedder.py`): embeds the
  CV and each job and cosine-ranks them. Question: *are the truly-relevant jobs on top?*
- **Judge** (rerank stage, `app/ai/judge.py`): Claude scores one (CV, job) pair into a
  tier + 0-100 score. Questions: *does it classify fit correctly, and is a score of 80
  worth ~80%?*
- **Cover letter** (`app/ai/cover_letter.py`): drafts a CV-grounded letter. Question:
  *how much of what it writes is actually supported by the CV?*

## Layout

| File | What it is |
| --- | --- |
| `golden_set.json` | The hand-labeled ground truth: (CV, job) pairs, each with a tier (strong/medium/weak). Committed. |
| `metrics.py` | Pure scoring math (ranking, classification, calibration). No I/O; unit-tested in `tests/test_evals.py`. |
| `run.py` | The runner. Loads the golden set, runs the stages, prints a table, writes results JSON. |
| `curate.py` | Builds a fresh draft golden set by sampling the live corpus, and merges labels. |

## Metrics

- **Matcher (ranking):** precision@k, recall@k, MRR, nDCG (graded: strong=2, medium=1,
  weak=0). Computed over the labeled pool, so it measures ordering, not full-corpus recall.
- **Judge (classification + calibration):** per-tier precision/recall/F1, confusion
  matrix, accuracy, Cohen's kappa (plain and quadratic-weighted, since tiers are
  ordinal), and Expected Calibration Error over the 0-100 score.
- **Cover letter (grounding):** mean `grounded_ratio` and the share of letters with any
  unsupported claim.
- **Cover letter (quality):** a G-Eval style LLM-judge rubric (`evals/quality.py`) scoring
  each letter 0-100 on specificity, relevance, authenticity, no-cliche, and overall.
  Grounding says the letter is *true*; this says whether it is any *good*. Skip it with
  `--no-quality`; swap the grader with `--quality-model`.

## Running it

Host Python is WDAC-blocked, so run inside Docker against the compose Postgres (only
`curate.py` needs the DB; `run.py` is self-contained from the JSON). Bring the DB up
with `docker compose up -d db` first if you plan to re-curate.

```sh
# Offline smoke test (deterministic fakes, no network, no cost):
docker run --rm -e UV_PROJECT_ENVIRONMENT=/opt/venv \
  -v "$PWD:/src" -w /src ghcr.io/astral-sh/uv:python3.12-bookworm-slim \
  sh -c "uv sync --frozen -q && uv run --no-sync python -m evals.run --offline"

# Real baseline (reads OPENAI_API_KEY + ANTHROPIC_API_KEY from .env). Add --network
# and DATABASE_URL only if a stage needs the DB (it does not; run.py is self-contained):
docker run --rm --env-file .env -e UV_PROJECT_ENVIRONMENT=/opt/venv \
  -v "$PWD:/src" -w /src ghcr.io/astral-sh/uv:python3.12-bookworm-slim \
  sh -c "uv sync --frozen -q && uv run --no-sync python -m evals.run"

# A/B the judge model (this is the point: model decisions from data):
#   ... python -m evals.run --model claude-sonnet-4-6
#   ... python -m evals.run --model claude-opus-4-8
```

Judge and letter verdicts are cached per (model, cv, pair) under `evals/.cache/`, so
re-runs and A/Bs do not re-spend. Pass `--refresh` to recompute. Useful flags:
`--stages matcher,judge`, `--no-letters`, `--k 1,3,5,10`, `--letter-limit N`, `--cv 1`,
`--out path.json`.

**Cost:** the runner calls the AI modules directly and bypasses the app's rate limiter.
On this ~40-pair set a full judge pass is Haiku x40 (fractions of a cent each) and the
letter pass is Sonnet x2-per-letter (~1-2 cents each). A whole run is well under a dollar;
keep the golden set small and lean on the cache.

## The golden set

Labels are the ground truth everything is measured against, so they are hand-made.

1. `python -m evals.curate --cv 1` samples a diverse, deliberately non-trivial set from
   the live corpus (head of the shortlist, a mid band, the tail, a random spread, and
   high-cosine off-target titles as hard negatives) and writes a template with
   `label_tier: null`, plus a compact summary to label from.
2. Fill each tier (a `{pair_id: {tier, rationale}}` map), then
   `python -m evals.curate --apply-labels <labels>.json` merges and validates them.

`status` is `draft` until a human signs off, then flip it to `reviewed`.

**CV text is not committed.** The committed `golden_set.json` stores a placeholder for each
CV; the real CV text lives in `evals/cvs.local.json` (gitignored). `curate.py` writes it there
automatically, and `load_golden_set` merges it back in when present. A real eval run needs that
file (regenerate with `python -m evals.curate`); CI runs against the placeholder, which is fine
because the fakes ignore CV content. To migrate an already-built set, run
`python -m evals.curate --externalize-cvs`.

> **Current status: `draft`.** The committed labels are a first-pass draft (see each
> pair's `rationale`) for CV id 1, curated 2026-08-22. They lean heavily "weak" on
> purpose: the junior EU-remote pool really is dominated by senior / sales / non-English
> roles, and cosine surfaces several of them in its top 18 (that is the retrieve stage's
> known weakness). Review and correct the tiers, then set `status: reviewed`.

## Baseline

Fill this from a real run (`python -m evals.run`, then `--model ...` for the A/B).
Numbers below are placeholders until the paid run is done.

### Matcher (retrieve / ranking)

| Metric | @1 | @3 | @5 | @10 |
| --- | --- | --- | --- | --- |
| Precision@k | _ | _ | _ | _ |
| Recall@k | _ | _ | _ | _ |
| nDCG@k | _ | _ | _ | _ |
| MRR | _ | | | |

### Judge (rerank / classification + calibration)

| Model | Accuracy | Macro F1 | Kappa (quad) | ECE |
| --- | --- | --- | --- | --- |
| claude-haiku-4-5 (baseline) | _ | _ | _ | _ |
| claude-sonnet-4-6 (A/B) | _ | _ | _ | _ |

### Cover letter (grounding)

| Model | Mean grounded ratio | % with unsupported |
| --- | --- | --- |
| claude-sonnet-4-6 | _ | _ |

### Cover letter (quality rubric, 0-100)

| Draft model | Overall | Specificity | Relevance | Authenticity | No-cliche |
| --- | --- | --- | --- | --- | --- |
| claude-sonnet-4-6 | _ | _ | _ | _ | _ |

## CI gate

`tests/test_evals.py` unit-tests every metric and runs the real `run_eval` pipeline with
the Fake providers over a tiny crafted set, asserting the deterministic metrics stay
above threshold. It runs in the normal `pytest` job, so a regression in the harness (or
the fakes) fails CI without spending any API budget. Full real-API runs stay manual.
