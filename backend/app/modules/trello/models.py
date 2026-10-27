import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MEMBER_ROLE_TAGS = ("unknown", "client", "internal")


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
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class TrelloClientRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A client derived from a Trello board, list, or label mapping."""

    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_clients_workspace_name"),
        Index("ix_clients_workspace", "workspace_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class TrelloClientMapping(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Maps one Trello board/list/label value to a workspace client."""

    __tablename__ = "client_mappings"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "mapping_type",
            "external_ref",
            name="uq_client_mappings_source_type_ref",
        ),
        Index("ix_client_mappings_workspace_source", "workspace_id", "source_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
    )
    mapping_type: Mapped[str] = mapped_column(String(20), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(255), nullable=False)


class TrelloCard(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A locally synchronized Trello card."""

    __tablename__ = "cards"
    __table_args__ = (
        UniqueConstraint("workspace_id", "trello_card_id", name="uq_cards_workspace_external"),
        Index("ix_cards_workspace_source", "workspace_id", "source_id"),
        Index("ix_cards_client", "client_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
    )
    trello_card_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(1000), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    list_id: Mapped[str] = mapped_column(String(255), nullable=False)
    list_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    labels: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False, default=list)
    member_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class TrelloComment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A Trello card comment action."""

    __tablename__ = "comments"
    __table_args__ = (
        UniqueConstraint("workspace_id", "trello_action_id", name="uq_comments_workspace_action"),
        Index("ix_comments_card", "card_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    trello_action_id: Mapped[str] = mapped_column(String(255), nullable=False)
    author_id: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at_trello: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TrelloMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A Trello member who belongs to a synchronized board."""

    __tablename__ = "members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "trello_member_id", name="uq_members_workspace_external"),
        CheckConstraint(
            "role_tag IN ('unknown', 'client', 'internal')",
            name="ck_members_role_tag",
        ),
        Index("ix_members_workspace", "workspace_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    trello_member_id: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_tag: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")


class TrelloWebhookEvent(Base):
    """Idempotency record for a Trello webhook action."""

    __tablename__ = "trello_webhook_events"

    action_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )


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
