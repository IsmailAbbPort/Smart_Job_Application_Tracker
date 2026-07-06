"""Shared test fixtures.

Tests run against an in-memory SQLite database (tables built from the ORM
metadata), so the whole Phase 1 flow - models, dedup, runner, routers - is
exercised without Docker or Postgres. The pgvector features arrive in Phase 2;
until then the models are portable and SQLite is a faithful stand-in.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register tables on Base.metadata
from app.db import Base, get_session
from app.ingest.base import CanonicalJob
from app.main import app as fastapi_app

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_canonical(
    source: str = "test",
    source_id: str = "1",
    *,
    title: str = "Backend Engineer",
    company: str = "Acme",
    location: str | None = "Remote",
    is_remote: bool = True,
    description: str = "desc",
    url: str = "https://example.com/job",
) -> CanonicalJob:
    """Build a CanonicalJob with sensible defaults for runner/route tests."""
    return CanonicalJob(
        source=source,
        source_id=source_id,
        title=title,
        company=company,
        url=url,
        description=description,
        location=location,
        is_remote=is_remote,
    )


class FakeSource:
    """In-memory source for testing the runner without network or adapters."""

    def __init__(self, name: str, jobs: list[CanonicalJob], *, ttl_seconds: int = 3600):
        self.name = name
        self.ttl_seconds = ttl_seconds
        self._jobs = jobs

    def fetch(self, client, session) -> list[CanonicalJob]:  # noqa: ANN001 - args unused
        return list(self._jobs)


class BrokenSource:
    """Source whose fetch always raises, to test error handling."""

    name = "broken"
    ttl_seconds = 3600

    def fetch(self, client, session):  # noqa: ANN001
        raise RuntimeError("boom")


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def session_factory(engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def session(session_factory) -> Iterator[Session]:
    with session_factory() as s:
        yield s


@pytest.fixture
def client(session_factory) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        with session_factory() as s:
            yield s

    fastapi_app.dependency_overrides[get_session] = override
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()
