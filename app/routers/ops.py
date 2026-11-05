"""Ops endpoints for the local runtime: run history and a notifier smoke test.

Both exist because the pipeline runs in the background: without them "did it run"
and "do the Telegram credentials work" are answered by reading container logs or by
waiting a day.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import PipelineRun
from app.notify import telegram

router = APIRouter(prefix="/ops", tags=["ops"])

_TEST_MESSAGE = "Job Tracker test message. Notifications are configured correctly."


@router.get("/runs")
def list_runs(
    session: Session = Depends(get_session),
    limit: int = Query(default=10, ge=1, le=100, description="Most recent runs to return"),
) -> dict:
    """The most recent pipeline runs, newest first."""
    rows = session.scalars(
        select(PipelineRun)
        .order_by(PipelineRun.started_at.desc(), PipelineRun.id.desc())
        .limit(limit)
    ).all()
    return {
        "runs": [
            {
                "id": r.id,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "trigger": r.trigger,
                "status": r.status,
                "inserted": r.inserted,
                "updated": r.updated,
                "removed_stale": r.removed_stale,
                "embedded": r.embedded,
                "classified": r.classified,
                "problems": r.problems,
                "error": r.error,
                "notified_at": r.notified_at,
            }
            for r in rows
        ]
    }


@router.post("/notify-test")
def notify_test(settings: Settings = Depends(get_settings)) -> dict:
    """Send a fixed test message, so the token and chat id are verified in one call."""
    if not telegram.notifications_configured(settings):
        raise HTTPException(
            status_code=503,
            detail="Telegram is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.",
        )
    return {"configured": True, "sent": telegram.send_message(_TEST_MESSAGE, settings=settings)}
