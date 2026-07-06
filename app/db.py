"""Database wiring: one SQLAlchemy engine/session against Postgres + pgvector.

Phase 0 only sets up the connection and a readiness ping. Tables (cv, job,
match, cover_letter, application) and the pgvector column type arrive in later
phases; this module is the single place the rest of the app gets a session.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

_settings = get_settings()

engine = create_engine(_settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for ORM models (defined from Phase 1 onward)."""


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
