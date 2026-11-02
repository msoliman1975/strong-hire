"""Role story fits (ST-5)

The story fit of each target role, stored in Postgres instead of only in Redis: the worker
computes it when the role is created and when a story changes, and the role page reads it. One
row per role; input_hash lets unchanged inputs skip the model, also across roles.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0026'
down_revision: str | None = '0025'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('role_story_fits',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('job_target_id', sa.Uuid(), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('fit_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='schemas.StoryFit'),
    sa.Column('model_profile', sa.String(length=50), nullable=False),
    sa.Column('model_id', sa.String(length=200), nullable=True, comment='Gateway alias; NULL when no model call was needed'),
    sa.Column('prompt_version', sa.String(length=200), nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_target_id'], ['job_targets.id'], name=op.f('fk_role_story_fits_job_target_id_job_targets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_role_story_fits_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_role_story_fits_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_role_story_fits')),
    sa.UniqueConstraint('job_target_id', name=op.f('uq_role_story_fits_job_target_id'))
    )
    op.create_index(op.f('ix_role_story_fits_input_hash'), 'role_story_fits', ['input_hash'], unique=False)
    op.create_index(op.f('ix_role_story_fits_org_id'), 'role_story_fits', ['org_id'], unique=False)
    op.create_index(op.f('ix_role_story_fits_user_id'), 'role_story_fits', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_role_story_fits_user_id'), table_name='role_story_fits')
    op.drop_index(op.f('ix_role_story_fits_org_id'), table_name='role_story_fits')
    op.drop_index(op.f('ix_role_story_fits_input_hash'), table_name='role_story_fits')
    op.drop_table('role_story_fits')
