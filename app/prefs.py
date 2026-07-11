"""Search preferences: the singleton default-filter row and how it becomes filters.

`preference_filters` turns a preferences row + any explicit per-request params into
SQLAlchemy conditions. Explicit params win over the stored defaults; the blocklist
always applies (unless the caller ignores prefs entirely).
"""

from __future__ import annotations

from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import Job, SearchPreferences


def get_preferences(session: Session) -> SearchPreferences:
    """Return the singleton preferences row, creating a permissive default if absent."""
    prefs = session.get(SearchPreferences, 1)
    if prefs is None:
        prefs = SearchPreferences(
            id=1,
            remote_only=False,
            require_european=False,
            exclude_countries=[],
            exclude_cities=[],
        )
        session.add(prefs)
        session.commit()
        session.refresh(prefs)
    return prefs


def preference_filters(
    prefs: SearchPreferences,
    *,
    is_remote: bool | None = None,
    europe: bool | None = None,
    country: str | None = None,
) -> list[ColumnElement[bool]]:
    """Build Job filter conditions from prefs + explicit overrides."""
    conditions: list[ColumnElement[bool]] = []

    # remote: explicit param wins; else the stored default (only filters when on).
    if is_remote is not None:
        conditions.append(Job.is_remote == is_remote)
    elif prefs.remote_only:
        conditions.append(Job.is_remote.is_(True))

    # europe: same precedence.
    if europe is not None:
        conditions.append(Job.is_european == europe)
    elif prefs.require_european:
        conditions.append(Job.is_european.is_(True))

    # explicit country include filter.
    if country is not None:
        conditions.append(func.lower(Job.country) == country.lower())

    # blocklist (always applied). NULLs never match, so they are kept.
    excluded_countries = [c.lower() for c in (prefs.exclude_countries or [])]
    if excluded_countries:
        conditions.append(
            or_(Job.country.is_(None), func.lower(Job.country).notin_(excluded_countries))
        )
    excluded_cities = [c.lower() for c in (prefs.exclude_cities or [])]
    if excluded_cities:
        conditions.append(or_(Job.city.is_(None), func.lower(Job.city).notin_(excluded_cities)))

    return conditions
