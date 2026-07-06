"""widen job free-text columns to Text

Revision ID: 0002_widen_text_columns
Revises: 0001_initial
Create Date: 2026-07-06

Real ATS data (Greenhouse concatenates every office into `location`, and titles
can be long) overflowed the original varchar caps. Free-text columns become Text.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_widen_text_columns"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TEXT_COLUMNS = [
    "title",
    "company",
    "location",
    "url",
    "company_norm",
    "title_norm",
    "location_norm",
    "dedup_key",
]

# (column, old varchar length) for the downgrade path.
_OLD_LENGTHS = {
    "title": 512,
    "company": 255,
    "location": 255,
    "url": 1024,
    "company_norm": 255,
    "title_norm": 512,
    "location_norm": 255,
    "dedup_key": 1024,
}


def upgrade() -> None:
    for col in _TEXT_COLUMNS:
        op.alter_column("job", col, type_=sa.Text(), existing_nullable=(col == "location"))


def downgrade() -> None:
    for col in _TEXT_COLUMNS:
        op.alter_column(
            "job",
            col,
            type_=sa.String(length=_OLD_LENGTHS[col]),
            existing_nullable=(col == "location"),
        )
