"""subscription foundation

Revision ID: b4c1d2e3f4a5
Revises: a7f3b9c2d1e4
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa


revision = "b4c1d2e3f4a5"
down_revision = "a7f3b9c2d1e4"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name):
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name):
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _add_column_if_missing(table_name, column):
    if column.name not in _columns(table_name):
        op.add_column(table_name, column)


def upgrade():
    # Defensive cleanup for a failed SQLite batch-alter attempt from early local
    # testing. The actual migration below only uses SQLite-safe ADD COLUMN.
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_plans")
    _add_column_if_missing("plans", sa.Column("description", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("plans", sa.Column("dataset_limit", sa.Integer(), nullable=False, server_default="-1"))
    _add_column_if_missing("plans", sa.Column("chart_limit", sa.Integer(), nullable=False, server_default="-1"))
    _add_column_if_missing("plans", sa.Column("api_usage_limit", sa.Integer(), nullable=False, server_default="0"))
    _add_column_if_missing("plans", sa.Column("workspace_limit", sa.Integer(), nullable=False, server_default="1"))
    _add_column_if_missing("plans", sa.Column("ai_prompt_limit", sa.Integer(), nullable=False, server_default="-1"))
    _add_column_if_missing("plans", sa.Column("reset_interval", sa.String(length=20), nullable=False, server_default="monthly"))
    _add_column_if_missing("plans", sa.Column("trial_days", sa.Integer(), nullable=False, server_default="14"))
    _add_column_if_missing("plans", sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.true()))
    _add_column_if_missing("plans", sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"))
    _add_column_if_missing("plans", sa.Column("created_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("plans", sa.Column("updated_at", sa.DateTime(), nullable=True))

    tables = _tables()
    if "features" not in tables:
        op.create_table(
            "features",
            sa.Column("feature_key", sa.String(length=100), nullable=False),
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("feature_key"),
        )
    if "plan_features" not in tables:
        op.create_table(
            "plan_features",
            sa.Column("id", sa.String(length=50), nullable=False),
            sa.Column("plan_id", sa.String(length=50), nullable=False),
            sa.Column("feature_key", sa.String(length=100), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["feature_key"], ["features.feature_key"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["plan_id"], ["plans.plan_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("plan_id", "feature_key", name="uq_plan_feature"),
        )
    if "plan_limits" not in tables:
        op.create_table(
            "plan_limits",
            sa.Column("id", sa.String(length=50), nullable=False),
            sa.Column("plan_id", sa.String(length=50), nullable=False),
            sa.Column("metric", sa.String(length=100), nullable=False),
            sa.Column("limit_value", sa.BigInteger(), nullable=False),
            sa.Column("reset_interval", sa.String(length=20), nullable=False, server_default="monthly"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["plan_id"], ["plans.plan_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("plan_id", "metric", name="uq_plan_limit"),
        )
    if "workspace_subscriptions" not in tables:
        op.create_table(
            "workspace_subscriptions",
            sa.Column("id", sa.String(length=50), nullable=False),
            sa.Column("workspace_id", sa.String(length=50), nullable=False),
            sa.Column("plan_id", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("previous_plan_id", sa.String(length=50), nullable=True),
            sa.Column("pending_plan_id", sa.String(length=50), nullable=True),
            sa.Column("trial_started_at", sa.DateTime(), nullable=True),
            sa.Column("trial_ends_at", sa.DateTime(), nullable=True),
            sa.Column("grace_period_ends_at", sa.DateTime(), nullable=True),
            sa.Column("current_period_start", sa.DateTime(), nullable=False),
            sa.Column("current_period_end", sa.DateTime(), nullable=False),
            sa.Column("renews_at", sa.DateTime(), nullable=True),
            sa.Column("canceled_at", sa.DateTime(), nullable=True),
            sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["pending_plan_id"], ["plans.plan_id"]),
            sa.ForeignKeyConstraint(["plan_id"], ["plans.plan_id"]),
            sa.ForeignKeyConstraint(["previous_plan_id"], ["plans.plan_id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_id"),
        )
    if "usage_records" not in tables:
        op.create_table(
            "usage_records",
            sa.Column("id", sa.String(length=50), nullable=False),
            sa.Column("workspace_id", sa.String(length=50), nullable=False),
            sa.Column("metric", sa.String(length=100), nullable=False),
            sa.Column("quantity", sa.BigInteger(), nullable=False, server_default="1"),
            sa.Column("period", sa.String(length=20), nullable=False),
            sa.Column("source", sa.String(length=100), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if "ix_usage_records_workspace_id" not in _indexes("usage_records"):
        op.create_index("ix_usage_records_workspace_id", "usage_records", ["workspace_id"])
    if "ix_usage_records_workspace_metric_period" not in _indexes("usage_records"):
        op.create_index("ix_usage_records_workspace_metric_period", "usage_records", ["workspace_id", "metric", "period"])

    if "quotas" not in tables:
        op.create_table(
            "quotas",
            sa.Column("id", sa.String(length=50), nullable=False),
            sa.Column("workspace_id", sa.String(length=50), nullable=False),
            sa.Column("metric", sa.String(length=100), nullable=False),
            sa.Column("limit_value", sa.BigInteger(), nullable=False),
            sa.Column("used_value", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("period", sa.String(length=20), nullable=False),
            sa.Column("reset_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_id", "metric", "period", name="uq_quota_workspace_metric_period"),
        )
    if "trials" not in tables:
        op.create_table(
            "trials",
            sa.Column("id", sa.String(length=50), nullable=False),
            sa.Column("workspace_id", sa.String(length=50), nullable=False),
            sa.Column("plan_id", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("ends_at", sa.DateTime(), nullable=False),
            sa.Column("grace_period_ends_at", sa.DateTime(), nullable=True),
            sa.Column("converted_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["plan_id"], ["plans.plan_id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if "ix_trials_workspace_id" not in _indexes("trials"):
        op.create_index("ix_trials_workspace_id", "trials", ["workspace_id"])

    if "subscription_history" not in tables:
        op.create_table(
            "subscription_history",
            sa.Column("id", sa.String(length=50), nullable=False),
            sa.Column("workspace_subscription_id", sa.String(length=50), nullable=False),
            sa.Column("workspace_id", sa.String(length=50), nullable=False),
            sa.Column("from_plan_id", sa.String(length=50), nullable=True),
            sa.Column("to_plan_id", sa.String(length=50), nullable=True),
            sa.Column("from_status", sa.String(length=50), nullable=True),
            sa.Column("to_status", sa.String(length=50), nullable=True),
            sa.Column("event_type", sa.String(length=100), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_subscription_id"], ["workspace_subscriptions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if "ix_subscription_history_workspace_id" not in _indexes("subscription_history"):
        op.create_index("ix_subscription_history_workspace_id", "subscription_history", ["workspace_id"])


def downgrade():
    op.drop_index("ix_subscription_history_workspace_id", table_name="subscription_history")
    op.drop_table("subscription_history")
    op.drop_index("ix_trials_workspace_id", table_name="trials")
    op.drop_table("trials")
    op.drop_table("quotas")
    op.drop_index("ix_usage_records_workspace_metric_period", table_name="usage_records")
    op.drop_index("ix_usage_records_workspace_id", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_table("workspace_subscriptions")
    op.drop_table("plan_limits")
    op.drop_table("plan_features")
    op.drop_table("features")

    with op.batch_alter_table("plans", schema=None) as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("created_at")
        batch_op.drop_column("display_order")
        batch_op.drop_column("is_public")
        batch_op.drop_column("trial_days")
        batch_op.drop_column("reset_interval")
        batch_op.drop_column("ai_prompt_limit")
        batch_op.drop_column("workspace_limit")
        batch_op.drop_column("api_usage_limit")
        batch_op.drop_column("chart_limit")
        batch_op.drop_column("dataset_limit")
        batch_op.drop_column("description")
