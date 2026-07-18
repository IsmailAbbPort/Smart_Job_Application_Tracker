"""add HNSW index on job.embedding for scalable cosine search

Revision ID: 0013_embedding_index
Revises: 0012_compensation
Create Date: 2026-07-18

Without this, cosine ranking is a sequential scan. HNSW with vector_cosine_ops
matches the `<=>` operator used by rank_jobs on PostgreSQL. PostgreSQL-only.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_embedding_index"
down_revision: str | None = "0012_compensation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_embedding_hnsw "
        "ON job USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_job_embedding_hnsw")
