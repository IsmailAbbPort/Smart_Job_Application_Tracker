"""add derived city column to job

Revision ID: 0004_add_city
Revises: 0003_geo_and_targets
Create Date: 2026-07-06

Canonical city (Munich for every "Munich"/"München"/"Munich, Germany" variant),
used for display/filtering and as part of the geo-aware dedup key.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_city"
down_revision: str | None = "0003_geo_and_targets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("city", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("job", "city")
