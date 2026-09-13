"""ai_usage: per-day counter for AI rate limiting

Revision ID: 0019_ai_usage
Revises: 0018_accounts_and_cv_files
Create Date: 2026-08-21

Adds the ai_usage table that backs the daily rate limits on the paid AI endpoints
(judge + cover letter). One row per (identity, action, day) holds that day's count;
a new UTC day is a new row, so the limit lifts without any purge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_ai_usage"
down_revision: str | None = "0018_accounts_and_cv_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("identity", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identity", "action", "day", name="uq_ai_usage_identity_action_day"),
    )
    op.create_index("ix_ai_usage_action_day", "ai_usage", ["action", "day"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_action_day", table_name="ai_usage")
    op.drop_table("ai_usage")
