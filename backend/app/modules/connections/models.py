import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProviderAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Encrypted provider credentials owned by the authorizing user."""

    __tablename__ = "provider_accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            "external_account_id",
            name="uq_provider_accounts_user_provider_external",
        ),
        Index("ix_provider_accounts_user_provider", "user_id", "provider"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_username: Mapped[str] = mapped_column(String(255), nullable=False)


class WorkspaceConnection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A user's provider account linked to one workspace."""

    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "user_id",
            name="uq_connections_workspace_provider_user",
        ),
        Index("ix_connections_workspace_provider_user", "workspace_id", "provider", "user_id"),
    )

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
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    provider_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )


class GithubOAuthState(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Single-use GitHub OAuth state bound to its initiating user and workspace."""

    __tablename__ = "github_oauth_states"
    __table_args__ = (
        Index("ix_github_oauth_states_hash", "state_hash", unique=True),
        Index("ix_github_oauth_states_expiry", "expires_at"),
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
