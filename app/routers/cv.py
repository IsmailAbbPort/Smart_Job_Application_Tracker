"""/cv - store the user's CV and embed it for matching."""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embedder import Embedder, build_cv_document, get_embedder
from app.cv_extract import extract_cv_text
from app.db import get_session
from app.models import Cv
from app.schemas import CvCreate, CvDetail, CvOut, CvUpload

router = APIRouter(prefix="/cv", tags=["cv"])


def _to_out(cv: Cv) -> CvOut:
    return CvOut(
        id=cv.id, label=cv.label, embedded=cv.embedding is not None, created_at=cv.created_at
    )


def _embed_and_store(label: str, content: str, session: Session, embedder: Embedder) -> CvOut:
    """Embed the CV text and persist it. Shared by the text and upload endpoints."""
    vector = embedder.embed([build_cv_document(content)])[0]
    cv = Cv(label=label, content=content, embedding=vector)
    session.add(cv)
    session.commit()
    session.refresh(cv)
    return _to_out(cv)


@router.post("", response_model=CvOut, status_code=201)
def create_cv(
    payload: CvCreate,
    session: Session = Depends(get_session),
    embedder: Embedder = Depends(get_embedder),
) -> CvOut:
    return _embed_and_store(payload.label, payload.content, session, embedder)


@router.post("/upload", response_model=CvOut, status_code=201)
def upload_cv(
    payload: CvUpload,
    session: Session = Depends(get_session),
    embedder: Embedder = Depends(get_embedder),
) -> CvOut:
    """Accept a base64-encoded CV file (PDF or text), extract its text, embed, store."""
    try:
        raw = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="content_base64 is not valid base64") from exc

    content = extract_cv_text(payload.filename, raw)
    if not content:
        raise HTTPException(
            status_code=422, detail="could not extract any text from the uploaded file"
        )
    return _embed_and_store(payload.label, content, session, embedder)


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
