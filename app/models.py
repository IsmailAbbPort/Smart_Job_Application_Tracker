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

from app.db import Base, EmbeddingType

EMBED_DIM = 1536


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        # A posting is unique within its source (re-poll idempotency key).
        UniqueConstraint("source", "source_id", name="uq_job_source_sourceid"),
        # Cross-source dedup + common filters.
        Index("ix_job_dedup_key", "dedup_key"),
        Index("ix_job_company_norm", "company_norm"),
        Index("ix_job_source", "source"),
        Index("ix_job_is_european", "is_european"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Provenance
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Raw canonical fields. Free text is Text (unbounded): job boards emit very
    # long titles/locations (Greenhouse concatenates every office), and a length
    # cap would drop whole batches. Postgres Text is as efficient as varchar.
    title: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_remote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Derived geo from location: country is the actual country (any continent),
    # city is set for European cities only, is_european gates the EU-remote search.
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_european: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Semantic embedding of the job (Phase 2). Null until embedded.
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType(EMBED_DIM), nullable=True)

    # Normalized forms (for dedup + fast filtering)
    company_norm: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title_norm: Mapped[str] = mapped_column(Text, nullable=False, default="")
    location_norm: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dedup_key: Mapped[str] = mapped_column(Text, nullable=False, default="")

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


class Cv(Base):
    """The user's CV: raw text + its semantic embedding (Phase 2)."""

    __tablename__ = "cv"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType(EMBED_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TargetCompany(Base):
    """A company whose ATS board we monitor directly.

    Seeded from app/ingest/target_companies.yaml but stored in the DB so the set
    is editable at runtime (via /targets endpoints today, a UI later) without a
    code change or redeploy.
    """

    __tablename__ = "target_company"
    __table_args__ = (UniqueConstraint("ats", "slug", name="uq_target_ats_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    ats: Mapped[str] = mapped_column(String(16), nullable=False)  # greenhouse|lever|ashby
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    hq: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_policy: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
