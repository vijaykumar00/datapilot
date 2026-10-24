"""question SQL cache for AI-free repeat answers

Revision ID: e7a1c2d3b4f5
Revises: d1e2f3a4b5c6
Create Date: 2026-10-24
"""

from alembic import op
import sqlalchemy as sa


revision = "e7a1c2d3b4f5"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "question_sql_cache" not in tables:
        op.create_table(
            "question_sql_cache",
            sa.Column("id", sa.String(length=50), primary_key=True),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("schema_hash", sa.String(length=64), nullable=False),
            sa.Column("question_key", sa.String(length=255), nullable=False),
            sa.Column("sql_template", sa.Text(), nullable=False),
            sa.Column("explanation", sa.Text(), nullable=True),
            sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("workspace_id", "schema_hash", "question_key", name="uq_question_sql_cache_key"),
        )
        op.create_index("ix_question_sql_cache_workspace_id", "question_sql_cache", ["workspace_id"])


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "question_sql_cache" in tables:
        op.drop_index("ix_question_sql_cache_workspace_id", table_name="question_sql_cache")
        op.drop_table("question_sql_cache")
