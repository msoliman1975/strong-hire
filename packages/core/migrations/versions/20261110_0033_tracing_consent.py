"""Tracing consent for production tracing (LT-20)

Adds users.tracing_consent (off by default, D-12) and users.tracing_consent_at.

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0033'
down_revision: str | None = '0032'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('tracing_consent', sa.Boolean(), server_default='false', nullable=False, comment='LT-20: interview turns may be kept for review. Off by default'))
    op.add_column('users', sa.Column('tracing_consent_at', sa.DateTime(timezone=True), nullable=True, comment='LT-20: when tracing_consent last changed'))


def downgrade() -> None:
    op.drop_column('users', 'tracing_consent_at')
    op.drop_column('users', 'tracing_consent')
