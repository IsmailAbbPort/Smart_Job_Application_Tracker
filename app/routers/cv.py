"""/cv - store the user's CV and embed it for matching."""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.embedder import Embedder, build_cv_document, get_embedder
from app.ai.role_family import AnthropicRoleClassifier, get_role_classifier
from app.auth import get_current_user_optional
from app.cv_extract import extract_cv_text, looks_like_pdf
from app.db import get_session
from app.models import CoverLetter, Cv, Match, User
from app.schemas import CvCreate, CvDetail, CvFileReplace, CvOut, CvUpdate, CvUpload

router = APIRouter(prefix="/cv", tags=["cv"])

# Upload limits (surfaced in the UI too). 5 MB, PDF or plain text only.
MAX_CV_BYTES = 5 * 1024 * 1024


def _owner_id(user: User | None) -> int | None:
    return user.id if user else None


def _to_out(cv: Cv) -> CvOut:
    return CvOut(
        id=cv.id,
        label=cv.label,
        embedded=cv.embedding is not None,
        created_at=cv.created_at,
        filename=cv.filename,
        content_type=cv.content_type,
        size_bytes=cv.size_bytes,
        suggested_role_families=cv.suggested_role_families or [],
    )


def _embed_and_store(
    label: str,
    content: str,
    session: Session,
    embedder: Embedder,
    owner_id: int | None,
    role_classifier: AnthropicRoleClassifier | None,
    *,
    file_data: bytes | None = None,
    filename: str | None = None,
    content_type: str | None = None,
) -> CvOut:
    """Embed the CV text, suggest role families, and persist it. Shared by the text and
    upload endpoints."""
    vector = embedder.embed([build_cv_document(content)])[0]
    suggestions = role_classifier.suggest_families(content) if role_classifier else []
    cv = Cv(
        owner_id=owner_id,
        label=label,
        content=content,
        embedding=vector,
        suggested_role_families=suggestions,
        file_data=file_data,
        filename=filename,
        content_type=content_type,
        size_bytes=len(file_data) if file_data is not None else None,
    )
    session.add(cv)
    session.commit()
    session.refresh(cv)
    return _to_out(cv)


def _decode_cv_file(filename: str, content_base64: str) -> tuple[bytes, str, str]:
    """Decode + validate an uploaded CV file into (raw bytes, extracted text, content type)."""
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="content_base64 is not valid base64") from exc

    if len(raw) > MAX_CV_BYTES:
        raise HTTPException(status_code=413, detail="CV file is too large (max 5 MB).")

    is_pdf = looks_like_pdf(filename, raw)
    if not is_pdf and not filename.lower().endswith(".txt"):
        raise HTTPException(status_code=422, detail="Only PDF or .txt files are accepted.")

    content = extract_cv_text(filename, raw)
    if not content:
        raise HTTPException(
            status_code=422, detail="could not extract any text from the uploaded file"
        )
    return raw, content, "application/pdf" if is_pdf else "text/plain"


@router.post("", response_model=CvOut, status_code=201)
def create_cv(
    payload: CvCreate,
    session: Session = Depends(get_session),
    embedder: Embedder = Depends(get_embedder),
    role_classifier: AnthropicRoleClassifier | None = Depends(get_role_classifier),
    user: User | None = Depends(get_current_user_optional),
) -> CvOut:
    return _embed_and_store(
        payload.label, payload.content, session, embedder, _owner_id(user), role_classifier
    )


@router.post("/upload", response_model=CvOut, status_code=201)
def upload_cv(
    payload: CvUpload,
    session: Session = Depends(get_session),
    embedder: Embedder = Depends(get_embedder),
    role_classifier: AnthropicRoleClassifier | None = Depends(get_role_classifier),
    user: User | None = Depends(get_current_user_optional),
) -> CvOut:
    """Accept a base64-encoded CV file (PDF or text), extract its text, embed, store."""
    raw, content, content_type = _decode_cv_file(payload.filename, payload.content_base64)
    return _embed_and_store(
        payload.label,
        content,
        session,
        embedder,
        _owner_id(user),
        role_classifier,
        file_data=raw,
        filename=payload.filename,
        content_type=content_type,
    )


@router.get("", response_model=list[CvOut])
def list_cvs(
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> list[CvOut]:
    rows = session.scalars(
        select(Cv).where(Cv.owner_id == _owner_id(user)).order_by(Cv.created_at.desc())
    ).all()
    return [_to_out(cv) for cv in rows]


def _get_owned(cv_id: int, session: Session, user: User | None) -> Cv:
    cv = session.get(Cv, cv_id)
    if cv is None or cv.owner_id != _owner_id(user):
        raise HTTPException(status_code=404, detail="cv not found")
    return cv


@router.get("/{cv_id}", response_model=CvDetail)
def get_cv(
    cv_id: int,
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> CvDetail:
    cv = _get_owned(cv_id, session, user)
    return CvDetail(
        id=cv.id,
        label=cv.label,
        embedded=cv.embedding is not None,
        created_at=cv.created_at,
        content=cv.content,
        filename=cv.filename,
        content_type=cv.content_type,
        size_bytes=cv.size_bytes,
        suggested_role_families=cv.suggested_role_families or [],
    )


@router.patch("/{cv_id}", response_model=CvOut)
def update_cv(
    cv_id: int,
    payload: CvUpdate,
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> CvOut:
    cv = _get_owned(cv_id, session, user)
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=422, detail="Label cannot be empty.")
    cv.label = label
    session.commit()
    session.refresh(cv)
    return _to_out(cv)


@router.put("/{cv_id}/file", response_model=CvOut)
def replace_cv_file(
    cv_id: int,
    payload: CvFileReplace,
    session: Session = Depends(get_session),
    embedder: Embedder = Depends(get_embedder),
    role_classifier: AnthropicRoleClassifier | None = Depends(get_role_classifier),
    user: User | None = Depends(get_current_user_optional),
) -> CvOut:
    """Swap a CV's file (keeping its label): re-extract, re-embed, re-suggest role
    families, and drop the verdicts and letters grounded in the old text, since they
    are now stale."""
    cv = _get_owned(cv_id, session, user)
    raw, content, content_type = _decode_cv_file(payload.filename, payload.content_base64)
    cv.content = content
    cv.embedding = embedder.embed([build_cv_document(content)])[0]
    cv.suggested_role_families = (
        role_classifier.suggest_families(content) if role_classifier else []
    )
    cv.file_data = raw
    cv.filename = payload.filename
    cv.content_type = content_type
    cv.size_bytes = len(raw)
    session.execute(delete(Match).where(Match.cv_id == cv.id))
    session.execute(delete(CoverLetter).where(CoverLetter.cv_id == cv.id))
    session.commit()
    session.refresh(cv)
    return _to_out(cv)


@router.delete("/{cv_id}", status_code=204)
def delete_cv(
    cv_id: int,
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> None:
    cv = _get_owned(cv_id, session, user)
    session.delete(cv)
    session.commit()


@router.get("/{cv_id}/file")
def get_cv_file(
    cv_id: int,
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> Response:
    """Serve the original uploaded file so the UI can preview it (inline)."""
    cv = _get_owned(cv_id, session, user)
    if cv.file_data is None:
        raise HTTPException(status_code=404, detail="no file stored for this CV")
    disposition = f'inline; filename="{(cv.filename or "cv").replace(chr(34), "")}"'
    return Response(
        content=cv.file_data,
        media_type=cv.content_type or "application/octet-stream",
        headers={"Content-Disposition": disposition},
    )
