"""Greenhouse adapter. Public board: /v1/boards/{slug}/jobs?content=true.

Response: {"jobs": [{id, title, location:{name}, absolute_url, first_published,
updated_at, content (entity-escaped HTML), company_name, ...}]}.
"""

from __future__ import annotations

import time

import httpx
from sqlalchemy.orm import Session

from app.ingest.base import CanonicalJob
from app.ingest.normalize import html_to_text, looks_remote, parse_dt
from app.ingest.targets import active_targets

NAME = "greenhouse"
TTL_SECONDS = 6 * 3600
_BASE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
_POLITE_DELAY = 0.2


def parse(payload: dict, *, slug: str, company: str) -> list[CanonicalJob]:
    jobs: list[CanonicalJob] = []
    for j in payload.get("jobs", []):
        loc = (j.get("location") or {}).get("name")
        jobs.append(
            CanonicalJob(
                source=NAME,
                source_id=f"{slug}:{j['id']}",
                title=j.get("title", "").strip(),
                # Prefer our curated target name over the board's self-reported
                # company_name: Remote.com reports itself as just "Remote", which
                # collides with the work-arrangement. The YAML is our source of truth.
                company=company or j.get("company_name"),
                url=j.get("absolute_url", ""),
                description=html_to_text(j.get("content")),
                location=loc,
                is_remote=looks_remote(loc, j.get("title")),
                posted_at=parse_dt(j.get("first_published") or j.get("updated_at")),
            )
        )
    return jobs


class GreenhouseSource:
    name = NAME
    ttl_seconds = TTL_SECONDS
    full_catalog = True

    def fetch(self, client: httpx.Client, session: Session) -> list[CanonicalJob]:
        out: list[CanonicalJob] = []
        for target in active_targets(session, NAME):
            resp = client.get(_BASE.format(slug=target.slug))
            if resp.status_code != 200:
                continue
            out.extend(parse(resp.json(), slug=target.slug, company=target.company))
            time.sleep(_POLITE_DELAY)
        return out
