# syntax=docker/dockerfile:1

FROM python:3.12-slim

# uv: fast, reproducible installs from pyproject.toml + uv.lock.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first (cached layer) using only the lock + manifest.
# Once you run `uv lock` and commit uv.lock, add `--frozen` here for reproducible builds.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-install-project --no-dev

# Then the app code.
COPY app ./app

# Put the project's venv on PATH.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
