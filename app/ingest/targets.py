"""Target companies: seed the DB from YAML, and query the active set.

The YAML (target_companies.yaml) is the initial, verified seed. At runtime the
list lives in the `target_company` table so it can be edited via the /targets
endpoints (and a UI later) without redeploying. Seeding is idempotent: it inserts
only companies not already present.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TargetCompany

SEED_PATH = Path(__file__).resolve().parent / "target_companies.yaml"


def load_seed() -> list[dict]:
    data = yaml.safe_load(SEED_PATH.read_text(encoding="utf-8"))
    return list(data.get("companies", []))


def seed_target_companies(session: Session) -> int:
    """Insert seed companies not already present. Returns the number inserted."""
    existing = {(t.ats, t.slug) for t in session.scalars(select(TargetCompany)).all()}
    inserted = 0
    for row in load_seed():
        key = (row["ats"], row["slug"])
        if key in existing:
            continue
        session.add(
            TargetCompany(
                company=row["company"],
                ats=row["ats"],
                slug=row["slug"],
                hq=row.get("hq"),
                remote_policy=row.get("remote_policy"),
                active=True,
            )
        )
        inserted += 1
    session.commit()
    return inserted


def active_targets(session: Session, vendor: str) -> list[TargetCompany]:
    """Active target companies for one ATS vendor."""
    return list(
        session.scalars(
            select(TargetCompany).where(TargetCompany.ats == vendor, TargetCompany.active.is_(True))
        ).all()
    )


def main() -> None:
    """CLI entrypoint: `python -m app.ingest.targets` seeds using the app DB."""
    from app.db import SessionLocal

    with SessionLocal() as session:
        inserted = seed_target_companies(session)
        print(f"seeded {inserted} target companies")


if __name__ == "__main__":
    main()
