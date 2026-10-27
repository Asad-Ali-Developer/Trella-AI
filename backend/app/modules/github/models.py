import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GithubRepository(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A GitHub repository available to a workspace's linked account."""

    __tablename__ = "github_repositories"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "connection_id",
            "github_repo_id",
            name="uq_github_repositories_workspace_external",
        ),
        Index("ix_github_repositories_workspace_included", "workspace_id", "included"),
        Index("ix_github_repositories_connection", "connection_id"),
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
    github_repo_id: Mapped[str] = mapped_column(String(64), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    private: Mapped[bool] = mapped_column(Boolean, nullable=False)
    included: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
    )
    sync_status: Mapped[str] = mapped_column(String(30), default="not_started", nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class GithubCommit(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A commit synchronized from a selected GitHub repository."""

    __tablename__ = "github_commits"
    __table_args__ = (
        UniqueConstraint("repository_id", "sha", name="uq_github_commits_repository_sha"),
        Index(
            "ix_github_commits_workspace_repo_date", "workspace_id", "repository_id", "committed_at"
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("github_repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    sha: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    author_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    author_login: Mapped[str | None] = mapped_column(String(255), nullable=True)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    additions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deletions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
