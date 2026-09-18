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

> **Current status: `reviewed`.** Labels for CV id 1, curated 2026-08-22 and signed off
> by hand. They lean heavily "weak" on purpose: the junior EU-remote pool really is
> dominated by senior / sales / non-English roles, and cosine surfaces several of them in
> its top 18 (that is the retrieve stage's known weakness).

## Baseline

First real run: 2026-09-15, CV 1, 41 pairs (8 relevant), golden set `reviewed`. Judge
baseline claude-haiku-4-5, letters drafted by claude-sonnet-4-6. Raw output is in
`evals/results/` (gitignored).

### Matcher (retrieve / ranking)

| Metric | @1 | @3 | @5 | @10 |
| --- | --- | --- | --- | --- |
| Precision@k | 0.000 | 0.667 | 0.600 | 0.300 |
| Recall@k | 0.000 | 0.250 | 0.375 | 0.375 |
| nDCG@k | 0.000 | 0.531 | 0.530 | 0.430 |
| MRR | 0.500 | | | |

### Judge (rerank / classification + calibration)

| Model | Accuracy | Macro F1 | Kappa (quad) | ECE |
| --- | --- | --- | --- | --- |
| claude-haiku-4-5 (baseline) | 0.707 | 0.293 | 0.140 (0.319) | 0.111 |
| claude-sonnet-4-6 (A/B) | 0.805 | 0.310 | 0.221 (0.369) | 0.169 |

Kappa column is plain (quadratic-weighted). The judge runs with strict tool use
(`strict: true`): without it, Sonnet returned `dimension_scores` as malformed JSON text on
pair `j4233` and crashed the run. The Haiku row was measured before strict mode was on.

Haiku confusion matrix (rows = true, cols = predicted):

| | strong | medium | weak |
| --- | --- | --- | --- |
| strong | 0 | 4 | 2 |
| medium | 0 | 0 | 2 |
| weak | 1 | 3 | 29 |

Sonnet confusion matrix:

| | strong | medium | weak |
| --- | --- | --- | --- |
| strong | 0 | 3 | 3 |
| medium | 0 | 0 | 2 |
| weak | 0 | 0 | 33 |

Accuracy is inflated by the weak-heavy set (33 of 41). Neither model ever predicts `strong`
for a truly strong pair and both under-rate every good fit, which is what the low macro F1
and kappa reflect. Sonnet is stricter still: perfect on weak pairs, but half of the strong
pairs fall to weak. A bigger model does not fix it, so the rubric/prompt is the lever.

### Judge v2: the model extracts facts, code grades them (2026-09-15)

The judge now returns only facts (each requirement as must-have/nice-to-have and
met/partial/absent with CV evidence, plus posting constraints); `app/ai/decide.py` applies
the candidate's rules to compute dealbreakers, score and tier. The golden set was relabeled
(v2, 63 pairs: 4 strong, 5 medium, 54 weak) under the same written rules with
`remote_only: true`, and split into tune (42) and held-out test (21). **Labels are
AI-drafted from the full postings and not yet human-reviewed.** The old judge's cached
verdicts were rescored against the same v2 labels, so all rows use identical ground truth.
Model: claude-haiku-4-5, one run each.

| Judge (all 63) | Accuracy | Macro F1 | QWK | AC1 | Strong recall | Strong precision |
| --- | --- | --- | --- | --- | --- | --- |
| Old (model picks tier) | 0.714 | 0.353 | 0.429 | 0.653 | 0/4 | - |
| Old + remote filter applied after | 0.841 | 0.413 | 0.661 | 0.817 | 0/4 | - |
| **v2 facts + rules** | **0.889** | **0.741** | **0.687** | **0.869** | **3/4** | **3/5** |

Held-out test split (21 pairs, only 1 strong and 2 medium, so treat as a sanity check):
old 0.667 acc / 0.354 macro F1; old + remote filter 0.857 / 0.448; v2 0.857 / 0.694.

v2 errors (7 of 63), by cause:
- **Work authorization read as "yes" for non-EU roles** (3): New York, Canada-only and
  US/Canada-only postings. The biggest fixable error class.
- **Work mode "unknown" for office postings with no remote statement** (2 of the same
  jobs, plus Mistral Paris), so the remote-only rule never fired; Mistral Paris was also
  read as junior although the text says "Senior Frontend Engineer".
- **Borderline must-have ratios** (3): Lucid Labs (label strong, v2 medium), Synthesia data
  (label weak, v2 medium), Qonto Milan (label medium, v2 weak; its twin posting j8340 got the
  same label and a correct prediction, so this is partly label noise).

**Facts v2 (same day):** the model now lists the countries a role can be done from and the
candidate's work rights, and code intersects them with the EU/EEA; when the posting's work
mode is unknown, the job's ingested remote flag decides for remote-only users; the prompt
names text-stated seniority. Re-extracted all 63 pairs (cache key `facts-v2`).

| Judge (all 63) | Accuracy | Macro F1 | QWK | AC1 | Strong recall | Strong precision |
| --- | --- | --- | --- | --- | --- | --- |
| Facts v1 + rules | 0.889 | 0.741 | 0.687 | 0.869 | 3/4 | 3/5 |
| Facts v2 + rules | 0.905 | 0.636 | 0.675 | 0.892 | 1/4 | 1/1 |

Every location/eligibility error from v1 is fixed (weak pairs: 53/54 correct, no false
strong). Strong recall fell because of two things the fix did not touch:
- **Requirement granularity varies between runs.** Dataiku (strong in v1) came back with 21
  "must-haves", most of them the team's product areas rather than candidate requirements, so
  the met ratio dropped to medium. The same posting can score strong or medium depending on
  how the model splits it: the ratio rule is sensitive to extraction noise.
- **Constraint-like items still listed as requirements** (Lucid Labs: "3+ years", "can work in
  Germany") despite the prompt, counting as absent must-haves.
- GitLab "Intermediate Backend Engineer, EMEA" is listed as "Remote, United Kingdom", so the
  country rule made it a dealbreaker; the label read the title's EMEA. A label question.

With 4 strong pairs, 3/4 vs 1/4 is within noise; the next step is making the score robust to
how requirements are split, then measuring run-to-run variance.

### Labels reviewed, and facts v3: core requirements (2026-09-18)

The nine non-weak labels were reviewed by hand against the full postings. Two changed:
Synthesia "ML Platform Engineer" medium -> weak (a Kubernetes/cloud-infrastructure platform
role whose core requirements are mostly absent, not one gap), and GitLab "Intermediate
Backend Engineer, EMEA" strong -> weak (the only location the text states is the United
Kingdom; the title's EMEA is not backed by any country list, and labelling from the stated
country is what the judge can actually read). The set is now 3 strong / 4 medium / 56 weak,
with those nine marked `reviewed`; the 54 weak labels are still AI-drafted, so `status`
stays `draft`. Rescoring facts v2 against the corrected labels: 0.905 acc, 0.621 macro F1,
**0.744 QWK** (was 0.675), 0.894 AC1, strong 1/3 at precision 1.00.

Facts v3 then addressed the extraction-noise problem above: the model marks the 3 to 6
requirements the role is really about (`core`), the tier is graded on those, and code drops
requirements that are really constraints ("3+ years", "can legally work in Germany") before
scoring, since they are already graded as constraints.

Measured on the 56 pairs that have both v2 and v3 facts (the v3 pass stopped at 56 when the
API credit ran out, so this is a subset: 3 strong, 1 medium, 52 weak, and not comparable to
the full-set rows above).

| Judge (56 pairs) | Accuracy | Macro F1 | QWK | AC1 | Strong recall | Strong precision |
| --- | --- | --- | --- | --- | --- | --- |
| Facts v2, graded as before | 0.929 | 0.494 | 0.787 | 0.923 | 1/3 | 1.00 |
| Facts v2 + the constraint filter | 0.929 | 0.494 | 0.787 | 0.923 | 1/3 | 1.00 |
| **Facts v3 + core requirements** | **0.946** | **0.594** | **0.860** | **0.943** | **2/3** | **1.00** |

Exactly one prediction moved, and it is the one the fix was aimed at: Dataiku, whose 21
product-area "must-haves" dragged it to medium in v2, is strong in v3 (19 requirements, 6
core). The constraint filter alone changed no prediction on this set; it earns its place by
removing a penalty that was double-counted, not by moving numbers today. Requirements per
posting: v2 mean 15.5 (max 43), v3 mean 15.4 (max 30), of which core mean 7.9 (max 21), so
the model still over-marks core on the longest postings.

Still open: the last 7 pairs, and the 2-3 repeat runs that would show whether strong vs
medium holds steady (use `--sample N`, which caches each run separately). Remaining misses
are Lucid Labs (label strong, v3 medium: 4 of its 8 core requirements come back `partial`),
Synthesia (label weak, v3 medium, the borderline relabel above), and ElevenLabs, where the
model read the London location as a country restriction although the text says "we
prioritize your talent, not your location".

### Cover letter (grounding)

| Model | Mean grounded ratio | % with unsupported |
| --- | --- | --- |
| claude-sonnet-4-6 | 0.993 | 12.5% (1 of 8 letters) |

### Cover letter (quality rubric, 0-100)

| Draft model | Overall | Specificity | Relevance | Authenticity | No-cliche |
| --- | --- | --- | --- | --- | --- |
| claude-sonnet-4-6 | 68.6 | 70.2 | 70.4 | 78.1 | 80.8 |

## CI gate

`tests/test_evals.py` unit-tests every metric and runs the real `run_eval` pipeline with
the Fake providers over a tiny crafted set, asserting the deterministic metrics stay
above threshold. It runs in the normal `pytest` job, so a regression in the harness (or
the fakes) fails CI without spending any API budget. Full real-API runs stay manual.
