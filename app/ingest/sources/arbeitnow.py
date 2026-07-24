"""Arbeitnow adapter (EU backbone aggregator). Public feed: /api/job-board-api.

Response: {"data": [{slug, company_name, title, description (HTML), remote (bool),
url, location, created_at (epoch s), tags, job_types}], "links", "meta"}. Paginated;
we pull a bounded number of pages to stay polite.
"""

from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.ingest.base import CanonicalJob
from app.ingest.normalize import html_to_text, parse_dt

NAME = "arbeitnow"
TTL_SECONDS = 3600
_BASE = "https://www.arbeitnow.com/api/job-board-api"
_MAX_PAGES = 3


def parse(payload: dict) -> list[CanonicalJob]:
    jobs: list[CanonicalJob] = []
    for j in payload.get("data", []):
        jobs.append(
            CanonicalJob(
                source=NAME,
                source_id=j["slug"],
                title=(j.get("title") or "").strip(),
                company=(j.get("company_name") or "").strip(),
                url=j.get("url", ""),
                description=html_to_text(j.get("description")),
                location=j.get("location"),
                is_remote=bool(j.get("remote")),
                posted_at=parse_dt(j.get("created_at")),
            )
        )
    return jobs


class ArbeitnowSource:
    name = NAME
    ttl_seconds = TTL_SECONDS
    full_catalog = False

    def fetch(self, client: httpx.Client, session: Session) -> list[CanonicalJob]:
        out: list[CanonicalJob] = []
        url: str | None = _BASE
        for _ in range(_MAX_PAGES):
            if not url:
                break
            resp = client.get(url)
            if resp.status_code != 200:
                break
            payload = resp.json()
            out.extend(parse(payload))
            url = (payload.get("links") or {}).get("next")
        return out
