from __future__ import annotations

from strong_core.db.models import PLATFORM_TABLES, USER_OWNED_TABLES, Base
from strong_core.gateway.types import Role

SPEC_TABLES = {
    "orgs",
    "users",
    "subscriptions",
    "resumes",
    "job_targets",
    "companies",
    "company_profiles",
    "gap_analyses",
    "sessions",
    "turns",
    "scorecards",
    "progress_snapshots",
    "usage_events",
    "audit_logs",
    "company_requests",  # spec: Companies outside the launch list, request this company
    "stripe_events",  # BL-1: webhook events already handled (idempotency)
    "exit_surveys",  # P9: cancellation exit survey
    "interviewer_traces",  # R2: admin review of interviewer calls, deleted after 90 days
    # Admin app (docs/admin-spec.md, "Data model changes")
    "admin_users",  # AA-1
    "admin_sessions",  # AA-3
    "minute_grants",  # AU-3..AU-5
    "voice_turn_timings",  # OB-3
    "error_groups",  # OB-4
    "error_events",  # OB-4
    "ops_samples",  # OB-5
    "alert_rules",  # AL-1
    "alert_events",  # AL-4
    "runtime_settings",  # OC
    "company_request_triage",  # AT-5
    "sim_runs",  # SM-2..SM-5, SM-13, SM-14
    # Custom interview (docs/custom-interview-spec.md)
    "saved_questions",  # CU-8
    # Launch (L04 marketing site)
    "waitlist_entries",  # L04 step 1: waitlist with double opt-in
    "session_feedback",  # L05: post-session realism rating
    "email_logs",  # L01, L06: lifecycle emails sent
}


def test_every_spec_entity_has_a_table() -> None:
    assert set(Base.metadata.tables) == SPEC_TABLES


def test_user_owned_tables_have_org_id() -> None:
    for name in USER_OWNED_TABLES:
        column = Base.metadata.tables[name].columns.get("org_id")
        assert column is not None, name
        assert not column.nullable, name
        assert column.foreign_keys, name


def test_every_table_is_user_owned_or_platform_exactly_once() -> None:
    """Admin spec 'Data model changes': each table is classified on purpose."""
    owned, platform = set(USER_OWNED_TABLES), set(PLATFORM_TABLES)
    assert len(owned) == len(USER_OWNED_TABLES) and len(platform) == len(PLATFORM_TABLES)
    assert not owned & platform
    assert owned | platform == set(Base.metadata.tables)


def test_platform_tables_have_no_org_fk() -> None:
    """Platform tables are not owned by an org. audit_logs keeps a plain org_id (no FK)."""
    for name in PLATFORM_TABLES:
        column = Base.metadata.tables[name].columns.get("org_id")
        assert column is None or not column.foreign_keys, name


def test_admin_user_and_session_columns() -> None:
    """AA-1, AA-3, AU-7, AU-8."""
    users = Base.metadata.tables["users"].columns
    assert users["suspended_at"].nullable and users["suspended_reason"].nullable
    epoch = users["session_epoch"]
    assert not epoch.nullable and epoch.server_default is not None
    assert str(epoch.server_default.arg) == "0"
    admins = Base.metadata.tables["admin_users"].columns
    assert admins["email"].unique
    sessions = Base.metadata.tables["admin_sessions"].columns
    for name in ("created_at", "last_seen_at", "expires_at"):
        assert not sessions[name].nullable, name
    assert sessions["revoked_at"].nullable


def test_minute_grants_ledger() -> None:
    """AU-3, AU-4, AU-5: one ledger for minutes, free interviews and comp plans."""
    table = Base.metadata.tables["minute_grants"]
    kind = table.columns["kind"].type
    assert set(getattr(kind, "enums", [])) == {"minutes", "free_interviews", "comp_plan"}
    assert table.columns["expires_at"].nullable and table.columns["revoked_at"].nullable
    assert not table.columns["reason"].nullable


def test_usage_events_role_and_cost_known() -> None:
    """OB-2: role holds a gateway Role value; old rows default to cost_known true."""
    columns = Base.metadata.tables["usage_events"].columns
    assert columns["role"].nullable
    length = getattr(columns["role"].type, "length", 0)
    assert all(len(r.value) <= length for r in Role)
    assert not columns["cost_known"].nullable
    assert str(columns["cost_known"].server_default.arg) == "true"  # type: ignore[union-attr]


def test_ops_samples_index_and_retention_constants() -> None:
    """OB-3, OB-4, OB-5: (metric, ts) index and the retention windows."""
    from strong_core.db import models

    indexes = {tuple(c.name for c in ix.columns) for ix in models.OpsSample.__table__.indexes}
    assert ("metric", "ts") in indexes
    assert models.OPS_SAMPLE_RETENTION_DAYS == 30
    assert models.ERROR_EVENT_RETENTION_DAYS == 30
    assert models.VOICE_TIMING_RETENTION_DAYS == 90


def test_training_consent_defaults_off() -> None:
    """AC-2."""
    column = Base.metadata.tables["users"].columns["training_consent"]
    assert column.server_default is not None
    assert str(column.server_default.arg) == "false"


def test_profile_fields_are_optional_until_completed() -> None:
    """AC-3: existing users have no profile yet, so the app asks them once."""
    users = Base.metadata.tables["users"].columns
    for name in (
        "full_name",
        "current_title",
        "years_experience",
        "target_level",
        "country",
        "time_zone",
        "linkedin_url",
        "profile_completed_at",
    ):
        assert users[name].nullable, name


def test_job_archive_and_session_resume_columns() -> None:
    """LB-2 (archived_at) and PR-3 (the CV used for a session)."""
    assert Base.metadata.tables["job_targets"].columns["archived_at"].nullable
    resume_id = Base.metadata.tables["sessions"].columns["resume_id"]
    assert resume_id.nullable
    assert {fk.column.table.name for fk in resume_id.foreign_keys} == {"resumes"}


def test_async_url_uses_asyncpg() -> None:
    from strong_core.db.engine import async_database_url

    url = async_database_url("postgresql+psycopg://u:p@db:5432/strong")
    assert url == "postgresql+asyncpg://u:p@db:5432/strong"
