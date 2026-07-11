"""/preferences - view and edit the persistent default search filters."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.prefs import get_preferences
from app.schemas import PreferencesOut, PreferencesUpdate

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=PreferencesOut)
def read_preferences(session: Session = Depends(get_session)) -> PreferencesOut:
    return PreferencesOut.model_validate(get_preferences(session))


@router.put("", response_model=PreferencesOut)
def update_preferences(
    payload: PreferencesUpdate, session: Session = Depends(get_session)
) -> PreferencesOut:
    prefs = get_preferences(session)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        # Normalize blocklists: trim, drop blanks, de-duplicate (case-insensitive).
        if field in ("exclude_countries", "exclude_cities") and value is not None:
            seen: dict[str, str] = {}
            for item in value:
                cleaned = item.strip()
                if cleaned:
                    seen.setdefault(cleaned.lower(), cleaned)
            value = list(seen.values())
        setattr(prefs, field, value)
    session.commit()
    session.refresh(prefs)
    return PreferencesOut.model_validate(prefs)
