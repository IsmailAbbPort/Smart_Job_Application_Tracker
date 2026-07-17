"""Search preferences: the singleton default-filter row and how it becomes filters.

`preference_filters` turns a preferences row + any explicit per-request params into
SQLAlchemy conditions. Explicit params win over the stored defaults; the blocklist
always applies (unless the caller ignores prefs entirely).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
            known_languages=[],
            max_age_days=None,
            require_sponsorship=False,
            exclude_remote_regions=[],
            user_utc_offset=None,
            min_timezone_overlap_hours=None,
            min_salary=None,
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
    cities: list[str] | None = None,
    language: str | None = None,
    max_age_days: int | None = None,
    min_salary: int | None = None,
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

    # explicit city include filter: keep jobs whose city is in the list (case-insensitive).
    included_cities = [c.strip().lower() for c in (cities or []) if c.strip()]
    if included_cities:
        conditions.append(func.lower(Job.city).in_(included_cities))

    # explicit posting-language include filter.
    if language is not None:
        conditions.append(func.lower(Job.language) == language.lower())

    # known-languages filter (Tier 2): drop jobs written in a language the user does
    # not read. Empty list = off. NULL language (undetected) is kept, matching the
    # blocklist philosophy of never dropping unknowns. This uses the *posting*
    # language as a proxy; English postings that still demand another language are
    # caught by the LLM judge (which reads required_languages / the full text).
    known = [c.strip().lower() for c in (prefs.known_languages or []) if c.strip()]
    if known:
        conditions.append(or_(Job.language.is_(None), func.lower(Job.language).in_(known)))

    # freshness cutoff: explicit param wins over the stored default. Jobs with no
    # post date are kept (unknown != old), matching the null-kept convention.
    effective_max_age = max_age_days if max_age_days is not None else prefs.max_age_days
    if effective_max_age:
        cutoff = datetime.now(UTC) - timedelta(days=effective_max_age)
        conditions.append(or_(Job.posted_at.is_(None), Job.posted_at >= cutoff))

    # eligibility: drop jobs that explicitly refuse visa sponsorship (unknown kept).
    if prefs.require_sponsorship:
        conditions.append(or_(Job.visa_sponsorship.is_(None), Job.visa_sponsorship.is_(True)))

    # eligibility: reject remote roles locked to unwanted regions (unknown kept).
    excluded_regions = [
        r.strip().lower() for r in (prefs.exclude_remote_regions or []) if r.strip()
    ]
    if excluded_regions:
        conditions.append(
            or_(Job.remote_region.is_(None), func.lower(Job.remote_region).notin_(excluded_regions))
        )

    # (Timezone-overlap eligibility is applied in the shortlist route, since the
    # overlap math over required_utc_offsets is not portable SQL.)

    # minimum salary: drop jobs whose stated max pay is below the floor. Currency-
    # naive (compares the number regardless of currency); jobs with no stated pay
    # are kept. Explicit param wins over the stored default.
    effective_min_salary = min_salary if min_salary is not None else prefs.min_salary
    if effective_min_salary:
        conditions.append(or_(Job.salary_max.is_(None), Job.salary_max >= effective_min_salary))

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
