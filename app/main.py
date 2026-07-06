"""FastAPI entrypoint.

Phase 0 exposes only liveness (`/health`) and readiness (`/ready`) endpoints.
Feature routers (jobs, match, letters, applications) are mounted in later phases.
"""

from fastapi import FastAPI

from app import __version__
from app.config import get_settings
from app.db import ping
from app.routers import ingest, jobs

settings = get_settings()

app = FastAPI(title=settings.app_name, version=__version__)

app.include_router(jobs.router)
app.include_router(ingest.router)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Liveness: the process is up. Does not touch the database."""
    return {"status": "ok", "version": __version__}


@app.get("/ready", tags=["ops"])
def ready() -> dict[str, str | bool]:
    """Readiness: the app can reach its dependencies (Postgres)."""
    db_ok = ping()
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}
