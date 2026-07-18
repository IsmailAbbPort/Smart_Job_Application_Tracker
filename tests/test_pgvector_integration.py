"""Integration test for the REAL pgvector `<=>` ranking path.

The rest of the suite runs on SQLite (the Python cosine fallback in rank_jobs).
This exercises the production path: it spins up an isolated database on the
PostgreSQL server given by DATABASE_URL, enables pgvector, and checks that
rank_jobs orders by cosine distance using the `<=>` operator.

Skipped unless DATABASE_URL points at PostgreSQL, so CI/SQLite stays green. Run it
against the compose db by setting DATABASE_URL to the postgres service before
invoking pytest on this file.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 - register tables on Base.metadata
from app.ai.matching import rank_jobs
from app.db import Base
from app.models import Job

PG_URL = os.getenv("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not PG_URL.startswith("postgresql"),
    reason="requires a PostgreSQL DATABASE_URL (pgvector integration)",
)

_TEST_DB = "jobtracker_pgtest"
EMBED_DIM = 1536


def _vec(*hot: int) -> list[float]:
    v = [0.0] * EMBED_DIM
    for i in hot:
        v[i] = 1.0
    return v


@pytest.fixture
def pg_session():
    admin = create_engine(PG_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {_TEST_DB} WITH (FORCE)"))
        c.execute(text(f"CREATE DATABASE {_TEST_DB}"))
    test_url = PG_URL.rsplit("/", 1)[0] + "/" + _TEST_DB
    engine = create_engine(test_url)
    with engine.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    with maker() as s:
        yield s
    engine.dispose()
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {_TEST_DB} WITH (FORCE)"))
    admin.dispose()


def test_pgvector_cosine_ranking(pg_session):
    # query = e0; near = e0 (cos 1), mid = e0+e1 (cos ~0.707), far = e5 (cos 0).
    pg_session.add_all(
        [
            Job(source="t", source_id="near", title="x", company="c", url="u1", embedding=_vec(0)),
            Job(
                source="t", source_id="mid", title="x", company="c", url="u2", embedding=_vec(0, 1)
            ),
            Job(source="t", source_id="far", title="x", company="c", url="u3", embedding=_vec(5)),
        ]
    )
    pg_session.commit()

    # PostgreSQL dialect -> rank_jobs uses Job.embedding.cosine_distance (the `<=>` op).
    assert pg_session.get_bind().dialect.name == "postgresql"
    ranked = rank_jobs(pg_session, _vec(0), filters=[], limit=10)

    ids = [job.source_id for job, _ in ranked]
    assert ids == ["near", "mid", "far"]
    assert ranked[0][1] == pytest.approx(1.0, abs=1e-4)  # perfect cosine match
    assert ranked[0][1] > ranked[1][1] > ranked[2][1]
