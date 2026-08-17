"""accounts (users) + per-owner scoping + stored CV files

Revision ID: 0018_accounts_and_cv_files
Revises: 0017_role_family
Create Date: 2026-08-15

Adds optional accounts: a user_account table, an owner_id on cv / application /
search_preferences (NULL = the pre-accounts "guest" scope), and keeps the original
uploaded CV file so the UI can preview it. Application uniqueness moves from
(job_id) to (owner_id, job_id) so each account tracks a job independently.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_accounts_and_cv_files"
down_revision: str | None = "0017_role_family"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_account",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_user_account_email"),
    )

    # cv: owner + stored original file for preview.
    op.add_column("cv", sa.Column("owner_id", sa.Integer(), nullable=True))
    op.add_column("cv", sa.Column("file_data", sa.LargeBinary(), nullable=True))
    op.add_column("cv", sa.Column("filename", sa.Text(), nullable=True))
    op.add_column("cv", sa.Column("content_type", sa.String(length=64), nullable=True))
    op.add_column("cv", sa.Column("size_bytes", sa.Integer(), nullable=True))
    op.create_index("ix_cv_owner_id", "cv", ["owner_id"])
    op.create_foreign_key(
        "fk_cv_owner", "cv", "user_account", ["owner_id"], ["id"], ondelete="CASCADE"
    )

    # search_preferences: one row per owner (guest = NULL).
    op.add_column("search_preferences", sa.Column("owner_id", sa.Integer(), nullable=True))
    op.create_unique_constraint("uq_search_preferences_owner", "search_preferences", ["owner_id"])
    op.create_foreign_key(
        "fk_search_preferences_owner",
        "search_preferences",
        "user_account",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # application: owner + move uniqueness to (owner_id, job_id).
    op.add_column("application", sa.Column("owner_id", sa.Integer(), nullable=True))
    op.create_index("ix_application_owner_id", "application", ["owner_id"])
    op.drop_constraint("uq_application_job", "application", type_="unique")
    op.create_unique_constraint("uq_application_owner_job", "application", ["owner_id", "job_id"])
    op.create_foreign_key(
        "fk_application_owner",
        "application",
        "user_account",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # The old guest preferences row was inserted with an explicit id=1, which never
    # advanced the serial sequence. Now that we insert per-owner rows via the
    # sequence, realign it to MAX(id)+1 so the first new insert doesn't collide.
    # (Postgres only; SQLite tests use autoincrement and are unaffected.)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "SELECT setval("
            "pg_get_serial_sequence('search_preferences', 'id'), "
            "(SELECT COALESCE(MAX(id), 0) FROM search_preferences) + 1, false)"
        )


def downgrade() -> None:
    op.drop_constraint("fk_application_owner", "application", type_="foreignkey")
    op.drop_constraint("uq_application_owner_job", "application", type_="unique")
    op.create_unique_constraint("uq_application_job", "application", ["job_id"])
    op.drop_index("ix_application_owner_id", table_name="application")
    op.drop_column("application", "owner_id")

    op.drop_constraint("fk_search_preferences_owner", "search_preferences", type_="foreignkey")
    op.drop_constraint("uq_search_preferences_owner", "search_preferences", type_="unique")
    op.drop_column("search_preferences", "owner_id")

    op.drop_constraint("fk_cv_owner", "cv", type_="foreignkey")
    op.drop_index("ix_cv_owner_id", table_name="cv")
    op.drop_column("cv", "size_bytes")
    op.drop_column("cv", "content_type")
    op.drop_column("cv", "filename")
    op.drop_column("cv", "file_data")
    op.drop_column("cv", "owner_id")

    op.drop_table("user_account")
