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
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
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
    # Language the posting is written in (ISO 639-1), null if too short to detect.
    # required_languages: spoken languages the text explicitly demands (best-effort).
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    required_languages: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Eligibility signals (see app/ingest/eligibility.py): can the user take this?
    # visa_sponsorship: True offered / False refused / None unstated.
    # remote_region: region a remote role is locked to (us/eu/uk/...), null if open.
    # required_utc_offsets: timezone offsets the working hours demand (may be empty).
    visa_sponsorship: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    remote_region: Mapped[str | None] = mapped_column(String(16), nullable=True)
    required_utc_offsets: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Compensation (best-effort, currency-anchored) + application effort signals.
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    effort_signals: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Minimum years of experience the posting requires (entry bar), null if unstated.
    min_years_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
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


class Match(Base):
    """The LLM judge's verdict for one (CV, job) pair (Phase 3, rerank stage).

    One row per CV+job. The structured sub-parts (dimension scores, matched
    requirements, gaps) are stored as JSON so the whole explainable verdict round-
    trips without extra tables. Re-judging overwrites the row (see the router).
    """

    __tablename__ = "match"
    __table_args__ = (UniqueConstraint("cv_id", "job_id", name="uq_match_cv_job"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cv_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cv.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job.id", ondelete="CASCADE"), nullable=False, index=True
    )

    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)  # strong|medium|weak
    one_line_verdict: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dimension_scores: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    matched_requirements: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    gaps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SearchPreferences(Base):
    """Persistent default filters for the job search. Single-user -> one row (id=1).

    Applied by default to /jobs and /match/shortlist so the user doesn't retype
    filters. remote_only / require_european are positive defaults; the exclude
    lists are a blocklist of countries/cities to drop.
    """

    __tablename__ = "search_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # singleton, always 1
    remote_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    require_european: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exclude_countries: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    exclude_cities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # ISO 639-1 codes the user can work in; jobs written in another language are
    # dropped from results when this is non-empty (empty = no language filtering).
    known_languages: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Hard freshness cutoff: drop postings older than this many days (null = off).
    # Jobs with no post date are kept. Distinct from the soft recency decay.
    max_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Eligibility preferences. require_sponsorship: drop jobs that explicitly refuse
    # visa sponsorship. exclude_remote_regions: region locks to reject (e.g. ["us"]).
    # user_utc_offset + min_timezone_overlap_hours: drop jobs whose working-hours
    # timezone overlaps the user's by fewer than N hours (both must be set).
    require_sponsorship: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exclude_remote_regions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    user_utc_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_timezone_overlap_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Drop jobs whose stated max pay is below this (null-pay kept unless require_salary).
    min_salary: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The user's years of experience + an optional hard cutoff on how many years
    # over that a posting may require before it is dropped (null cutoff = soft only).
    years_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_experience_gap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CoverLetter(Base):
    """A CV-grounded cover letter for one job + its fabrication audit (Phase 4).

    One row per (cv, job). `body` is the current text (drafted or user-edited);
    `fabrication` stores the audit JSON (claims, placeholders, counts); `edited`
    flips true once the user saves their own version.
    """

    __tablename__ = "cover_letter"
    __table_args__ = (UniqueConstraint("cv_id", "job_id", name="uq_cover_letter_cv_job"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cv_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cv.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fabrication: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Application(Base):
    """A tracked application to one job posting (the pipeline).

    One row per job (single user), keyed for lookup by job_id. status walks the
    pipeline (saved -> applied -> screening -> ... -> offer/rejected); applied_at is
    stamped when it first leaves 'saved'. cv_id records which CV version was sent.
    """

    __tablename__ = "application"
    __table_args__ = (UniqueConstraint("job_id", name="uq_application_job"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cv_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cv.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="saved")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
