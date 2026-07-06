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
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ingest import cache
from app.ingest.base import CanonicalJob, Source
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
from app.models import Job

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


def _persist(session: Session, source: str, jobs: list[CanonicalJob], stats: IngestStats) -> None:
    """Upsert a batch, tracking insert/update/dedup counts."""
    for cj in jobs:
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
        jobs = source.fetch(client)
        stats.fetched = len(jobs)
        _persist(session, name, jobs, stats)
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
