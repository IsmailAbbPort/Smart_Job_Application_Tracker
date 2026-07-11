"""The retrieve stage: cosine-rank jobs against a CV embedding.

On PostgreSQL the ranking runs in the database via pgvector's `<=>` operator
(fast, scales). On other dialects (SQLite tests) it falls back to computing
cosine similarity in Python, so ranking is testable without pgvector.
"""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import Job


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
    conditions = [Job.embedding.is_not(None), *filters]

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
