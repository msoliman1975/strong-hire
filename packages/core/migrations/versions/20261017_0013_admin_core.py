"""admin core: data model for the admin app (docs/admin-spec.md, A0)

Platform tables (no org_id): admin_users and admin_sessions (AA-1, AA-3), error_groups and
error_events (OB-4), ops_samples (OB-5), alert_rules and alert_events (AL-1, AL-4),
runtime_settings (OC) and company_request_triage (AT-5).
User-owned tables (org_id): minute_grants (AU-3..AU-5) and voice_turn_timings (OB-3).
Columns: users.suspended_at, suspended_reason, session_epoch (AU-7, AU-8) and
usage_events.role, cost_known (OB-2). Existing usage rows keep role NULL and cost_known true.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-17 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0013'
down_revision: str | None = '0012'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('admin_users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False, comment='Stored lower case'),
    sa.Column('added_by', sa.String(length=320), nullable=True, comment="Admin email, 'ADMIN_EMAILS' for the seed, or 'strongctl'"),
    sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('disabled_at', sa.DateTime(timezone=True), nullable=True, comment='Removed admin. NULL: active'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_users')),
    sa.UniqueConstraint('email', name=op.f('uq_admin_users_email'))
    )
    op.create_table('alert_rules',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('metric', sa.String(length=100), nullable=False, comment='An ops_samples metric or a domain metric the engine knows'),
    sa.Column('labels_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Only samples with these labels count. NULL: all'),
    sa.Column('aggregation', sa.Enum('last', 'avg', 'p95', 'rate', 'count', name='alert_aggregation', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('window_s', sa.Integer(), nullable=False, comment='Samples from the last window_s count'),
    sa.Column('comparator', sa.Enum('gt', 'gte', 'lt', 'lte', name='alert_comparator', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('threshold', sa.Double(), nullable=False),
    sa.Column('min_samples', sa.Integer(), server_default='1', nullable=False, comment='Fewer samples: the rule stays as it is'),
    sa.Column('for_s', sa.Integer(), server_default='0', nullable=False, comment='Pending this long before firing'),
    sa.Column('severity', sa.Enum('critical', 'warning', name='alert_severity', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('renotify_s', sa.Integer(), nullable=True, comment='Re-send while firing. NULL: never (AL-3)'),
    sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('muted_until', sa.DateTime(timezone=True), nullable=True, comment='No email until then; state still changes'),
    sa.Column('state', sa.Enum('ok', 'pending', 'firing', name='alert_state', native_enum=False, create_constraint=True, length=32), server_default='ok', nullable=False),
    sa.Column('state_since', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_notified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_value', sa.Double(), nullable=True, comment='At the last evaluation'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alert_rules')),
    sa.UniqueConstraint('name', name=op.f('uq_alert_rules_name'))
    )
    op.create_table('error_groups',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False, comment='Hash of exception type + top in-app frames'),
    sa.Column('service', sa.String(length=20), nullable=False, comment='api, worker or voice'),
    sa.Column('exception_type', sa.String(length=200), nullable=False),
    sa.Column('message', sa.Text(), nullable=False, comment='PII scrubbed before writing'),
    sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('count', sa.Integer(), server_default='1', nullable=False),
    sa.Column('status', sa.Enum('open', 'resolved', name='error_group_status', native_enum=False, create_constraint=True, length=32), server_default='open', nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_by', sa.String(length=320), nullable=True, comment='Admin email'),
    sa.Column('sample_stack', sa.Text(), nullable=True, comment='One scrubbed stack trace'),
    sa.Column('release', sa.String(length=100), nullable=True, comment='Latest release seen'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_error_groups')),
    sa.UniqueConstraint('fingerprint', name=op.f('uq_error_groups_fingerprint'))
    )
    op.create_index(op.f('ix_error_groups_last_seen'), 'error_groups', ['last_seen'], unique=False)
    op.create_table('ops_samples',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('metric', sa.String(length=100), nullable=False, comment='For example probe.postgres.ok'),
    sa.Column('value', sa.Double(), nullable=False),
    sa.Column('labels_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="Small string map, for example {'service': 'api'}"),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ops_samples'))
    )
    op.create_index('ix_ops_samples_metric_ts', 'ops_samples', ['metric', 'ts'], unique=False)
    op.create_table('runtime_settings',
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('value_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Validated by strong_core.runtime_settings'),
    sa.Column('updated_by', sa.String(length=320), nullable=False, comment='Admin email'),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_runtime_settings'))
    )
    op.create_table('admin_sessions',
    sa.Column('id', sa.String(length=64), nullable=False, comment='SHA-256 hex of the sh_admin cookie token'),
    sa.Column('admin_user_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False, comment='AA-3: idle timeout 2 h from here'),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, comment='AA-3: absolute timeout, created_at + 12 h'),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=500), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True, comment='Sign-out or AA-8 revoke. NULL: live'),
    sa.ForeignKeyConstraint(['admin_user_id'], ['admin_users.id'], name=op.f('fk_admin_sessions_admin_user_id_admin_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_sessions'))
    )
    op.create_index(op.f('ix_admin_sessions_admin_user_id'), 'admin_sessions', ['admin_user_id'], unique=False)
    op.create_table('alert_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('rule_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Enum('fired', 'resolved', 'test', name='alert_event_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('value', sa.Double(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('notified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('notify_error', sa.Text(), nullable=True, comment='Last send failure'),
    sa.ForeignKeyConstraint(['rule_id'], ['alert_rules.id'], name=op.f('fk_alert_events_rule_id_alert_rules'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alert_events'))
    )
    op.create_index(op.f('ix_alert_events_at'), 'alert_events', ['at'], unique=False)
    op.create_index(op.f('ix_alert_events_rule_id'), 'alert_events', ['rule_id'], unique=False)
    op.create_table('company_request_triage',
    sa.Column('normalized_name', sa.String(length=200), nullable=False, comment='company_requests.normalized_name'),
    sa.Column('state', sa.Enum('new', 'planned', 'declined', 'added', name='triage_state', native_enum=False, create_constraint=True, length=32), server_default='new', nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=True, comment='Set when state is added'),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('updated_by', sa.String(length=320), nullable=False, comment='Admin email'),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_request_triage_company_id_companies'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('normalized_name', name=op.f('pk_company_request_triage'))
    )
    op.create_table('error_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('group_id', sa.Uuid(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('service', sa.String(length=20), nullable=False),
    sa.Column('release', sa.String(length=100), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('session_id', sa.Uuid(), nullable=True, comment='Interview session, if any. No FK: errors outlive deleted sessions'),
    sa.ForeignKeyConstraint(['group_id'], ['error_groups.id'], name=op.f('fk_error_events_group_id_error_groups'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_error_events'))
    )
    op.create_index(op.f('ix_error_events_at'), 'error_events', ['at'], unique=False)
    op.create_index(op.f('ix_error_events_group_id'), 'error_events', ['group_id'], unique=False)
    op.create_table('minute_grants',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Enum('minutes', 'free_interviews', 'comp_plan', name='grant_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False, comment='minutes: minutes (negative removes); free_interviews: count; comp_plan: the minutes cap of the comp'),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True, comment='NULL: does not expire. Required for comp_plan'),
    sa.Column('reason', sa.Text(), nullable=False, comment='AA-6: the reason the admin gave'),
    sa.Column('granted_by', sa.String(length=320), nullable=False, comment='Admin email'),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_by', sa.String(length=320), nullable=True, comment='Admin email'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_minute_grants_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_minute_grants_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_minute_grants'))
    )
    op.create_index(op.f('ix_minute_grants_org_id'), 'minute_grants', ['org_id'], unique=False)
    op.create_index(op.f('ix_minute_grants_user_id'), 'minute_grants', ['user_id'], unique=False)
    op.create_table('voice_turn_timings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('turn_index', sa.Integer(), nullable=False, comment='Order of the turn in the session'),
    sa.Column('e2e_ms', sa.Integer(), nullable=True, comment='End of candidate speech to first interviewer audio'),
    sa.Column('turn_detection_ms', sa.Integer(), nullable=True),
    sa.Column('stt_ms', sa.Integer(), nullable=True),
    sa.Column('llm_ttft_ms', sa.Integer(), nullable=True, comment='LLM time to first token'),
    sa.Column('tts_ttfb_ms', sa.Integer(), nullable=True, comment='TTS time to first byte'),
    sa.Column('other_ms', sa.Integer(), nullable=True, comment='e2e minus the parts above'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_voice_turn_timings_org_id_orgs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_voice_turn_timings_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_voice_turn_timings'))
    )
    op.create_index(op.f('ix_voice_turn_timings_created_at'), 'voice_turn_timings', ['created_at'], unique=False)
    op.create_index(op.f('ix_voice_turn_timings_org_id'), 'voice_turn_timings', ['org_id'], unique=False)
    op.create_index('ix_voice_turn_timings_session_turn', 'voice_turn_timings', ['session_id', 'turn_index'], unique=False)
    op.add_column('usage_events', sa.Column('role', sa.String(length=32), nullable=True, comment='OB-2: gateway role (strong_core.gateway.Role value). NULL: written before OB-2'))
    op.add_column('usage_events', sa.Column('cost_known', sa.Boolean(), server_default='true', nullable=False, comment='OB-2, D-12: false when the model has no price in config (cost_usd is then 0)'))
    op.add_column('users', sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True, comment='AU-7: requests get 403 while set. NULL: active'))
    op.add_column('users', sa.Column('suspended_reason', sa.Text(), nullable=True, comment="AU-7: the admin's reason, shown in the admin app only"))
    op.add_column('users', sa.Column('session_epoch', sa.Integer(), server_default='0', nullable=False, comment='AU-8: carried in the session cookie; bumping it signs the user out everywhere'))


def downgrade() -> None:
    op.drop_column('users', 'session_epoch')
    op.drop_column('users', 'suspended_reason')
    op.drop_column('users', 'suspended_at')
    op.drop_column('usage_events', 'cost_known')
    op.drop_column('usage_events', 'role')
    op.drop_index('ix_voice_turn_timings_session_turn', table_name='voice_turn_timings')
    op.drop_index(op.f('ix_voice_turn_timings_org_id'), table_name='voice_turn_timings')
    op.drop_index(op.f('ix_voice_turn_timings_created_at'), table_name='voice_turn_timings')
    op.drop_table('voice_turn_timings')
    op.drop_index(op.f('ix_minute_grants_user_id'), table_name='minute_grants')
    op.drop_index(op.f('ix_minute_grants_org_id'), table_name='minute_grants')
    op.drop_table('minute_grants')
    op.drop_index(op.f('ix_error_events_group_id'), table_name='error_events')
    op.drop_index(op.f('ix_error_events_at'), table_name='error_events')
    op.drop_table('error_events')
    op.drop_table('company_request_triage')
    op.drop_index(op.f('ix_alert_events_rule_id'), table_name='alert_events')
    op.drop_index(op.f('ix_alert_events_at'), table_name='alert_events')
    op.drop_table('alert_events')
    op.drop_index(op.f('ix_admin_sessions_admin_user_id'), table_name='admin_sessions')
    op.drop_table('admin_sessions')
    op.drop_table('runtime_settings')
    op.drop_index('ix_ops_samples_metric_ts', table_name='ops_samples')
    op.drop_table('ops_samples')
    op.drop_index(op.f('ix_error_groups_last_seen'), table_name='error_groups')
    op.drop_table('error_groups')
    op.drop_table('alert_rules')
    op.drop_table('admin_users')
