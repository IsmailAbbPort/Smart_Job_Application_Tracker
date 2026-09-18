"""match.facts: the judge's extracted facts, graded in code under the user's rules

Revision ID: 0023_match_facts
Revises: 0022_job_source_gone
Create Date: 2026-09-15

The judge now returns facts (requirements checked against the CV + posting constraints)
instead of a tier; app/ai/decide.py computes the score and tier on read. Existing rows
keep facts NULL and are treated as not judged, so they are re-judged on next request.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_match_facts"
down_revision: str | None = "0022_job_source_gone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("match", sa.Column("facts", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("match", "facts")
