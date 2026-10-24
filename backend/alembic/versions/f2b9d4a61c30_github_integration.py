"""Add GitHub OAuth, selected repositories, and synchronized commits.

Revision ID: f2b9d4a61c30
Revises: ed5a1bc90372
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f2b9d4a61c30"
down_revision: str | Sequence[str] | None = "ed5a1bc90372"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "github_oauth_states",
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
        "ix_github_oauth_states_hash",
        "github_oauth_states",
        ["state_hash"],
        unique=True,
    )
    op.create_index("ix_github_oauth_states_expiry", "github_oauth_states", ["expires_at"])

    op.create_table(
        "github_repositories",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("github_repo_id", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("default_branch", sa.String(length=255), nullable=False),
        sa.Column("private", sa.Boolean(), nullable=False),
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
            "github_repo_id",
            name="uq_github_repositories_workspace_external",
        ),
    )
    op.create_index(
        "ix_github_repositories_workspace_included",
        "github_repositories",
        ["workspace_id", "included"],
    )
    op.create_index("ix_github_repositories_connection", "github_repositories", ["connection_id"])

    op.create_table(
        "github_commits",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sha", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("author_name", sa.String(length=255), nullable=False),
        sa.Column("author_login", sa.String(length=255), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("additions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deletions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("changed_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["github_repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repository_id", "sha", name="uq_github_commits_repository_sha"),
    )
    op.create_index(
        "ix_github_commits_workspace_repo_date",
        "github_commits",
        ["workspace_id", "repository_id", "committed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_github_commits_workspace_repo_date", table_name="github_commits")
    op.drop_table("github_commits")
    op.drop_index("ix_github_repositories_connection", table_name="github_repositories")
    op.drop_index("ix_github_repositories_workspace_included", table_name="github_repositories")
    op.drop_table("github_repositories")
    op.drop_index("ix_github_oauth_states_expiry", table_name="github_oauth_states")
    op.drop_index("ix_github_oauth_states_hash", table_name="github_oauth_states")
    op.drop_table("github_oauth_states")
