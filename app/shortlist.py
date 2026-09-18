"""The shortlist ranking, shared by the /match/shortlist route and the nightly sweep.

`rank_shortlist` is the retrieve stage end to end: filters -> cosine candidates ->
Python-side eligibility -> fit x freshness x experience re-rank. The nightly
liveness sweep replays each owner's last shortlist query through the same function,
so it checks exactly the jobs that owner sees rather than an approximation.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.matching import experience_gap, experience_weight, rank_jobs, recency_weight
from app.config import Settings, get_settings
from app.ingest.eligibility import timezone_overlap_hours
from app.ingest.liveness import AGGREGATOR_SOURCES, sweep_dead_jobs
from app.models import Cv, Job, SearchPreferences
from app.prefs import get_preferences, preference_filters

log = logging.getLogger("app.shortlist")

# How many fit-ranked candidates to pull before the recency re-rank. A few times
# the page size is plenty for a gentle, floored decay to reshuffle near-ties.
_CANDIDATE_MULTIPLIER = 3
_MAX_CANDIDATES = 300


@dataclass
class ShortlistQuery:
    """The explicit /match/shortlist parameters (saved prefs apply on top)."""

    cv_id: int | None = None
    limit: int = 25
    is_remote: bool | None = None
    europe: bool | None = None
    region: str | None = None
    country: str | None = None
    cities: list[str] | None = None
    language: str | None = None
    max_age_days: int | None = None
    min_salary: int | None = None
    min_salary_currency: str | None = None
    require_salary: bool = False
    max_experience_gap: int | None = None
    ignore_prefs: bool = False

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ShortlistQuery:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


# (job, similarity, recency weight, timezone overlap, experience gap)
ShortlistRow = tuple[Job, float, float, int | None, int | None]


def resolve_cv(session: Session, cv_id: int | None, owner_id: int | None) -> Cv | None:
    """The requested CV, or the owner's most recent one; None if there is none.

    Scopes to owner_id (None = guest) so accounts only see their own CVs.
    """
    if cv_id:
        cv = session.get(Cv, cv_id)
        return cv if cv is not None and cv.owner_id == owner_id else None
    return session.scalar(
        select(Cv).where(Cv.owner_id == owner_id).order_by(Cv.created_at.desc()).limit(1)
    )


def rank_shortlist(
    session: Session,
    cv: Cv,
    prefs: SearchPreferences,
    query: ShortlistQuery,
    settings: Settings,
) -> list[ShortlistRow]:
    """Cosine-rank embedded jobs against the CV, then adjust for freshness.

    Fit (cosine) is the primary signal; a floored recency decay then reshuffles
    comparably-fit jobs so newer ones rank higher, without burying a clearly-better
    older match. Saved search preferences (remote/europe defaults + blocklist +
    freshness cutoff) apply unless overridden by the query or bypassed with ignore_prefs.
    """
    filters = preference_filters(
        prefs,
        is_remote=query.is_remote,
        europe=query.europe,
        region=query.region,
        country=query.country,
        cities=query.cities,
        language=query.language,
        max_age_days=query.max_age_days,
        min_salary=query.min_salary,
        min_salary_currency=query.min_salary_currency,
        require_salary=query.require_salary,
        max_experience_gap=query.max_experience_gap,
    )

    # Over-fetch by fit, then re-rank by fit x freshness x experience penalty.
    candidate_limit = min(query.limit * _CANDIDATE_MULTIPLIER, _MAX_CANDIDATES)
    ranked = rank_jobs(session, list(cv.embedding), filters=filters, limit=candidate_limit)

    # Normalize fit across the candidate set before applying the recency/experience
    # multipliers. Cosine values cluster in a narrow band (~0.49-0.55), so multiplying
    # raw cosine by a recency weight that swings 0.85-1.0 lets freshness dominate fit
    # (a fresh mediocre role would outrank a stale strong one). Min-max normalizing
    # spreads fit to [0, 1] so recency/experience become gentle tiebreakers, not the
    # primary signal. When all candidates tie, every fit is treated as best (1.0).
    sims = [s for _, s in ranked]
    lo, hi = (min(sims), max(sims)) if sims else (0.0, 1.0)
    span = hi - lo

    # Languages the user speaks -> drop jobs requiring one they don't (hard filter).
    # In Python (not SQL) because required_languages is a JSON array. Empty = off.
    known_langs = {c.strip().lower() for c in (prefs.known_languages or []) if c.strip()}

    now = datetime.now(UTC)
    scored = []  # (job, similarity, recency, overlap, gap, rank_score)
    for job, similarity in ranked:
        if known_langs and set(job.required_languages or []) - known_langs:
            continue  # requires a language the user doesn't have
        # Timezone-overlap eligibility (see prefs.py: done here, not in SQL).
        overlap = timezone_overlap_hours(job.required_utc_offsets, prefs.user_utc_offset)
        if (
            prefs.min_timezone_overlap_hours is not None
            and overlap is not None
            and overlap < prefs.min_timezone_overlap_hours
        ):
            continue
        recency = recency_weight(
            job.posted_at,
            now,
            half_life_days=settings.recency_half_life_days,
            floor=settings.recency_floor,
        )
        # Soft experience penalty: over-experienced roles rank lower but stay visible.
        gap = experience_gap(job.min_years_experience, prefs.years_experience)
        exp = experience_weight(
            gap,
            penalty_per_year=settings.experience_penalty_per_year,
            floor=settings.experience_floor,
        )
        fit = (similarity - lo) / span if span else 1.0
        scored.append((job, similarity, recency, overlap, gap, fit * recency * exp))

    scored.sort(key=lambda t: t[5], reverse=True)
    return [row[:5] for row in scored[: query.limit]]


def check_shortlist_liveness(bind, job_ids: list[int], settings: Settings) -> None:
    """On-view background check of the aggregator jobs a shortlist just showed.

    Runs after the response in its own session (the request's is closed by then).
    Never waits behind another sweep: if one is running, the next view picks it up.
    """
    maker = sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)
    with maker() as session:
        stats = sweep_dead_jobs(
            session,
            job_ids=job_ids,
            recheck_after=timedelta(hours=settings.liveness_view_recheck_hours),
            limit=settings.liveness_view_max_checks,
            min_interval=settings.liveness_min_interval_seconds,
            wait=False,
        )
    if stats["deleted"]:
        log.info("on-view liveness check removed %d expired jobs", stats["deleted"])


def aggregator_ids(rows: list[ShortlistRow]) -> list[int]:
    return [job.id for job, *_ in rows if job.source in AGGREGATOR_SOURCES]


def sweep_saved_shortlists(session: Session) -> dict:
    """Nightly: replay each owner's last shortlist and sweep its aggregator jobs."""
    settings = get_settings()
    totals = {"owners": 0, "checked": 0, "deleted": 0, "stopped_early": False}
    rows = session.scalars(
        select(SearchPreferences).where(SearchPreferences.last_shortlist_query.is_not(None))
    ).all()
    for saved in rows:
        query = ShortlistQuery.from_dict(saved.last_shortlist_query)
        cv = resolve_cv(session, query.cv_id, saved.owner_id)
        if cv is None or cv.embedding is None:
            continue
        prefs = (
            SearchPreferences() if query.ignore_prefs else get_preferences(session, saved.owner_id)
        )
        ids = aggregator_ids(rank_shortlist(session, cv, prefs, query, settings))
        if not ids:
            continue
        totals["owners"] += 1
        stats = sweep_dead_jobs(
            session,
            job_ids=ids,
            recheck_after=timedelta(hours=settings.liveness_nightly_recheck_hours),
            limit=len(ids),
            min_interval=settings.liveness_min_interval_seconds,
        )
        totals["checked"] += stats["checked"]
        totals["deleted"] += stats["deleted"]
        if stats["stopped_early"]:
            totals["stopped_early"] = True
            break  # being blocked: don't carry on for the next owner
    return totals
