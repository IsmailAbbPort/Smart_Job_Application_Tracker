"""/match - embed jobs and shortlist them against the CV (retrieve stage)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.embedder import Embedder, build_job_document, get_embedder
from app.ai.judge import Judge, build_job_text, get_judge
from app.ai.matching import rank_jobs, recency_weight
from app.applications import annotate_application_status
from app.config import Settings, get_settings
from app.db import get_session
from app.ingest.eligibility import timezone_overlap_hours
from app.models import Cv, Job, Match, SearchPreferences
from app.prefs import get_preferences, preference_filters
from app.schemas import JobOut, MatchOut, MatchVerdict, ShortlistItem, ShortlistResponse

# How many fit-ranked candidates to pull before the recency re-rank. A few times
# the page size is plenty for a gentle, floored decay to reshuffle near-ties.
_CANDIDATE_MULTIPLIER = 3
_MAX_CANDIDATES = 300

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
    )

    # Over-fetch by fit, then re-rank by fit x freshness and keep the top `limit`.
    candidate_limit = min(limit * _CANDIDATE_MULTIPLIER, _MAX_CANDIDATES)
    ranked = rank_jobs(session, list(cv.embedding), filters=filters, limit=candidate_limit)

    now = datetime.now(UTC)
    scored: list[tuple[Job, float, float, int | None]] = []
    for job, similarity in ranked:
        # Timezone-overlap eligibility (see prefs.py: done here, not in SQL).
        overlap = timezone_overlap_hours(job.required_utc_offsets, prefs.user_utc_offset)
        if (
            prefs.min_timezone_overlap_hours is not None
            and overlap is not None
            and overlap < prefs.min_timezone_overlap_hours
        ):
            continue
        weight = recency_weight(
            job.posted_at,
            now,
            half_life_days=settings.recency_half_life_days,
            floor=settings.recency_floor,
        )
        scored.append((job, similarity, weight, overlap))

    scored.sort(key=lambda t: t[1] * t[2], reverse=True)

    items = [
        ShortlistItem(
            **JobOut.model_validate(job).model_dump(),
            similarity=round(similarity, 4),
            recency_weight=round(weight, 3),
            timezone_overlap_hours=overlap,
        )
        for job, similarity, weight, overlap in scored[:limit]
    ]
    annotate_application_status(session, items)
    return ShortlistResponse(cv_id=cv.id, count=len(items), items=items)


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

    existing = session.scalar(select(Match).where(Match.cv_id == cv.id, Match.job_id == job.id))
    if existing is not None and not refresh:
        return _to_match_out(existing)

    verdict: MatchVerdict = judge.judge(cv.content, build_job_text(job))
    model = getattr(judge, "model", "")

    match = existing or Match(cv_id=cv.id, job_id=job.id)
    match.overall_score = verdict.overall_score
    match.verdict = verdict.verdict.value
    match.one_line_verdict = verdict.one_line_verdict
    match.dimension_scores = verdict.dimension_scores.model_dump()
    match.matched_requirements = [r.model_dump() for r in verdict.matched_requirements]
    match.gaps = verdict.gaps
    match.model = model
    session.add(match)
    session.commit()
    session.refresh(match)
    return _to_match_out(match)


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
