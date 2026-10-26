"""The post-session rating (L05): "felt like a real interview", 1 to 5, one per session."""

from __future__ import annotations

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import SessionFeedback
from strong_core.schemas import SessionStatus

from .conftest import sign_in
from .test_scoring_api import make_session, make_target

Maker = async_sessionmaker[AsyncSession]


async def test_l05_rate_an_ended_session_and_change_the_rating(
    client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    session_id = await make_session(sessionmaker, await make_target(sessionmaker))
    assert (await client.get(f"/sessions/{session_id}/feedback")).json() is None

    r = await client.put(f"/sessions/{session_id}/feedback", json={"realism": 4})
    assert r.status_code == 200
    assert (r.json()["realism"], r.json()["comment"]) == (4, None)

    r = await client.put(
        f"/sessions/{session_id}/feedback", json={"realism": 2, "comment": "  Too polite  "}
    )
    assert (r.json()["realism"], r.json()["comment"]) == (2, "Too polite")
    got = (await client.get(f"/sessions/{session_id}/feedback")).json()
    assert (got["realism"], got["comment"]) == (2, "Too polite")
    async with sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(SessionFeedback)) == 1


async def test_l05_rating_is_1_to_5_and_only_after_the_end(
    client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    target = await make_target(sessionmaker)
    ended = await make_session(sessionmaker, target)
    for bad in (0, 6):
        r = await client.put(f"/sessions/{ended}/feedback", json={"realism": bad})
        assert r.status_code == 422
    live = await make_session(sessionmaker, target, status=SessionStatus.IN_PROGRESS)
    r = await client.put(f"/sessions/{live}/feedback", json={"realism": 5})
    assert r.status_code == 409


async def test_l05_only_the_owner_can_rate(
    client: httpx.AsyncClient, anon_client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    session_id = await make_session(sessionmaker, await make_target(sessionmaker))
    await sign_in(anon_client, "other@example.com")
    r = await anon_client.put(f"/sessions/{session_id}/feedback", json={"realism": 5})
    assert r.status_code == 404
    assert (await anon_client.get(f"/sessions/{session_id}/feedback")).status_code == 404
