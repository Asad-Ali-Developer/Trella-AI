"""Add chunks and links tables with halfvec(768) and FTS indexes.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("card_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("group_key", sa.Text(), nullable=True),
        sa.Column("chunk_kind", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', text)", persisted=True),
            nullable=True,
        ),
        sa.Column("embedding", HALFVEC(768), nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column("chunker_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repository_id"], ["github_repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(card_id IS NOT NULL)::int + (repository_id IS NOT NULL)::int = 1",
            name="ck_chunks_exactly_one_parent",
        ),
        sa.CheckConstraint(
            "source_type IN ('trello', 'github', 'jira')",
            name="ck_chunks_source_type",
        ),
        sa.CheckConstraint(
            "chunk_kind IN ('card_body', 'comment_group', 'commit_group')",
            name="ck_chunks_chunk_kind",
        ),
        # NOTE: 'jira' source_type is reserved in ck_chunks_source_type above;
        # ck_chunks_parent_source_consistency and ck_chunks_exactly_one_parent
        # will be replaced in the Jira prompt when issue_id is added.
        sa.CheckConstraint(
            "(card_id IS NULL OR (source_type = 'trello' AND source_id IS NOT NULL)) "
            "AND (repository_id IS NULL OR (source_type = 'github' AND source_id IS NULL AND group_key IS NOT NULL))",
            name="ck_chunks_parent_source_consistency",
        ),
        sa.CheckConstraint(
            "embedding IS NULL OR embedding_model IS NOT NULL",
            name="ck_chunks_embedding_model_present",
        ),
    )

    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")
    op.create_index(
        "ix_chunks_embedding_halfvec_cosine",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )
    op.create_index(
        "ix_chunks_workspace_client_occurred",
        "chunks",
        ["workspace_id", "client_id", "occurred_at"],
    )
    op.create_index("ix_chunks_workspace_source", "chunks", ["workspace_id", "source_id"])
    op.create_index(
        "ix_chunks_workspace_repository",
        "chunks",
        ["workspace_id", "repository_id"],
        postgresql_where=sa.text("repository_id IS NOT NULL"),
    )
    op.create_index(
        "uq_chunks_card_kind_ordinal",
        "chunks",
        ["card_id", "chunk_kind", "ordinal"],
        unique=True,
        postgresql_where=sa.text("card_id IS NOT NULL"),
    )
    op.create_index(
        "uq_chunks_repo_kind_group_ordinal",
        "chunks",
        ["repository_id", "chunk_kind", "group_key", "ordinal"],
        unique=True,
        postgresql_where=sa.text("repository_id IS NOT NULL"),
    )
    op.create_index(
        "ix_chunks_workspace_unembedded",
        "chunks",
        ["workspace_id"],
        postgresql_where=sa.text("embedding IS NULL"),
    )

    op.create_table(
        "links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_card_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("from_commit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("to_card_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("to_commit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("link_type", sa.Text(), nullable=False),
        sa.Column(
            "confidence",
            sa.Float(),
            server_default=sa.text("1.0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_commit_id"], ["github_commits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_commit_id"], ["github_commits.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(from_card_id IS NOT NULL)::int + (from_commit_id IS NOT NULL)::int = 1",
            name="ck_links_from_exactly_one",
        ),
        sa.CheckConstraint(
            "(to_card_id IS NOT NULL)::int + (to_commit_id IS NOT NULL)::int = 1",
            name="ck_links_to_exactly_one",
        ),
        sa.CheckConstraint(
            "link_type IN ('mentions', 'fixes', 'derived_from')",
            name="ck_links_type",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "from_card_id",
            "from_commit_id",
            "to_card_id",
            "to_commit_id",
            "link_type",
            name="uq_links_edge",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_links_workspace", "links", ["workspace_id"])
    op.create_index("ix_links_from_card", "links", ["from_card_id"])
    op.create_index("ix_links_from_commit", "links", ["from_commit_id"])
    op.create_index("ix_links_to_card", "links", ["to_card_id"])
    op.create_index("ix_links_to_commit", "links", ["to_commit_id"])


def downgrade() -> None:
    op.drop_index("ix_links_to_commit", table_name="links")
    op.drop_index("ix_links_to_card", table_name="links")
    op.drop_index("ix_links_from_commit", table_name="links")
    op.drop_index("ix_links_from_card", table_name="links")
    op.drop_index("ix_links_workspace", table_name="links")
    op.drop_table("links")

    op.drop_index("ix_chunks_workspace_unembedded", table_name="chunks")
    op.drop_index("uq_chunks_repo_kind_group_ordinal", table_name="chunks")
    op.drop_index("uq_chunks_card_kind_ordinal", table_name="chunks")
    op.drop_index("ix_chunks_workspace_repository", table_name="chunks")
    op.drop_index("ix_chunks_workspace_source", table_name="chunks")
    op.drop_index("ix_chunks_workspace_client_occurred", table_name="chunks")
    op.drop_index("ix_chunks_embedding_halfvec_cosine", table_name="chunks")
    op.drop_index("ix_chunks_tsv", table_name="chunks")
    op.drop_table("chunks")
