"""workspace switch: never send this workspace's data to an AI service

Revision ID: f2b3c4d5e6a7
Revises: e7a1c2d3b4f5
Create Date: 2026-10-24

A plain ADD COLUMN on purpose: SQLite "batch" mode would rebuild the workspaces
table, and dropping the old copy cascades to workspace_members.
"""

from alembic import op
import sqlalchemy as sa


revision = "f2b3c4d5e6a7"
down_revision = "e7a1c2d3b4f5"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("workspaces")}
    if "ai_enabled" not in columns:
        op.add_column("workspaces", sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        # Leave the column in place on SQLite: removing it would rebuild the table
        # (and cascade-delete memberships). An unused column is harmless.
        return
    op.drop_column("workspaces", "ai_enabled")
