# syntax=docker/dockerfile:1

# --- Stage 1: build the React (Vite) frontend into app/static ---
FROM node:22-slim AS frontend
WORKDIR /fe
# Install deps first (cached layer) from the lockfile only.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
# Then the source; `npm run build` emits to ../app/static (see vite.config.ts),
# i.e. /app/static inside this stage.
COPY frontend/ ./
RUN npm run build

# --- Stage 2: the Python API, serving the built frontend ---
FROM python:3.12-slim

# uv: fast, reproducible installs from pyproject.toml + uv.lock.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first (cached layer) using only the lock + manifest.
# --frozen: use uv.lock exactly; fail if it's missing or out of date (reproducible builds).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Then the app code + migrations.
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

# Overlay the built frontend (index.html + assets) from the Node stage so the
# image never ships stale or locally-built static files.
COPY --from=frontend /app/static ./app/static

# Put the project's venv on PATH.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
