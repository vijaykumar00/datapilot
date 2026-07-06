"""
Phase 2 migration: Add guest_sessions, usage_stats, user_settings tables
and extend existing tables with guest_session_id column.

Revision ID: 3dc2726cdc1e
Revises: 96e4e347edff
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '3dc2726cdc1e'
down_revision = '96e4e347edff'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── New table: guest_sessions ────────────────────────────
    op.create_table(
        'guest_sessions',
        sa.Column('guest_session_id', sa.String(50), nullable=False),
        sa.Column('session_token', sa.String(255), nullable=False),
        sa.Column('ip_address', sa.String(50), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('upload_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('query_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('report_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('export_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('converted_to_user_id', sa.String(50), sa.ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True),
        sa.Column('converted_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('guest_session_id'),
    )
    op.create_index('ix_guest_sessions_token', 'guest_sessions', ['session_token'], unique=True)

    # ── New table: usage_stats ───────────────────────────────
    op.create_table(
        'usage_stats',
        sa.Column('id', sa.String(50), nullable=False),
        sa.Column('workspace_id', sa.String(50), sa.ForeignKey('workspaces.workspace_id', ondelete='CASCADE'), nullable=False),
        sa.Column('period', sa.String(20), nullable=False),
        sa.Column('upload_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('query_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('report_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('export_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('storage_bytes', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('ai_tokens_used', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_usage_stats_workspace', 'usage_stats', ['workspace_id'])

    # ── New table: user_settings ─────────────────────────────
    op.create_table(
        'user_settings',
        sa.Column('user_id', sa.String(50), sa.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False),
        sa.Column('default_workspace_id', sa.String(50), sa.ForeignKey('workspaces.workspace_id', ondelete='SET NULL'), nullable=True),
        sa.Column('theme', sa.String(20), nullable=False, server_default='dark'),
        sa.Column('notification_email', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('timezone', sa.String(50), nullable=False, server_default='UTC'),
        sa.Column('language', sa.String(10), nullable=False, server_default='en'),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('user_id'),
    )

    # ── Extend users table ───────────────────────────────────
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('full_name', sa.String(255), nullable=True))
        batch_op.add_column(sa.Column('avatar_url', sa.String(500), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))

    # ── Extend workspaces table ──────────────────────────────
    with op.batch_alter_table('workspaces') as batch_op:
        batch_op.add_column(sa.Column('slug', sa.String(100), nullable=True))
        batch_op.add_column(sa.Column('owner_id', sa.String(50), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))

    # ── Extend user_api_keys table ───────────────────────────
    with op.batch_alter_table('user_api_keys') as batch_op:
        batch_op.add_column(sa.Column('label', sa.String(100), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))

    # ── Extend audit_logs table ──────────────────────────────
    with op.batch_alter_table('audit_logs') as batch_op:
        batch_op.add_column(sa.Column('guest_session_id', sa.String(50), nullable=True))

    # ── Extend sessions table ────────────────────────────────
    with op.batch_alter_table('sessions') as batch_op:
        batch_op.add_column(sa.Column('guest_session_id', sa.String(50), nullable=True))

    # ── Extend messages table ────────────────────────────────
    with op.batch_alter_table('messages') as batch_op:
        batch_op.add_column(sa.Column('guest_session_id', sa.String(50), nullable=True))

    # ── Extend saved_analyses table ──────────────────────────
    with op.batch_alter_table('saved_analyses') as batch_op:
        batch_op.add_column(sa.Column('guest_session_id', sa.String(50), nullable=True))

    # ── Extend reports table ─────────────────────────────────
    with op.batch_alter_table('reports') as batch_op:
        batch_op.add_column(sa.Column('guest_session_id', sa.String(50), nullable=True))

    # ── Extend dataset_registry table ───────────────────────
    with op.batch_alter_table('dataset_registry') as batch_op:
        batch_op.add_column(sa.Column('guest_session_id', sa.String(50), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('dataset_registry') as batch_op:
        batch_op.drop_column('guest_session_id')
    with op.batch_alter_table('reports') as batch_op:
        batch_op.drop_column('guest_session_id')
    with op.batch_alter_table('saved_analyses') as batch_op:
        batch_op.drop_column('guest_session_id')
    with op.batch_alter_table('messages') as batch_op:
        batch_op.drop_column('guest_session_id')
    with op.batch_alter_table('sessions') as batch_op:
        batch_op.drop_column('guest_session_id')
    with op.batch_alter_table('audit_logs') as batch_op:
        batch_op.drop_column('guest_session_id')
    with op.batch_alter_table('user_api_keys') as batch_op:
        batch_op.drop_column('updated_at')
        batch_op.drop_column('label')
    with op.batch_alter_table('workspaces') as batch_op:
        batch_op.drop_column('updated_at')
        batch_op.drop_column('owner_id')
        batch_op.drop_column('slug')
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('updated_at')
        batch_op.drop_column('avatar_url')
        batch_op.drop_column('full_name')
    op.drop_table('user_settings')
    op.drop_index('ix_usage_stats_workspace', table_name='usage_stats')
    op.drop_table('usage_stats')
    op.drop_index('ix_guest_sessions_token', table_name='guest_sessions')
    op.drop_table('guest_sessions')
