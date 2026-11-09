"""Production LLM trace deletion and retention (LT-24 to LT-27): job, overdue alert, prune."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from arq import Retry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import strong_worker.account.jobs as account_jobs
from strong_core.config import get_settings
from strong_core.db.models import AlertRule, AuditLog
from strong_core.ops.alerts import DEFAULT_RULES
from strong_worker import retention
from strong_worker.account.jobs import (
    TRACES_DELETED,
    TRACES_REQUESTED,
    AccountContext,
    delete_traces,
)
from strong_worker.alerts.readings import read

Maker = async_sessionmaker[AsyncSession]


class NoStore:
    async def delete(self, ref: str) -> None:
        return None


class NoExports:
    async def put(self, key: str, data: bytes, ttl_s: int) -> None:
        return None


def _ctx(maker: Maker, job_try: int = 1) -> dict[str, Any]:
    account = AccountContext(sessionmaker=maker, store=NoStore(), exports=NoExports())  # type: ignore[arg-type]
    return {account_jobs.CTX_KEY: account, "job_try": job_try}


async def _audits(maker: Maker, action: str) -> list[AuditLog]:
    async with maker() as db:
        return list((await db.execute(select(AuditLog).where(AuditLog.action == action))).scalars())


# --- LT-24 to LT-26: the job ---------------------------------------------------------------------


async def test_lt26_job_deletes_and_records_the_count(
    sessionmaker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-26: success writes tracing.traces_deleted with scope, request id and count."""
    calls: list[tuple[uuid.UUID, str]] = []

    def fake(org_id: uuid.UUID, scope: str) -> int:
        calls.append((org_id, scope))
        return 7

    monkeypatch.setattr(account_jobs, "delete_org_traces", fake)
    org = uuid.uuid4()
    out = await delete_traces(_ctx(sessionmaker), str(org), "content", "req-1")
    assert out == {"outcome": "deleted", "scope": "content", "traces": 7}
    assert calls == [(org, "content")]
    (row,) = await _audits(sessionmaker, TRACES_DELETED)
    assert row.org_id == org and row.details_json == {
        "scope": "content",
        "request_id": "req-1",
        "traces": 7,
    }


async def test_lt26_mlflow_errors_are_retried_then_raised(
    sessionmaker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-26: never reports success while MLflow fails; retries, then raises on the last try."""

    def down(org_id: uuid.UUID, scope: str) -> int:
        raise ConnectionError("mlflow down")

    monkeypatch.setattr(account_jobs, "delete_org_traces", down)
    with pytest.raises(Retry):
        await delete_traces(_ctx(sessionmaker, job_try=1), str(uuid.uuid4()), "all", "r")
    last = account_jobs.DELETE_MAX_TRIES
    with pytest.raises(ConnectionError):
        await delete_traces(_ctx(sessionmaker, job_try=last), str(uuid.uuid4()), "all", "r")
    assert await _audits(sessionmaker, TRACES_DELETED) == []


async def test_lt26_unknown_scope_is_refused(sessionmaker: Maker) -> None:
    with pytest.raises(ValueError):
        await delete_traces(_ctx(sessionmaker), str(uuid.uuid4()), "everything", "r")


# --- LT-26: the overdue alert ---------------------------------------------------------------------


async def _audit(maker: Maker, action: str, request_id: str, hours_ago: float) -> None:
    async with maker() as db:
        db.add(
            AuditLog(
                org_id=uuid.uuid4(),
                actor="system",
                action=action,
                entity="org:x",
                details_json={"scope": "all", "request_id": request_id},
                at=datetime.now(UTC) - timedelta(hours=hours_ago),
            )
        )
        await db.commit()


async def _overdue(maker: Maker) -> float | None:
    rule = AlertRule(name="t", metric="tracing.deletes_overdue", window_s=900, threshold=0)
    async with maker() as db:
        return (await read(db, rule, datetime.now(UTC))).value


async def test_lt26_overdue_counts_old_requests_without_success(sessionmaker: Maker) -> None:
    """LT-26: a request over 12 h old with no success counts; done or recent ones do not."""
    await _audit(sessionmaker, TRACES_REQUESTED, "late", 13)
    await _audit(sessionmaker, TRACES_REQUESTED, "done", 13)
    await _audit(sessionmaker, TRACES_DELETED, "done", 12.5)
    await _audit(sessionmaker, TRACES_REQUESTED, "fresh", 2)
    await _audit(sessionmaker, TRACES_REQUESTED, "ancient", 24 * 40)  # past the lookback
    assert await _overdue(sessionmaker) == 1.0


def test_lt26_overdue_alert_is_a_default_critical_rule() -> None:
    """LT-26: seeded for every install, critical."""
    (rule,) = [r for r in DEFAULT_RULES if r.metric == "tracing.deletes_overdue"]
    assert rule.name == "Trace deletion overdue" and rule.threshold == 0
    assert rule.severity.value == "critical"


# --- LT-27: retention ---------------------------------------------------------------------------


async def test_lt27_retention_prunes_30_and_90_days_only_with_production_tracing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """LT-27: content after 30 days, the rest after 90; nothing while production is off."""
    import strong_core.tracing.prod as prod

    calls: list[tuple[int, int]] = []

    def fake(content_days: int, metadata_days: int) -> dict[str, int]:
        calls.append((content_days, metadata_days))
        return {"content": 2, "metadata": 5}

    monkeypatch.setattr(prod, "prune_prod", fake)
    monkeypatch.delenv("LLM_TRACING_PROD", raising=False)
    get_settings.cache_clear()
    assert await retention.prune_production_traces() == {}
    monkeypatch.setenv("LLM_TRACING_PROD", "on")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    get_settings.cache_clear()
    try:
        out = await retention.prune_production_traces()
    finally:
        get_settings.cache_clear()
    assert calls == [(30, 90)]
    assert out == {"prod_traces_content": 2, "prod_traces_metadata": 5}


async def test_lt27_a_failed_prune_never_fails_the_retention_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LT-27: MLflow trouble is logged; the database retention still counts as done."""
    import strong_core.tracing.prod as prod

    def down(content_days: int, metadata_days: int) -> dict[str, int]:
        raise ConnectionError("mlflow down")

    monkeypatch.setattr(prod, "prune_prod", down)
    monkeypatch.setenv("LLM_TRACING_PROD", "on")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    get_settings.cache_clear()
    try:
        assert await retention.prune_production_traces() == {"prod_traces_failed": 1}
    finally:
        get_settings.cache_clear()
