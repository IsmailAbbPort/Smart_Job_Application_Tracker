"""Error tracking via Sentry.

`init_sentry` is a no-op unless `SENTRY_DSN` is set, so local dev and the test
suite run without a DSN and never report anything. In production the DSN is
injected via the environment (see .env.example / docker-compose), and unhandled
exceptions in the FastAPI app are captured automatically by the SDK's ASGI
integration. Called once from app/main.py before the app is created.
"""

from __future__ import annotations

import logging

from app.config import Settings

log = logging.getLogger("app.observability")


def init_sentry(settings: Settings) -> None:
    """Initialise Sentry when a DSN is configured; otherwise do nothing."""
    if not settings.sentry_dsn:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        # Errors only by default: tracing/profiling add cost and aren't needed to
        # catch crashes. Turn up sample rates here if performance data is wanted.
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    log.info("Sentry error tracking enabled (environment=%s)", settings.environment)
