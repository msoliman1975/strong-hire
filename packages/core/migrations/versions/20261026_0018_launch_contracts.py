"""launch contracts (L01)

Plans and the price test on subscriptions (L03), the real interview date on job targets and
the email log (L06), email preferences and analytics consent on users (L05, L06), and paid
top-ups as minute_grants rows of kind top_up (L03), with minutes_used, the Stripe checkout
session id and the amount paid. The waitlist (0016) and session feedback (0017) tables already
exist.

Backfill: active and trialing subscriptions that are not test-plan rows get plan_code monthly
and allowance_start = period_start.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-26 01:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0018'
down_revision: str | None = '0017'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('email_logs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Enum('welcome', 'finish_setup', 'free_interview_nudge', 'debrief_ready', 'paywall_followup', 'interview_countdown_7', 'interview_countdown_2', 'interview_day', 'after_interview', 'minutes_low', 'winback', name='email_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('ref', sa.String(length=64), server_default='', nullable=False, comment='A job or session id; empty for one-off emails (NULLs would defeat the unique key)'),
    sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_email_logs_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_email_logs_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_logs')),
    sa.UniqueConstraint('user_id', 'kind', 'ref', name=op.f('uq_email_logs_user_id'))
    )
    op.create_index(op.f('ix_email_logs_org_id'), 'email_logs', ['org_id'], unique=False)
    op.create_index(op.f('ix_email_logs_user_id'), 'email_logs', ['user_id'], unique=False)

    op.add_column('job_targets', sa.Column('interview_date', sa.Date(), nullable=True, comment="L01, L06: the candidate's real interview date, if they know it"))

    op.add_column('subscriptions', sa.Column('plan_code', sa.Enum('monthly', 'job_hunt_3m', name='plan_code', native_enum=False, create_constraint=True, length=32), nullable=True, comment='L03: NULL for free and test-plan rows'))
    op.add_column('subscriptions', sa.Column('stripe_price_id', sa.String(length=100), nullable=True, comment='L03: the price the user bought'))
    op.add_column('subscriptions', sa.Column('price_variant', sa.String(length=40), nullable=True, comment='L03: the paywall price-test arm, for example p29'))
    op.add_column('subscriptions', sa.Column('allowance_start', sa.DateTime(timezone=True), nullable=True, comment='L03: start of the current monthly allowance; resets monthly inside a 3-month plan'))

    op.add_column('users', sa.Column('product_email', sa.Boolean(), server_default='true', nullable=False, comment="L06: debrief ready, reminders and nudges about the user's own jobs"))
    op.add_column('users', sa.Column('marketing_email', sa.Boolean(), server_default='false', nullable=False, comment='L06: win-back and newsletters. Express consent (CASL), off by default'))
    op.add_column('users', sa.Column('email_unsubscribe_token', sa.String(length=64), nullable=True, comment='L06: the one-click unsubscribe link'))
    op.add_column('users', sa.Column('analytics_consent', sa.Boolean(), server_default='false', nullable=False, comment='L05: client-side analytics only when true'))
    op.create_unique_constraint(op.f('uq_users_email_unsubscribe_token'), 'users', ['email_unsubscribe_token'])

    op.drop_constraint(op.f('ck_minute_grants_grant_kind'), 'minute_grants', type_='check')
    op.create_check_constraint(op.f('ck_minute_grants_grant_kind'), 'minute_grants', "kind IN ('minutes', 'free_interviews', 'comp_plan', 'top_up')")
    op.add_column('minute_grants', sa.Column('minutes_used', sa.Integer(), server_default='0', nullable=False, comment='L01: top_up only, minutes spent so far'))
    op.add_column('minute_grants', sa.Column('stripe_checkout_session_id', sa.String(length=255), nullable=True, comment='L01: top_up only; one credit per checkout'))
    op.add_column('minute_grants', sa.Column('amount_usd', sa.Numeric(precision=10, scale=2), nullable=True, comment='L01: top_up only, what the user paid'))
    op.create_unique_constraint(op.f('uq_minute_grants_stripe_checkout_session_id'), 'minute_grants', ['stripe_checkout_session_id'])

    op.execute(
        "UPDATE subscriptions SET plan_code = 'monthly', allowance_start = period_start "
        "WHERE status IN ('active', 'trialing') "
        "AND (stripe_customer_id IS NULL OR stripe_customer_id NOT LIKE 'test-plan:%')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f('uq_minute_grants_stripe_checkout_session_id'), 'minute_grants', type_='unique')
    op.drop_column('minute_grants', 'amount_usd')
    op.drop_column('minute_grants', 'stripe_checkout_session_id')
    op.drop_column('minute_grants', 'minutes_used')
    op.execute("DELETE FROM minute_grants WHERE kind = 'top_up'")
    op.drop_constraint(op.f('ck_minute_grants_grant_kind'), 'minute_grants', type_='check')
    op.create_check_constraint(op.f('ck_minute_grants_grant_kind'), 'minute_grants', "kind IN ('minutes', 'free_interviews', 'comp_plan')")
    op.drop_constraint(op.f('uq_users_email_unsubscribe_token'), 'users', type_='unique')
    op.drop_column('users', 'analytics_consent')
    op.drop_column('users', 'email_unsubscribe_token')
    op.drop_column('users', 'marketing_email')
    op.drop_column('users', 'product_email')
    op.drop_column('subscriptions', 'allowance_start')
    op.drop_column('subscriptions', 'price_variant')
    op.drop_column('subscriptions', 'stripe_price_id')
    op.drop_column('subscriptions', 'plan_code')
    op.drop_column('job_targets', 'interview_date')
    op.drop_index(op.f('ix_email_logs_user_id'), table_name='email_logs')
    op.drop_index(op.f('ix_email_logs_org_id'), table_name='email_logs')
    op.drop_table('email_logs')
