# Smart Job Application Tracker

AI-assisted job hunt for an EU remote search: ingest jobs from official APIs,
score each against my CV with **explainable, evidence-grounded** matches, draft
cover letters that are checked for fabrication, and track the pipeline end to end.

> Built Python-first (FastAPI) and dogfooded during a real job search. This README
> will lead with dogfood metrics (jobs ingested, applications sent, interviews) once
> those exist. See [docs/RESEARCH_AND_PLAN.md](docs/RESEARCH_AND_PLAN.md) for the
> full concept briefing and phased build plan.

## Status

**Phase 0 — Skeleton & rails.** FastAPI app + Postgres/pgvector via Docker Compose,
health/readiness endpoints, pytest, and CI (ruff + black + pytest). No job data or
AI yet — those land in Phases 1-7.

## Stack

- **Backend:** FastAPI (Python 3.12), SQLAlchemy 2.0
- **Data store:** Postgres + pgvector (one datastore for rows *and* embeddings)
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

### Local dev (needs uv + Python 3.12)

```bash
uv sync --all-extras --dev
uv run uvicorn app.main:app --reload
uv run pytest        # or: make test
```

## Layout

```
app/            FastAPI app (config, db, main)
tests/          pytest suite
docs/           research/plan/primer (committed — part of the story)
docker-compose.yml   API + Postgres(pgvector)
Dockerfile           uv-based API image
.github/workflows/   CI
```
