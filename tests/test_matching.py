"""Cosine similarity + rank_jobs (Python fallback path exercised on SQLite)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from app.ai.matching import cosine_similarity, rank_jobs, recency_weight
from app.models import Job

_NOW = datetime(2026, 7, 17, tzinfo=UTC)


def test_recency_weight():
    # Fresh, future, and unknown dates are all neutral (1.0).
    assert recency_weight(_NOW, _NOW, half_life_days=30, floor=0.5) == 1.0
    assert recency_weight(None, _NOW, half_life_days=30, floor=0.5) == 1.0
    assert recency_weight(_NOW + timedelta(days=5), _NOW, half_life_days=30, floor=0.5) == 1.0
    # One half-life old -> halved (no floor in the way).
    one_hl = recency_weight(_NOW - timedelta(days=30), _NOW, half_life_days=30, floor=0.1)
    assert math.isclose(one_hl, 0.5, abs_tol=1e-9)
    # Very old is clamped to the floor, never below.
    assert recency_weight(_NOW - timedelta(days=999), _NOW, half_life_days=30, floor=0.85) == 0.85


def test_recency_weight_handles_naive_datetime():
    # SQLite returns naive datetimes; they are assumed UTC, not rejected.
    naive = (_NOW - timedelta(days=30)).replace(tzinfo=None)
    assert math.isclose(
        recency_weight(naive, _NOW, half_life_days=30, floor=0.1), 0.5, abs_tol=1e-9
    )


def test_cosine_similarity():
    assert cosine_similarity([1, 0, 0], [1, 0, 0]) == 1.0
    assert cosine_similarity([1, 0], [0, 1]) == 0.0
    assert math.isclose(cosine_similarity([1, 1], [1, 0]), 1 / math.sqrt(2))
    assert cosine_similarity([], [1]) == 0.0
    assert cosine_similarity([0, 0], [1, 1]) == 0.0


def _job(session, source_id, embedding, **kwargs):
    job = Job(
        source="test",
        source_id=source_id,
        title=kwargs.get("title", "Engineer"),
        company="Acme",
        url=f"https://example.com/{source_id}",
        is_remote=kwargs.get("is_remote", True),
        is_european=kwargs.get("is_european", True),
        embedding=embedding,
    )
    session.add(job)
    return job


def test_rank_jobs_orders_by_similarity(session):
    _job(session, "a", [1.0, 0.0, 0.0])
    _job(session, "c", [0.8, 0.2, 0.0])
    _job(session, "b", [0.0, 1.0, 0.0])
    _job(session, "none", None)  # unembedded, must be excluded
    session.commit()

    ranked = rank_jobs(session, [1.0, 0.0, 0.0], filters=[], limit=10)
    ids = [job.source_id for job, _ in ranked]
    assert ids == ["a", "c", "b"]  # closest first, unembedded dropped
    assert ranked[0][1] == 1.0  # perfect match


def test_rank_jobs_respects_filters_and_limit(session):
    _job(session, "eu", [1.0, 0.0, 0.0], is_european=True)
    _job(session, "us", [1.0, 0.0, 0.0], is_european=False)
    session.commit()

    ranked = rank_jobs(session, [1.0, 0.0, 0.0], filters=[Job.is_european.is_(True)], limit=1)
    assert [job.source_id for job, _ in ranked] == ["eu"]
