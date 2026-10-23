import uuid

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WorkspaceConnection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Encrypted credentials for an external provider in one workspace."""

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
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_username: Mapped[str] = mapped_column(String(255), nullable=False)
