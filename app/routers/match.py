"""/match - embed jobs and shortlist them against the CV (retrieve stage)."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.decide import CandidateRules, decide, rules_from_preferences, verdict_from_facts
from app.ai.embedder import Embedder, build_job_document, get_embedder
from app.ai.judge import Judge, build_job_text, get_judge
from app.ai.role_family import AnthropicRoleClassifier, RoleClassifier, get_role_classifier
from app.applications import annotate_application_status, job_visible_to
from app.auth import get_current_user_optional
from app.config import Settings, get_settings
from app.db import get_session
from app.models import MANUAL_SOURCE, Cv, Job, Match, SearchPreferences, User
from app.prefs import get_preferences
from app.ratelimit import charge
from app.schemas import (
    JobOut,
    MatchOut,
    RerankRequest,
    ShortlistItem,
    ShortlistResponse,
)
from app.shortlist import (
    ShortlistQuery,
    aggregator_ids,
    check_shortlist_liveness,
    rank_shortlist,
    resolve_cv,
)

# Cap on how many jobs one rerank call will judge (each is an LLM call + spend).
_MAX_RERANK = 20

router = APIRouter(prefix="/match", tags=["match"])


def _resolve_cv(session: Session, cv_id: int | None, owner_id: int | None = None) -> Cv:
    """The requested CV, or the owner's most recent one. 404 if there is none."""
    cv = resolve_cv(session, cv_id, owner_id)
    if cv is None:
        raise HTTPException(status_code=404, detail="no CV found; POST /cv first")
    return cv


def _rules(session: Session, owner_id: int | None) -> CandidateRules:
    return rules_from_preferences(get_preferences(session, owner_id))


def _to_match_out(match: Match, rules: CandidateRules, job: Job | None) -> MatchOut | None:
    """The stored facts graded under the user's current rules; None for a pre-facts row."""
    verdict = verdict_from_facts(match.facts, rules, job.is_remote if job else None)
    if verdict is None:
        return None
    return MatchOut(
        job_id=match.job_id,
        cv_id=match.cv_id,
        model=match.model,
        created_at=match.created_at,
        **verdict.model_dump(),
    )


@router.post("/embed-jobs")
def embed_jobs(
    session: Session = Depends(get_session),
    embedder: Embedder = Depends(get_embedder),
    force: bool = Query(default=False, description="Re-embed all jobs, not just missing ones"),
    limit: int = Query(default=5000, ge=1, le=10000, description="Max jobs to embed this call"),
) -> dict:
    """Embed jobs that lack an embedding (or all, with force)."""
    # Manual jobs never enter the cosine shortlist, so embedding them is wasted spend.
    stmt = select(Job).where(Job.source != MANUAL_SOURCE)
    if not force:
        stmt = stmt.where(Job.embedding.is_(None))
    jobs = session.scalars(stmt.limit(limit)).all()

    if jobs:
        vectors = embedder.embed([build_job_document(j) for j in jobs])
        for job, vector in zip(jobs, vectors, strict=True):
            job.embedding = vector
        session.commit()

    remaining = session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.embedding.is_(None), Job.source != MANUAL_SOURCE)
    )
    return {"embedded": len(jobs), "remaining_unembedded": remaining or 0}


