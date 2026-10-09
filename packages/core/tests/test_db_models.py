from __future__ import annotations

from strong_core.db.models import USER_OWNED_TABLES, Base

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
    "company_requests",  # spec: Companies outside the 20, request this company
    "stripe_events",  # BL-1: webhook events already handled (idempotency)
    "exit_surveys",  # P9: cancellation exit survey
    "interviewer_traces",  # R2: admin review of interviewer calls, deleted after 90 days
}


def test_every_spec_entity_has_a_table() -> None:
    assert set(Base.metadata.tables) == SPEC_TABLES


def test_user_owned_tables_have_org_id() -> None:
    for name in USER_OWNED_TABLES:
        column = Base.metadata.tables[name].columns.get("org_id")
        assert column is not None, name
        assert not column.nullable, name
        assert column.foreign_keys, name


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
