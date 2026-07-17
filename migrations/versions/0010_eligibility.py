"""add eligibility signals (job + preferences)

Revision ID: 0010_eligibility
Revises: 0009_max_age_days
Create Date: 2026-07-17

Job: visa_sponsorship, remote_region, required_utc_offsets.
Preferences: require_sponsorship, exclude_remote_regions, user_utc_offset,
min_timezone_overlap_hours.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_eligibility"
down_revision: str | None = "0009_max_age_days"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("visa_sponsorship", sa.Boolean(), nullable=True))
    op.add_column("job", sa.Column("remote_region", sa.String(length=16), nullable=True))
    op.add_column(
        "job",
        sa.Column(
            "required_utc_offsets", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
        ),
    )
    op.add_column(
        "search_preferences",
        sa.Column("require_sponsorship", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "search_preferences",
        sa.Column(
            "exclude_remote_regions", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
        ),
    )
    op.add_column("search_preferences", sa.Column("user_utc_offset", sa.Integer(), nullable=True))
    op.add_column(
        "search_preferences",
        sa.Column("min_timezone_overlap_hours", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("search_preferences", "min_timezone_overlap_hours")
    op.drop_column("search_preferences", "user_utc_offset")
    op.drop_column("search_preferences", "exclude_remote_regions")
    op.drop_column("search_preferences", "require_sponsorship")
    op.drop_column("job", "required_utc_offsets")
    op.drop_column("job", "remote_region")
    op.drop_column("job", "visa_sponsorship")
