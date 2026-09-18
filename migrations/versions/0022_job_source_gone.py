"""job.source_gone_at: when a tracked posting was found gone from its source

Revision ID: 0022_job_source_gone
Revises: 0021_liveness_suggestions
Create Date: 2026-09-15

Tracked jobs are never deleted when their posting disappears, so this marks them
expired instead. The UI labels them and shows the last saved copy of the description.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_job_source_gone"
down_revision: str | None = "0021_liveness_suggestions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("source_gone_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("job", "source_gone_at")
