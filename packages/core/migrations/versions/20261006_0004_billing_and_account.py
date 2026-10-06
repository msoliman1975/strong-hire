"""billing and account: stripe events, exit surveys

P9 (BL-1, AC-1). Adds stripe_events (handled webhook event ids, for idempotency), exit_surveys
(cancellation exit survey, user-owned), and two subscription columns: stripe_subscription_id
and cancel_at_period_end.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06 02:03:24.272549
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('stripe_events',
    sa.Column('id', sa.String(length=100), nullable=False, comment='Stripe event id'),
    sa.Column('type', sa.String(length=100), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stripe_events'))
    )
    op.create_table('exit_surveys',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('reason', sa.String(length=50), nullable=False),
    sa.Column('reason_detail', sa.Text(), nullable=True),
    sa.Column('got_job', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_exit_surveys_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_exit_surveys_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_exit_surveys'))
    )
    op.create_index(op.f('ix_exit_surveys_org_id'), 'exit_surveys', ['org_id'], unique=False)
    op.create_index(op.f('ix_exit_surveys_user_id'), 'exit_surveys', ['user_id'], unique=False)
    op.add_column('subscriptions', sa.Column('stripe_subscription_id', sa.String(length=100), nullable=True, comment='The current Stripe subscription. A new one replaces a canceled one.'))
    op.add_column('subscriptions', sa.Column('cancel_at_period_end', sa.Boolean(), server_default='false', nullable=False, comment='Canceled; ends at period_end'))


def downgrade() -> None:
    op.drop_column('subscriptions', 'cancel_at_period_end')
    op.drop_column('subscriptions', 'stripe_subscription_id')
    op.drop_index(op.f('ix_exit_surveys_user_id'), table_name='exit_surveys')
    op.drop_index(op.f('ix_exit_surveys_org_id'), table_name='exit_surveys')
    op.drop_table('exit_surveys')
    op.drop_table('stripe_events')
