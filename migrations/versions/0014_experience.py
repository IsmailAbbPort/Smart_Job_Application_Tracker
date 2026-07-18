"""add experience signals (job.min_years_experience + preferences)

Revision ID: 0014_experience
Revises: 0013_embedding_index
Create Date: 2026-07-18

Job: min_years_experience (entry bar the posting states).
Preferences: years_experience (the user's) + max_experience_gap (optional cutoff).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_experience"
down_revision: str | None = "0013_embedding_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("min_years_experience", sa.Integer(), nullable=True))
    op.add_column("search_preferences", sa.Column("years_experience", sa.Integer(), nullable=True))
    op.add_column(
        "search_preferences", sa.Column("max_experience_gap", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("search_preferences", "max_experience_gap")
    op.drop_column("search_preferences", "years_experience")
    op.drop_column("job", "min_years_experience")
