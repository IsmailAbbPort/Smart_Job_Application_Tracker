"""pipeline_run: a history row per daily ingest, for catch-up and Telegram reporting

Revision ID: 0025_pipeline_run
Revises: 0024_work_rights
Create Date: 2026-11-05

The scheduler fired once a day and left no trace, so a laptop asleep through
INGEST_HOUR_UTC silently skipped the day and nothing could tell afterwards. This
table records each run, which is what the startup catch-up decision reads ("when
did this last succeed") and what the Telegram notifier formats into a message.

Nothing backfills: the table starts empty, and an empty table means "never ran",
which makes the first startup after this migration schedule a catch-up run.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_pipeline_run"
down_revision: str | None = "0024_work_rights"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_run",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger", sa.String(length=16), server_default="schedule", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="running", nullable=False),
        sa.Column("inserted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("removed_stale", sa.Integer(), server_default="0", nullable=False),
        sa.Column("embedded", sa.Integer(), server_default="0", nullable=False),
        sa.Column("classified", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sources", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("problems", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The catch-up decision asks for the newest ok/partial run on every startup.
    op.create_index("ix_pipeline_run_status_started", "pipeline_run", ["status", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_run_status_started", table_name="pipeline_run")
    op.drop_table("pipeline_run")
