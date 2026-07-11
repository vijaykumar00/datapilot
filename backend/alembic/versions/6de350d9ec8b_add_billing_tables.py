"""add_billing_tables

Revision ID: 6de350d9ec8b
Revises: 3dc2726cdc1e
Create Date: 2026-07-11 12:30:24.034843

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6de350d9ec8b'
down_revision: Union[str, None] = '3dc2726cdc1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create billing and plan tables
    op.create_table('plans',
    sa.Column('plan_id', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('monthly_price_cents', sa.Integer(), nullable=False),
    sa.Column('annual_price_cents', sa.Integer(), nullable=False),
    sa.Column('query_limit', sa.Integer(), nullable=False),
    sa.Column('upload_limit', sa.Integer(), nullable=False),
    sa.Column('file_size_limit_bytes', sa.BigInteger(), nullable=False),
    sa.Column('storage_limit_bytes', sa.BigInteger(), nullable=False),
    sa.Column('report_limit', sa.Integer(), nullable=False),
    sa.Column('export_limit', sa.Integer(), nullable=False),
    sa.Column('member_limit', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('plan_id')
    )
    op.create_table('subscription_events',
    sa.Column('id', sa.String(length=50), nullable=False),
    sa.Column('stripe_subscription_id', sa.String(length=255), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('payload', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('webhook_events',
    sa.Column('id', sa.String(length=50), nullable=False),
    sa.Column('stripe_event_id', sa.String(length=255), nullable=False),
    sa.Column('processed', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stripe_event_id')
    )
    op.create_table('billing_customers',
    sa.Column('id', sa.String(length=50), nullable=False),
    sa.Column('workspace_id', sa.String(length=50), nullable=False),
    sa.Column('stripe_customer_id', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.workspace_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stripe_customer_id'),
    sa.UniqueConstraint('workspace_id')
    )
    op.create_table('subscriptions',
    sa.Column('id', sa.String(length=50), nullable=False),
    sa.Column('workspace_id', sa.String(length=50), nullable=False),
    sa.Column('stripe_subscription_id', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('plan_id', sa.String(length=50), nullable=False),
    sa.Column('current_period_start', sa.DateTime(), nullable=False),
    sa.Column('current_period_end', sa.DateTime(), nullable=False),
    sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['plans.plan_id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.workspace_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stripe_subscription_id')
    )


def downgrade() -> None:
    # Drop tables in reverse order of creation dependencies
    op.drop_table('subscriptions')
    op.drop_table('billing_customers')
    op.drop_table('webhook_events')
    op.drop_table('subscription_events')
    op.drop_table('plans')
