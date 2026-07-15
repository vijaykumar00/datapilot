"""RC-1 performance indexes — add missing indexes on high-frequency filter columns

Revision ID: a7f3b9c2d1e4
Revises: 6de350d9ec8b
Create Date: 2026-07-15

Indexes added:
  - sessions.user_id, sessions.workspace_id (session list queries)
  - messages.user_id, messages.workspace_id (history queries)
  - email_verification_tokens.token_hash (auth hot path)
  - password_reset_tokens.token_hash (auth hot path)
  - workspace_members.user_id (workspace list queries)
  - refresh_tokens.user_id (logout-all queries)
  - usage_stats.(workspace_id, period) composite unique (usage tracking)
  - audit_logs.(user_id, workspace_id) (audit view queries)
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a7f3b9c2d1e4'
down_revision = '6de350d9ec8b'
branch_labels = None
depends_on = None


def upgrade():
    # ── sessions table ───────────────────────────────────────────────────────
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.create_index('ix_sessions_user_id', ['user_id'], unique=False)
        batch_op.create_index('ix_sessions_workspace_id', ['workspace_id'], unique=False)

    # ── messages table ───────────────────────────────────────────────────────
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.create_index('ix_messages_user_id', ['user_id'], unique=False)
        batch_op.create_index('ix_messages_workspace_id', ['workspace_id'], unique=False)
        batch_op.create_index('ix_messages_session_id', ['session_id'], unique=False)

    # ── email_verification_tokens ────────────────────────────────────────────
    with op.batch_alter_table('email_verification_tokens', schema=None) as batch_op:
        batch_op.create_index('ix_email_verification_tokens_token_hash', ['token_hash'], unique=False)

    # ── password_reset_tokens ────────────────────────────────────────────────
    with op.batch_alter_table('password_reset_tokens', schema=None) as batch_op:
        batch_op.create_index('ix_password_reset_tokens_token_hash', ['token_hash'], unique=False)

    # ── workspace_members ────────────────────────────────────────────────────
    with op.batch_alter_table('workspace_members', schema=None) as batch_op:
        batch_op.create_index('ix_workspace_members_user_id', ['user_id'], unique=False)

    # ── refresh_tokens ───────────────────────────────────────────────────────
    with op.batch_alter_table('refresh_tokens', schema=None) as batch_op:
        batch_op.create_index('ix_refresh_tokens_user_id', ['user_id'], unique=False)

    # ── usage_stats — composite index + unique constraint ────────────────────
    with op.batch_alter_table('usage_stats', schema=None) as batch_op:
        batch_op.create_index('ix_usage_stats_workspace_period', ['workspace_id', 'period'], unique=True)

    # ── audit_logs ───────────────────────────────────────────────────────────
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.create_index('ix_audit_logs_user_workspace', ['user_id', 'workspace_id'], unique=False)


def downgrade():
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_logs_user_workspace')

    with op.batch_alter_table('usage_stats', schema=None) as batch_op:
        batch_op.drop_index('ix_usage_stats_workspace_period')

    with op.batch_alter_table('refresh_tokens', schema=None) as batch_op:
        batch_op.drop_index('ix_refresh_tokens_user_id')

    with op.batch_alter_table('workspace_members', schema=None) as batch_op:
        batch_op.drop_index('ix_workspace_members_user_id')

    with op.batch_alter_table('password_reset_tokens', schema=None) as batch_op:
        batch_op.drop_index('ix_password_reset_tokens_token_hash')

    with op.batch_alter_table('email_verification_tokens', schema=None) as batch_op:
        batch_op.drop_index('ix_email_verification_tokens_token_hash')

    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_index('ix_messages_session_id')
        batch_op.drop_index('ix_messages_workspace_id')
        batch_op.drop_index('ix_messages_user_id')

    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index('ix_sessions_workspace_id')
        batch_op.drop_index('ix_sessions_user_id')
