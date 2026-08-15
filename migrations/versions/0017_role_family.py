"""add role_family signal + include_role_families preference

Revision ID: 0017_role_family
Revises: 0016_seniority_filters
Create Date: 2026-07-24

Job: role_family (title-inferred, in embedding space). Preferences:
include_role_families - a positive filter that keeps only the wanted role domains,
cleaning the retrieve pool upstream of the LLM judge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_role_family"
down_revision: str | None = "0016_seniority_filters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("role_family", sa.String(length=32), nullable=True))
    op.add_column(
        "search_preferences",
        sa.Column(
            "include_role_families", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("search_preferences", "include_role_families")
    op.drop_column("job", "role_family")
