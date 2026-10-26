"""SQLAlchemy models for Jira OAuth states and synchronized Jira projects."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
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
