"""sim runs: admin-started AI candidate interviews (docs/admin-spec.md, Simulations, S0)

User-owned table (org_id, the sim org): sim_runs (SM-2..SM-5, SM-13, SM-14).
The two new runtime settings (sim_paused, sim_max_live_sessions) need no schema change.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-18 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0014'
down_revision: str | None = '0013'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('sim_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('scenario_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='strong_sim Scenario, as the admin chose it (SM-1)'),
    sa.Column('status', sa.Enum('queued', 'waiting', 'starting', 'interviewing', 'judging', 'done', 'failed', 'cancelled', name='sim_run_status', native_enum=False, create_constraint=True, length=32), server_default='queued', nullable=False),
    sa.Column('status_reason', sa.Text(), nullable=True, comment='Why it waits, failed or was cancelled'),
    sa.Column('run_dir', sa.String(length=200), nullable=True, comment='Folder name under SIM_RESULTS_DIR; set when it starts'),
    sa.Column('session_id', sa.Uuid(), nullable=True),
    sa.Column('created_by', sa.String(length=320), nullable=False, comment='Admin email'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('progress_s', sa.Integer(), server_default='0', nullable=False, comment='SM-4: interview time so far'),
    sa.Column('cost_sim_usd', sa.Numeric(precision=10, scale=4), server_default='0', nullable=False, comment='Candidate and judge cost; the app side is in usage_events of the session'),
    sa.Column('cancel_requested_at', sa.DateTime(timezone=True), nullable=True, comment='SM-5'),
    sa.Column('keep', sa.Boolean(), server_default='false', nullable=False, comment='SM-13: retention skips it'),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, comment='SM-13, SM-14: files deleted'),
    sa.Column('deleted_by', sa.String(length=320), nullable=True, comment="Admin email, or 'retention'"),
    sa.Column('delete_reason', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_sim_runs_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_sim_runs_session_id_sessions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sim_runs')),
    sa.UniqueConstraint('run_dir', name=op.f('uq_sim_runs_run_dir'))
    )
    op.create_index(op.f('ix_sim_runs_org_id'), 'sim_runs', ['org_id'], unique=False)
    op.create_index(op.f('ix_sim_runs_session_id'), 'sim_runs', ['session_id'], unique=False)
    op.create_index('ix_sim_runs_status_created_at', 'sim_runs', ['status', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_sim_runs_status_created_at', table_name='sim_runs')
    op.drop_index(op.f('ix_sim_runs_session_id'), table_name='sim_runs')
    op.drop_index(op.f('ix_sim_runs_org_id'), table_name='sim_runs')
    op.drop_table('sim_runs')
