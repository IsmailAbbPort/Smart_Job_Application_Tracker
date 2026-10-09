"""job.work_countries + search_preferences.work_rights: country eligibility before the judge

Revision ID: 0024_work_rights
Revises: 0023_match_facts
Create Date: 2026-10-03

A posting's hiring countries were only readable by the LLM judge, one paid call per pair,
after the job had already reached the shortlist. job.work_countries records what the text
states at ingest, and work_rights is the user's side, so the shortlist can drop a job that
hires only where the user cannot work. Both default to empty, which means unstated and
keeps the job, so existing rows change nothing until they are re-derived.

Existing rows need `backfill_enrichment(force=True)` (or POST /ingest/backfill?force=true):
the ordinary backfill only visits rows with no detected language, which an already-enriched
corpus has none of, so without force every old row keeps an empty work_countries and the
filter falls back to the weaker location-only rule for them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_work_rights"
down_revision: str | None = "0023_match_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job",
        sa.Column("work_countries", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "search_preferences",
        sa.Column("work_rights", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("search_preferences", "work_rights")
    op.drop_column("job", "work_countries")
