"""Add issue_id, project_id, and Jira chunk kinds to chunks table.

Revision ID: a7b8c9d0e1f2
Revises: f5a6b7c8d9e0

Operational Note:
- Background workers (Celery sync/ai workers) MUST be stopped before running this migration
  so no worker writes chunks while constraints are being updated.
- Downgrade note: `downgrade()` permanently deletes all derived Jira chunks
  (`WHERE issue_id IS NOT NULL OR project_id IS NOT NULL OR source_type = 'jira'`)
  before restoring the pre-Jira CHECK constraints and dropping `issue_id` and `project_id`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "f5a6b7c8d9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add nullable project_id FK -> jira_projects(id) ON DELETE CASCADE
    #    and nullable issue_id FK -> jira_issues(id) ON DELETE CASCADE
    op.add_column(
        "chunks",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "chunks",
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "chunks_project_id_fkey",
        "chunks",
        "jira_projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "chunks_issue_id_fkey",
        "chunks",
        "jira_issues",
        ["issue_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 2. Atomically replace CHECK constraints inside the migration transaction.
    #    Note: ck_chunks_source_type already allows ('trello', 'github', 'jira') from c3d4e5f6a7b8.
    op.drop_constraint("ck_chunks_exactly_one_parent", "chunks", type_="check")
    op.create_check_constraint(
        "ck_chunks_exactly_one_parent",
        "chunks",
        "(card_id IS NOT NULL)::int + (repository_id IS NOT NULL)::int + (issue_id IS NOT NULL)::int = 1",
    )

    op.drop_constraint("ck_chunks_chunk_kind", "chunks", type_="check")
    op.create_check_constraint(
        "ck_chunks_chunk_kind",
        "chunks",
        "chunk_kind IN ('card_body', 'comment_group', 'commit_group', 'issue_body', 'issue_comment_group', 'issue_transition_group')",
    )

    op.drop_constraint("ck_chunks_parent_source_consistency", "chunks", type_="check")
    op.create_check_constraint(
        "ck_chunks_parent_source_consistency",
        "chunks",
        "(card_id IS NULL OR (source_type = 'trello' AND source_id IS NOT NULL AND repository_id IS NULL AND project_id IS NULL)) "
        "AND (repository_id IS NULL OR (source_type = 'github' AND source_id IS NULL AND project_id IS NULL AND group_key IS NOT NULL)) "
        "AND (issue_id IS NULL OR (source_type = 'jira' AND project_id IS NOT NULL AND source_id IS NULL AND repository_id IS NULL))",
    )

    # 3. Partial indexes for Jira project_id and issue_id lookups and uniqueness
    op.create_index(
        "ix_chunks_workspace_project",
        "chunks",
        ["workspace_id", "project_id"],
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )
    op.create_index(
        "uq_chunks_issue_kind_ordinal",
        "chunks",
        ["issue_id", "chunk_kind", "ordinal"],
        unique=True,
        postgresql_where=sa.text("issue_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Delete derived Jira chunk rows before restoring the narrower CHECK constraints
    op.execute(
        "DELETE FROM chunks WHERE issue_id IS NOT NULL OR project_id IS NOT NULL OR source_type = 'jira'"
    )

    op.drop_index("uq_chunks_issue_kind_ordinal", table_name="chunks")
    op.drop_index("ix_chunks_workspace_project", table_name="chunks")

    op.drop_constraint("ck_chunks_parent_source_consistency", "chunks", type_="check")
    op.create_check_constraint(
        "ck_chunks_parent_source_consistency",
        "chunks",
        "(card_id IS NULL OR (source_type = 'trello' AND source_id IS NOT NULL)) "
        "AND (repository_id IS NULL OR (source_type = 'github' AND source_id IS NULL AND group_key IS NOT NULL))",
    )

    op.drop_constraint("ck_chunks_chunk_kind", "chunks", type_="check")
    op.create_check_constraint(
        "ck_chunks_chunk_kind",
        "chunks",
        "chunk_kind IN ('card_body', 'comment_group', 'commit_group')",
    )

    op.drop_constraint("ck_chunks_exactly_one_parent", "chunks", type_="check")
    op.create_check_constraint(
        "ck_chunks_exactly_one_parent",
        "chunks",
        "(card_id IS NOT NULL)::int + (repository_id IS NOT NULL)::int = 1",
    )

    op.drop_constraint("chunks_issue_id_fkey", "chunks", type_="foreignkey")
    op.drop_constraint("chunks_project_id_fkey", "chunks", type_="foreignkey")
    op.drop_column("chunks", "issue_id")
    op.drop_column("chunks", "project_id")

