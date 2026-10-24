import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

EMBEDDING_DIMENSIONS = 768


class TrelloCardSummary(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A generated card summary cached for a specific source-content hash and prompt."""

    __tablename__ = "card_summaries"
    __table_args__ = (
        UniqueConstraint(
            "card_id",
            "content_hash",
            "model",
            "prompt_version",
            name="uq_card_summaries_cache_key",
        ),
        Index("ix_card_summaries_workspace_card", "workspace_id", "card_id"),
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
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)


class TrelloCardEmbedding(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A semantic vector cached for a specific card content hash and model."""

    __tablename__ = "card_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "card_id",
            "content_hash",
            "model",
            name="uq_card_embeddings_cache_key",
        ),
        Index("ix_card_embeddings_workspace_card", "workspace_id", "card_id"),
        Index(
            "ix_card_embeddings_vector_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
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
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
