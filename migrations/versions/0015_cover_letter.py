"""add cover_letter (CV-grounded letters + fabrication audit)

Revision ID: 0015_cover_letter
Revises: 0014_experience
Create Date: 2026-07-18

One letter per (cv, job): body + fabrication-check JSON + edited flag.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_cover_letter"
down_revision: str | None = "0014_experience"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cover_letter",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cv_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("fabrication", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("edited", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["cv_id"], ["cv.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cv_id", "job_id", name="uq_cover_letter_cv_job"),
    )
    op.create_index("ix_cover_letter_cv_id", "cover_letter", ["cv_id"])
    op.create_index("ix_cover_letter_job_id", "cover_letter", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_cover_letter_job_id", table_name="cover_letter")
    op.drop_index("ix_cover_letter_cv_id", table_name="cover_letter")
    op.drop_table("cover_letter")
