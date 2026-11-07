import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import HALFVEC, Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
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


class ContextChunkRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A chunk of workspace context (card body, comment group, or daily repo commit group).

    Note on client_id staleness:
    `client_id` is denormalized from `cards.client_id` / `github_repositories.client_id`
    for single-query retrieval filtering. Any client remapping operation must update
    `chunks.client_id` in tandem so filter predicates never read stale client IDs.
    """

    __tablename__ = "chunks"
    __table_args__ = (
        CheckConstraint(
            "(card_id IS NOT NULL)::int + (repository_id IS NOT NULL)::int = 1",
            name="ck_chunks_exactly_one_parent",
        ),
        CheckConstraint(
            "source_type IN ('trello', 'github', 'jira')",
            name="ck_chunks_source_type",
        ),
        CheckConstraint(
            "chunk_kind IN ('card_body', 'comment_group', 'commit_group')",
            name="ck_chunks_chunk_kind",
        ),
        # NOTE: 'jira' source_type is reserved in ck_chunks_source_type above;
        # ck_chunks_parent_source_consistency and ck_chunks_exactly_one_parent
        # will be replaced in the Jira prompt when issue_id is added.
        CheckConstraint(
            "(card_id IS NULL OR (source_type = 'trello' AND source_id IS NOT NULL)) "
            "AND (repository_id IS NULL OR (source_type = 'github' AND source_id IS NULL AND group_key IS NOT NULL))",
            name="ck_chunks_parent_source_consistency",
        ),
        CheckConstraint(
            "embedding IS NULL OR embedding_model IS NOT NULL",
            name="ck_chunks_embedding_model_present",
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_halfvec_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
        Index(
            "ix_chunks_workspace_client_occurred",
            "workspace_id",
            "client_id",
            "occurred_at",
        ),
        Index("ix_chunks_workspace_source", "workspace_id", "source_id"),
        Index(
            "ix_chunks_workspace_repository",
            "workspace_id",
            "repository_id",
            postgresql_where=sa_text("repository_id IS NOT NULL"),
        ),
        Index(
            "uq_chunks_card_kind_ordinal",
            "card_id",
            "chunk_kind",
            "ordinal",
            unique=True,
            postgresql_where=sa_text("card_id IS NOT NULL"),
        ),
        Index(
            "uq_chunks_repo_kind_group_ordinal",
            "repository_id",
            "chunk_kind",
            "group_key",
            "ordinal",
            unique=True,
            postgresql_where=sa_text("repository_id IS NOT NULL"),
        ),
        Index(
            "ix_chunks_workspace_unembedded",
            "workspace_id",
            postgresql_where=sa_text("embedding IS NULL"),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=True,
    )
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("github_repositories.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    card_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cards.id", ondelete="CASCADE"),
        nullable=True,
    )
    group_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_kind: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', text)", persisted=True),
        nullable=True,
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        HALFVEC(EMBEDDING_DIMENSIONS),
        nullable=True,
    )
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunker_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB(astext_type=Text()),
        default=dict,
        server_default=sa_text("'{}'::jsonb"),
        nullable=False,
    )


class ContextLink(Base, UUIDPrimaryKeyMixin):
    """A directed cross-reference link between cards and/or commits within a workspace."""

    __tablename__ = "links"
    __table_args__ = (
        CheckConstraint(
            "(from_card_id IS NOT NULL)::int + (from_commit_id IS NOT NULL)::int = 1",
            name="ck_links_from_exactly_one",
        ),
        CheckConstraint(
            "(to_card_id IS NOT NULL)::int + (to_commit_id IS NOT NULL)::int = 1",
            name="ck_links_to_exactly_one",
        ),
        CheckConstraint(
            "link_type IN ('mentions', 'fixes', 'derived_from')",
            name="ck_links_type",
        ),
        UniqueConstraint(
            "workspace_id",
            "from_card_id",
            "from_commit_id",
            "to_card_id",
            "to_commit_id",
            "link_type",
            name="uq_links_edge",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_links_workspace", "workspace_id"),
        Index("ix_links_from_card", "from_card_id"),
        Index("ix_links_from_commit", "from_commit_id"),
        Index("ix_links_to_card", "to_card_id"),
        Index("ix_links_to_commit", "to_commit_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_card_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cards.id", ondelete="CASCADE"),
        nullable=True,
    )
    from_commit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("github_commits.id", ondelete="CASCADE"),
        nullable=True,
    )
    to_card_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cards.id", ondelete="CASCADE"),
        nullable=True,
    )
    to_commit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("github_commits.id", ondelete="CASCADE"),
        nullable=True,
    )
    link_type: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        server_default=sa_text("1.0"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa_text("now()"),
        nullable=False,
    )
