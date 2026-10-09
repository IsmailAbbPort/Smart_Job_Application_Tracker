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
| `curate.py` | Builds a fresh draft golden set by sampling the live corpus, and merges labels. `--add-pairs N` appends from the filtered shortlist; `--refresh-descriptions` re-reads snapshots at the current char cap. |

## Metrics

- **Matcher (ranking):** precision@k, recall@k, MRR, nDCG (graded: strong=2, medium=1,
  weak=0). Computed over the labeled pool, so it measures ordering, not full-corpus recall.
- **Pre-filter (deterministic eligibility):** how many pairs the free language and
  work-country gate removes, split by label. `excluded_relevant` must stay 0 and is
  asserted in CI, since a wrong exclusion hides a job the user should have seen.
- **Judge (classification + calibration):** per-tier precision/recall/F1, confusion
  matrix, accuracy, Cohen's kappa (plain and quadratic-weighted, since tiers are
  ordinal), AUROC of the 0-100 score against relevance, and Expected Calibration Error.
  AUROC is the one to read: the score is a weighted requirement ratio, not a probability,
  so ECE partly measures its scale, while AUROC only measures the ordering.
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

`status` is `draft` until the labels have been reviewed, then `reviewed`. The current set is
`reviewed`: every pair was labelled against the full posting and then re-reviewed pair by
pair by a second model under rules its owner confirmed, which is recorded in the file's
`notes` along with what that review was not (line-by-line human sign-off). Treat a single
pair's tier as reviewed judgement rather than certain ground truth, and expect the odd label
to be wrong: two were, and finding them moved the metrics more than any model change has
(see "Labels reviewed" below).

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

### Facts v4: the whole posting, and AUROC instead of ECE (2026-10-03)

