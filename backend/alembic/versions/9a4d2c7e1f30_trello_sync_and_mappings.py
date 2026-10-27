"""Add Trello sync entities, client mappings, and webhook metadata.

Revision ID: 9a4d2c7e1f30
Revises: 7b2c9d4e1f60
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "9a4d2c7e1f30"
down_revision: str | Sequence[str] | None = "7b2c9d4e1f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("sync_error", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("webhook_id", sa.String(length=255), nullable=True))

    op.create_table(
        "clients",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
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
        sa.UniqueConstraint("workspace_id", "name", name="uq_clients_workspace_name"),
    )
    op.create_index("ix_clients_workspace", "clients", ["workspace_id"])

    op.create_table(
        "client_mappings",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mapping_type", sa.String(length=20), nullable=False),
        sa.Column("external_ref", sa.String(length=255), nullable=False),
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
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "mapping_type",
            "external_ref",
            name="uq_client_mappings_source_type_ref",
        ),
    )
    op.create_index(
        "ix_client_mappings_workspace_source",
        "client_mappings",
        ["workspace_id", "source_id"],
    )

    op.create_table(
        "cards",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trello_card_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=1000), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("list_id", sa.String(length=255), nullable=False),
        sa.Column("list_name", sa.String(length=255), nullable=False),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("member_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
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
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "trello_card_id",
            name="uq_cards_workspace_external",
        ),
    )
    op.create_index("ix_cards_workspace_source", "cards", ["workspace_id", "source_id"])
    op.create_index("ix_cards_client", "cards", ["client_id"])

    op.create_table(
        "comments",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("card_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trello_action_id", sa.String(length=255), nullable=False),
        sa.Column("author_id", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at_trello", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "trello_action_id",
            name="uq_comments_workspace_action",
        ),
    )
    op.create_index("ix_comments_card", "comments", ["card_id"])

    op.create_table(
        "members",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trello_member_id", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
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
        sa.UniqueConstraint(
            "workspace_id",
            "trello_member_id",
            name="uq_members_workspace_external",
        ),
    )
    op.create_index("ix_members_workspace", "members", ["workspace_id"])

    op.create_table(
        "trello_webhook_events",
        sa.Column("action_id", sa.String(length=255), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("action_id"),
    )


def downgrade() -> None:
    op.drop_table("trello_webhook_events")
    op.drop_index("ix_members_workspace", table_name="members")
    op.drop_table("members")
    op.drop_index("ix_comments_card", table_name="comments")
    op.drop_table("comments")
    op.drop_index("ix_cards_client", table_name="cards")
    op.drop_index("ix_cards_workspace_source", table_name="cards")
    op.drop_table("cards")
    op.drop_index("ix_client_mappings_workspace_source", table_name="client_mappings")
    op.drop_table("client_mappings")
    op.drop_index("ix_clients_workspace", table_name="clients")
    op.drop_table("clients")
    op.drop_column("sources", "webhook_id")
    op.drop_column("sources", "sync_error")
