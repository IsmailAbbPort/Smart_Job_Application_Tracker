"""add job geo columns + target_company table

Revision ID: 0003_geo_and_targets
Revises: 0002_widen_text_columns
Create Date: 2026-07-06

Adds best-effort geo (country, is_european) to job for EU-remote filtering, and a
target_company table so the monitored ATS boards are editable at runtime.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_geo_and_targets"
down_revision: str | None = "0002_widen_text_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("country", sa.Text(), nullable=True))
    op.add_column(
        "job",
        sa.Column("is_european", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_job_is_european", "job", ["is_european"])

    op.create_table(
        "target_company",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("ats", sa.String(length=16), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("hq", sa.Text(), nullable=True),
        sa.Column("remote_policy", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ats", "slug", name="uq_target_ats_slug"),
    )


def downgrade() -> None:
    op.drop_table("target_company")
    op.drop_index("ix_job_is_european", table_name="job")
    op.drop_column("job", "is_european")
    op.drop_column("job", "country")
