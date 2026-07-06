"""/targets - manage the monitored ATS companies at runtime.

Backs a future UI: list, add, toggle-active, and delete target companies without
a redeploy. Ingestion reads only `active` targets.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import TargetCompany
from app.schemas import TargetCompanyCreate, TargetCompanyOut, TargetCompanyUpdate

router = APIRouter(prefix="/targets", tags=["targets"])

_VENDORS = {"greenhouse", "lever", "ashby"}


@router.get("", response_model=list[TargetCompanyOut])
def list_targets(
    session: Session = Depends(get_session),
    ats: str | None = Query(default=None),
    active: bool | None = Query(default=None),
) -> list[TargetCompany]:
    filters = []
    if ats is not None:
        filters.append(TargetCompany.ats == ats)
    if active is not None:
        filters.append(TargetCompany.active.is_(active))
    return list(
        session.scalars(select(TargetCompany).where(*filters).order_by(TargetCompany.company)).all()
    )


@router.post("", response_model=TargetCompanyOut, status_code=201)
def add_target(
    payload: TargetCompanyCreate, session: Session = Depends(get_session)
) -> TargetCompany:
    if payload.ats not in _VENDORS:
        raise HTTPException(status_code=422, detail=f"ats must be one of {sorted(_VENDORS)}")
    target = TargetCompany(
        company=payload.company,
        ats=payload.ats,
        slug=payload.slug,
        hq=payload.hq,
        remote_policy=payload.remote_policy,
        active=True,
    )
    session.add(target)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="target (ats, slug) already exists") from None
    session.refresh(target)
    return target


@router.patch("/{target_id}", response_model=TargetCompanyOut)
def update_target(
    target_id: int, payload: TargetCompanyUpdate, session: Session = Depends(get_session)
) -> TargetCompany:
    target = session.get(TargetCompany, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    target.active = payload.active
    session.commit()
    session.refresh(target)
    return target


@router.delete("/{target_id}", status_code=204)
def delete_target(target_id: int, session: Session = Depends(get_session)) -> None:
    target = session.get(TargetCompany, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    session.delete(target)
    session.commit()
