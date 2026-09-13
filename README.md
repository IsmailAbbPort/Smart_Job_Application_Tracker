# Smart Job Application Tracker

An AI-assisted job hunt for a European-remote search, **built Python-first and dogfooded
during my own real search.** It ingests jobs from official APIs, scores each against my CV
with explainable, evidence-grounded matches, drafts cover letters that are checked for
fabrication before I ever see them, and tracks the pipeline end to end.

The point of the project is not "another job board." It is a small, production-shaped AI
system with the parts that usually get skipped: a **retrieve-then-rerank** matching core, an
**LLM judge that must cite its evidence**, a **fabrication guard** on generated text, and
**evals** that make all of it measurable.

> **Dogfood metrics** (jobs ingested, applications sent, interviews) will lead this README
> once they accrue from real use. Corpus today: ~5,200 live jobs across five sources.
> **Live demo:** deploying (Hetzner); until then, `docker compose up` runs the whole thing
> locally in one command.

## What it does

1. **Ingest** jobs from five official sources, normalize and de-duplicate them, and enrich
   each with geo, language, eligibility, salary, experience, seniority, and role-family
   signals. A daily scheduler keeps the corpus fresh.
2. **Retrieve** a shortlist by semantic similarity between the CV and each job (embeddings +
   pgvector), then gently re-rank for freshness and experience fit.
3. **Rerank** the shortlist with an LLM judge that returns a structured, evidence-grounded
   verdict: a 0-100 score, a tier, per-dimension sub-scores, the requirements the CV meets
   *with the CV line that proves each*, and the gaps.
4. **Draft** a cover letter grounded only in the CV, then audit it: every factual claim is
   checked against the CV, unsupported ones are rewritten out, and missing specifics become
   `[NEEDS INPUT: ...]` placeholders instead of fabrications. Human-in-the-loop: it drafts
   and audits; I edit and send.
5. **Track** each application through a pipeline (saved -> applied -> ... -> offer/rejected)
   on a kanban board.

## The AI core

**Retrieve then rerank.** Embeddings are cheap and fuzzy; the LLM judge is expensive and
precise, so it only ever runs on the shortlist.

- **Retrieve** (`app/ai/embedder.py`, `app/ai/matching.py`): OpenAI `text-embedding-3-small`
  (1536-dim) stored in **pgvector**, cosine-ranked in the database (HNSW index), then
  re-ranked by a floored recency decay and a soft over-experience penalty. Cosine clusters in
  a narrow band, so *ranking*, not the absolute score, is what matters. The retrieved pool is
  pre-cleaned with deterministic filters (seniority, role family, language, blocklists) so the
  judge spends its budget on plausible candidates.
- **Rerank** (`app/ai/judge.py`): Claude Haiku 4.5 with output forced through tool-use, so the
  verdict is always schema-valid JSON. The prompt separates *hard eligibility gates*
  (unmet spoken-language, work authorization, mandatory relocation, hard minimum years) from
  ordinary skill gaps, and caps the score when a gate is unmet. Verdicts are cached per
  (CV, job).
- **Cover letters** (`app/ai/cover_letter.py`): Claude Sonnet 4.6 drafts grounded in the CV
  (and, when a match verdict exists, built around its evidenced strengths), a second
  structured pass audits every claim against the CV, and a revise pass removes anything
  unsupported. The model is swappable via config; the fabrication audit can run on a cheaper
  model as an A/B.

The model IDs are all config-driven, so swapping providers/models is a one-line change (and
an eval A/B, not a guess).

## Evals (the part most portfolios skip)

`evals/` measures the two LLM subsystems against a **hand-labeled golden set** of real
(CV, job) pairs, so a prompt or model change is decided from data, not vibes.

- **Matcher (ranking):** precision@k, recall@k, MRR, graded nDCG - are the truly-relevant
  jobs on top?
- **Judge (classification + calibration):** per-tier precision/recall/F1, confusion matrix,
  Cohen's kappa (ordinal-weighted), and Expected Calibration Error - does a score of 80 mean
  ~80% good?
- **Cover letter:** grounding ratio (share of claims the CV supports) plus a G-Eval style
  rubric for letter *quality* (specificity, relevance, authenticity, no-cliche).

`python -m evals.run` prints the tables and writes results JSON; `--model` swaps the judge for
an A/B; a mocked subset runs in CI (deterministic fakes, no API spend) as a regression gate.
See [evals/README.md](evals/README.md) for how to run it and the baseline table.

## Fabrication guard

An unguarded model will happily invent "5 years of Kubernetes" you do not have - which is
disqualifying in a real application. Every letter is drafted from CV facts only, then a
separate structured pass extracts each factual claim and marks it supported (with the CV
evidence) or unsupported; unsupported claims are revised out. The UI surfaces the grounding
result, and nothing is sent automatically.

## EU AI Act note

Tools that "shortlist CVs, rank candidates, or score interviews" are high-risk AI systems
under the EU AI Act. This tool scores *opportunities for the job-seeker* (me), not
*candidates for an employer*, so I am the data subject and it falls outside the high-risk
hiring provisions - a distinction worth being explicit about.

## Stack

- **Backend:** FastAPI (Python 3.12), SQLAlchemy 2.0, Alembic
- **Data store:** Postgres + **pgvector** (one datastore for rows and embeddings)
- **AI:** OpenAI embeddings + Anthropic Claude (judge + cover letters), structured tool-use
- **Frontend:** Vite + React + TypeScript SPA (shortlist + kanban board, light/dark themes)
- **Ops:** Docker Compose, a daily in-process ingest scheduler, per-identity + monthly-global
  rate limits on the paid AI endpoints, optional Sentry, optional user accounts with per-user
  data scoping
- **Quality:** ruff, black, pytest (300+ tests), GitHub Actions CI (lint + test + a
  production Docker image build)

## Quick start

```bash
cp .env.example .env      # add OPENAI_API_KEY + ANTHROPIC_API_KEY for the AI features
docker compose up --build
```

- App / SPA: http://localhost:8000
- API docs: http://localhost:8000/docs
- Readiness (checks DB): http://localhost:8000/ready

```bash
# Ingest, embed, and shortlist (manual triggers; a daily scheduler does this automatically)
curl -X POST "http://localhost:8000/ingest/all?force=true"
curl -X POST "http://localhost:8000/match/embed-jobs"
curl "http://localhost:8000/match/shortlist?is_remote=true&europe=true&limit=10"
```

Cost awareness: judging one job with Haiku is a fraction of a cent; a Sonnet cover letter is
one to two cents. Dogfooding a whole search costs single-digit dollars.

## Layout

```
app/
  ai/           embedder, matcher, judge, cover-letter drafter, role-family classifier
  ingest/       source adapters, normalize/dedup, geo/language/eligibility/salary enrichment
  routers/      jobs, ingest, match, letters, applications, cv, auth, preferences, targets
  scheduler.py  daily ingest -> embed -> classify
evals/          golden set + metrics + runner + CI gate  (the differentiator)
frontend/       Vite + React + TypeScript SPA
migrations/     Alembic
docs/           research + phased build plan
tests/          pytest suite
```

See [docs/RESEARCH_AND_PLAN.md](docs/RESEARCH_AND_PLAN.md) for the full concept briefing and
build plan.

## Roadmap

- Fill the eval baseline tables from a full run; wire the judge score into the default ranking.
- Deploy the live demo.
- Keep dogfooding and report the real numbers here.
