"""user_scoped_trello_connections

Revision ID: 4c8d1e7a6b20
Revises: 2f7a9b1c4e60
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "4c8d1e7a6b20"
down_revision: str | Sequence[str] | None = "2f7a9b1c4e60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("user_id", postgresql.UUID(as_uuid=True)))
    op.execute(
        sa.text(
            "UPDATE connections "
            "SET user_id = workspaces.owner_id "
            "FROM workspaces "
            "WHERE connections.workspace_id = workspaces.id"
        )
    )
    op.alter_column("connections", "user_id", nullable=False)
    op.create_foreign_key(
        "fk_connections_user_id_users",
        "connections",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("uq_connections_workspace_provider", "connections", type_="unique")
    op.drop_index("ix_connections_workspace_provider", table_name="connections")
    op.create_unique_constraint(
        "uq_connections_workspace_provider_user",
        "connections",
        ["workspace_id", "provider", "user_id"],
    )
    op.create_index(
        "ix_connections_workspace_provider_user",
        "connections",
        ["workspace_id", "provider", "user_id"],
    )

    op.drop_constraint("uq_sources_workspace_board", "sources", type_="unique")
    op.create_unique_constraint(
        "uq_sources_connection_board",
        "sources",
        ["workspace_id", "connection_id", "trello_board_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_sources_connection_board", "sources", type_="unique")
    op.create_unique_constraint(
        "uq_sources_workspace_board",
        "sources",
        ["workspace_id", "trello_board_id"],
    )

    op.drop_index("ix_connections_workspace_provider_user", table_name="connections")
    op.drop_constraint(
        "uq_connections_workspace_provider_user",
        "connections",
        type_="unique",
    )
    op.create_index(
        "ix_connections_workspace_provider",
        "connections",
        ["workspace_id", "provider"],
    )
    op.create_unique_constraint(
        "uq_connections_workspace_provider",
        "connections",
        ["workspace_id", "provider"],
    )
    op.drop_constraint("fk_connections_user_id_users", "connections", type_="foreignkey")
    op.drop_column("connections", "user_id")
