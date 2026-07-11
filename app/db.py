"""Database wiring: one SQLAlchemy engine/session against Postgres + pgvector.

Phase 0 only sets up the connection and a readiness ping. Tables (cv, job,
match, cover_letter, application) and the pgvector column type arrive in later
phases; this module is the single place the rest of the app gets a session.
"""

import json
from collections.abc import Iterator

from sqlalchemy import Float, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import get_settings

_settings = get_settings()

engine = create_engine(_settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for ORM models (defined from Phase 1 onward)."""


class EmbeddingType(TypeDecorator):
    """A vector column that is pgvector `Vector` on PostgreSQL and JSON text
    elsewhere (SQLite in tests).

    This lets the same models back both the Postgres runtime (real vector search)
    and the SQLite-based unit tests (embeddings stored/compared in Python). The
    `cosine_distance` comparator emits pgvector's `<=>` operator on PostgreSQL.
    """

    impl = Text
    cache_ok = True

    def __init__(self, dim: int = 1536):
        self.dim = dim
        super().__init__()

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        value = list(value)
        return value if dialect.name == "postgresql" else json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return list(value) if dialect.name == "postgresql" else json.loads(value)

    # Name mandated by SQLAlchemy (it looks up `comparator_factory`).
    class comparator_factory(TypeDecorator.Comparator):  # noqa: N801
        def cosine_distance(self, other):
            return self.op("<=>", return_type=Float)(other)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped DB session."""
    with SessionLocal() as session:
        yield session


def ping() -> bool:
    """Return True if the database answers a trivial query, else False."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
