"""durable datasets, jobs, oauth identities, security and performance indexes

Revision ID: d1e2f3a4b5c6
Revises: c9f1a2b3d4e5
Create Date: 2026-10-02
"""

from alembic import op
import sqlalchemy as sa


revision = "d1e2f3a4b5c6"
down_revision = "c9f1a2b3d4e5"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name):
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name):
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _add_column(table, column):
    if table in _tables() and column.name not in _columns(table):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(column)


def _index(name, table, columns, unique=False):
    if table in _tables() and name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def _server_default(table, column, default, type_=None):
    """Give NOT NULL JSON/text columns a server default so raw SQL inserts cannot fail."""
    if table in _tables() and column in _columns(table):
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(column, existing_type=type_ or sa.Text(), server_default=default,
                                  existing_nullable=False)


def upgrade():
    tables = _tables()
    for table, column, default in [
        ("dataset_registry", "column_summary", "[]"),
        ("dataset_registry", "schema_warnings", "[]"),
        ("dataset_registry", "tags", "[]"),
        ("reports", "export_formats", "[]"),
        ("reports", "tags", "[]"),
        ("reports", "metadata", "{}"),
    ]:
        _server_default(table, column, default)

    # ── Durable dataset registry columns ────────────────────────────────────
    _add_column("dataset_registry", sa.Column("status", sa.String(length=20), nullable=False, server_default="ready"))
    _add_column("dataset_registry", sa.Column("current_version", sa.Integer(), nullable=True))
    _add_column("dataset_registry", sa.Column("storage_workspace_id", sa.String(length=64), nullable=True))
    _add_column("dataset_registry", sa.Column("original_key", sa.String(length=512), nullable=True))
    _add_column("dataset_registry", sa.Column("metadata_json", sa.Text(), nullable=True))
    _add_column("dataset_registry", sa.Column("error", sa.Text(), nullable=True))
    _add_column("dataset_registry", sa.Column("storage_bytes", sa.BigInteger(), nullable=False, server_default="0"))

    if "dataset_versions" not in tables:
        op.create_table(
            "dataset_versions",
            sa.Column("id", sa.String(length=50), primary_key=True),
            sa.Column("dataset_id", sa.String(length=50), sa.ForeignKey("dataset_registry.dataset_id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("storage_key", sa.String(length=512), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("action_json", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("column_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.String(length=50), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("dataset_id", "version", name="uq_dataset_versions_dataset_version"),
        )
    _index("ix_dataset_versions_dataset_id", "dataset_versions", ["dataset_id"])

    if "staged_transforms" not in tables:
        op.create_table(
            "staged_transforms",
            sa.Column("id", sa.String(length=50), primary_key=True),
            sa.Column("dataset_id", sa.String(length=50), sa.ForeignKey("dataset_registry.dataset_id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("base_version", sa.Integer(), nullable=False),
            sa.Column("actions_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
        )
    _index("ix_staged_transforms_dataset_id", "staged_transforms", ["dataset_id"])
    _index("ix_staged_transforms_expires_at", "staged_transforms", ["expires_at"])

    if "jobs" not in tables:
        op.create_table(
            "jobs",
            sa.Column("id", sa.String(length=50), primary_key=True),
            sa.Column("job_type", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
            sa.Column("workspace_id", sa.String(length=64), nullable=True),
            sa.Column("user_id", sa.String(length=64), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("result_key", sa.String(length=512), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("run_after", sa.DateTime(), nullable=False),
            sa.Column("locked_by", sa.String(length=100), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        )
    _index("ix_jobs_status_run_after", "jobs", ["status", "run_after"])
    _index("ix_jobs_workspace_id", "jobs", ["workspace_id"])

    if "oauth_identities" not in tables:
        op.create_table(
            "oauth_identities",
            sa.Column("id", sa.String(length=50), primary_key=True),
            sa.Column("provider", sa.String(length=20), nullable=False),
            sa.Column("subject", sa.String(length=255), nullable=False),
            sa.Column("user_id", sa.String(length=50), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("provider", "subject", name="uq_oauth_identities_provider_subject"),
        )
    _index("ix_oauth_identities_user_id", "oauth_identities", ["user_id"])

    # ── Auth / settings / billing columns ───────────────────────────────────
    _add_column("refresh_tokens", sa.Column("workspace_id", sa.String(length=50), nullable=True))
    _add_column("refresh_tokens", sa.Column("rotated_at", sa.DateTime(), nullable=True))
    _add_column("user_settings", sa.Column("llm_provider", sa.String(length=20), nullable=True))
    _add_column("subscriptions", sa.Column("last_event_at", sa.BigInteger(), nullable=True))

    # ── Query-path indexes ──────────────────────────────────────────────────
    _index("ix_messages_session_created", "messages", ["session_id", "created_at"])
    _index("ix_messages_scope_role_created", "messages", ["user_id", "workspace_id", "role", "created_at"])
    _index("ix_reports_scope", "reports", ["user_id", "workspace_id"])
    _index("ix_reports_parent", "reports", ["parent_report_id"])
    _index("ix_saved_analyses_scope", "saved_analyses", ["user_id", "workspace_id"])
    _index("ix_dataset_registry_workspace", "dataset_registry", ["workspace_id", "archived"])
    _index("ix_templates_scope", "templates", ["user_id", "workspace_id"])
    _index("ix_error_logs_timestamp", "error_logs", ["timestamp"])
    _index("ix_workspace_members_workspace_id", "workspace_members", ["workspace_id"])
    _index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    _index("ix_guest_sessions_expires_at", "guest_sessions", ["expires_at"])


def downgrade():
    for name, table in [
        ("ix_guest_sessions_expires_at", "guest_sessions"),
        ("ix_password_reset_tokens_user_id", "password_reset_tokens"),
        ("ix_workspace_members_workspace_id", "workspace_members"),
        ("ix_error_logs_timestamp", "error_logs"),
        ("ix_templates_scope", "templates"),
        ("ix_dataset_registry_workspace", "dataset_registry"),
        ("ix_saved_analyses_scope", "saved_analyses"),
        ("ix_reports_parent", "reports"),
        ("ix_reports_scope", "reports"),
        ("ix_messages_scope_role_created", "messages"),
        ("ix_messages_session_created", "messages"),
    ]:
        if table in _tables() and name in _indexes(table):
            op.drop_index(name, table_name=table)
    for table in ("oauth_identities", "jobs", "staged_transforms", "dataset_versions"):
        if table in _tables():
            op.drop_table(table)
    for table, column in [
        ("subscriptions", "last_event_at"),
        ("user_settings", "llm_provider"),
        ("refresh_tokens", "rotated_at"),
        ("refresh_tokens", "workspace_id"),
        ("dataset_registry", "storage_bytes"),
        ("dataset_registry", "error"),
        ("dataset_registry", "metadata_json"),
        ("dataset_registry", "original_key"),
        ("dataset_registry", "storage_workspace_id"),
        ("dataset_registry", "current_version"),
        ("dataset_registry", "status"),
    ]:
        if table in _tables() and column in _columns(table):
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_column(column)
