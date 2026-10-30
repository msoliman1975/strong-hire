"""UX with Strova core (U01)

users.plan_style and users.plan_email_muted (PS-2, PS-6); resumes.is_main with at most one
main per user among non-deleted resumes (RM-2); the user-owned target_interviews (RH-1) and
suggestions (SG-1) tables.

Backfill: each user's newest non-deleted resume becomes main. One target interview per
distinct (job target, resume, type) found in existing sessions, with the newest session's
custom spec; it is archived when its job or resume is deleted or archived.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-30 16:31:15.620812
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0023'
down_revision: str | None = '0022'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('target_interviews',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('job_target_id', sa.Uuid(), nullable=False),
    sa.Column('resume_id', sa.Uuid(), nullable=False),
    sa.Column('interview_type', sa.Enum('behavioral', 'hiring_manager', 'technical_qa', 'case', 'custom', 'recruiter_screen', name='interview_type', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('custom_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='CU-1: schemas.CustomSessionSpec. NULL for the standard types'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True, comment='TG-3: removed by the user. NULL: kept'),
    sa.ForeignKeyConstraint(['job_target_id'], ['job_targets.id'], name=op.f('fk_target_interviews_job_target_id_job_targets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_target_interviews_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], name=op.f('fk_target_interviews_resume_id_resumes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_target_interviews_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_target_interviews'))
    )
    op.create_index(op.f('ix_target_interviews_job_target_id'), 'target_interviews', ['job_target_id'], unique=False)
    op.create_index(op.f('ix_target_interviews_org_id'), 'target_interviews', ['org_id'], unique=False)
    op.create_index(op.f('ix_target_interviews_resume_id'), 'target_interviews', ['resume_id'], unique=False)
    op.create_index(op.f('ix_target_interviews_user_id'), 'target_interviews', ['user_id'], unique=False)
    op.create_index('uq_target_interviews_role_resume_type', 'target_interviews', ['job_target_id', 'resume_id', 'interview_type'], unique=True, postgresql_where=sa.text('archived_at IS NULL'), sqlite_where=sa.text('archived_at IS NULL'))
    op.execute(
        """
        INSERT INTO target_interviews
            (id, org_id, user_id, job_target_id, resume_id, interview_type, custom_json,
             created_at, archived_at)
        SELECT DISTINCT ON (s.job_target_id, s.resume_id, s.type)
            gen_random_uuid(), j.org_id, j.user_id, s.job_target_id, s.resume_id, s.type,
            s.custom_json, s.created_at, COALESCE(j.deleted_at, j.archived_at, r.deleted_at)
        FROM sessions s
        JOIN job_targets j ON j.id = s.job_target_id
        JOIN resumes r ON r.id = s.resume_id
        ORDER BY s.job_target_id, s.resume_id, s.type, s.created_at DESC, s.id DESC
        """
    )
    op.create_table('suggestions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Enum('tune_story', 'new_story', 'missing_skill', 'tailor_role', 'improve_resume_line', 'story_idea', 'review', name='suggestion_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('open', 'accepted', 'dismissed', name='suggestion_status', native_enum=False, create_constraint=True, length=32), server_default='open', nullable=False),
    sa.Column('source_session_id', sa.Uuid(), nullable=True, comment="The debrief's session"),
    sa.Column('source_question_ref', sa.String(length=200), nullable=True, comment='QuestionScore.question_ref of the answer'),
    sa.Column('source_resume_id', sa.Uuid(), nullable=True, comment='The resume it came from'),
    sa.Column('job_target_id', sa.Uuid(), nullable=True, comment='The role it is for'),
    sa.Column('story_id', sa.Uuid(), nullable=True, comment='The story it changes'),
    sa.Column('resume_id', sa.Uuid(), nullable=True, comment='The resume it changes'),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='schemas.SuggestionPayload'),
    sa.Column('reason', sa.Text(), nullable=False, comment='Why Strova suggests it'),
    sa.Column('prompt_ref', sa.String(length=200), nullable=True, comment='The prompt that wrote it. NULL for rule-based suggestions'),
    sa.Column('undo', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='SG-2: what accepting changed, to restore it. NULL until applied'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True, comment='When it was accepted or dismissed'),
    sa.ForeignKeyConstraint(['job_target_id'], ['job_targets.id'], name=op.f('fk_suggestions_job_target_id_job_targets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_suggestions_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], name=op.f('fk_suggestions_resume_id_resumes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_resume_id'], ['resumes.id'], name=op.f('fk_suggestions_source_resume_id_resumes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_session_id'], ['sessions.id'], name=op.f('fk_suggestions_source_session_id_sessions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['story_id'], ['stories.id'], name=op.f('fk_suggestions_story_id_stories'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_suggestions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_suggestions'))
    )
    op.create_index(op.f('ix_suggestions_org_id'), 'suggestions', ['org_id'], unique=False)
    op.create_index(op.f('ix_suggestions_story_id'), 'suggestions', ['story_id'], unique=False)
    op.create_index('ix_suggestions_user_status', 'suggestions', ['user_id', 'status'], unique=False)
    op.add_column('resumes', sa.Column('is_main', sa.Boolean(), server_default='false', nullable=False, comment="RM-2: the user's main resume, preselected for new roles. One per user"))
    op.execute(
        """
        UPDATE resumes SET is_main = true
        WHERE id IN (
            SELECT DISTINCT ON (user_id) id FROM resumes
            WHERE deleted_at IS NULL
            ORDER BY user_id, uploaded_at DESC, id DESC
        )
        """
    )
    op.create_index('uq_resumes_main_per_user', 'resumes', ['user_id'], unique=True, postgresql_where=sa.text('is_main AND deleted_at IS NULL'), sqlite_where=sa.text('is_main AND deleted_at IS NULL'))
    op.add_column('users', sa.Column('plan_style', sa.Enum('weekly', 'checklist', name='plan_style', native_enum=False, create_constraint=True, length=32), nullable=True, comment='PS-2: weekly or checklist. NULL until chosen'))
    op.add_column('users', sa.Column('plan_email_muted', sa.Boolean(), server_default='false', nullable=False, comment='PS-6: true mutes the weekly plan reminder emails'))


def downgrade() -> None:
    op.drop_column('users', 'plan_email_muted')
    op.drop_column('users', 'plan_style')
    op.drop_index('uq_resumes_main_per_user', table_name='resumes', postgresql_where=sa.text('is_main AND deleted_at IS NULL'), sqlite_where=sa.text('is_main AND deleted_at IS NULL'))
    op.drop_column('resumes', 'is_main')
    op.drop_index('ix_suggestions_user_status', table_name='suggestions')
    op.drop_index(op.f('ix_suggestions_story_id'), table_name='suggestions')
    op.drop_index(op.f('ix_suggestions_org_id'), table_name='suggestions')
    op.drop_table('suggestions')
    op.drop_index('uq_target_interviews_role_resume_type', table_name='target_interviews', postgresql_where=sa.text('archived_at IS NULL'), sqlite_where=sa.text('archived_at IS NULL'))
    op.drop_index(op.f('ix_target_interviews_user_id'), table_name='target_interviews')
    op.drop_index(op.f('ix_target_interviews_resume_id'), table_name='target_interviews')
    op.drop_index(op.f('ix_target_interviews_org_id'), table_name='target_interviews')
    op.drop_index(op.f('ix_target_interviews_job_target_id'), table_name='target_interviews')
    op.drop_table('target_interviews')
