"""The retrieve stage: cosine-rank jobs against a CV embedding.

On PostgreSQL the ranking runs in the database via pgvector's `<=>` operator
(fast, scales). On other dialects (SQLite tests) it falls back to computing
cosine similarity in Python, so ranking is testable without pgvector.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import MANUAL_SOURCE, Job


def recency_weight(
    posted_at: datetime | None,
    now: datetime,
    *,
    half_life_days: float,
    floor: float,
) -> float:
    """Freshness multiplier in [floor, 1.0]: 1.0 when fresh, halving every
    half_life_days, never below floor. A missing/future date -> 1.0 (neutral), so
    jobs are never penalized for absent metadata (same spirit as null-kept filters).
    """
    if posted_at is None:
        return 1.0
    # SQLite round-trips tz-aware columns as naive; assume UTC so the math is valid.
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)
    age_days = (now - posted_at).total_seconds() / 86400.0
    if age_days <= 0:
        return 1.0
    return max(floor, 0.5 ** (age_days / half_life_days))


def experience_gap(min_years_required: int | None, user_years: int | None) -> int | None:
    """How many years a posting requires beyond the user's, or None if unknown.

    Negative/zero means the user meets the bar; positive is the stretch. None when
    either side is unknown, so the signal never penalizes missing data.
    """
    if min_years_required is None or user_years is None:
        return None
    return min_years_required - user_years


def experience_weight(
    gap: int | None,
    *,
    penalty_per_year: float,
    floor: float,
) -> float:
    """Soft de-prioritization multiplier in [floor, 1.0] for over-experience.

    A job requiring N years more than the user has loses penalty_per_year per year,
    floored. Meeting/under the bar (gap <= 0) or unknown gap is neutral (1.0). This
    keeps a stretch role visible but ranked lower, rather than dropping it.
    """
    if gap is None or gap <= 0:
        return 1.0
    return max(floor, 1.0 - penalty_per_year * gap)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]; 0 if either vector is empty/zero."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def rank_jobs(
    session: Session,
    cv_vector: list[float],
    *,
    filters: list[ColumnElement[bool]],
    limit: int,
) -> list[tuple[Job, float]]:
    """Return the top `limit` (job, similarity) pairs, most similar first."""
    conditions = [Job.embedding.is_not(None), Job.source != MANUAL_SOURCE, *filters]

    if session.get_bind().dialect.name == "postgresql":
        distance = Job.embedding.cosine_distance(cv_vector).label("distance")
        rows = session.execute(
            select(Job, distance).where(*conditions).order_by(distance).limit(limit)
        ).all()
        return [(job, 1.0 - float(dist)) for job, dist in rows]

    # Portable fallback (tests): score in Python.
    jobs = session.scalars(select(Job).where(*conditions)).all()
    scored = [(job, cosine_similarity(cv_vector, job.embedding)) for job in jobs]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]
