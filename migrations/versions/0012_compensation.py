"""add compensation + effort signals (job + preferences)

Revision ID: 0012_compensation
Revises: 0011_application
Create Date: 2026-07-17

Job: salary_min/max/currency, effort_signals. Preferences: min_salary.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_compensation"
down_revision: str | None = "0011_application"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("salary_min", sa.Integer(), nullable=True))
    op.add_column("job", sa.Column("salary_max", sa.Integer(), nullable=True))
    op.add_column("job", sa.Column("salary_currency", sa.String(length=8), nullable=True))
    op.add_column(
        "job",
        sa.Column("effort_signals", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column("search_preferences", sa.Column("min_salary", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("search_preferences", "min_salary")
    op.drop_column("job", "effort_signals")
    op.drop_column("job", "salary_currency")
    op.drop_column("job", "salary_max")
    op.drop_column("job", "salary_min")
