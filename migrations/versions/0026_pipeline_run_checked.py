"""pipeline_run.checked: what a run actually re-examined, so recoveries are real

Revision ID: 0026_pipeline_run_checked
Revises: 0025_pipeline_run
Create Date: 2026-11-05

The notifier announced "Recovered: X" whenever a problem code present last run was
absent this run. Absent is not the same as fixed: a throttled source is not fetched
at all, and the missing-OpenAI-key problem is only raised when a run inserts
something, so a quiet night cleared it with the key still missing. Both produced a
recovery line for something nobody had fixed.

This column records the scopes a run genuinely exercised (each source it fetched,
the AI providers it called, whether anything answered at all), and a recovery line
now requires the cleared problem's scope to appear in it.

Existing rows get an empty list, which reads as "re-checked nothing": the first run
after this migration announces no recoveries against them, which is the safe
direction. Nothing backfills.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_pipeline_run_checked"
down_revision: str | None = "0025_pipeline_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pipeline_run",
        sa.Column("checked", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("pipeline_run", "checked")
