"""Telegram notifier: one message per run, only when there is something to say.

Split in two on purpose. `format_run_message` is pure (a run row in, a string or
None out) so every wording and silence rule is a unit test; `send_message` is the
only part that touches the network and it never raises, because a Telegram outage
must not cost a night's ingest.

Plain text, no `parse_mode`: a job title with an underscore, asterisk or bracket
would otherwise break the send. Times are Africa/Cairo (the laptop's timezone),
since a UTC timestamp on a phone is a small puzzle every single day.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select

from app.config import Settings, get_settings
from app.notify.problems import recovered_label

log = logging.getLogger("app.notify.telegram")

LOCAL_TZ = ZoneInfo("Africa/Cairo")
_API = "https://api.telegram.org"
_TIMEOUT = 10.0
_MAX_ERROR_CHARS = 200

INTERRUPTED_LINE = (
    "Previous run was interrupted (laptop sleep or container restart). Catching up now."
)


def notifications_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def send_message(text: str, *, settings: Settings | None = None) -> bool:
    """Post one message. Returns whether it was delivered; never raises."""
    settings = settings or get_settings()
    if not notifications_configured(settings):
        log.debug("telegram not configured; message dropped")
        return False
    url = f"{_API}/bot{settings.telegram_bot_token}/sendMessage"
    try:
        resp = httpx.post(
            url,
            json={
                "chat_id": settings.telegram_chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=_TIMEOUT,
        )
    except Exception:  # noqa: BLE001 - an unreachable bot API is not our failure
        log.warning("telegram send failed (network)", exc_info=True)
        return False
    if resp.status_code != 200:
        log.warning("telegram send failed: HTTP %s %s", resp.status_code, resp.text[:200])
        return False
    return True


def _local(moment: datetime) -> datetime:
    if moment.tzinfo is None:  # SQLite hands datetimes back naive
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(LOCAL_TZ)


def _header(started_at: datetime | None) -> str:
    moment = _local(started_at or datetime.now(UTC))
    return f"Job Tracker - {moment.day} {moment:%b %Y, %H:%M}"


def _day(moment: datetime) -> str:
    local = _local(moment)
    return f"{local.day} {local:%b}"


def _problem_dicts(run) -> list[dict]:
    return [p for p in (run.problems or []) if isinstance(p, dict) and p.get("code")]


def _breakdown(run) -> str:
    sources = (run.sources or {}).get("sources") or []
    parts = [
        f"{src.get('source')} {src['inserted']}"
        for src in sources
        if isinstance(src, dict) and src.get("inserted")
    ]
    return f" ({', '.join(parts)})" if parts else ""


def format_run_message(
    run,
    *,
    previous=None,
    heartbeat_days: int = 0,
    last_notified_at: datetime | None = None,
    now: datetime | None = None,
) -> str | None:
    """The message for a finished run, or None when the run is not worth a ping.

    Silent when the run succeeded, inserted nothing and hit no problems: an
    updated-only run is not news, and a bot that pings daily about nothing is a bot
    whose pings stop being read.

    `previous` is the run before this one, which is what makes a persistently broken
    source report once rather than every day, and what lets a cleared problem be
    announced as recovered. No extra storage: it is just the previous row.
    """
    now = now or datetime.now(UTC)
    problems = _problem_dicts(run)
    codes = [p["code"] for p in problems]
    previous_codes = [p["code"] for p in _problem_dicts(previous)] if previous is not None else []

    body: list[str] = []
    if run.status == "failed":
        body.append(f"Pipeline FAILED: {(run.error or 'no error recorded')[:_MAX_ERROR_CHARS]}")
    else:
        if run.inserted:
            plural = "" if run.inserted == 1 else "s"
            body.append(f"{run.inserted} new job{plural}{_breakdown(run)}")
            # Subordinate to the new-jobs line on purpose: the classifier walks the
            # whole corpus every run, so counting it as news would ping daily about
            # a run that ingested nothing.
            body.append(f"embedded {run.embedded}, classified {run.classified}")

    if problems:
        if previous is not None and set(codes) == set(previous_codes):
            body.append(
                f"Problems unchanged since {_day(previous.started_at)}: {problems[0]['line']}"
            )
        else:
            body.extend(p["line"] for p in problems)
    body.extend(
        f"Recovered: {recovered_label(code)}" for code in previous_codes if code not in codes
    )

    if not body:
        if not _heartbeat_due(heartbeat_days, last_notified_at, now):
            return None
        quiet = (now - _aware(last_notified_at)).days if last_notified_at else heartbeat_days
        body.append(f"Still running. Nothing new in {quiet} days.")
    elif run.inserted and run.status != "failed":
        body.append("Open the Job Tracker shortcut to review.")

    return "\n".join([_header(run.started_at), *body])


def _aware(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def _heartbeat_due(heartbeat_days: int, last_notified_at: datetime | None, now: datetime) -> bool:
    """Due after that many quiet days. Never notified counts as due, so a stack that
    has never said anything proves once that it can."""
    if heartbeat_days <= 0:
        return False
    if last_notified_at is None:
        return True
    return now - _aware(last_notified_at) >= timedelta(days=heartbeat_days)


def notify_run(session_factory, run_id: int, *, settings: Settings | None = None) -> bool:
    """Format and send the message for one finished run. Returns whether it sent."""
    from app.models import PipelineRun

    settings = settings or get_settings()
    with session_factory() as session:
        run = session.get(PipelineRun, run_id)
        if run is None:  # pragma: no cover - only if the row was deleted mid-run
            return False
        previous = session.scalar(
            select(PipelineRun)
            .where(PipelineRun.id != run_id, PipelineRun.status != "running")
            .order_by(PipelineRun.started_at.desc(), PipelineRun.id.desc())
            .limit(1)
        )
        last_notified_at = session.scalar(select(func.max(PipelineRun.notified_at)))
        text = format_run_message(
            run,
            previous=previous,
            heartbeat_days=settings.notify_heartbeat_days,
            last_notified_at=last_notified_at,
        )
        if text is None:
            return False
        if not send_message(text, settings=settings):
            return False
        run.notified_at = datetime.now(UTC)
        session.commit()
        return True
