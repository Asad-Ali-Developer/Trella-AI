"""Add schedules, deliveries, and Slack OAuth states for Phase 6.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create slack_oauth_states table
    op.create_table(
        "slack_oauth_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_slack_oauth_states_hash", "slack_oauth_states", ["state_hash"], unique=True)
    op.create_index("ix_slack_oauth_states_expiry", "slack_oauth_states", ["expires_at"])

    # 2. Create schedules table
    op.create_table(
        "schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("cron", sa.String(length=100), nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("channel", sa.String(length=32), server_default="email", nullable=False),
        sa.Column("recipients", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("slack_channel_id", sa.String(length=100), nullable=True),
        sa.Column("slack_channel_name", sa.String(length=100), nullable=True),
        sa.Column("is_delta_only", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_schedules_workspace_id", "schedules", ["workspace_id"])
    op.create_index("ix_schedules_skill_id", "schedules", ["skill_id"])
    op.create_index("ix_schedules_client_id", "schedules", ["client_id"])
    op.create_index("ix_schedules_active_next_run", "schedules", ["active", "next_run_at"])

    # 3. Create deliveries table
    op.create_table(
        "deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="1", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_deliveries_workspace_id", "deliveries", ["workspace_id"])
    op.create_index("ix_deliveries_run_id", "deliveries", ["run_id"])
    op.create_index("ix_deliveries_schedule_id", "deliveries", ["schedule_id"])
    op.create_index("ix_deliveries_status", "deliveries", ["status"])
    op.create_index("ix_deliveries_created_at", "deliveries", ["created_at"])


def downgrade() -> None:
    op.drop_table("deliveries")
    op.drop_table("schedules")
    op.drop_table("slack_oauth_states")
