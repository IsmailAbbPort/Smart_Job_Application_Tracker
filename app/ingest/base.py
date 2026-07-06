"""Source adapter interface + the canonical job shape every adapter maps into.

Design note: each adapter separates *parsing* from *fetching*.
- `parse(payload, ...)` is pure: JSON in, list[CanonicalJob] out. Unit-testable
  against saved fixtures with no network.
- `fetch(client)` does the HTTP and delegates to `parse`.

This split is what makes the adapters cheap to test and keeps network flakiness
out of the test suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx
import yaml

SEED_PATH = Path(__file__).resolve().parent / "target_companies.yaml"


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

    def fetch(self, client: httpx.Client) -> list[CanonicalJob]: ...


def load_targets(ats: str, *, path: Path = SEED_PATH) -> list[dict]:
    """Return verified target companies for one ATS vendor from the seed file."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [c for c in data.get("companies", []) if c.get("ats") == ats]
