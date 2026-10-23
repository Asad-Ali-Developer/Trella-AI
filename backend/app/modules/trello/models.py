import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TrelloSource(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A Trello board registered as a workspace source."""

    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "connection_id",
            "trello_board_id",
            name="uq_sources_connection_board",
        ),
        Index("ix_sources_workspace_external", "workspace_id", "trello_board_id"),
        Index("ix_sources_connection", "connection_id"),
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
    trello_board_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sync_status: Mapped[str] = mapped_column(String(30), default="not_started", nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TrelloOAuthState(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Single-use OAuth state and PKCE verifier bound to its initiating user/workspace."""

    __tablename__ = "trello_oauth_states"
    __table_args__ = (
        Index("ix_trello_oauth_states_hash", "state_hash", unique=True),
        Index("ix_trello_oauth_states_expiry", "expires_at"),
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
    encrypted_code_verifier: Mapped[str] = mapped_column(String(512), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
