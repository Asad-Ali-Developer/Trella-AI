"""Add Jira OAuth states and synchronized Jira projects.

Revision ID: e4a1b2c3d4e5
Revises: f2b9d4a61c30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e4a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "f2b9d4a61c30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jira_oauth_states",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_jira_oauth_states_hash",
        "jira_oauth_states",
        ["state_hash"],
        unique=True,
    )
    op.create_index("ix_jira_oauth_states_expiry", "jira_oauth_states", ["expires_at"])

    op.create_table(
        "jira_projects",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cloud_id", sa.String(length=128), nullable=False),
        sa.Column("jira_project_id", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("project_type_key", sa.String(length=64), nullable=False, server_default="software"),
        sa.Column("avatar_url", sa.String(length=1000), nullable=True),
        sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sync_status", sa.String(length=30), nullable=False, server_default="not_started"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "connection_id",
            "jira_project_id",
            name="uq_jira_projects_workspace_conn_project",
        ),
    )
    op.create_index(
        "ix_jira_projects_workspace",
        "jira_projects",
        ["workspace_id"],
    )
    op.create_index("ix_jira_projects_connection", "jira_projects", ["connection_id"])


def downgrade() -> None:
    op.drop_index("ix_jira_projects_connection", table_name="jira_projects")
    op.drop_index("ix_jira_projects_workspace", table_name="jira_projects")
    op.drop_table("jira_projects")
    op.drop_index("ix_jira_oauth_states_expiry", table_name="jira_oauth_states")
    op.drop_index("ix_jira_oauth_states_hash", table_name="jira_oauth_states")
    op.drop_table("jira_oauth_states")