@router.post("/classify-roles")
def classify_roles(
    session: Session = Depends(get_session),
    llm: AnthropicRoleClassifier | None = Depends(get_role_classifier),
    settings: Settings = Depends(get_settings),
    force: bool = Query(default=False, description="Re-classify all jobs, not just unclassified"),
    limit: int = Query(default=6000, ge=1, le=20000, description="Max jobs to classify this call"),
) -> dict:
    """Assign each job a role_family from its title (see app/ai/role_family.py).

    Uses the LLM classifier when ANTHROPIC_API_KEY is set, else the embedding
    fallback (which needs OPENAI_API_KEY; 503 when neither is configured).
    Idempotent: classifies rows without a family unless force re-does all.
    """
    stmt = select(Job).where(Job.source != MANUAL_SOURCE)
    if not force:
        stmt = stmt.where(Job.role_family.is_(None))
    jobs = session.scalars(stmt.limit(limit)).all()

    distribution: dict[str, int] = {}
    if jobs:
        titles = [j.title for j in jobs]
        if llm is not None:
            families = llm.classify_titles(titles)
        else:
            embedder = get_embedder(settings)
            classifier = RoleClassifier.from_embedder(
                embedder,
                min_similarity=settings.role_min_similarity,
                min_margin=settings.role_min_margin,
            )
            families = classifier.classify_titles(titles, embedder)
        for job, family in zip(jobs, families, strict=True):
            job.role_family = family
            key = family or "unclassified"
            distribution[key] = distribution.get(key, 0) + 1
        session.commit()

    remaining = session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.role_family.is_(None), Job.source != MANUAL_SOURCE)
    )
    return {
        "classified": len(jobs),
        "remaining_unclassified": remaining or 0,
        "distribution": distribution,
    }


@router.get("/shortlist", response_model=ShortlistResponse)
def shortlist(
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    cv_id: int | None = Query(default=None, description="CV to match; defaults to the latest"),
    limit: int = Query(default=25, ge=1, le=100),
    is_remote: bool | None = Query(default=None),
    europe: bool | None = Query(default=None),
    region: str | None = Query(
        default=None,
        description="Keep only jobs on this continent/region "
        "(africa|asia|europe|latin_america|north_america|oceania)",
    ),
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
    user: User | None = Depends(get_current_user_optional),
) -> ShortlistResponse:
    """Cosine-rank embedded jobs against the CV, then adjust for freshness
    (see app/shortlist.py).

    Also remembers this query (the nightly liveness sweep replays it) and, after
    responding, checks the shown Arbeitnow/Remotive jobs for expired postings.
    """
    owner_id = user.id if user else None
    cv = _resolve_cv(session, cv_id, owner_id)
    if cv.embedding is None:
        raise HTTPException(status_code=409, detail="CV has no embedding")

    # Accept both repeated params (?cities=a&cities=b) and comma lists (?cities=a,b).
    city_list = [c for raw in (cities or []) for c in raw.split(",")] or None
    query = ShortlistQuery(
        cv_id=cv_id,
        limit=limit,
        is_remote=is_remote,
        europe=europe,
        region=region,
        country=country,
        cities=city_list,
        language=language,
        max_age_days=max_age_days,
        min_salary=min_salary,
        min_salary_currency=min_salary_currency,
        require_salary=require_salary,
        max_experience_gap=max_experience_gap,
        ignore_prefs=ignore_prefs,
    )

    saved = get_preferences(session, owner_id)
    saved.last_shortlist_query = query.as_dict()
    session.commit()
    prefs = SearchPreferences() if ignore_prefs else saved
    rows = rank_shortlist(session, cv, prefs, query, settings)

    items = [
        ShortlistItem(
            **JobOut.model_validate(job).model_dump(),
            similarity=round(similarity, 4),
            recency_weight=round(recency, 3),
            timezone_overlap_hours=overlap,
            experience_gap=gap,
        )
        for job, similarity, recency, overlap, gap in rows
    ]
    annotate_application_status(session, items, owner_id)

    to_check = aggregator_ids(rows)
    if to_check:
        background_tasks.add_task(check_shortlist_liveness, session.get_bind(), to_check, settings)
    return ShortlistResponse(cv_id=cv.id, count=len(items), items=items)


