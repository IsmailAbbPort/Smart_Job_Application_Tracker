"""add match (LLM judge verdicts)

Revision ID: 0007_match
Revises: 0006_search_preferences
Create Date: 2026-07-17

The Phase 3 rerank stage: one row per (cv, job) holding the judge's structured,
evidence-grounded verdict. Sub-parts (dimension scores, matched requirements,
gaps) are JSON.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_match"
down_revision: str | None = "0006_search_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "match",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cv_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("one_line_verdict", sa.Text(), nullable=False, server_default=""),
        sa.Column("dimension_scores", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "matched_requirements", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
        ),
        sa.Column("gaps", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["cv_id"], ["cv.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cv_id", "job_id", name="uq_match_cv_job"),
    )
    op.create_index("ix_match_cv_id", "match", ["cv_id"])
    op.create_index("ix_match_job_id", "match", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_match_job_id", table_name="match")
    op.drop_index("ix_match_cv_id", table_name="match")
    op.drop_table("match")
