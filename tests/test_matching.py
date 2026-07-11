"""Cosine similarity + rank_jobs (Python fallback path exercised on SQLite)."""

from __future__ import annotations

import math

from app.ai.matching import cosine_similarity, rank_jobs
from app.models import Job


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
