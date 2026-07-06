# Convenience wrappers. Local targets need `uv` installed; `up`/`down` need Docker.

.PHONY: install up down logs fmt lint test check

install:        ## Sync dependencies into a local .venv
	uv sync --all-extras --dev

up:             ## Start API + Postgres (pgvector) in Docker
	docker compose up --build

down:           ## Stop and remove containers
	docker compose down

logs:           ## Tail compose logs
	docker compose logs -f

fmt:            ## Auto-format with black
	uv run black .

lint:           ## Lint with ruff
	uv run ruff check .

test:           ## Run the test suite
	uv run pytest

check: lint test  ## Lint + test (what CI runs)
	uv run black --check .

probe:          ## Verify target-company ATS slugs are live (needs uv, or run in Docker)
	uv run python scripts/probe_ats.py --reserves --try-all
