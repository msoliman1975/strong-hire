"""profile, job archive and session resume

AC-3: adds the profile fields that the app asks for at the first sign-in (users.full_name,
current_title, years_experience, target_level, country, time_zone, linkedin_url) and
users.profile_completed_at. Existing users stay NULL, so the app asks them once.

LB-2: adds job_targets.archived_at. An archived job description is kept with its reports but
left out of the pickers.

PR-3: adds sessions.resume_id, the CV used for the session. Existing sessions get the CV of the
job's latest ready gap analysis made before the session, else of any gap analysis made before it.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-09 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0011'
down_revision: str | None = '0010'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'job_targets',
        sa.Column(
            'archived_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='LB-2: hidden from pickers but kept, for a job that has reports. NULL: active',
        ),
    )
    op.add_column(
        'sessions',
        sa.Column(
            'resume_id',
            sa.Uuid(),
            nullable=True,
            comment="PR-3: the CV of the job's latest gap analysis when the session was created",
        ),
    )
    op.create_index(op.f('ix_sessions_resume_id'), 'sessions', ['resume_id'], unique=False)
    op.create_foreign_key(
        op.f('fk_sessions_resume_id_resumes'), 'sessions', 'resumes', ['resume_id'], ['id']
    )
    op.execute(
        """
        UPDATE sessions AS s
        SET resume_id = (
            SELECT g.resume_id
            FROM gap_analyses AS g
            WHERE g.job_target_id = s.job_target_id AND g.created_at <= s.created_at
            ORDER BY (g.status = 'ready') DESC, g.created_at DESC
            LIMIT 1
        )
        WHERE s.resume_id IS NULL
        """
    )
    op.add_column('users', sa.Column('full_name', sa.String(length=120), nullable=True, comment='AC-3'))
    op.add_column(
        'users',
        sa.Column('current_title', sa.String(length=120), nullable=True, comment='AC-3: optional'),
    )
    op.add_column(
        'users', sa.Column('years_experience', sa.Integer(), nullable=True, comment='AC-3: 0 to 50')
    )
    op.add_column(
        'users',
        sa.Column(
            'target_level',
            sa.Enum(
                'new_grad',
                'mid',
                'senior',
                'staff_principal',
                name='target_level',
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
            comment='AC-3: default level for new sessions',
        ),
    )
    op.add_column(
        'users', sa.Column('country', sa.String(length=100), nullable=True, comment='AC-3: optional')
    )
    op.add_column(
        'users',
        sa.Column('time_zone', sa.String(length=64), nullable=True, comment='AC-3: IANA name, optional'),
    )
    op.add_column(
        'users',
        sa.Column('linkedin_url', sa.String(length=300), nullable=True, comment='AC-3: optional'),
    )
    op.add_column(
        'users',
        sa.Column(
            'profile_completed_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='AC-3: NULL until the user saves the profile once',
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'profile_completed_at')
    op.drop_column('users', 'linkedin_url')
    op.drop_column('users', 'time_zone')
    op.drop_column('users', 'country')
    op.drop_column('users', 'target_level')
    op.drop_column('users', 'years_experience')
    op.drop_column('users', 'current_title')
    op.drop_column('users', 'full_name')
    op.drop_constraint(op.f('fk_sessions_resume_id_resumes'), 'sessions', type_='foreignkey')
    op.drop_index(op.f('ix_sessions_resume_id'), table_name='sessions')
    op.drop_column('sessions', 'resume_id')
    op.drop_column('job_targets', 'archived_at')
