"""/cv - store the user's CV and embed it for matching."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embedder import Embedder, build_cv_document, get_embedder
from app.db import get_session
from app.models import Cv
from app.schemas import CvCreate, CvDetail, CvOut

router = APIRouter(prefix="/cv", tags=["cv"])


def _to_out(cv: Cv) -> CvOut:
    return CvOut(
        id=cv.id, label=cv.label, embedded=cv.embedding is not None, created_at=cv.created_at
    )


@router.post("", response_model=CvOut, status_code=201)
def create_cv(
    payload: CvCreate,
    session: Session = Depends(get_session),
    embedder: Embedder = Depends(get_embedder),
) -> CvOut:
    vector = embedder.embed([build_cv_document(payload.content)])[0]
    cv = Cv(label=payload.label, content=payload.content, embedding=vector)
    session.add(cv)
    session.commit()
    session.refresh(cv)
    return _to_out(cv)


@router.get("", response_model=list[CvOut])
def list_cvs(session: Session = Depends(get_session)) -> list[CvOut]:
    rows = session.scalars(select(Cv).order_by(Cv.created_at.desc())).all()
    return [_to_out(cv) for cv in rows]


@router.get("/{cv_id}", response_model=CvDetail)
def get_cv(cv_id: int, session: Session = Depends(get_session)) -> CvDetail:
    cv = session.get(Cv, cv_id)
    if cv is None:
        raise HTTPException(status_code=404, detail="cv not found")
    return CvDetail(
        id=cv.id,
        label=cv.label,
        embedded=cv.embedding is not None,
        created_at=cv.created_at,
        content=cv.content,
    )
