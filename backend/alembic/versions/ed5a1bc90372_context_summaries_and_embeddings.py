"""Add context member labels, cached summaries, and vector embeddings.

Revision ID: ed5a1bc90372
Revises: c1e8a7d4f902
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "ed5a1bc90372"
down_revision: str | Sequence[str] | None = "c1e8a7d4f902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "members",
        sa.Column("role_tag", sa.String(length=20), server_default="unknown", nullable=False),
    )
    op.create_check_constraint(
        "ck_members_role_tag",
        "members",
        "role_tag IN ('unknown', 'client', 'internal')",
    )

    op.create_table(
        "card_summaries",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("card_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "card_id",
            "content_hash",
            "model",
            "prompt_version",
            name="uq_card_summaries_cache_key",
        ),
    )
    op.create_index(
        "ix_card_summaries_workspace_card",
        "card_summaries",
        ["workspace_id", "card_id"],
    )

    op.create_table(
        "card_embeddings",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("card_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "card_id",
            "content_hash",
            "model",
            name="uq_card_embeddings_cache_key",
        ),
    )
    op.create_index(
        "ix_card_embeddings_workspace_card",
        "card_embeddings",
        ["workspace_id", "card_id"],
    )
    op.create_index(
        "ix_card_embeddings_vector_cosine",
        "card_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_card_embeddings_vector_cosine", table_name="card_embeddings")
    op.drop_index("ix_card_embeddings_workspace_card", table_name="card_embeddings")
    op.drop_table("card_embeddings")
    op.drop_index("ix_card_summaries_workspace_card", table_name="card_summaries")
    op.drop_table("card_summaries")
    op.drop_constraint("ck_members_role_tag", "members", type_="check")
    op.drop_column("members", "role_tag")
