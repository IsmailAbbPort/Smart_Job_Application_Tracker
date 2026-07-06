"""Ashby adapter. Public board: /posting-api/job-board/{slug}?includeCompensation=true.

Response: {"jobs": [{id, title, location, isRemote (bool), workplaceType, isListed,
publishedAt, jobUrl, descriptionPlain, address:{postalAddress:{...}}, ...}]}.
"""

from __future__ import annotations

import time

import httpx

from app.ingest.base import CanonicalJob, load_targets
from app.ingest.normalize import parse_dt

NAME = "ashby"
TTL_SECONDS = 6 * 3600
_BASE = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
_POLITE_DELAY = 0.2


def parse(payload: dict, *, slug: str, company: str) -> list[CanonicalJob]:
    jobs: list[CanonicalJob] = []
    for j in payload.get("jobs", []):
        # Skip unlisted/draft postings.
        if j.get("isListed") is False:
            continue
        jobs.append(
            CanonicalJob(
                source=NAME,
                source_id=f"{slug}:{j['id']}",
                title=(j.get("title") or "").strip(),
                company=company,
                url=j.get("jobUrl") or j.get("applyUrl", ""),
                description=(j.get("descriptionPlain") or "").strip(),
                location=j.get("location"),
                is_remote=bool(j.get("isRemote")),
                posted_at=parse_dt(j.get("publishedAt")),
            )
        )
    return jobs


class AshbySource:
    name = NAME
    ttl_seconds = TTL_SECONDS

    def fetch(self, client: httpx.Client) -> list[CanonicalJob]:
        out: list[CanonicalJob] = []
        for target in load_targets(NAME):
            slug, company = target["slug"], target["company"]
            resp = client.get(_BASE.format(slug=slug))
            if resp.status_code != 200:
                continue
            out.extend(parse(resp.json(), slug=slug, company=company))
            time.sleep(_POLITE_DELAY)
        return out
