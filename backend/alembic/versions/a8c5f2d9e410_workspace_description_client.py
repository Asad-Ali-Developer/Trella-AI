"""Add optional description and client name to workspaces.

Revision ID: a8c5f2d9e410
Revises: 9a4d2c7e1f30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8c5f2d9e410"
down_revision: str | Sequence[str] | None = "9a4d2c7e1f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("workspaces", sa.Column("client_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("workspaces", "client_name")
    op.drop_column("workspaces", "description")
