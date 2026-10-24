"""Separate reusable provider accounts from workspace links.

Revision ID: c1e8a7d4f902
Revises: a8c5f2d9e410
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c1e8a7d4f902"
down_revision: str | Sequence[str] | None = "a8c5f2d9e410"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_accounts",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=False),
        sa.Column("external_username", sa.String(length=255), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "external_account_id",
            name="uq_provider_accounts_user_provider_external",
        ),
    )
    op.create_index(
        "ix_provider_accounts_user_provider",
        "provider_accounts",
        ["user_id", "provider"],
    )
    op.add_column(
        "connections",
        sa.Column("provider_account_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO provider_accounts (
                id, user_id, provider, encrypted_token, status,
                external_account_id, external_username, created_at, updated_at
            )
            SELECT DISTINCT ON (user_id, provider, external_account_id)
                id, user_id, provider, encrypted_token, status,
                external_account_id, external_username, created_at, updated_at
            FROM connections
            ORDER BY user_id, provider, external_account_id, updated_at DESC, id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE connections AS c
            SET provider_account_id = a.id
            FROM provider_accounts AS a
            WHERE a.user_id = c.user_id
              AND a.provider = c.provider
              AND a.external_account_id = c.external_account_id
            """
        )
    )
    op.alter_column("connections", "provider_account_id", nullable=False)
    op.create_foreign_key(
        "fk_connections_provider_account_id_provider_accounts",
        "connections",
        "provider_accounts",
        ["provider_account_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_connections_provider_account_id",
        "connections",
        ["provider_account_id"],
    )
    op.drop_column("connections", "encrypted_token")
    op.drop_column("connections", "external_account_id")
    op.drop_column("connections", "external_username")


def downgrade() -> None:
    op.add_column("connections", sa.Column("encrypted_token", sa.Text(), nullable=True))
    op.add_column(
        "connections",
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "connections",
        sa.Column("external_username", sa.String(length=255), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE connections AS c
            SET encrypted_token = a.encrypted_token,
                external_account_id = a.external_account_id,
                external_username = a.external_username
            FROM provider_accounts AS a
            WHERE a.id = c.provider_account_id
            """
        )
    )
    op.alter_column("connections", "encrypted_token", nullable=False)
    op.alter_column("connections", "external_account_id", nullable=False)
    op.alter_column("connections", "external_username", nullable=False)
    op.drop_index("ix_connections_provider_account_id", table_name="connections")
    op.drop_constraint(
        "fk_connections_provider_account_id_provider_accounts",
        "connections",
        type_="foreignkey",
    )
    op.drop_column("connections", "provider_account_id")
    op.drop_index("ix_provider_accounts_user_provider", table_name="provider_accounts")
    op.drop_table("provider_accounts")
