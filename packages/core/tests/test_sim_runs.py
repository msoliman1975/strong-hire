"""SM-4: the sim_runs table and its status lifecycle (docs/admin-spec.md, Simulations)."""

from __future__ import annotations

from strong_core.db.models import USER_OWNED_TABLES, Base, SimRun
from strong_core.schemas.enums import SimRunStatus


def test_sim_runs_is_user_owned_by_the_sim_org() -> None:
    """SM-2: runs belong to the sim org, so they never mix with real users' data."""
    assert "sim_runs" in USER_OWNED_TABLES
    org_id = Base.metadata.tables["sim_runs"].c.org_id
    assert not org_id.nullable
    assert {fk.column.table.name for fk in org_id.foreign_keys} == {"orgs"}


def test_sim_run_status_finished() -> None:
    """SM-4: done, failed and cancelled are final; the rest are still moving."""
    final = {s for s in SimRunStatus if s.finished}
    assert final == {SimRunStatus.DONE, SimRunStatus.FAILED, SimRunStatus.CANCELLED}
    assert SimRun.__table__.c.status.server_default is not None


def test_sim_run_defaults() -> None:
    """SM-13: a new run is not kept and has no files deleted; SM-4: it starts queued."""
    cols = SimRun.__table__.c
    assert cols.keep.server_default.arg == "false"
    assert cols.deleted_at.nullable and cols.session_id.nullable and cols.run_dir.nullable
    assert cols.run_dir.unique
    assert cols.status.server_default.arg == "queued"
