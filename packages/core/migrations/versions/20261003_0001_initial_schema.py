"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-03 16:27:36.693219
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table('audit_logs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=True, comment='No FK: rows must survive org deletion'),
    sa.Column('actor', sa.String(length=320), nullable=False),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('entity', sa.String(length=200), nullable=False),
    sa.Column('details_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index(op.f('ix_audit_logs_org_id'), 'audit_logs', ['org_id'], unique=False)
    op.create_table('companies',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_companies')),
    sa.UniqueConstraint('slug', name=op.f('uq_companies_slug'))
    )
    op.create_table('orgs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('type', sa.Enum('personal', 'business', name='org_type', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('plan', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_orgs'))
    )
    op.create_table('company_profiles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('draft', 'in_review', 'published', 'archived', name='profile_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('profile_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='schemas.CompanyProfile'),
    sa.Column('sources_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='schemas.Source list'),
    sa.Column('reviewed_by', sa.String(length=200), nullable=True),
    sa.Column('imported_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_profiles_company_id_companies'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_profiles')),
    sa.UniqueConstraint('company_id', 'version', name=op.f('uq_company_profiles_company_id'))
    )
    op.create_index(op.f('ix_company_profiles_company_id'), 'company_profiles', ['company_id'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('auth_provider', sa.Enum('google', 'email', 'dev', name='auth_provider', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('training_consent', sa.Boolean(), server_default='false', nullable=False, comment='AC-2: off by default'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_users_org_id_orgs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_index(op.f('ix_users_org_id'), 'users', ['org_id'], unique=False)
    op.create_table('job_targets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=True, comment='NULL means generic mode'),
    sa.Column('source_url', sa.String(length=2000), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('parsed_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='schemas.JobPosting'),
    sa.Column('level', sa.Enum('new_grad', 'mid', 'senior', 'staff_principal', name='level', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('stage', sa.String(length=100), nullable=True),
    sa.Column('context_notes', sa.Text(), nullable=True, comment='IN-4 optional context'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_job_targets_company_id_companies'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_job_targets_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_job_targets_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_targets'))
    )
    op.create_index(op.f('ix_job_targets_org_id'), 'job_targets', ['org_id'], unique=False)
    op.create_index(op.f('ix_job_targets_user_id'), 'job_targets', ['user_id'], unique=False)
    op.create_table('resumes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('parsed_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='schemas.Resume'),
    sa.Column('file_ref', sa.String(length=500), nullable=True, comment='Object storage key of the encrypted original file'),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_resumes_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_resumes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resumes'))
    )
    op.create_index(op.f('ix_resumes_org_id'), 'resumes', ['org_id'], unique=False)
    op.create_index(op.f('ix_resumes_user_id'), 'resumes', ['user_id'], unique=False)
    op.create_table('subscriptions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('stripe_customer_id', sa.String(length=100), nullable=True),
    sa.Column('status', sa.Enum('trialing', 'active', 'past_due', 'canceled', 'incomplete', name='subscription_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('period_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('minutes_cap', sa.Integer(), nullable=False),
    sa.Column('minutes_used', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_subscriptions_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_subscriptions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_subscriptions')),
    sa.UniqueConstraint('stripe_customer_id', name=op.f('uq_subscriptions_stripe_customer_id'))
    )
    op.create_index(op.f('ix_subscriptions_org_id'), 'subscriptions', ['org_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_user_id'), 'subscriptions', ['user_id'], unique=False)
    op.create_table('gap_analyses',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('job_target_id', sa.Uuid(), nullable=False),
    sa.Column('resume_id', sa.Uuid(), nullable=False),
    sa.Column('match_score', sa.Integer(), nullable=False),
    sa.Column('breakdown_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='schemas.GapAnalysis'),
    sa.Column('session_plan_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='schemas.PlannedSession list'),
    sa.Column('model_version', sa.String(length=200), nullable=False, comment='Gateway alias + prompt ref'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['job_target_id'], ['job_targets.id'], name=op.f('fk_gap_analyses_job_target_id_job_targets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_gap_analyses_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], name=op.f('fk_gap_analyses_resume_id_resumes'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_gap_analyses'))
    )
    op.create_index(op.f('ix_gap_analyses_job_target_id'), 'gap_analyses', ['job_target_id'], unique=False)
    op.create_index(op.f('ix_gap_analyses_org_id'), 'gap_analyses', ['org_id'], unique=False)
    op.create_index(op.f('ix_gap_analyses_resume_id'), 'gap_analyses', ['resume_id'], unique=False)
    op.create_table('sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('job_target_id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.Enum('behavioral', 'hiring_manager', 'technical_qa', 'case', name='interview_type', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('difficulty', sa.Enum('friendly', 'realistic', 'tough', name='difficulty', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('mode', sa.Enum('coach', 'realistic', name='mode', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('duration_min', sa.Integer(), nullable=False),
    sa.Column('profile_version', sa.Integer(), nullable=True, comment='NULL in generic mode'),
    sa.Column('brief_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='schemas.InterviewerBrief'),
    sa.Column('status', sa.Enum('created', 'in_progress', 'interrupted', 'scoring', 'completed', 'failed', name='session_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('minutes_billed', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['job_target_id'], ['job_targets.id'], name=op.f('fk_sessions_job_target_id_job_targets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_sessions_org_id_orgs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions'))
    )
    op.create_index(op.f('ix_sessions_job_target_id'), 'sessions', ['job_target_id'], unique=False)
    op.create_index(op.f('ix_sessions_org_id'), 'sessions', ['org_id'], unique=False)
    op.create_table('progress_snapshots',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('job_target_id', sa.Uuid(), nullable=False),
    sa.Column('competency', sa.Enum('ownership', 'impact', 'collaboration', 'conflict_handling', 'learning_from_failure', 'communication', 'role_fit', 'depth_of_experience', 'judgment', 'motivation', 'team_fit', 'scope_at_level', 'technical_depth', 'accuracy', 'reasoning', 'trade_offs', 'clarity_of_explanation', 'problem_framing', 'structure', 'user_and_business_sense', 'estimation_logic', 'prioritization', 'recommendation', name='competency', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('score', sa.Numeric(precision=3, scale=2), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_target_id'], ['job_targets.id'], name=op.f('fk_progress_snapshots_job_target_id_job_targets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_progress_snapshots_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_progress_snapshots_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_progress_snapshots'))
    )
    op.create_index('ix_progress_job_competency', 'progress_snapshots', ['job_target_id', 'competency', 'at'], unique=False)
    op.create_index(op.f('ix_progress_snapshots_org_id'), 'progress_snapshots', ['org_id'], unique=False)
    op.create_index(op.f('ix_progress_snapshots_session_id'), 'progress_snapshots', ['session_id'], unique=False)
    op.create_table('scorecards',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('hire_signal', sa.Enum('Strong Hire', 'Hire', 'Lean Hire', 'Lean No Hire', 'No Hire', name='hire_signal', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('competency_scores_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='schemas.CompetencyScore'),
    sa.Column('per_question_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='schemas.QuestionScore list'),
    sa.Column('scorer_model', sa.String(length=200), nullable=False),
    sa.Column('rubric_version', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_scorecards_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_scorecards_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_scorecards')),
    sa.UniqueConstraint('session_id', name=op.f('uq_scorecards_session_id'))
    )
    op.create_index(op.f('ix_scorecards_org_id'), 'scorecards', ['org_id'], unique=False)
    op.create_table('turns',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('speaker', sa.Enum('interviewer', 'candidate', name='speaker', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('phase', sa.Enum('intro', 'small_talk', 'agenda', 'core', 'candidate_questions', 'wrap_up', name='phase', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('start_ms', sa.Integer(), nullable=False),
    sa.Column('end_ms', sa.Integer(), nullable=False),
    sa.Column('question_ref', sa.String(length=100), nullable=True),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_turns_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_turns_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_turns'))
    )
    op.create_index(op.f('ix_turns_org_id'), 'turns', ['org_id'], unique=False)
    op.create_index('ix_turns_session_start', 'turns', ['session_id', 'start_ms'], unique=False)
    op.create_table('usage_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=True),
    sa.Column('component', sa.Enum('stt', 'llm', 'tts', name='usage_component', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('units', sa.Numeric(precision=14, scale=4), nullable=False, comment='Tokens, seconds or characters'),
    sa.Column('cost_usd', sa.Numeric(precision=12, scale=6), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_usage_events_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_usage_events_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usage_events'))
    )
    op.create_index(op.f('ix_usage_events_org_id'), 'usage_events', ['org_id'], unique=False)
    op.create_index(op.f('ix_usage_events_session_id'), 'usage_events', ['session_id'], unique=False)


def downgrade() -> None:

    op.drop_index(op.f('ix_usage_events_session_id'), table_name='usage_events')
    op.drop_index(op.f('ix_usage_events_org_id'), table_name='usage_events')
    op.drop_table('usage_events')
    op.drop_index('ix_turns_session_start', table_name='turns')
    op.drop_index(op.f('ix_turns_org_id'), table_name='turns')
    op.drop_table('turns')
    op.drop_index(op.f('ix_scorecards_org_id'), table_name='scorecards')
    op.drop_table('scorecards')
    op.drop_index(op.f('ix_progress_snapshots_session_id'), table_name='progress_snapshots')
    op.drop_index(op.f('ix_progress_snapshots_org_id'), table_name='progress_snapshots')
    op.drop_index('ix_progress_job_competency', table_name='progress_snapshots')
    op.drop_table('progress_snapshots')
    op.drop_index(op.f('ix_sessions_org_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_job_target_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index(op.f('ix_gap_analyses_resume_id'), table_name='gap_analyses')
    op.drop_index(op.f('ix_gap_analyses_org_id'), table_name='gap_analyses')
    op.drop_index(op.f('ix_gap_analyses_job_target_id'), table_name='gap_analyses')
    op.drop_table('gap_analyses')
    op.drop_index(op.f('ix_subscriptions_user_id'), table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_org_id'), table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_index(op.f('ix_resumes_user_id'), table_name='resumes')
    op.drop_index(op.f('ix_resumes_org_id'), table_name='resumes')
    op.drop_table('resumes')
    op.drop_index(op.f('ix_job_targets_user_id'), table_name='job_targets')
    op.drop_index(op.f('ix_job_targets_org_id'), table_name='job_targets')
    op.drop_table('job_targets')
    op.drop_index(op.f('ix_users_org_id'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_company_profiles_company_id'), table_name='company_profiles')
    op.drop_table('company_profiles')
    op.drop_table('orgs')
    op.drop_table('companies')
    op.drop_index(op.f('ix_audit_logs_org_id'), table_name='audit_logs')
    op.drop_table('audit_logs')
