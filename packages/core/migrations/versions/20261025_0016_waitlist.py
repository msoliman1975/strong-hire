"""waitlist (L04 step 1)

Adds the platform table waitlist_entries: people who asked to hear when Strong Hire opens,
with double opt-in (confirmed_at) and a separate marketing consent (CASL).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-25 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0016'
down_revision: str | None = '0015'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('waitlist_entries',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False, comment='Lowercased'),
    sa.Column('role_family', sa.Enum('swe', 'data_ml', 'pm', 'design', 'tpm', 'other', name='role_family', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('interview_within', sa.Enum('two_weeks', 'month', 'later', 'not_yet', name='interview_within', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('marketing_consent', sa.Boolean(), server_default='false', nullable=False, comment='CASL: express, unticked box'),
    sa.Column('source', sa.String(length=100), nullable=True, comment='utm_source, if any'),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True, comment='Set when the email link is opened'),
    sa.Column('invited_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_waitlist_entries')),
    sa.UniqueConstraint('email', name=op.f('uq_waitlist_entries_email'))
    )


def downgrade() -> None:
    op.drop_table('waitlist_entries')
