"""MLflow behind admin sign-in (LT-28) and the trace-view audit (LT-29)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.admin.mlflow_auth import TRACE_VIEWED, TraceRead, trace_read
from strong_core.db.models import AuditLog

from .conftest import ADMIN_EMAIL, make_admin

AUTH = "/admin/mlflow-auth"
TOKEN = "sim-token-for-tests"


def _forwarded(method: str, uri: str) -> dict[str, str]:
    return {"X-Forwarded-Method": method, "X-Forwarded-Uri": uri}


async def _views(maker: async_sessionmaker[AsyncSession]) -> list[AuditLog]:
    async with maker() as db:
        rows = await db.execute(select(AuditLog).where(AuditLog.action == TRACE_VIEWED))
        return list(rows.scalars())


@pytest.fixture
def sim_token(app: FastAPI) -> str:
    settings = app.state.admin_auth_settings
    app.state.admin_auth_settings = settings.model_copy(
        update={"mlflow_sim_token": SecretStr(TOKEN)}
    )
    return TOKEN


# --- LT-28: who passes ---------------------------------------------------------------------------


async def test_lt28_an_admin_session_passes(admin_client: httpx.AsyncClient) -> None:
    """LT-28: a live admin session (AA-4) gets 200, so Caddy proxies to MLflow."""
    resp = await admin_client.get(AUTH, headers=_forwarded("GET", "/mlflow/"))
    assert resp.status_code == 200


async def test_lt28_nobody_signed_in_is_refused(anon_client: httpx.AsyncClient) -> None:
    """LT-28: no session, 401."""
    assert (await anon_client.get(AUTH)).status_code == 401


async def test_lt28_a_candidate_session_never_passes(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """LT-28: rules out the candidate cookie opening MLflow, even for an admin's email."""
    await make_admin(app, "dev@example.com")
    assert (await client.get(AUTH)).status_code == 401


async def test_lt28_the_sim_token_passes_only_when_set(
    app: FastAPI, anon_client: httpx.AsyncClient
) -> None:
    """LT-28: without MLFLOW_SIM_TOKEN no bearer token opens MLflow; with it, only that one."""
    bearer = {"Authorization": f"Bearer {TOKEN}"}
    assert (await anon_client.get(AUTH, headers=bearer)).status_code == 401
    app.state.admin_auth_settings = app.state.admin_auth_settings.model_copy(
        update={"mlflow_sim_token": SecretStr(TOKEN)}
    )
    assert (await anon_client.get(AUTH, headers=bearer)).status_code == 200
    wrong = {"Authorization": "Bearer something-else"}
    assert (await anon_client.get(AUTH, headers=wrong)).status_code == 401
    basic = {"Authorization": f"Basic {TOKEN}"}
    assert (await anon_client.get(AUTH, headers=basic)).status_code == 401


# The Caddy routing (LT-28) is checked in packages/core/tests/test_infra_mlflow.py.


# --- LT-29: the view audit -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "uri", "expected"),
    [
        ("GET", "/mlflow/ajax-api/3.0/mlflow/traces/tr-abc", TraceRead("get", "tr-abc")),
        (
            "GET",
            "/mlflow/ajax-api/3.0/mlflow/get-trace-artifact?request_id=tr-1",
            TraceRead("get", "tr-1"),
        ),
        ("GET", "/api/3.0/mlflow/traces/get?trace_id=tr-2", TraceRead("get", "tr-2")),
        ("GET", "/api/2.0/mlflow/traces/tr-3/info", TraceRead("get", "tr-3")),
        (
            "GET",
            "/mlflow/ajax-api/2.0/mlflow/traces?experiment_ids=1&filter=tags.org_id%3D%27x%27",
            TraceRead("search", "experiment_ids=1&filter=tags.org_id%3D%27x%27"),
        ),
        ("POST", "/mlflow/ajax-api/3.0/mlflow/traces/search", TraceRead("search", "traces/search")),
        ("POST", "/api/3.0/mlflow/traces", None),  # the sim writing a trace
        ("POST", "/api/3.0/mlflow/traces/delete-traces", None),
        ("GET", "/mlflow/ajax-api/2.0/mlflow/experiments/search", None),
        ("GET", "/mlflow/static-files/app.js", None),
        ("GET", "/mlflow/", None),
    ],
)
def test_lt29_which_requests_read_traces(method: str, uri: str, expected: TraceRead | None) -> None:
    assert trace_read(method, uri) == expected


async def test_lt29_a_trace_read_is_audited_once_per_window(
    admin_client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """LT-29: an admin opening a trace writes admin.trace_viewed with the trace id; the UI's
    repeated reads of the same trace add no rows; other MLflow requests write nothing."""
    get = _forwarded("GET", "/mlflow/ajax-api/3.0/mlflow/traces/tr-abc")
    assert (await admin_client.get(AUTH, headers=get)).status_code == 200
    assert (await admin_client.get(AUTH, headers=get)).status_code == 200
    other = _forwarded("GET", "/mlflow/ajax-api/2.0/mlflow/experiments/search")
    assert (await admin_client.get(AUTH, headers=other)).status_code == 200
    (row,) = await _views(sessionmaker)
    assert row.actor == ADMIN_EMAIL
    assert row.entity == "trace:tr-abc"
    assert row.details_json is not None
    assert row.details_json["kind"] == "get" and row.details_json["target"] == "tr-abc"


async def test_lt29_the_sim_token_writes_no_view_rows(
    sim_token: str,
    anon_client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """LT-29 is about people: the sim server's reads are not admin views."""
    headers = {
        "Authorization": f"Bearer {sim_token}",
        **_forwarded("GET", "/api/3.0/mlflow/traces/tr-abc"),
    }
    assert (await anon_client.get(AUTH, headers=headers)).status_code == 200
    assert await _views(sessionmaker) == []


# --- LT-19: the Controls switch ------------------------------------------------------------------


async def test_lt19_pausing_production_tracing_is_a_reasoned_audited_setting(
    admin_client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """LT-19, AA-6: the Controls switch writes llm_tracing_paused with the reason and an audit
    row with the value before and after."""
    put = {"value": True, "reason": "MLflow disk nearly full"}
    resp = await admin_client.put(
        "/admin/ops/settings/llm_tracing_paused", json=put, headers={"X-Admin-Request": "1"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["values"]["llm_tracing_paused"] is True
    async with sessionmaker() as db:
        row = (
            await db.scalars(select(AuditLog).where(AuditLog.action == "ops.setting_changed"))
        ).one()
    assert row.actor == ADMIN_EMAIL and row.entity == "runtime_setting:llm_tracing_paused"
    assert row.details_json is not None
    assert row.details_json["reason"] == "MLflow disk nearly full"
    assert row.details_json["before"] == {"llm_tracing_paused": False}
    assert row.details_json["after"] == {"llm_tracing_paused": True}
