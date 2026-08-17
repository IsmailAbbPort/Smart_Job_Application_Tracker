"""Search preferences: the singleton default-filter row and how it becomes filters.

`preference_filters` turns a preferences row + any explicit per-request params into
SQLAlchemy conditions. Explicit params win over the stored defaults; the blocklist
always applies (unless the caller ignores prefs entirely).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.geo_region import region_country_names
from app.models import Job, SearchPreferences


def get_preferences(session: Session, owner_id: int | None = None) -> SearchPreferences:
    """Return the owner's preferences row, creating a permissive default if absent.

    owner_id is None for guests (the pre-accounts singleton behaviour).
    """
    prefs = session.scalar(select(SearchPreferences).where(SearchPreferences.owner_id == owner_id))
    if prefs is None:
        prefs = SearchPreferences(
            owner_id=owner_id,
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
            years_experience=None,
            max_experience_gap=None,
            exclude_seniorities=[],
            exclude_title_keywords=[],
            include_role_families=[],
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
    region: str | None = None,
    country: str | None = None,
    cities: list[str] | None = None,
    language: str | None = None,
    max_age_days: int | None = None,
    min_salary: int | None = None,
    min_salary_currency: str | None = None,
    require_salary: bool = False,
    max_experience_gap: int | None = None,
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

    # explicit continent/region include filter: keep jobs whose country falls in the
    # region. Unknown/unmappable regions add no condition (kept permissive).
    if region:
        names = region_country_names(region)
        if names:
            conditions.append(func.lower(Job.country).in_(names))

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

    # minimum salary: drop jobs whose stated max pay is below the floor. Jobs with no
    # stated pay are kept unless require_salary is set. When a currency is given, only
    # same-currency jobs are compared (a EUR floor can't judge a USD figure), so
    # different-currency jobs are kept. Explicit param wins over the stored default.
    effective_min_salary = min_salary if min_salary is not None else prefs.min_salary
    if effective_min_salary:
        keep = [Job.salary_max >= effective_min_salary]
        if not require_salary:
            keep.append(Job.salary_max.is_(None))
        if min_salary_currency:
            keep.append(func.lower(Job.salary_currency) != min_salary_currency.lower())
        conditions.append(or_(*keep))
    elif require_salary:
        conditions.append(Job.salary_max.is_not(None))

    # seniority exclude: drop roles whose inferred level is unwanted (unknown kept).
    excluded_levels = [s.strip().lower() for s in (prefs.exclude_seniorities or []) if s.strip()]
    if excluded_levels:
        conditions.append(
            or_(Job.seniority.is_(None), func.lower(Job.seniority).notin_(excluded_levels))
        )

    # title blocklist: drop jobs whose title contains any excluded keyword.
    for kw in [k.strip().lower() for k in (prefs.exclude_title_keywords or []) if k.strip()]:
        conditions.append(~func.lower(Job.title).contains(kw))

    # role-family include: keep only jobs whose inferred family is wanted (unknown
    # kept, matching the null-kept convention). Empty list = no role filtering.
    included_families = [
        f.strip().lower() for f in (prefs.include_role_families or []) if f.strip()
    ]
    if included_families:
        conditions.append(
            or_(Job.role_family.is_(None), func.lower(Job.role_family).in_(included_families))
        )

    # experience hard cutoff (optional; soft de-ranking is done in the shortlist).
    # Drop jobs that require more than max_experience_gap years beyond the user's.
    # Needs the user's years; unknown-requirement jobs are kept. Explicit param wins.
    gap_cutoff = max_experience_gap if max_experience_gap is not None else prefs.max_experience_gap
    if gap_cutoff is not None and prefs.years_experience is not None:
        conditions.append(
            or_(
                Job.min_years_experience.is_(None),
                Job.min_years_experience <= prefs.years_experience + gap_cutoff,
            )
        )

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
