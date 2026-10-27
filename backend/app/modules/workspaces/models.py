import enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.auth.models import User


class MembershipRole(enum.StrEnum):
    """Roles for workspace memberships."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class Workspace(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Workspace tenant container isolating data and configurations."""

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Relationships
    memberships: Mapped[list["Membership"]] = relationship(
        "Membership",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )


class Membership(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """User membership and authorization role within a workspace."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_user"),
        Index("ix_memberships_workspace_user", "workspace_id", "user_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, name="membership_role_enum", native_enum=False),
        default=MembershipRole.MEMBER,
        nullable=False,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="memberships")
    user: Mapped["User"] = relationship("User", back_populates="memberships")


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Immutable audit trail of sensitive actions performed within a workspace."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_workspace_created", "workspace_id", "created_at"),
        Index("ix_audit_logs_workspace_action", "workspace_id", "action"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="audit_logs")
    user: Mapped["User | None"] = relationship("User", back_populates="audit_logs")
