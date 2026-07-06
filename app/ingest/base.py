"""Source adapter interface + the canonical job shape every adapter maps into.

Design note: each adapter separates *parsing* from *fetching*.
- `parse(payload, ...)` is pure: JSON in, list[CanonicalJob] out. Unit-testable
  against saved fixtures with no network.
- `fetch(client, session)` does the HTTP and delegates to `parse`. The session lets
  ATS adapters read their active target companies from the DB (aggregators ignore it).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx
from sqlalchemy.orm import Session


@dataclass(slots=True)
class CanonicalJob:
    """One posting in our internal shape, pre-normalization."""

    source: str
    source_id: str
    title: str
    company: str
    url: str
    description: str = ""
    location: str | None = None
    is_remote: bool = False
    posted_at: datetime | None = None


class Source(Protocol):
    """The contract every source adapter satisfies."""

    name: str
    ttl_seconds: int

    def fetch(self, client: httpx.Client, session: Session) -> list[CanonicalJob]: ...
