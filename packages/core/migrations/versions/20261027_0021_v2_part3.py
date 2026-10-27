"""v2 part 3 (C3)

The user-owned coach_sessions, coach_turns and takes tables (CO-2, CO-5, CO-6, CO-7). The
recruiter_screen interview type and its logistics_and_expectations competency (RS-1): the
CHECK constraints for the interview_type, saved_question_category and competency enums are
replaced to allow the new values.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-27 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0021'
down_revision: str | None = '0020'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = "'behavioral', 'hiring_manager', 'technical_qa', 'case', 'custom'"
_COMPETENCIES = (
    "'ownership', 'impact', 'collaboration', 'conflict_handling', 'learning_from_failure', "
    "'communication', 'role_fit', 'depth_of_experience', 'judgment', 'motivation', 'team_fit', "
    "'scope_at_level', 'technical_depth', 'accuracy', 'reasoning', 'trade_offs', "
    "'clarity_of_explanation', 'problem_framing', 'structure', 'user_and_business_sense', "
    "'estimation_logic', 'prioritization', 'recommendation'"
)
# (constraint, table, column, old values, new value)
_ENUM_CHECKS = (
    ('ck_sessions_interview_type', 'sessions', 'type', _TYPES, 'recruiter_screen'),
    ('ck_saved_questions_saved_question_category', 'saved_questions', 'category', _TYPES, 'recruiter_screen'),
    ('ck_progress_snapshots_competency', 'progress_snapshots', 'competency', _COMPETENCIES, 'logistics_and_expectations'),
)


def upgrade() -> None:
    for ck, table, column, old, new in _ENUM_CHECKS:
        op.drop_constraint(op.f(ck), table, type_='check')
        op.create_check_constraint(op.f(ck), table, f"{column} IN ({old}, '{new}')")

    op.create_table('coach_sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('story_id', sa.Uuid(), nullable=True, comment='The story it builds; NULL until the coach creates one'),
    sa.Column('style', sa.Enum('gentle', 'direct', name='coach_style', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('channel', sa.Enum('voice', 'text', name='session_channel', native_enum=False, create_constraint=True, length=32), nullable=False, comment='CO-6: voice or text'),
    sa.Column('status', sa.Enum('active', 'ended', 'failed', name='coach_session_status', native_enum=False, create_constraint=True, length=32), server_default='active', nullable=False),
    sa.Column('minutes', sa.Integer(), server_default='0', nullable=False, comment='Recorded like any session'),
    sa.Column('model_profile', sa.String(length=20), nullable=True, comment='PL-6: MODEL_PROFILE the session ran on'),
    sa.Column('model_id', sa.String(length=200), nullable=True, comment='PL-6: gateway alias that served the coach role'),
    sa.Column('prompt_version', sa.String(length=200), nullable=True, comment='PL-6: coach prompt refs, comma separated'),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_coach_sessions_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['story_id'], ['stories.id'], name=op.f('fk_coach_sessions_story_id_stories'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_coach_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_coach_sessions'))
    )
    op.create_index(op.f('ix_coach_sessions_org_id'), 'coach_sessions', ['org_id'], unique=False)
    op.create_index(op.f('ix_coach_sessions_story_id'), 'coach_sessions', ['story_id'], unique=False)
    op.create_index(op.f('ix_coach_sessions_user_id'), 'coach_sessions', ['user_id'], unique=False)

    op.create_table('coach_turns',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('coach_session_id', sa.Uuid(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False, comment='Order of the turn in its session, from 1'),
    sa.Column('speaker', sa.Enum('coach', 'candidate', name='coach_speaker', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('start_ms', sa.Integer(), nullable=False),
    sa.Column('end_ms', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['coach_session_id'], ['coach_sessions.id'], name=op.f('fk_coach_turns_coach_session_id_coach_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_coach_turns_org_id_orgs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_coach_turns'))
    )
    op.create_index('ix_coach_turns_session_seq', 'coach_turns', ['coach_session_id', 'seq'], unique=False)
    op.create_index(op.f('ix_coach_turns_org_id'), 'coach_turns', ['org_id'], unique=False)

    op.create_table('takes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('story_id', sa.Uuid(), nullable=False),
    sa.Column('channel', sa.Enum('voice', 'text', name='session_channel', native_enum=False, create_constraint=True, length=32), nullable=False, comment='Spoken (voice) or typed (text)'),
    sa.Column('text', sa.Text(), nullable=False, comment='The telling, transcribed or typed'),
    sa.Column('duration_s', sa.Double(), nullable=True, comment='Length of a spoken take; NULL for a typed one'),
    sa.Column('skill_scores_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='schemas.CompetencyScore list; NULL until scored'),
    sa.Column('model_profile', sa.String(length=20), nullable=True, comment='PL-6: MODEL_PROFILE the scorer ran on'),
    sa.Column('model_id', sa.String(length=200), nullable=True, comment='PL-6: gateway alias that served the scorer role'),
    sa.Column('prompt_version', sa.String(length=200), nullable=True, comment='PL-6: scorer prompt refs, comma separated'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_takes_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['story_id'], ['stories.id'], name=op.f('fk_takes_story_id_stories'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_takes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_takes'))
    )
    op.create_index(op.f('ix_takes_org_id'), 'takes', ['org_id'], unique=False)
    op.create_index(op.f('ix_takes_story_id'), 'takes', ['story_id'], unique=False)
    op.create_index(op.f('ix_takes_user_id'), 'takes', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_takes_user_id'), table_name='takes')
    op.drop_index(op.f('ix_takes_story_id'), table_name='takes')
    op.drop_index(op.f('ix_takes_org_id'), table_name='takes')
    op.drop_table('takes')
    op.drop_index(op.f('ix_coach_turns_org_id'), table_name='coach_turns')
    op.drop_index('ix_coach_turns_session_seq', table_name='coach_turns')
    op.drop_table('coach_turns')
    op.drop_index(op.f('ix_coach_sessions_user_id'), table_name='coach_sessions')
    op.drop_index(op.f('ix_coach_sessions_story_id'), table_name='coach_sessions')
    op.drop_index(op.f('ix_coach_sessions_org_id'), table_name='coach_sessions')
    op.drop_table('coach_sessions')

    # Rows with the new values cannot exist under the old constraints. Transcripts and
    # scorecards cascade from the session row.
    op.execute("DELETE FROM progress_snapshots WHERE competency = 'logistics_and_expectations'")
    op.execute("DELETE FROM saved_questions WHERE category = 'recruiter_screen'")
    op.execute("DELETE FROM sessions WHERE type = 'recruiter_screen'")
    for ck, table, column, old, _new in _ENUM_CHECKS:
        op.drop_constraint(op.f(ck), table, type_='check')
        op.create_check_constraint(op.f(ck), table, f"{column} IN ({old})")
