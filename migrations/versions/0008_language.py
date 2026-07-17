"""add language signals (job.language, job.required_languages, prefs.known_languages)

Revision ID: 0008_language
Revises: 0007_match
Create Date: 2026-07-17

Tier 1: store the posting's written language + best-effort required spoken
languages. Tier 2: the user's known languages, used to filter the feed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_language"
down_revision: str | None = "0007_match"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("language", sa.String(length=8), nullable=True))
    op.add_column(
        "job",
        sa.Column("required_languages", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.create_index("ix_job_language", "job", ["language"])
    op.add_column(
        "search_preferences",
        sa.Column("known_languages", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("search_preferences", "known_languages")
    op.drop_index("ix_job_language", table_name="job")
    op.drop_column("job", "required_languages")
    op.drop_column("job", "language")