Two input bugs, found by auditing rather than by a metric moving. 22 of the 63 pairs were
snapshotted at exactly 6000 chars, three of the four strong ones among them, so the
eligibility paragraph that decides them was never in the prompt (GitLab's "Country Hiring
Guidelines" starts at char 6004). And the constraint filter matched anywhere in a line, so
it threw away real requirements that merely mentioned a constraint word ("Go language
proficiency", "mentorship and horizontal sponsorship"), including the seniority asks ("12+
years in software/ML engineering"), which raised the score on exactly the senior roles the
rules exclude. Both caps now sit past the corpus p99 (about 12k chars), a line is dropped
only when nothing but filler is left once the constraint phrase is removed, and
`--refresh-descriptions` recovered 20 of the 22 truncated snapshots (the other 9 pairs'
jobs have left the corpus and keep the text they have).

Three samples, so this is a range rather than a point. The headline is that the v3 to v4
gain sits **inside** run-to-run noise on 8 non-weak pairs: sample 1 lands exactly on the v3
point estimate. The fixes are still right (the model genuinely could not read the
eligibility text, and the regex genuinely ate real requirements), but three samples cannot
show it.

| Judge (63 pairs, facts v4) | Accuracy | Macro F1 | QWK | AC1 | Strong recall | Strong precision | AUROC |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Facts v3 (one run) | 0.889 | 0.633 | 0.639 | 0.874 | 2/4 | 0.50 | - |
| Facts v4, 3 samples | 0.889-0.921 | 0.633-0.702 | 0.639-0.701 | 0.874-0.912 | 2/4 | 0.50-0.667 | 0.926-0.945 |

**AUROC is now the headline instead of ECE.** ECE asks whether `overall_score / 100` is a
truthful probability, which it was never built to be: it is a weighted requirement ratio, so
a poor ECE can mean nothing more than a mis-scaled score. AUROC asks the question the score
is actually used for, whether the ordering is right, and it is unchanged by any monotonic
rescaling. ECE stays in the results JSON.

### 30 more pairs, and what they showed (2026-10-03)

The set was sampled over the whole corpus, so only 8 of 63 pairs were a real fit and every
strong/medium number rested on a handful. `--add-pairs` draws from the pool the shortlist
actually shows (remote, not senior, engineering or data/ML), after dropping reposts of one
role and capping any single company. 30 pairs, each labelled by hand against the full
posting: **6 strong / 4 medium / 83 weak**, 93 total.

The yield is the finding. 28 of the 30 are a bad fit, and not for subtle reasons: 9 require
German at B2 to C2, 6 are scoped to a country with no work rights, 8 ask for Senior/Staff or
5 to 12 years, 5 are infrastructure disciplines. That is a product problem, not a judge
problem, and it is what the pre-filter below addresses.

| Judge (93 pairs, facts v4, 3 samples) | Accuracy | Macro F1 | QWK | AC1 | Strong recall | Strong precision | AUROC |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Facts v4 | 0.892-0.914 | 0.622-0.690 | 0.668-0.724 | 0.878-0.904 | 3-4 / 6 | 0.667-0.750 | 0.935-0.946 |

Accuracy is not comparable to the 63-pair rows: weak is now 89% of the set, so accuracy
inflates mechanically. AUROC barely moved (0.926-0.945 to 0.935-0.946), which is the point
of reporting it.

### Pre-filter: eligibility without a model call (2026-10-09)

The 93-pair labelling showed that most of the noise is decidable from the text for free, so
a required spoken language and a stated hiring country are now checked before the judge
runs, in `app/shortlist.py::eligibility_block`. The `prefilter` stage scores it offline.

| Pre-filter (93 pairs) | Excluded | Of which weak | Wrongly excluded |
| --- | --- | --- | --- |
| language + work country | 51 | 51 (61% of all weak pairs) | **0** |

61% of the noise removed, nothing good hidden, and 51 fewer paid judge calls per run.
`excluded_relevant` is asserted to be 0 in `tests/test_evals.py`: the gate hides jobs, so a
false exclusion is a job the user never sees, and any future pattern that hides a strong or
medium pair fails CI. That is why the country rule is deliberately incomplete: a remote role
listed in a European country outside the user's rights is kept, because European boards
routinely name one office country for a role open EU-wide (every UK-located pair labelled
strong or medium in this set is like that). The judge still reads the full text.

### Labels reviewed, and the judge was right where I was wrong (2026-10-09)

Every one of the 93 labels was re-reviewed pair by pair by a second model under the same
rules, told to disagree rather than ratify. It changed two tiers, and both were mine:

- **j8715** (GitLab EMEA, UK) strong -> **weak**. This label had been flipped to strong from
  the live posting, which asks "Are you located in the UK or Poland?". The ingested snapshot
  contains neither "Poland" nor "United Kingdom" in 7454 chars: the only country signal is
  the `location` field, `Remote, United Kingdom`. **A label has to be derivable from the
  snapshot the judge reads**, or the eval is scoring the judge against facts it cannot see.
  Its Poland-scoped twin j8714 carries that case properly.
- **j8438** (Lucid Labs) strong -> **medium**. "Remote, but not anonymous. Our team works
  mostly out of Berlin, with a team day every Wednesday" is hybrid in practice, and two
  requirements the posting marks Important (working eval-driven, having built agent systems
  with tool calling and human-in-the-loop) are absent from the CV.

Also rewritten: two rationales that reached the right tier by the wrong route (j6817 called a
posting on-site that states neither, j2723 blamed a Paris location when "Senior" is the
actual dealbreaker), and seven that quoted the structured `location` field as though it were
description text, which reads as fabricated evidence to anyone checking.

Set is now **4 strong / 5 medium / 84 weak**, `status: reviewed`.

| Judge (93 pairs, facts v4, 3 samples) | Accuracy | Macro F1 | QWK | AC1 | Strong recall | Strong precision | AUROC |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Draft labels | 0.892-0.914 | 0.622-0.690 | 0.668-0.724 | 0.878-0.904 | 3-4 / 6 | 0.667-0.750 | 0.935-0.946 |
| **Reviewed labels** | **0.914-0.925** | **0.714-0.740** | **0.768-0.806** | **0.903-0.916** | **3-4 / 4** | **0.667-0.750** | **0.974-0.984** |

Read that honestly: **the model did not change between those two rows.** Every number moved
because the ground truth got more correct, and the two labels that were wrong were exactly
the two the judge was being marked down on. The judge had been right about both. That makes
label review, not prompt or rule tuning, the highest-leverage work left on this eval, and it
is the single clearest result in this file.

The remaining weakness is unchanged and now slightly sharper: with 4 strong and 5 medium out
of 93, a judge that answered "weak" to everything would score about 90% accuracy. That is
why AUROC leads these tables, and why growing the positive side matters more than any
further tuning.

### Cover letter (grounding)

| Draft prompt | Mean grounded ratio | % with unsupported |
| --- | --- | --- |
| v1 (cliches forbidden) | 0.993 | 12.5% (1 of 8 letters) |
| **v2 (structure required)** | **1.000** | **0%** |

### Cover letter (quality rubric, 0-100)

The v1 prompt listed phrases to avoid and the letters stayed generic. Naming the forbidden
phrases puts them in the context and makes them likelier, and no prohibition adds
specificity, which is what the rubric was scoring lowest. v2 asks for a shape instead: a
hook only a reader of this posting could write, then one paragraph per requirement bridged
to a named CV project and the outcome it records, plus examples of the target register. Same
8 pairs, same grader, so the prompt is the only thing that differs.

| Draft prompt | Overall | Specificity | Relevance | Authenticity | No-cliche |
| --- | --- | --- | --- | --- | --- |
| v1 (cliches forbidden) | 68.6 | 70.2 | 70.4 | 78.1 | 80.8 |
| **v2 (structure required)** | **82.1** | **79.8** | **84.0** | **83.2** | **84.2** |

Grounding improved alongside quality, so the specificity did not come at the cost of
faithfulness. `LETTER_PROMPT_VERSION` keys the letter cache, because without it a prompt
change silently scores letters cached from the old prompt.

## CI gate

`tests/test_evals.py` unit-tests every metric and runs the real `run_eval` pipeline with
the Fake providers over a tiny crafted set, asserting the deterministic metrics stay
above threshold. It runs in the normal `pytest` job, so a regression in the harness (or
the fakes) fails CI without spending any API budget. Full real-API runs stay manual.
