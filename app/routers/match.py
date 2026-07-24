"""/match - embed jobs and shortlist them against the CV (retrieve stage)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.embedder import Embedder, build_job_document, get_embedder
from app.ai.judge import Judge, build_job_text, get_judge
from app.ai.matching import experience_gap, experience_weight, rank_jobs, recency_weight
from app.applications import annotate_application_status
from app.config import Settings, get_settings
from app.db import get_session
from app.ingest.eligibility import timezone_overlap_hours
from app.models import Cv, Job, Match, SearchPreferences
from app.prefs import get_preferences, preference_filters
from app.schemas import (
    JobOut,
    MatchOut,
    MatchVerdict,
    RerankRequest,
    ShortlistItem,
    ShortlistResponse,
)

# How many fit-ranked candidates to pull before the recency re-rank. A few times
# the page size is plenty for a gentle, floored decay to reshuffle near-ties.
_CANDIDATE_MULTIPLIER = 3
_MAX_CANDIDATES = 300
# Cap on how many jobs one rerank call will judge (each is an LLM call + spend).
_MAX_RERANK = 20

router = APIRouter(prefix="/match", tags=["match"])


def _resolve_cv(session: Session, cv_id: int | None) -> Cv:
    """The requested CV, or the most recent one. 404 if there is none, 409 if unembedded."""
    cv = (
        session.get(Cv, cv_id)
        if cv_id
        else session.scalar(select(Cv).order_by(Cv.created_at.desc()).limit(1))
    )
    if cv is None:
        raise HTTPException(status_code=404, detail="no CV found; POST /cv first")
    return cv


def _to_match_out(match: Match) -> MatchOut:
    return MatchOut(
        job_id=match.job_id,
        cv_id=match.cv_id,
        model=match.model,
        created_at=match.created_at,
        overall_score=match.overall_score,
        verdict=match.verdict,
        one_line_verdict=match.one_line_verdict,
        dimension_scores=match.dimension_scores,
        matched_requirements=match.matched_requirements,
        gaps=match.gaps,
    )


@router.post("/embed-jobs")
def embed_jobs(
    session: Session = Depends(get_session),
    embedder: Embedder = Depends(get_embedder),
    force: bool = Query(default=False, description="Re-embed all jobs, not just missing ones"),
    limit: int = Query(default=5000, ge=1, le=10000, description="Max jobs to embed this call"),
) -> dict:
    """Embed jobs that lack an embedding (or all, with force)."""
    stmt = select(Job)
    if not force:
        stmt = stmt.where(Job.embedding.is_(None))
    jobs = session.scalars(stmt.limit(limit)).all()

    if jobs:
        vectors = embedder.embed([build_job_document(j) for j in jobs])
        for job, vector in zip(jobs, vectors, strict=True):
            job.embedding = vector
        session.commit()

    remaining = session.scalar(select(func.count()).select_from(Job).where(Job.embedding.is_(None)))
    return {"embedded": len(jobs), "remaining_unembedded": remaining or 0}


@router.get("/shortlist", response_model=ShortlistResponse)
def shortlist(
    session: Session = Depends(get_session),
    cv_id: int | None = Query(default=None, description="CV to match; defaults to the latest"),
    limit: int = Query(default=25, ge=1, le=100),
    is_remote: bool | None = Query(default=None),
    europe: bool | None = Query(default=None),
    country: str | None = Query(default=None),
    cities: list[str] | None = Query(
        default=None,
        description="Keep only jobs in these cities (case-insensitive). Repeat or comma-separate.",
    ),
    language: str | None = Query(
        default=None, description="Keep only jobs in this posting language (ISO)"
    ),
    max_age_days: int | None = Query(
        default=None, ge=1, description="Drop postings older than this many days"
    ),
    min_salary: int | None = Query(
        default=None, ge=1, description="Drop jobs whose stated max pay is below this"
    ),
    min_salary_currency: str | None = Query(
        default=None, description="Currency for min_salary; only same-currency compared"
    ),
    require_salary: bool = Query(default=False, description="Also drop jobs with no stated salary"),
    max_experience_gap: int | None = Query(
        default=None, ge=0, description="Hard-drop jobs needing >N years beyond your experience"
    ),
    ignore_prefs: bool = Query(default=False, description="Ignore saved default filters"),
    settings: Settings = Depends(get_settings),
) -> ShortlistResponse:
    """Cosine-rank embedded jobs against the CV, then adjust for freshness.

    Fit (cosine) is the primary signal; a floored recency decay then reshuffles
    comparably-fit jobs so newer ones rank higher, without burying a clearly-better
    older match. Saved search preferences (remote/europe defaults + blocklist +
    freshness cutoff) apply unless overridden per request or bypassed with ignore_prefs.
    """
    cv = _resolve_cv(session, cv_id)
    if cv.embedding is None:
        raise HTTPException(status_code=409, detail="CV has no embedding")

    # Accept both repeated params (?cities=a&cities=b) and comma lists (?cities=a,b).
    city_list = [c for raw in (cities or []) for c in raw.split(",")] or None

    prefs = SearchPreferences() if ignore_prefs else get_preferences(session)
    filters = preference_filters(
        prefs,
        is_remote=is_remote,
        europe=europe,
        country=country,
        cities=city_list,
        language=language,
        max_age_days=max_age_days,
        min_salary=min_salary,
        min_salary_currency=min_salary_currency,
        require_salary=require_salary,
        max_experience_gap=max_experience_gap,
    )

    # Over-fetch by fit, then re-rank by fit x freshness x experience penalty.
    candidate_limit = min(limit * _CANDIDATE_MULTIPLIER, _MAX_CANDIDATES)
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

    items = [
        ShortlistItem(
            **JobOut.model_validate(job).model_dump(),
            similarity=round(similarity, 4),
            recency_weight=round(recency, 3),
            timezone_overlap_hours=overlap,
            experience_gap=gap,
        )
        for job, similarity, recency, overlap, gap, _score in scored[:limit]
    ]
    annotate_application_status(session, items)
    return ShortlistResponse(cv_id=cv.id, count=len(items), items=items)


def _judge_and_store(session: Session, judge: Judge, cv: Cv, job: Job, refresh: bool) -> Match:
    """Judge one (cv, job) and persist the verdict. Returns the cached row unless refresh."""
    existing = session.scalar(select(Match).where(Match.cv_id == cv.id, Match.job_id == job.id))
    if existing is not None and not refresh:
        return existing
    verdict: MatchVerdict = judge.judge(cv.content, build_job_text(job))
    match = existing or Match(cv_id=cv.id, job_id=job.id)
    match.overall_score = verdict.overall_score
    match.verdict = verdict.verdict.value
    match.one_line_verdict = verdict.one_line_verdict
    match.dimension_scores = verdict.dimension_scores.model_dump()
    match.matched_requirements = [r.model_dump() for r in verdict.matched_requirements]
    match.gaps = verdict.gaps
    match.model = getattr(judge, "model", "")
    session.add(match)
    session.commit()
    session.refresh(match)
    return match


@router.post("/rerank", response_model=list[MatchOut])
def rerank(
    payload: RerankRequest,
    session: Session = Depends(get_session),
    judge: Judge = Depends(get_judge),
) -> list[MatchOut]:
    """Batch-judge the given jobs (the high-precision rerank stage) and return them
    ordered by the LLM judge's score - highest fit first.

    The frontend passes the job_ids it is showing (top of the cosine shortlist), so
    this reranks exactly the visible set. Cached per (cv, job); capped, and needs
    ANTHROPIC_API_KEY (503 without it).
    """
    cv = _resolve_cv(session, payload.cv_id)
    verdicts: list[MatchOut] = []
    for job_id in payload.job_ids[:_MAX_RERANK]:
        job = session.get(Job, job_id)
        if job is None:
            continue
        verdicts.append(_to_match_out(_judge_and_store(session, judge, cv, job, payload.refresh)))
    # Highest judge score first; cosine order (input order) breaks ties stably.
    verdicts.sort(key=lambda m: m.overall_score, reverse=True)
    return verdicts


@router.post("/{job_id}", response_model=MatchOut)
def judge_job(
    job_id: int,
    session: Session = Depends(get_session),
    judge: Judge = Depends(get_judge),
    cv_id: int | None = Query(default=None, description="CV to judge against; defaults to latest"),
    refresh: bool = Query(default=False, description="Re-run the judge even if a verdict exists"),
) -> MatchOut:
    """Run the LLM judge on one job (the rerank stage) and persist the verdict.

    Cached: returns the stored verdict unless `refresh=true`. Needs ANTHROPIC_API_KEY
    (503 without it).
    """
    cv = _resolve_cv(session, cv_id)
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _to_match_out(_judge_and_store(session, judge, cv, job, refresh))


@router.get("/{job_id}", response_model=MatchOut)
def get_match(
    job_id: int,
    session: Session = Depends(get_session),
    cv_id: int | None = Query(
        default=None, description="CV whose verdict to fetch; defaults to latest"
    ),
) -> MatchOut:
    """Return the stored judge verdict for a job. 404 if it has not been judged yet."""
    cv = _resolve_cv(session, cv_id)
    match = session.scalar(select(Match).where(Match.cv_id == cv.id, Match.job_id == job_id))
    if match is None:
        raise HTTPException(status_code=404, detail="not judged yet; POST /match/{job_id} first")
    return _to_match_out(match)
