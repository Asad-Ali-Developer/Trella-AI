"""SQLAlchemy models for Report Schedules."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.delivery.models import Delivery


class Schedule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An automated schedule for recurring Skill runs and report deliveries."""

    __tablename__ = "schedules"
    __table_args__ = (
        Index("ix_schedules_workspace_id", "workspace_id"),
        Index("ix_schedules_skill_id", "skill_id"),
        Index("ix_schedules_client_id", "client_id"),
        Index("ix_schedules_active_next_run", "active", "next_run_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    cron: Mapped[str] = mapped_column(String(100), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    channel: Mapped[str] = mapped_column(String(32), default="email", nullable=False)
    recipients: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    slack_channel_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    slack_channel_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_delta_only: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    deliveries: Mapped[list["Delivery"]] = relationship(
        "Delivery",
        back_populates="schedule",
        cascade="all, delete-orphan",
        order_by="Delivery.created_at.desc()",
    )
