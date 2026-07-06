"""Remotive adapter (remote-only aggregator). Public feed: /api/remote-jobs.

IMPORTANT: Remotive hard-limits >2 req/min and asks for ~4 polls/day. One request
returns the whole feed, so the 6h TTL (see TTL_SECONDS) keeps us well within that.
Response: {"jobs": [{id, url, title, company_name, candidate_required_location,
job_type, publication_date (naive ISO), description (HTML), ...}], "0-legal-notice"}.
"""

from __future__ import annotations

import httpx

from app.ingest.base import CanonicalJob
from app.ingest.normalize import html_to_text, parse_dt

NAME = "remotive"
TTL_SECONDS = 6 * 3600  # ~4x/day, honoring Remotive's stated request
_BASE = "https://remotive.com/api/remote-jobs"


def parse(payload: dict) -> list[CanonicalJob]:
    jobs: list[CanonicalJob] = []
    for j in payload.get("jobs", []):
        loc = j.get("candidate_required_location")
        jobs.append(
            CanonicalJob(
                source=NAME,
                source_id=str(j["id"]),
                title=(j.get("title") or "").strip(),
                company=(j.get("company_name") or "").strip(),
                url=j.get("url", ""),
                description=html_to_text(j.get("description")),
                location=loc,
                is_remote=True,  # remote-only board
                posted_at=parse_dt(j.get("publication_date")),
            )
        )
    return jobs


class RemotiveSource:
    name = NAME
    ttl_seconds = TTL_SECONDS

    def fetch(self, client: httpx.Client) -> list[CanonicalJob]:
        resp = client.get(_BASE)
        if resp.status_code != 200:
            return []
        return parse(resp.json())
