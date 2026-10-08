"""admin traces and last sign-in

R2 (admin area). Adds the interviewer_traces table: one row per interviewer model call (or fixed
line) in a session, with the controller's move and reason, the timer state, the prompt, the raw
reply, tokens, cost and latency. A worker cron job deletes rows older than 90 days. Adds
users.last_sign_in_at, set at each sign-in.

Revision ID: 0008
Revises: 0006
Create Date: 2026-10-08 06:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0008'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('interviewer_traces',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False, comment='Order of the call in the session'),
    sa.Column('turn_index', sa.Integer(), nullable=False, comment='Transcript length at the call'),
    sa.Column('call', sa.String(length=20), nullable=False, comment='say, decide, line or rollback'),
    sa.Column('move', sa.String(length=40), nullable=False, comment='Controller move or fixed line name'),
    sa.Column('reason_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="Why: the ProbeDecision and the controller's reason"),
    sa.Column('phase', sa.Enum('intro', 'small_talk', 'agenda', 'core', 'candidate_questions', 'wrap_up', name='phase', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('elapsed_ms', sa.Integer(), nullable=False),
    sa.Column('phase_deadline_ms', sa.Integer(), nullable=True),
    sa.Column('question_ref', sa.String(length=100), nullable=True),
    sa.Column('messages_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Prompt messages sent'),
    sa.Column('raw_reply', sa.Text(), nullable=True),
    sa.Column('spoken_text', sa.Text(), nullable=True),
    sa.Column('model', sa.String(length=200), nullable=True, comment='Gateway alias'),
    sa.Column('prompt_refs', sa.String(length=500), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=12, scale=6), nullable=True, comment='From the LiteLLM config prices; NULL when unknown'),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_interviewer_traces_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_interviewer_traces_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interviewer_traces'))
    )
    op.create_index(op.f('ix_interviewer_traces_org_id'), 'interviewer_traces', ['org_id'], unique=False)
    op.create_index(op.f('ix_interviewer_traces_created_at'), 'interviewer_traces', ['created_at'], unique=False)
    op.create_index('ix_interviewer_traces_session_seq', 'interviewer_traces', ['session_id', 'seq'], unique=False)
    op.add_column('users', sa.Column('last_sign_in_at', sa.DateTime(timezone=True), nullable=True, comment='Set at each sign-in (admin users page)'))


def downgrade() -> None:
    op.drop_column('users', 'last_sign_in_at')
    op.drop_index('ix_interviewer_traces_session_seq', table_name='interviewer_traces')
    op.drop_index(op.f('ix_interviewer_traces_created_at'), table_name='interviewer_traces')
    op.drop_index(op.f('ix_interviewer_traces_org_id'), table_name='interviewer_traces')
    op.drop_table('interviewer_traces')
