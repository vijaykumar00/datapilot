"""auth social phone otp

Revision ID: c9f1a2b3d4e5
Revises: b4c1d2e3f4a5
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "c9f1a2b3d4e5"
down_revision = "b4c1d2e3f4a5"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name):
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name):
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade():
    if "users" in _tables() and "phone_number" not in _columns("users"):
        op.add_column("users", sa.Column("phone_number", sa.String(length=32), nullable=True))
    if "users" in _tables() and "ix_users_phone_number" not in _indexes("users"):
        op.create_index("ix_users_phone_number", "users", ["phone_number"], unique=True)

    if "phone_otp_challenges" not in _tables():
        op.create_table(
            "phone_otp_challenges",
            sa.Column("id", sa.String(length=50), nullable=False),
            sa.Column("phone_number", sa.String(length=32), nullable=False),
            sa.Column("code_hash", sa.String(length=255), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    if "phone_otp_challenges" in _tables():
        indexes = _indexes("phone_otp_challenges")
        if "ix_phone_otp_challenges_phone_number" not in indexes:
            op.create_index(
                "ix_phone_otp_challenges_phone_number",
                "phone_otp_challenges",
                ["phone_number"],
                unique=False,
            )
        if "ix_phone_otp_challenges_expires_at" not in indexes:
            op.create_index(
                "ix_phone_otp_challenges_expires_at",
                "phone_otp_challenges",
                ["expires_at"],
                unique=False,
            )


def downgrade():
    if "phone_otp_challenges" in _tables():
        op.drop_table("phone_otp_challenges")
    if "users" in _tables() and "phone_number" in _columns("users"):
        indexes = _indexes("users")
        with op.batch_alter_table("users") as batch_op:
            if "ix_users_phone_number" in indexes:
                batch_op.drop_index("ix_users_phone_number")
            batch_op.drop_column("phone_number")
