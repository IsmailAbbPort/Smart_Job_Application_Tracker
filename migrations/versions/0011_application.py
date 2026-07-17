"""add application (pipeline tracking)

Revision ID: 0011_application
Revises: 0010_eligibility
Create Date: 2026-07-17

One tracked application per job posting: status pipeline + which CV was sent.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_application"
down_revision: str | None = "0010_eligibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("cv_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="saved"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cv_id"], ["cv.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_application_job"),
    )
    op.create_index("ix_application_job_id", "application", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_application_job_id", table_name="application")
    op.drop_table("application")
