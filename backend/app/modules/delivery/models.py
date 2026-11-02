"""SQLAlchemy models for Report Deliveries and Audit Logs."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.scheduler.models import Schedule


class Delivery(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Log record of an individual report delivery attempt via Slack or Email."""

    __tablename__ = "deliveries"
    __table_args__ = (
        Index("ix_deliveries_workspace_id", "workspace_id"),
        Index("ix_deliveries_run_id", "run_id"),
        Index("ix_deliveries_schedule_id", "schedule_id"),
        Index("ix_deliveries_status", "status"),
        Index("ix_deliveries_created_at", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schedules.id", ondelete="SET NULL"),
        nullable=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    schedule: Mapped["Schedule | None"] = relationship(
        "Schedule",
        back_populates="deliveries",
    )
