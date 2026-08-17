"""/preferences - view and edit the persistent default search filters."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user_optional
from app.db import get_session
from app.models import User
from app.prefs import get_preferences
from app.schemas import PreferencesOut, PreferencesUpdate

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=PreferencesOut)
def read_preferences(
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> PreferencesOut:
    return PreferencesOut.model_validate(get_preferences(session, user.id if user else None))


@router.put("", response_model=PreferencesOut)
def update_preferences(
    payload: PreferencesUpdate,
    session: Session = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
) -> PreferencesOut:
    prefs = get_preferences(session, user.id if user else None)
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
        # Codes / keywords are stored lowercased, trimmed, and de-duplicated.
        elif (
            field
            in (
                "known_languages",
                "exclude_remote_regions",
                "exclude_seniorities",
                "exclude_title_keywords",
                "include_role_families",
            )
            and value is not None
        ):
            value = sorted({item.strip().lower() for item in value if item.strip()})
        # A non-positive max age means "no cutoff" (store null).
        elif field == "max_age_days" and value is not None and value <= 0:
            value = None
        # A negative experience gap makes no sense; treat it as "no cutoff".
        elif field == "max_experience_gap" and value is not None and value < 0:
            value = None
        # Years of experience clamps at 0 (negative is meaningless).
        elif field == "years_experience" and value is not None and value < 0:
            value = 0
        setattr(prefs, field, value)
    session.commit()
    session.refresh(prefs)
    return PreferencesOut.model_validate(prefs)
