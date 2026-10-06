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


def test_async_url_uses_asyncpg() -> None:
    from strong_core.db.engine import async_database_url

    url = async_database_url("postgresql+psycopg://u:p@db:5432/strong")
    assert url == "postgresql+asyncpg://u:p@db:5432/strong"
