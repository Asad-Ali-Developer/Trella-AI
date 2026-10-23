"""phase2_trello_connections

Revision ID: 2f7a9b1c4e60
Revises: 6995a6cae3a5
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2f7a9b1c4e60"
down_revision: str | Sequence[str] | None = "6995a6cae3a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "provider", name="uq_connections_workspace_provider"),
    )
    op.create_index(
        "ix_connections_workspace_provider",
        "connections",
        ["workspace_id", "provider"],
    )

    op.create_table(
        "sources",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trello_board_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("excluded", sa.Boolean(), nullable=False),
        sa.Column("sync_status", sa.String(length=30), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "trello_board_id", name="uq_sources_workspace_board"),
    )
    op.create_index(
        "ix_sources_workspace_external",
        "sources",
        ["workspace_id", "trello_board_id"],
    )
    op.create_index("ix_sources_connection", "sources", ["connection_id"])

    op.create_table(
        "trello_oauth_states",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("encrypted_code_verifier", sa.String(length=512), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trello_oauth_states_hash", "trello_oauth_states", ["state_hash"], unique=True
    )
    op.create_index("ix_trello_oauth_states_expiry", "trello_oauth_states", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_trello_oauth_states_expiry", table_name="trello_oauth_states")
    op.drop_index("ix_trello_oauth_states_hash", table_name="trello_oauth_states")
    op.drop_table("trello_oauth_states")
    op.drop_index("ix_sources_connection", table_name="sources")
    op.drop_index("ix_sources_workspace_external", table_name="sources")
    op.drop_table("sources")
    op.drop_index("ix_connections_workspace_provider", table_name="connections")
    op.drop_table("connections")
