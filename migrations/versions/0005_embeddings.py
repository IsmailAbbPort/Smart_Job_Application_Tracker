"""enable pgvector; add job.embedding + cv table

Revision ID: 0005_embeddings
Revises: 0004_add_city
Create Date: 2026-07-11

Phase 2 retrieve stage: store 1536-dim embeddings (text-embedding-3-small) for
jobs and the CV in pgvector, so cosine ranking happens in the database.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0005_embeddings"
down_revision: str | None = "0004_add_city"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column("job", sa.Column("embedding", Vector(_DIM), nullable=True))

    op.create_table(
        "cv",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(_DIM), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("cv")
    op.drop_column("job", "embedding")
    # Leave the vector extension in place; other objects may rely on it.
