"""Admin write actions (AA-5, AA-6): the header, the required reason and the audit row."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.admin.actions import ActionIn, AdminWrite, audit_action
from strong_api.auth.deps import DbSession
from strong_api.main import create_app
from strong_core.db.models import AuditLog

from .conftest import InlineQueue, sign_in_admin

Maker = async_sessionmaker[AsyncSession]
ADMIN = "boss@example.com"


class PokeIn(ActionIn):
    level: int


probe = APIRouter(prefix="/admin")


@probe.post("/_probe")
async def poke(body: PokeIn, admin: AdminWrite, db: DbSession) -> dict[str, str]:
    audit_action(
        db,
        admin,
        "probe.poke",
        "probe:1",
        reason=body.reason,
        before={"level": 0},
        after={"level": body.level},
    )
    await db.commit()
    return {"ok": "yes"}


async def _ok() -> None:
    return None


@pytest.fixture
def app(sessionmaker: Maker, queue: InlineQueue) -> FastAPI:
    app = create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)
    app.include_router(probe)
    return app


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await sign_in_admin(http, app, ADMIN)
        yield http


HEADERS = {"X-Admin-Request": "1"}
BODY: dict[str, Any] = {"reason": "testing the probe", "level": 3}


async def test_aa5_write_needs_the_admin_request_header(admin: httpx.AsyncClient) -> None:
    assert (await admin.post("/admin/_probe", json=BODY)).status_code == 403
    assert (await admin.post("/admin/_probe", json=BODY, headers=HEADERS)).status_code == 200


async def test_aa4_non_admins_get_404_even_with_the_header(
    anon_client: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    assert (await anon_client.post("/admin/_probe", json=BODY, headers=HEADERS)).status_code == 404
    assert (await client.post("/admin/_probe", json=BODY, headers=HEADERS)).status_code == 404


async def test_aa6_reason_is_required(admin: httpx.AsyncClient) -> None:
    for body in ({"level": 3}, {"reason": "", "level": 3}, {**BODY, "extra": 1}):
        assert (await admin.post("/admin/_probe", json=body, headers=HEADERS)).status_code == 422


async def test_aa6_action_writes_audit_row_with_reason_before_and_after(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    assert (await admin.post("/admin/_probe", json=BODY, headers=HEADERS)).status_code == 200
    async with sessionmaker() as db:
        row = await db.scalar(select(AuditLog).where(AuditLog.action == "probe.poke"))
    assert row is not None and row.actor == ADMIN and row.entity == "probe:1"
    assert row.details_json == {
        "reason": "testing the probe",
        "before": {"level": 0},
        "after": {"level": 3},
    }
