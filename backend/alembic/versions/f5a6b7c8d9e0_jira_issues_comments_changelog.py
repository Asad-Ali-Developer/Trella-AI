"""Add jira_issues, jira_comments, and jira_changelog_items tables.

Revision ID: f5a6b7c8d9e0
Revises: d4e5f6a7b8c9
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_jira_projects_workspace_included",
        "jira_projects",
        ["workspace_id", "included"],
    )

    op.create_table(
        "jira_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cloud_id", sa.String(length=128), nullable=False),
        sa.Column("jira_issue_id", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(length=1000), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("issue_type", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("priority", sa.String(length=128), nullable=True),
        sa.Column("assignee", sa.String(length=255), nullable=True),
        sa.Column("reporter", sa.String(length=255), nullable=True),
        sa.Column(
            "labels",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at_jira", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at_jira", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
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
        sa.ForeignKeyConstraint(["project_id"], ["jira_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "workspace_id",
            "cloud_id",
            "jira_issue_id",
            name="uq_jira_issues_workspace_cloud_external",
        ),
    )
    op.create_index(
        "ix_jira_issues_workspace_project",
        "jira_issues",
        ["workspace_id", "project_id"],
    )
    op.create_index(
        "ix_jira_issues_workspace_key",
        "jira_issues",
        ["workspace_id", "key"],
    )
    op.create_index("ix_jira_issues_client", "jira_issues", ["client_id"])

    op.create_table(
        "jira_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cloud_id", sa.String(length=128), nullable=False),
        sa.Column("jira_comment_id", sa.String(length=64), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at_jira", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_jira", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
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
        sa.ForeignKeyConstraint(["issue_id"], ["jira_issues.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "workspace_id",
            "cloud_id",
            "jira_comment_id",
            name="uq_jira_comments_workspace_cloud_external",
        ),
    )
    op.create_index(
        "ix_jira_comments_workspace_issue",
        "jira_comments",
        ["workspace_id", "issue_id"],
    )

    op.create_table(
        "jira_changelog_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("jira_history_id", sa.String(length=64), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("field", sa.String(length=255), nullable=False),
        sa.Column("from_value", sa.Text(), nullable=True),
        sa.Column("to_value", sa.Text(), nullable=True),
        sa.Column("author", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at_jira", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(["issue_id"], ["jira_issues.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "workspace_id",
            "issue_id",
            "jira_history_id",
            "item_index",
            name="uq_jira_changelog_workspace_issue_history_item",
        ),
    )
    op.create_index(
        "ix_jira_changelog_workspace_issue",
        "jira_changelog_items",
        ["workspace_id", "issue_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_jira_changelog_workspace_issue", table_name="jira_changelog_items")
    op.drop_table("jira_changelog_items")
    op.drop_index("ix_jira_comments_workspace_issue", table_name="jira_comments")
    op.drop_table("jira_comments")
    op.drop_index("ix_jira_issues_client", table_name="jira_issues")
    op.drop_index("ix_jira_issues_workspace_key", table_name="jira_issues")
    op.drop_index("ix_jira_issues_workspace_project", table_name="jira_issues")
    op.drop_table("jira_issues")
    op.drop_index("ix_jira_projects_workspace_included", table_name="jira_projects")

