"""saved_view: named filter presets per owner

Revision ID: 0020_saved_views
Revises: 0019_ai_usage
Create Date: 2026-09-14

Adds the saved_view table: a named, owner-scoped (NULL = guest) filter preset whose
`filters` JSON is owned by the frontend and stored as-is.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_saved_views"
down_revision: str | None = "0019_ai_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_view",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("filters", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_saved_view_owner_id", "saved_view", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_saved_view_owner_id", table_name="saved_view")
    op.drop_table("saved_view")
