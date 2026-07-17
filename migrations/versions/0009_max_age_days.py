"""add search_preferences.max_age_days (freshness cutoff)

Revision ID: 0009_max_age_days
Revises: 0008_language
Create Date: 2026-07-17

Optional hard cutoff: drop postings older than N days. Complements the soft
recency decay applied to shortlist ordering (that decay needs no schema).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_max_age_days"
down_revision: str | None = "0008_language"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("search_preferences", sa.Column("max_age_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("search_preferences", "max_age_days")
