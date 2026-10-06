"""gap analysis status and input hash

A gap analysis row now exists while the analysis runs (status running, ready or failed), so the
API can show progress and failures (GA-1 to GA-4). Score, breakdown, plan and model version are
NULL until the row is ready. input_hash and profile_version record what the analysis used, so
the API can tell when the job, resume or profile changed.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06 02:04:45.649394
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('gap_analyses', sa.Column('status', sa.Enum('running', 'ready', 'failed', name='gap_status', native_enum=False, create_constraint=True, length=32), server_default='ready', nullable=False))
    op.add_column('gap_analyses', sa.Column('error', sa.Text(), nullable=True, comment='Plain reason when status is failed'))
    op.add_column('gap_analyses', sa.Column('input_hash', sa.String(length=64), nullable=True, comment='Hash of the posting, resume and profile version it was built from'))
    op.add_column('gap_analyses', sa.Column('profile_version', sa.Integer(), nullable=True, comment='NULL in generic mode'))
    op.add_column('gap_analyses', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('gap_analyses', 'match_score',
               existing_type=sa.INTEGER(),
               nullable=True,
               comment='NULL until ready')
    op.alter_column('gap_analyses', 'breakdown_json',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               nullable=True,
               existing_comment='schemas.GapAnalysis')
    op.alter_column('gap_analyses', 'session_plan_json',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               nullable=True,
               existing_comment='schemas.PlannedSession list')
    op.alter_column('gap_analyses', 'model_version',
               existing_type=sa.VARCHAR(length=200),
               nullable=True,
               existing_comment='Gateway alias + prompt ref')


def downgrade() -> None:
    # Rows that never finished have NULL scores and cannot fit the old NOT NULL columns.
    op.execute(
        "DELETE FROM gap_analyses WHERE match_score IS NULL OR breakdown_json IS NULL "
        "OR session_plan_json IS NULL OR model_version IS NULL"
    )
    op.alter_column('gap_analyses', 'model_version',
               existing_type=sa.VARCHAR(length=200),
               nullable=False,
               existing_comment='Gateway alias + prompt ref')
    op.alter_column('gap_analyses', 'session_plan_json',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               nullable=False,
               existing_comment='schemas.PlannedSession list')
    op.alter_column('gap_analyses', 'breakdown_json',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               nullable=False,
               existing_comment='schemas.GapAnalysis')
    op.alter_column('gap_analyses', 'match_score',
               existing_type=sa.INTEGER(),
               nullable=False,
               comment=None,
               existing_comment='NULL until ready')
    op.drop_column('gap_analyses', 'updated_at')
    op.drop_column('gap_analyses', 'profile_version')
    op.drop_column('gap_analyses', 'input_hash')
    op.drop_column('gap_analyses', 'error')
    op.drop_column('gap_analyses', 'status')
