"""SQLAlchemy models for Skills."""

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Skill(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A skill defines an LLM prompt, context scope, output schema, and configuration."""

    __tablename__ = "skills"
    __table_args__ = (
        Index("ix_skills_workspace_id", "workspace_id"),
        Index("ix_skills_slug", "slug"),
        UniqueConstraint("slug", "workspace_id", name="uq_skills_slug_workspace"),
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    scope_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=lambda: {
            "sources": ["*"],
            "clients": "all",
            "include": ["cards", "comments", "commits"],
        },
        nullable=False,
    )
    output_schema_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    model_config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=lambda: {
            "provider": "gemini",
            "model": "gemini-3.5-flash",
            "temperature": 0.1,
        },
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
