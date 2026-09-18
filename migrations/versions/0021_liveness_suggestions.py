"""liveness bookkeeping + CV role-family suggestions + replayable shortlist query

Revision ID: 0021_liveness_suggestions
Revises: 0020_saved_views
Create Date: 2026-09-15

Job: last_checked_at - when the posting was last confirmed live (seen in its source
feed, or a liveness check answered 2xx), so expired aggregator listings can be swept
without re-checking fresh ones. Cv: suggested_role_families - the LLM's filter
suggestion for that CV. SearchPreferences: last_shortlist_query - the owner's most
recent shortlist parameters, replayed by the nightly liveness sweep.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_liveness_suggestions"
down_revision: str | None = "0020_saved_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "cv",
        sa.Column(
            "suggested_role_families", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
        ),
    )
    op.add_column("search_preferences", sa.Column("last_shortlist_query", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("search_preferences", "last_shortlist_query")
    op.drop_column("cv", "suggested_role_families")
    op.drop_column("job", "last_checked_at")
