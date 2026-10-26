"""session feedback (L05)

Adds the user-owned table session_feedback: the post-session rating, "felt like a real
interview", 1 to 5, one per session.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-25 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0017'
down_revision: str | None = '0016'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('session_feedback',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False, comment='One per session'),
    sa.Column('realism', sa.Integer(), nullable=False, comment='1 to 5'),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('realism BETWEEN 1 AND 5', name=op.f('ck_session_feedback_realism_range')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_session_feedback_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_session_feedback_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_session_feedback')),
    sa.UniqueConstraint('session_id', name=op.f('uq_session_feedback_session_id'))
    )
    op.create_index(op.f('ix_session_feedback_org_id'), 'session_feedback', ['org_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_session_feedback_org_id'), table_name='session_feedback')
    op.drop_table('session_feedback')
