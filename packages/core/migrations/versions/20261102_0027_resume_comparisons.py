"""Resume comparisons (RC-1 to RC-8)

A resume comparison ranks the user's resumes against one target role. It is saved on the role
(resume_comparisons) and points at the gap analysis each resume is ranked by. Gap analyses get a
purpose: a comparison row is never the role's latest analysis (RC-7), and a role row copied from
a comparison row (source_gap_id) made no model call (RC-6). Existing rows are role rows.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0027'
down_revision: str | None = '0026'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('resume_comparisons',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('job_target_id', sa.Uuid(), nullable=False),
    sa.Column('entries_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='schemas.ResumeComparisonEntry list, one per compared resume'),
    sa.Column('new_runs', sa.Integer(), server_default='0', nullable=False, comment='RC-7: gap analyses this comparison started. A comparison with any counts as one run against the rate limit; 0 means every pair was reused'),
    sa.Column('chosen_resume_id', sa.Uuid(), nullable=True, comment='RC-6: the resume the user picked with Use this one. NULL: not picked yet'),
    sa.Column('dismissed_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='RC-4: keys of the gap hints the user dismissed'),
    sa.Column('applied_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='RC-4: keys of the gap hints whose line the user added to the resume'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chosen_resume_id'], ['resumes.id'], name=op.f('fk_resume_comparisons_chosen_resume_id_resumes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['job_target_id'], ['job_targets.id'], name=op.f('fk_resume_comparisons_job_target_id_job_targets')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_resume_comparisons_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_resume_comparisons_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resume_comparisons'))
    )
    op.create_index(op.f('ix_resume_comparisons_job_target_id'), 'resume_comparisons', ['job_target_id'], unique=False)
    op.create_index(op.f('ix_resume_comparisons_org_id'), 'resume_comparisons', ['org_id'], unique=False)
    op.create_index(op.f('ix_resume_comparisons_user_id'), 'resume_comparisons', ['user_id'], unique=False)
    op.add_column('gap_analyses', sa.Column('purpose', sa.Enum('role', 'comparison', name='gap_purpose', native_enum=False, create_constraint=True, length=32), server_default='role', nullable=False, comment="RC-7: role is the role's own analysis; comparison was made by a resume comparison and is never the role's latest analysis"))
    op.add_column('gap_analyses', sa.Column('source_gap_id', sa.Uuid(), nullable=True, comment='RC-6: the comparison row this role row was copied from. A copy made no model call and does not count against the rate limit. NULL: computed by the worker'))
    op.create_foreign_key(op.f('fk_gap_analyses_source_gap_id_gap_analyses'), 'gap_analyses', 'gap_analyses', ['source_gap_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint(op.f('fk_gap_analyses_source_gap_id_gap_analyses'), 'gap_analyses', type_='foreignkey')
    op.drop_column('gap_analyses', 'source_gap_id')
    op.drop_column('gap_analyses', 'purpose')
    op.drop_index(op.f('ix_resume_comparisons_user_id'), table_name='resume_comparisons')
    op.drop_index(op.f('ix_resume_comparisons_org_id'), table_name='resume_comparisons')
    op.drop_index(op.f('ix_resume_comparisons_job_target_id'), table_name='resume_comparisons')
    op.drop_table('resume_comparisons')
