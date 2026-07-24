"""add seniority signal + seniority/title-keyword exclude preferences

Revision ID: 0016_seniority_filters
Revises: 0015_cover_letter
Create Date: 2026-07-24

Job: seniority (title-inferred). Preferences: exclude_seniorities,
exclude_title_keywords - deterministic filters to keep the shortlist pool clean.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_seniority_filters"
down_revision: str | None = "0015_cover_letter"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("seniority", sa.String(length=16), nullable=True))
    op.add_column(
        "search_preferences",
        sa.Column("exclude_seniorities", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "search_preferences",
        sa.Column(
            "exclude_title_keywords", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("search_preferences", "exclude_title_keywords")
    op.drop_column("search_preferences", "exclude_seniorities")
    op.drop_column("job", "seniority")
