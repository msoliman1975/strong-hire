"""company values and company requests

Adds scorecards.value_scores_json (ValueScore list) and the company_requests table (IN-5).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05 22:17:49.683575
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('company_requests',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('job_target_id', sa.Uuid(), nullable=True),
    sa.Column('company_name', sa.String(length=200), nullable=False, comment='As the user or posting wrote it'),
    sa.Column('normalized_name', sa.String(length=200), nullable=False),
    sa.Column('matched_company_id', sa.Uuid(), nullable=True, comment='NULL means not curated'),
    sa.Column('source_host', sa.String(length=200), nullable=True, comment='Host of the posting URL, without www.'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['job_target_id'], ['job_targets.id'], name=op.f('fk_company_requests_job_target_id_job_targets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['matched_company_id'], ['companies.id'], name=op.f('fk_company_requests_matched_company_id_companies'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_company_requests_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_company_requests_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_requests'))
    )
    op.create_index(op.f('ix_company_requests_normalized_name'), 'company_requests', ['normalized_name'], unique=False)
    op.create_index(op.f('ix_company_requests_org_id'), 'company_requests', ['org_id'], unique=False)
    op.create_index(op.f('ix_company_requests_user_id'), 'company_requests', ['user_id'], unique=False)
    op.add_column('scorecards', sa.Column('value_scores_json', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False, comment='schemas.ValueScore list; empty in generic mode'))


def downgrade() -> None:
    op.drop_column('scorecards', 'value_scores_json')
    op.drop_index(op.f('ix_company_requests_user_id'), table_name='company_requests')
    op.drop_index(op.f('ix_company_requests_org_id'), table_name='company_requests')
    op.drop_index(op.f('ix_company_requests_normalized_name'), table_name='company_requests')
    op.drop_table('company_requests')
