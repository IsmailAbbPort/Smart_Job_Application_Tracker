"""Daily rate limits on the paid AI endpoints (judge + cover letter).

Goal: one visitor (or a runaway loop) can't drain the Anthropic budget. Two caps
apply per calendar day (UTC): a per-identity cap and a global backstop across
everyone. An identity is the signed-in user, or a guest's client IP.

Charging happens right before the real LLM call (see `charge`), so cached results
and 503s (missing key) are never counted against the user. When a cap is hit the
429 detail states the limit and reset, which the UI surfaces verbatim ("shown, not
told"). Counts live in the `ai_usage` table so they survive restarts. No Redis.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AiUsage

# Paid action -> a human label used in the 429 message.
_LABELS = {"judge": "AI fit assessments", "letter": "cover letters"}


def _limits(action: str) -> tuple[int, int]:
    """(per-identity daily cap, global monthly cap) for an action, from settings."""
    s = get_settings()
    if action == "judge":
        return s.rl_judge_per_day, s.rl_judge_global_per_month
    if action == "letter":
        return s.rl_letter_per_day, s.rl_letter_global_per_month
    raise KeyError(action)


def _identity(request: Request, owner_id: int | None) -> str:
    """Stable key for the caller: the account if signed in, else the client IP.

    Guests all share the NULL owner scope, so without this one guest could spend
    the whole quota; keying on IP gives each visitor their own bucket. X-Forwarded-For
    is only trusted when `trust_forwarded_for` is set (deploy behind a proxy that
    overwrites it); otherwise it is ignored, since a direct caller can spoof it to
    forge a fresh identity per request and bypass the per-identity cap.
    """
    if owner_id is not None:
        return f"user:{owner_id}"
    ip = None
    if get_settings().trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
    if ip is None:
        ip = request.client.host if request.client else "unknown"
    return f"ip:{ip}"


def _today() -> date:
    return datetime.now(UTC).date()


def consume(session: Session, request: Request, owner_id: int | None, action: str) -> None:
    """Charge one unit of `action` to this identity; raise 429 if a cap is hit.

    Call immediately before the paid LLM call so cached hits are never charged.
    """
    per_id_cap, global_cap = _limits(action)
    today = _today()
    label = _LABELS.get(action, action)

    # Global backstop first: a hard monthly ceiling that protects the API budget
    # regardless of who is calling (summed over the current calendar month, UTC).
    month_start = today.replace(day=1)
    used_global = (
        session.scalar(
            select(func.coalesce(func.sum(AiUsage.count), 0)).where(
                AiUsage.action == action, AiUsage.day >= month_start
            )
        )
        or 0
    )
    if used_global >= global_cap:
        raise HTTPException(
            status_code=429,
            detail=f"The monthly {label} limit for the demo has been reached. "
            "Please try again next month.",
        )

    identity = _identity(request, owner_id)
    row = session.scalar(
        select(AiUsage).where(
            AiUsage.identity == identity, AiUsage.action == action, AiUsage.day == today
        )
    )
    used = row.count if row else 0
    if used >= per_id_cap:
        raise HTTPException(
            status_code=429,
            detail=f"You've used your {per_id_cap} {label} for today. This resets at 00:00 UTC.",
        )
    if row is None:
        row = AiUsage(identity=identity, action=action, day=today, count=0)
        session.add(row)
    row.count += 1
    session.commit()


def refund(session: Session, request: Request, owner_id: int | None, action: str) -> None:
    """Give a unit back if the paid call failed after `consume` charged it."""
    row = session.scalar(
        select(AiUsage).where(
            AiUsage.identity == _identity(request, owner_id),
            AiUsage.action == action,
            AiUsage.day == _today(),
        )
    )
    if row is not None and row.count > 0:
        row.count -= 1
        session.commit()


@contextmanager
def charge(session: Session, request: Request, owner_id: int | None, action: str) -> Iterator[None]:
    """Charge before the wrapped LLM call; refund it if that call raises.

    A 429 from `consume` propagates out of __enter__, so the body never runs and
    nothing is spent when over budget.
    """
    consume(session, request, owner_id, action)
    try:
        yield
    except Exception:
        refund(session, request, owner_id, action)
        raise
