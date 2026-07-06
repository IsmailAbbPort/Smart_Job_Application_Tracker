"""Lever adapter. Public board: /v0/postings/{slug}?mode=json.

Response: a top-level JSON array of postings, each {id, text (title),
categories:{location, commitment, team}, workplaceType, createdAt (epoch ms),
descriptionPlain, hostedUrl, ...}.
"""

from __future__ import annotations

import time

import httpx

from app.ingest.base import CanonicalJob, load_targets
from app.ingest.normalize import looks_remote, parse_dt

NAME = "lever"
TTL_SECONDS = 6 * 3600
_BASE = "https://api.lever.co/v0/postings/{slug}?mode=json"
_POLITE_DELAY = 0.2


def parse(payload: list, *, slug: str, company: str) -> list[CanonicalJob]:
    jobs: list[CanonicalJob] = []
    for j in payload:
        categories = j.get("categories") or {}
        loc = categories.get("location")
        workplace = j.get("workplaceType")
        jobs.append(
            CanonicalJob(
                source=NAME,
                source_id=f"{slug}:{j['id']}",
                title=(j.get("text") or "").strip(),
                company=company,
                url=j.get("hostedUrl") or j.get("applyUrl", ""),
                description=(j.get("descriptionPlain") or "").strip(),
                location=loc,
                is_remote=looks_remote(workplace, loc),
                posted_at=parse_dt(j.get("createdAt")),
            )
        )
    return jobs


class LeverSource:
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
