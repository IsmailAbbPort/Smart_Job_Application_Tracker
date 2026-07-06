# Smart Job Application Tracker

AI-assisted job hunt for an EU remote search: ingest jobs from official APIs,
score each against my CV with **explainable, evidence-grounded** matches, draft
cover letters that are checked for fabrication, and track the pipeline end to end.

> Built Python-first (FastAPI) and dogfooded during a real job search. This README
> will lead with dogfood metrics (jobs ingested, applications sent, interviews) once
> those exist. See [docs/RESEARCH_AND_PLAN.md](docs/RESEARCH_AND_PLAN.md) for the
> full concept briefing and phased build plan.

## Status

**Phase 1 - Ingest & normalize (done).** Job data flows from five sources into
Postgres, deduped and served by a `/jobs` API. No AI yet (Phases 2-7).

- **Sources:** Arbeitnow (EU backbone) + Remotive (remote-only), plus direct ATS
  monitoring of ~30 verified target companies across Greenhouse / Lever / Ashby.
- **Ingest:** `POST /ingest/{source}` (or `all`), manual-trigger first, with a
  per-source TTL throttle so rate-limited feeds (Remotive) are polled politely.
- **Dedup:** `(source, source_id)` for re-poll idempotency + a normalized
  `(company, title, location)` key for cross-source dedup.
- **Read:** `GET /jobs` with source / remote / **europe** / country / city / company /
  text filters + pagination. Every job gets a best-effort canonical `city` +
  `country` + `is_european` derived from its raw location (so "Munich", "München"
  and "Munich, Germany" all collapse to one place, which also tightens cross-source
  dedup). `?is_remote=true&europe=true` gives the actual EU-remote search scope
  (US/Worldwide-remote roles are stored but filtered out).
- **Adjustable targets:** monitored companies live in a `target_company` table
  (seeded from YAML), editable at runtime via `/targets` (list/add/toggle/delete).
- Verified end to end: `docker compose up` -> Alembic migrates + seeds -> ingested
  ~3,900 real jobs (582 remote-European). 78 tests green.

Phase 0 (skeleton & rails: FastAPI, Docker Compose, CI, health endpoints) is also complete.

## Stack

- **Backend:** FastAPI (Python 3.12), SQLAlchemy 2.0, Alembic migrations
- **Data store:** Postgres + pgvector (one datastore for rows and embeddings)
- **Ingest:** httpx source adapters + normalizer/dedup, per-source throttle
- **Packaging:** uv
- **Quality:** ruff (lint), black (format), pytest, GitHub Actions CI

## Quick start

### Run everything in Docker (recommended)

```bash
cp .env.example .env      # defaults work for local dev
docker compose up --build
```

Then:

- Liveness: http://localhost:8000/health
- Readiness (checks DB): http://localhost:8000/ready
- API docs: http://localhost:8000/docs

### Ingest and browse jobs

```bash
# Pull one source (or 'all'). Manual trigger; add ?force=true to bypass the throttle.
curl -X POST "http://localhost:8000/ingest/arbeitnow?force=true"
curl -X POST "http://localhost:8000/ingest/remotive?force=true"

# Browse the deduped feed. Filters: source, is_remote, europe, country, company, q.
curl "http://localhost:8000/jobs?is_remote=true&europe=true&q=engineer&limit=10"

# Manage which company ATS boards are monitored (backs a future UI).
curl "http://localhost:8000/targets?ats=greenhouse"
```

Verify target-company ATS slugs are live before ingesting: `make probe`.

### Local dev (needs uv + Python 3.12)

```bash
uv sync --all-extras --dev
uv run uvicorn app.main:app --reload
uv run pytest        # or: make test
```

## Layout

```
app/
  ingest/       source adapters, normalizer/dedup, throttle, target_companies.yaml
  routers/      /jobs and /ingest endpoints
  models.py     Job + SourceFetch ORM
  config.py db.py main.py schemas.py
migrations/     Alembic (schema versioning)
scripts/        probe_ats.py (verify ATS slugs)
tests/          pytest suite (normalize, adapters, runner/dedup, cache, routes)
docs/           research + build plan (committed, part of the story)
docker-compose.yml   API + Postgres(pgvector)
Dockerfile           uv-based API image
.github/workflows/   CI
```
