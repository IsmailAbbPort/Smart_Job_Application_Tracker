"""initial schema: job + source_fetch

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-06

Hand-authored to match app/models.py. Later revisions (e.g. the pgvector
`embedding` column in Phase 2) can use --autogenerate against a live DB.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("is_remote", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("company_norm", sa.String(length=255), nullable=False),
        sa.Column("title_norm", sa.String(length=512), nullable=False),
        sa.Column("location_norm", sa.String(length=255), nullable=False),
        sa.Column("dedup_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_id", name="uq_job_source_sourceid"),
    )
    op.create_index("ix_job_dedup_key", "job", ["dedup_key"])
    op.create_index("ix_job_company_norm", "job", ["company_norm"])
    op.create_index("ix_job_source", "job", ["source"])

    op.create_table(
        "source_fetch",
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_status", sa.String(length=32), nullable=True),
        sa.Column("last_count", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("source"),
    )


def downgrade() -> None:
    op.drop_table("source_fetch")
    op.drop_index("ix_job_source", table_name="job")
    op.drop_index("ix_job_company_norm", table_name="job")
    op.drop_index("ix_job_dedup_key", table_name="job")
    op.drop_table("job")
