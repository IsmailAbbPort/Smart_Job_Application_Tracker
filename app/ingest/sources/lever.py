"""Lever adapter. Public board: /v0/postings/{slug}?mode=json.

Response: a top-level JSON array of postings, each {id, text (title),
categories:{location, commitment, team}, workplaceType, createdAt (epoch ms),
descriptionPlain, hostedUrl, ...}.
"""

from __future__ import annotations

import time

import httpx
from sqlalchemy.orm import Session

from app.ingest.base import CanonicalJob
from app.ingest.normalize import looks_remote, parse_dt
from app.ingest.targets import active_targets

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
    full_catalog = True
    fetched_slugs: frozenset[str] | set[str] = frozenset()

    def fetch(self, client: httpx.Client, session: Session) -> list[CanonicalJob]:
        out: list[CanonicalJob] = []
        answered: set[str] = set()
        for target in active_targets(session, NAME):
            resp = client.get(_BASE.format(slug=target.slug))
            if resp.status_code != 200:
                continue
            # Recorded even when the board is empty: that is a board with nothing left
            # to offer, not a board we failed to reach, and the sweep must tell them apart.
            answered.add(target.slug)
            out.extend(parse(resp.json(), slug=target.slug, company=target.company))
            time.sleep(_POLITE_DELAY)
        self.fetched_slugs = answered
        return out
