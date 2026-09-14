"""FastAPI entrypoint.

Phase 0 exposes only liveness (`/health`) and readiness (`/ready`) endpoints.
Feature routers (jobs, match, letters, applications) are mounted in later phases.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import get_settings
from app.db import ping
from app.observability import init_sentry
from app.routers import (
    applications,
    auth,
    cv,
    ingest,
    jobs,
    letters,
    match,
    preferences,
    targets,
    views,
)
from app.scheduler import start_scheduler, stop_scheduler

settings = get_settings()

# Error tracking. No-op unless SENTRY_DSN is set, so local/tests are unaffected.
init_sentry(settings)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the daily ingest scheduler on boot; stop it on shutdown."""
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)

app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(ingest.router)
app.include_router(targets.router)
app.include_router(cv.router)
app.include_router(match.router)
app.include_router(preferences.router)
app.include_router(applications.router)
app.include_router(letters.router)
app.include_router(views.router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def ui() -> FileResponse:
    """Serve the shortlist viewer (single-page frontend).

    no-cache so the browser always revalidates the SPA; otherwise a cached page
    keeps showing old markup/JS after a redeploy.
    """
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Liveness: the process is up. Does not touch the database."""
    return {"status": "ok", "version": __version__}


@app.get("/ready", tags=["ops"])
def ready() -> dict[str, str | bool]:
    """Readiness: the app can reach its dependencies (Postgres)."""
    db_ok = ping()
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}