def _judge_and_store(
    session: Session,
    judge: Judge,
    cv: Cv,
    job: Job,
    refresh: bool,
    rules: CandidateRules,
    charge_cm: Callable[[], AbstractContextManager[None]] | None = None,
) -> Match:
    """Judge one (cv, job) and persist the facts. Returns the cached row unless refresh
    (a row judged before facts existed is re-judged).

    charge_cm (when given) wraps the actual LLM call so the rate limiter charges only
    a real judge invocation, never a cache hit (see app/ratelimit.charge).
    """
    existing = session.scalar(select(Match).where(Match.cv_id == cv.id, Match.job_id == job.id))
    if existing is not None and existing.facts and not refresh:
        return existing
    with charge_cm() if charge_cm else nullcontext():
        facts = judge.judge(cv.content, build_job_text(job))
    verdict = decide(facts, rules, job.is_remote)
    match = existing or Match(cv_id=cv.id, job_id=job.id)
    match.facts = facts.model_dump(mode="json")
    match.overall_score = verdict.overall_score
    match.verdict = verdict.verdict.value
    match.one_line_verdict = verdict.one_line_verdict
    match.dimension_scores = {}
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
    request: Request,
    session: Session = Depends(get_session),
    judge: Judge = Depends(get_judge),
    user: User | None = Depends(get_current_user_optional),
) -> list[MatchOut]:
    """Batch-judge the given jobs (the high-precision rerank stage) and return them
    ordered by the LLM judge's score - highest fit first.

    The frontend passes the job_ids it is showing (top of the cosine shortlist), so
    this reranks exactly the visible set. Cached per (cv, job); capped, and needs
    ANTHROPIC_API_KEY (503 without it).
    """
    owner_id = user.id if user else None
    cv = _resolve_cv(session, payload.cv_id, owner_id)
    rules = _rules(session, owner_id)
    verdicts: list[MatchOut] = []
    for job_id in payload.job_ids[:_MAX_RERANK]:
        job = session.get(Job, job_id)
        if job is None or not job_visible_to(session, job, owner_id):
            continue
        out = _to_match_out(
            _judge_and_store(
                session,
                judge,
                cv,
                job,
                payload.refresh,
                rules,
                charge_cm=lambda: charge(session, request, owner_id, "judge"),
            ),
            rules,
            job,
        )
        if out is not None:
            verdicts.append(out)
    # Highest judge score first; cosine order (input order) breaks ties stably.
    verdicts.sort(key=lambda m: m.overall_score, reverse=True)
    return verdicts


@router.post("/{job_id}", response_model=MatchOut)
def judge_job(
    job_id: int,
    request: Request,
    session: Session = Depends(get_session),
    judge: Judge = Depends(get_judge),
    cv_id: int | None = Query(default=None, description="CV to judge against; defaults to latest"),
    refresh: bool = Query(default=False, description="Re-run the judge even if a verdict exists"),
    user: User | None = Depends(get_current_user_optional),
) -> MatchOut:
    """Run the LLM judge on one job (the rerank stage) and persist the verdict.

    Cached: returns the stored verdict unless `refresh=true`. Needs ANTHROPIC_API_KEY
    (503 without it). Rate-limited per day (429 when the cap is hit).
    """
    owner_id = user.id if user else None
    cv = _resolve_cv(session, cv_id, owner_id)
    job = session.get(Job, job_id)
    if job is None or not job_visible_to(session, job, owner_id):
        raise HTTPException(status_code=404, detail="job not found")
    rules = _rules(session, owner_id)
    out = _to_match_out(
        _judge_and_store(
            session,
            judge,
            cv,
            job,
            refresh,
            rules,
            charge_cm=lambda: charge(session, request, owner_id, "judge"),
        ),
        rules,
        job,
    )
    if out is None:
        raise HTTPException(status_code=502, detail="the judge returned unreadable facts")
    return out


@router.get("/{job_id}", response_model=MatchOut)
def get_match(
    job_id: int,
    session: Session = Depends(get_session),
    cv_id: int | None = Query(
        default=None, description="CV whose verdict to fetch; defaults to latest"
    ),
    user: User | None = Depends(get_current_user_optional),
) -> MatchOut:
    """Return the stored judge verdict for a job. 404 if it has not been judged yet."""
    owner_id = user.id if user else None
    cv = _resolve_cv(session, cv_id, owner_id)
    match = session.scalar(select(Match).where(Match.cv_id == cv.id, Match.job_id == job_id))
    out = (
        _to_match_out(match, _rules(session, owner_id), session.get(Job, job_id))
        if match is not None
        else None
    )
    if out is None:
        raise HTTPException(status_code=404, detail="not judged yet; POST /match/{job_id} first")
    return out
