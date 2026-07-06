"""SQLAlchemy ORM models.

Phase 1 introduces two tables:
- `job`: the canonical, normalized job posting (one row per real posting).
- `source_fetch`: per-source last-fetch bookkeeping for the ingest throttle/cache.

Column types are kept portable (no Postgres-only types yet) so the same models
back both the Postgres runtime and SQLite-based tests. The pgvector `embedding`
column arrives in Phase 2 via a later migration.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        # A posting is unique within its source (re-poll idempotency key).
        UniqueConstraint("source", "source_id", name="uq_job_source_sourceid"),
        # Cross-source dedup + common filters.
        Index("ix_job_dedup_key", "dedup_key"),
        Index("ix_job_company_norm", "company_norm"),
        Index("ix_job_source", "source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Provenance
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Raw canonical fields
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_remote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Normalized forms (for dedup + fast filtering)
    company_norm: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    title_norm: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    location_norm: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    dedup_key: Mapped[str] = mapped_column(String(1024), nullable=False, default="")

    # Bookkeeping
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Job {self.source}:{self.source_id} {self.company} - {self.title!r}>"


class SourceFetch(Base):
    """Last-fetch record per source, powering the ingest throttle (see cache.py)."""

    __tablename__ = "source_fetch"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
