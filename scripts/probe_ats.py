"""Probe target companies' public ATS boards and report which slugs are live.

Run this before trusting the slugs in app/ingest/target_companies.yaml. Board
slugs go stale and companies migrate ATS vendors, so we verify before seeding.

For each company it hits the vendor's public, no-auth JSON endpoint, reports
LIVE/DEAD + open-job count, and (with --try-all, default on for reserves) checks
the other two vendors when the declared one is dead.

Usage (needs httpx + pyyaml):
    python scripts/probe_ats.py                # probe primary list
    python scripts/probe_ats.py --reserves     # probe reserves too
    python scripts/probe_ats.py --try-all      # if declared ATS is dead, try the others
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
import yaml

SEED = Path(__file__).resolve().parent.parent / "app" / "ingest" / "target_companies.yaml"

# Identify ourselves politely rather than masquerading as a browser.
HEADERS = {"User-Agent": "SmartJobTracker/0.1 (portfolio project; polite ATS probe)"}
TIMEOUT = 12.0

VENDORS = ("greenhouse", "lever", "ashby")


def endpoint(ats: str, slug: str) -> str:
    if ats == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    if ats == "lever":
        return f"https://api.lever.co/v0/postings/{slug}?mode=json"
    if ats == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    raise ValueError(f"unknown ats: {ats}")


def count_jobs(ats: str, data: object) -> int | None:
    """Extract the open-job count from each vendor's differently-shaped payload."""
    try:
        if ats == "lever":
            # Lever returns a top-level JSON array of postings.
            return len(data) if isinstance(data, list) else None
        if ats in ("greenhouse", "ashby"):
            # Both wrap postings in a "jobs" array.
            return len(data["jobs"]) if isinstance(data, dict) else None
    except (KeyError, TypeError):
        return None
    return None


def probe_one(client: httpx.Client, ats: str, slug: str) -> tuple[str, int | None]:
    """Return (status, job_count). status is LIVE, EMPTY, DEAD, or a short error."""
    try:
        resp = client.get(endpoint(ats, slug))
    except httpx.RequestError as exc:
        return (f"ERR:{type(exc).__name__}", None)
    if resp.status_code == 404:
        return ("DEAD", None)
    if resp.status_code != 200:
        return (f"HTTP:{resp.status_code}", None)
    try:
        data = resp.json()
    except ValueError:
        return ("BADJSON", None)
    n = count_jobs(ats, data)
    if n is None:
        return ("BADSHAPE", None)
    return ("LIVE" if n > 0 else "EMPTY", n)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe target companies' ATS boards.")
    parser.add_argument("--reserves", action="store_true", help="include the reserves list")
    parser.add_argument(
        "--try-all",
        action="store_true",
        help="when the declared ATS is dead, also try the other two vendors",
    )
    args = parser.parse_args()

    seed = yaml.safe_load(SEED.read_text(encoding="utf-8"))
    rows = list(seed["companies"])
    if args.reserves:
        rows += list(seed.get("reserves", []))

    live: list[str] = []
    print(f"{'COMPANY':<16} {'ATS':<11} {'SLUG':<14} {'STATUS':<12} JOBS")
    print("-" * 62)

    with httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
        for row in rows:
            company, ats, slug = row["company"], row["ats"], row["slug"]
            status, n = probe_one(client, ats, slug)

            # Reserves default to try-all; primaries only if asked.
            declared_dead = not status.startswith(("LIVE", "EMPTY"))
            if declared_dead and args.try_all:
                for alt in (v for v in VENDORS if v != ats):
                    alt_status, alt_n = probe_one(client, alt, slug)
                    if alt_status.startswith(("LIVE", "EMPTY")):
                        status, n, ats = f"{alt_status}(as {alt})", alt_n, alt
                        break

            print(f"{company:<16} {ats:<11} {slug:<14} {status:<12} {n if n is not None else '-'}")
            if status.startswith("LIVE"):
                live.append(f"{slug} ({ats}, {n} jobs)")

    print("-" * 62)
    print(f"\nLIVE with open jobs ({len(live)}/{len(rows)}):")
    for item in live:
        print(f"  - {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
