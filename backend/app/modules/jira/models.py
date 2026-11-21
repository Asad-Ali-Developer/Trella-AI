"""SQLAlchemy models for Jira OAuth states and synchronized Jira projects, issues, comments, and changelog."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class JiraOAuthState(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Single-use Atlassian OAuth state bound to initiating user and workspace."""

    __tablename__ = "jira_oauth_states"
    __table_args__ = (
        Index("ix_jira_oauth_states_hash", "state_hash", unique=True),
        Index("ix_jira_oauth_states_expiry", "expires_at"),
    )

    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JiraProject(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Jira project associated with a workspace connection."""

    __tablename__ = "jira_projects"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "connection_id",
            "jira_project_id",
            name="uq_jira_projects_workspace_conn_project",
        ),
        Index("ix_jira_projects_workspace", "workspace_id"),
        Index("ix_jira_projects_workspace_included", "workspace_id", "included"),
        Index("ix_jira_projects_connection", "connection_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    cloud_id: Mapped[str] = mapped_column(String(128), nullable=False)
    jira_project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    project_type_key: Mapped[str] = mapped_column(String(64), default="software", nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    included: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
    )
    sync_status: Mapped[str] = mapped_column(String(30), default="not_started", nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class JiraIssue(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A Jira issue synchronized from a selected Jira project.

    content_hash is SHA-256 over canonical JSON (sort_keys=True) with exact fields:
    {
        "key": str,
        "summary": str,
        "description": str,
        "status": str,
        "issue_type": str,
        "priority": str | None,
        "assignee": str | None,
        "reporter": str | None,
        "labels": list[str] (sorted),
        "created_at_jira": str | None (ISO-8601 UTC),
        "updated_at_jira": str | None (ISO-8601 UTC),
        "url": str,
    }
    """

    __tablename__ = "jira_issues"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "cloud_id",
            "jira_issue_id",
            name="uq_jira_issues_workspace_cloud_external",
        ),
        Index("ix_jira_issues_workspace_project", "workspace_id", "project_id"),
        Index("ix_jira_issues_workspace_key", "workspace_id", "key"),
        Index("ix_jira_issues_client", "client_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jira_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
    )
    cloud_id: Mapped[str] = mapped_column(String(128), nullable=False)
    jira_issue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    issue_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    priority: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reporter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    labels: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at_jira: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at_jira: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class JiraComment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A Jira issue comment synchronized from Jira Cloud.

    content_hash is SHA-256 over canonical JSON (sort_keys=True) with exact fields:
    {
        "jira_comment_id": str,
        "author": str,
        "body": str,
        "created_at_jira": str (ISO-8601 UTC),
        "updated_at_jira": str | None (ISO-8601 UTC),
    }
    """

    __tablename__ = "jira_comments"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "cloud_id",
            "jira_comment_id",
            name="uq_jira_comments_workspace_cloud_external",
        ),
        Index("ix_jira_comments_workspace_issue", "workspace_id", "issue_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    issue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jira_issues.id", ondelete="CASCADE"),
        nullable=False,
    )
    cloud_id: Mapped[str] = mapped_column(String(128), nullable=False)
    jira_comment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at_jira: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at_jira: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class JiraChangelogItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single field transition item from a Jira issue changelog history entry."""

    __tablename__ = "jira_changelog_items"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "issue_id",
            "jira_history_id",
            "item_index",
            name="uq_jira_changelog_workspace_issue_history_item",
        ),
        Index("ix_jira_changelog_workspace_issue", "workspace_id", "issue_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    issue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jira_issues.id", ondelete="CASCADE"),
        nullable=False,
    )
    jira_history_id: Mapped[str] = mapped_column(String(64), nullable=False)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    field: Mapped[str] = mapped_column(String(255), nullable=False)
    from_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at_jira: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

