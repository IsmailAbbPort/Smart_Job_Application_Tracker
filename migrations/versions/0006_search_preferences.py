"""add search_preferences (singleton default filters)

Revision ID: 0006_search_preferences
Revises: 0005_embeddings
Create Date: 2026-07-11

Persistent default filters (remote_only, require_european, country/city blocklist)
applied to /jobs and /match/shortlist.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_search_preferences"
down_revision: str | None = "0005_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("remote_only", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("require_european", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("exclude_countries", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("exclude_cities", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("search_preferences")
