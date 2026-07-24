"""Ingest orchestration: fetch -> normalize -> dedup -> upsert, with stats.

Two levels of dedup, matching the plan:
1. (source, source_id) upsert  -> re-poll idempotency (same posting, same source).
2. dedup_key (company|title|location) -> cross-source identity (same role from a
   different source is stored once; first source to bring it wins).

Upserts are done in portable Python (query-then-write), not Postgres ON CONFLICT,
so the runner is exercised by SQLite-backed tests without a live database.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ingest import cache
from app.ingest.base import CanonicalJob, Source
from app.ingest.compensation import extract_effort_signals, extract_salary
from app.ingest.eligibility import (
    detect_remote_region,
    detect_visa_sponsorship,
    extract_required_utc_offsets,
)
from app.ingest.experience import extract_min_years_experience
from app.ingest.geo import is_european, resolve_city, resolve_country
from app.ingest.language import detect_language, extract_required_languages
from app.ingest.normalize import (
    dedup_key,
    normalize_company,
    normalize_location,
    normalize_title,
)
from app.ingest.sources.arbeitnow import ArbeitnowSource
from app.ingest.sources.ashby import AshbySource
from app.ingest.sources.greenhouse import GreenhouseSource
from app.ingest.sources.lever import LeverSource
from app.ingest.sources.remotive import RemotiveSource
from app.models import Application, Job

# The source registry. Adding a source = adding one line here.
SOURCES: dict[str, Source] = {
    s.name: s
    for s in (
        GreenhouseSource(),
        LeverSource(),
        AshbySource(),
        ArbeitnowSource(),
        RemotiveSource(),
    )
}

_USER_AGENT = "SmartJobTracker/0.1 (portfolio project; polite ingest)"
_TIMEOUT = 20.0


@dataclass
class IngestStats:
    source: str
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    deduped: int = 0  # dropped as a cross-source duplicate
    removed_stale: int = 0  # deleted: gone from a full-catalogue source's feed
    skipped_throttled: bool = False
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class IngestSummary:
    results: list[IngestStats] = field(default_factory=list)

    def as_dict(self) -> dict:
        totals = {
            "fetched": sum(r.fetched for r in self.results),
            "inserted": sum(r.inserted for r in self.results),
            "updated": sum(r.updated for r in self.results),
            "deduped": sum(r.deduped for r in self.results),
            "removed_stale": sum(r.removed_stale for r in self.results),
        }
        return {"totals": totals, "sources": [r.as_dict() for r in self.results]}


def _apply_fields(job: Job, cj: CanonicalJob) -> None:
    """Copy canonical fields + normalized forms onto an ORM row."""
    job.title = cj.title
    job.company = cj.company
    job.url = cj.url
    job.description = cj.description
    job.location = cj.location
    job.is_remote = cj.is_remote
    job.posted_at = cj.posted_at
    job.company_norm = normalize_company(cj.company)
    job.title_norm = normalize_title(cj.title)
    job.location_norm = normalize_location(cj.location)
    job.dedup_key = dedup_key(cj.company, cj.title, cj.location)
    # Derived geo: country is the actual country (any continent); city is European
    # only; is_european gates the EU-remote search.
    job.city = resolve_city(cj.location)
    job.country = resolve_country(cj.location)
    job.is_european = is_european(cj.location)
    _apply_derived(job)


def _apply_derived(job: Job) -> None:
    """Set language + eligibility signals from a job's own text (title/description).

    Shared by ingest and backfill so both stay in sync. Reads from the ORM row so
    it works whether fields were just copied from a CanonicalJob or loaded from DB.
    """
    job.language = detect_language(job.title, job.description)
    job.required_languages = extract_required_languages(job.description)
    job.visa_sponsorship = detect_visa_sponsorship(job.description)
    job.remote_region = detect_remote_region(job.description, is_remote=job.is_remote)
    job.required_utc_offsets = extract_required_utc_offsets(job.description)
    job.salary_min, job.salary_max, job.salary_currency = extract_salary(job.description)
    job.effort_signals = extract_effort_signals(job.description)
    job.min_years_experience = extract_min_years_experience(job.description)


def _persist(session: Session, source: str, jobs: list[CanonicalJob], stats: IngestStats) -> None:
    """Upsert a batch, tracking insert/update/dedup counts."""
    # A single fetch can list the same posting twice (source_id repeated). The session
    # doesn't autoflush, so a duplicate wouldn't be seen by the existing-row query below
    # until commit, where it would violate uq_job_source_sourceid and roll back the whole
    # batch. Collapse in-batch duplicates up front (first occurrence wins).
    seen_ids: set[str] = set()
    for cj in jobs:
        if cj.source_id in seen_ids:
            stats.deduped += 1
            continue
        seen_ids.add(cj.source_id)
        existing = session.scalar(
            select(Job).where(Job.source == source, Job.source_id == cj.source_id)
        )
        if existing is not None:
            _apply_fields(existing, cj)
            stats.updated += 1
            continue

        # Cross-source dedup: same real role already stored from another source.
        key = dedup_key(cj.company, cj.title, cj.location)
        clash = session.scalar(
            select(Job).where(Job.dedup_key == key, Job.source != source).limit(1)
        )
        if clash is not None:
            stats.deduped += 1
            continue

        job = Job(source=source, source_id=cj.source_id)
        _apply_fields(job, cj)
        session.add(job)
        stats.inserted += 1


def _sweep_stale(session: Session, source: str, fetched_ids: list[str], stats: IngestStats) -> None:
    """Delete stored jobs of a full-catalogue source that vanished from its feed.

    Reliable removal for ATS boards (which serve a complete per-company list, and
    return HTTP 200 even for deleted postings, so a URL check can't tell). Scoped
    conservatively: only prunes within companies (source_id slug prefixes) that
    actually appeared in this fetch, so a company whose board failed or was skipped
    is left untouched. Jobs with a tracked Application are never removed. Does
    nothing on an empty fetch (a total failure must not wipe the corpus).
    """
    fetched = set(fetched_ids)
    if not fetched:
        return
    seen_slugs = {sid.split(":", 1)[0] for sid in fetched}
    tracked = set(session.scalars(select(Application.job_id)))
    for job in session.scalars(select(Job).where(Job.source == source)):
        slug = job.source_id.split(":", 1)[0]
        if slug not in seen_slugs or job.source_id in fetched or job.id in tracked:
            continue
        session.delete(job)
        stats.removed_stale += 1


def ingest_source(
    session: Session,
    name: str,
    *,
    force: bool = False,
    client: httpx.Client | None = None,
) -> IngestStats:
    """Fetch one source (unless throttled) and persist its jobs."""
    if name not in SOURCES:
        raise KeyError(name)
    source = SOURCES[name]
    stats = IngestStats(source=name)

    if not force and not cache.should_fetch(session, name, source.ttl_seconds):
        stats.skipped_throttled = True
        return stats

    owns_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT, follow_redirects=True
    )
    try:
        jobs = source.fetch(client, session)
        stats.fetched = len(jobs)
        _persist(session, name, jobs, stats)
        # For full-catalogue sources, remove postings that dropped out of the feed.
        if getattr(source, "full_catalog", False):
            _sweep_stale(session, name, [cj.source_id for cj in jobs], stats)
        cache.record_fetch(session, name, status="ok", count=len(jobs))
        session.commit()
    except Exception as exc:  # noqa: BLE001 - surface any source failure as stats
        session.rollback()
        stats.error = f"{type(exc).__name__}: {exc}"
        cache.record_fetch(session, name, status="error", count=0)
        session.commit()
    finally:
        if owns_client:
            client.close()
    return stats


def backfill_enrichment(session: Session, *, limit: int = 5000, force: bool = False) -> dict:
    """Recompute derived signals (language + eligibility) for pre-existing jobs.

    Idempotent: processes only rows without a language unless force re-does all
    (language is the proxy for "not yet enriched"). Rows too short to detect a
    language stay null - expected, not an error - so `remaining` may not reach zero.
    """
    stmt = select(Job)
    if not force:
        stmt = stmt.where(Job.language.is_(None))
    jobs = session.scalars(stmt.limit(limit)).all()
    for job in jobs:
        _apply_derived(job)
    session.commit()
    remaining = session.scalar(select(func.count()).select_from(Job).where(Job.language.is_(None)))
    return {"processed": len(jobs), "remaining_undetected": remaining or 0}


def ingest_all(session: Session, *, force: bool = False) -> IngestSummary:
    """Ingest every registered source.

    Each source runs in its OWN session (bound to the caller's engine) so a
    failure in one source's transaction can't corrupt another's - one bad source
    fails in isolation with its error captured in stats. One HTTP client is shared.
    """
    summary = IngestSummary()
    maker = sessionmaker(bind=session.get_bind(), autoflush=False, expire_on_commit=False)
    client = httpx.Client(
        headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT, follow_redirects=True
    )
    try:
        for name in SOURCES:
            with maker() as source_session:
                summary.results.append(
                    ingest_source(source_session, name, force=force, client=client)
                )
    finally:
        client.close()
    return summary
