# Convenience wrappers. Local targets need `uv` installed; `up`/`down` need Docker.

.PHONY: install up down logs fmt lint test check fe-install fe-dev fe-build

install:        ## Sync dependencies into a local .venv
	uv sync --all-extras --dev

fe-install:     ## Install frontend (Vite/React) dependencies
	cd frontend && npm install

fe-dev:         ## Run the Vite dev server (proxies API paths to :8000)
	cd frontend && npm run dev

fe-build:       ## Build the React app into app/static (what the API serves)
	cd frontend && npm run build

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
