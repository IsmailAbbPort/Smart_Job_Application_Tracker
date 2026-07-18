"""/letters - draft a CV-grounded cover letter and audit it for fabrication.

Drafting spends tokens (needs ANTHROPIC_API_KEY -> 503 without it). The letter is
stored per (cv, job); the user edits and saves their own version via PUT (the
human-in-the-loop that keeps this honest - the app never "sends" anything).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.cover_letter import Drafter, get_drafter
from app.ai.judge import build_job_text
from app.db import get_session
from app.models import CoverLetter, Cv, Job
from app.schemas import CoverLetterOut, CoverLetterUpdate, FabricationReport

router = APIRouter(prefix="/letters", tags=["letters"])


def _resolve_cv(session: Session, cv_id: int | None) -> Cv:
    cv = (
        session.get(Cv, cv_id)
        if cv_id
        else session.scalar(select(Cv).order_by(Cv.created_at.desc()).limit(1))
    )
    if cv is None:
        raise HTTPException(status_code=404, detail="no CV found; POST /cv first")
    return cv


def _to_out(letter: CoverLetter) -> CoverLetterOut:
    return CoverLetterOut(
        body=letter.body,
        fabrication=FabricationReport.model_validate(letter.fabrication),
        job_id=letter.job_id,
        cv_id=letter.cv_id,
        model=letter.model,
        edited=letter.edited,
        created_at=letter.created_at,
        updated_at=letter.updated_at,
    )


@router.post("/{job_id}", response_model=CoverLetterOut)
def draft_letter(
    job_id: int,
    session: Session = Depends(get_session),
    drafter: Drafter = Depends(get_drafter),
    cv_id: int | None = Query(default=None, description="CV to draft from; defaults to latest"),
    refresh: bool = Query(default=False, description="Re-draft even if a letter exists"),
) -> CoverLetterOut:
    """Draft a CV-grounded cover letter and audit it. Cached unless refresh=true."""
    cv = _resolve_cv(session, cv_id)
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    existing = session.scalar(
        select(CoverLetter).where(CoverLetter.cv_id == cv.id, CoverLetter.job_id == job.id)
    )
    if existing is not None and not refresh:
        return _to_out(existing)

    result = drafter.write(cv.content, build_job_text(job))
    letter = existing or CoverLetter(cv_id=cv.id, job_id=job.id)
    letter.body = result.body
    letter.fabrication = result.fabrication.model_dump()
    letter.model = getattr(drafter, "model", "")
    letter.edited = False
    session.add(letter)
    session.commit()
    session.refresh(letter)
    return _to_out(letter)


@router.get("/{job_id}", response_model=CoverLetterOut)
def get_letter(
    job_id: int,
    session: Session = Depends(get_session),
    cv_id: int | None = Query(
        default=None, description="CV whose letter to fetch; defaults to latest"
    ),
) -> CoverLetterOut:
    """Return the stored cover letter for a job. 404 if none has been drafted."""
    cv = _resolve_cv(session, cv_id)
    letter = session.scalar(
        select(CoverLetter).where(CoverLetter.cv_id == cv.id, CoverLetter.job_id == job_id)
    )
    if letter is None:
        raise HTTPException(status_code=404, detail="no letter yet; POST /letters/{job_id} first")
    return _to_out(letter)


@router.put("/{job_id}", response_model=CoverLetterOut)
def save_letter(
    job_id: int,
    payload: CoverLetterUpdate,
    session: Session = Depends(get_session),
    cv_id: int | None = Query(
        default=None, description="CV whose letter to update; defaults to latest"
    ),
) -> CoverLetterOut:
    """Save the user's edited letter body. Keeps the last fabrication audit."""
    cv = _resolve_cv(session, cv_id)
    letter = session.scalar(
        select(CoverLetter).where(CoverLetter.cv_id == cv.id, CoverLetter.job_id == job_id)
    )
    if letter is None:
        raise HTTPException(status_code=404, detail="no letter yet; POST /letters/{job_id} first")
    letter.body = payload.body
    letter.edited = True
    session.commit()
    session.refresh(letter)
    return _to_out(letter)
