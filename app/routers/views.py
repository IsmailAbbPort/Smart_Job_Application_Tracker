"""/views - named filter presets (saved views), scoped to the caller."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user_optional
from app.db import get_session
from app.models import SavedView, User
from app.schemas import SavedViewCreate, SavedViewOut, SavedViewUpdate

router = APIRouter(prefix="/views", tags=["views"])


def _owner_id(user: User | None) -> int | None:
    return user.id if user else None


def _clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Name cannot be empty.")
    return cleaned


def _get_owned(view_id: int, session: Session, user: User | None) -> SavedView:
    view = session.get(SavedView, view_id)
    if view is None or view.owner_id != _owner_id(user):
        raise HTTPException(status_code=404, detail="view not found")
    return view


@router.get("", response_model=list[SavedViewOut])
def list_views(
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> list[SavedViewOut]:
    rows = session.scalars(
        select(SavedView)
        .where(SavedView.owner_id == _owner_id(user))
        .order_by(SavedView.created_at.desc(), SavedView.id.desc())
    ).all()
    return [SavedViewOut.model_validate(view) for view in rows]


@router.post("", response_model=SavedViewOut, status_code=201)
def create_view(
    payload: SavedViewCreate,
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> SavedViewOut:
    view = SavedView(
        owner_id=_owner_id(user), name=_clean_name(payload.name), filters=payload.filters
    )
    session.add(view)
    session.commit()
    session.refresh(view)
    return SavedViewOut.model_validate(view)


@router.patch("/{view_id}", response_model=SavedViewOut)
def update_view(
    view_id: int,
    payload: SavedViewUpdate,
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> SavedViewOut:
    view = _get_owned(view_id, session, user)
    if payload.name is not None:
        view.name = _clean_name(payload.name)
    if payload.filters is not None:
        view.filters = payload.filters
    session.commit()
    session.refresh(view)
    return SavedViewOut.model_validate(view)


@router.delete("/{view_id}", status_code=204)
def delete_view(
    view_id: int,
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> None:
    view = _get_owned(view_id, session, user)
    session.delete(view)
    session.commit()
