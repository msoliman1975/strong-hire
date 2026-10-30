"""RM-2: one main resume per user. The first is main, the user can switch, deleting the main
makes the newest other one main, and the main resume comes first as the default for new roles."""

from __future__ import annotations

from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import Resume as ResumeRow

from .conftest import sign_in
from .test_library_api import add_resume


async def mains(maker: async_sessionmaker[AsyncSession]) -> int:
    async with maker() as db:
        return (
            await db.scalar(
                select(func.count())
                .select_from(ResumeRow)
                .where(ResumeRow.is_main.is_(True), ResumeRow.deleted_at.is_(None))
            )
        ) or 0


async def test_rm2_first_resume_is_main_and_later_ones_are_not(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """RM-2: the first resume becomes main; a second one does not."""
    await sign_in(client)
    first = await add_resume(client, fake_fixtures, "first.txt")
    second = await add_resume(client, fake_fixtures, "second.txt")
    assert first["is_main"] is True
    assert second["is_main"] is False
    assert await mains(sessionmaker) == 1


async def test_rm2_switch_the_main_resume(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """RM-2: POST /resumes/{id}/main switches it; the main one is listed first, as the default
    resume for a new role."""
    await sign_in(client)
    first = await add_resume(client, fake_fixtures, "first.txt")
    second = await add_resume(client, fake_fixtures, "second.txt")
    third = await add_resume(client, fake_fixtures, "third.txt")
    listed = (await client.get("/resumes")).json()
    assert [r["id"] for r in listed] == [first["id"], third["id"], second["id"]]

    resp = await client.post(f"/resumes/{second['id']}/main")
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_main"] is True
    listed = (await client.get("/resumes")).json()
    assert listed[0]["id"] == second["id"]
    assert [r["is_main"] for r in listed] == [True, False, False]
    assert (await client.get(f"/resumes/{first['id']}")).json()["is_main"] is False
    assert await mains(sessionmaker) == 1
    # Setting it again is fine.
    assert (await client.post(f"/resumes/{second['id']}/main")).status_code == 200
    assert await mains(sessionmaker) == 1


async def test_rm2_deleting_the_main_makes_the_newest_other_main(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """RM-2: delete the main resume and the newest other one becomes main; delete the last one
    and the next resume added is main again."""
    await sign_in(client)
    first = await add_resume(client, fake_fixtures, "first.txt")
    second = await add_resume(client, fake_fixtures, "second.txt")
    third = await add_resume(client, fake_fixtures, "third.txt")
    assert (await client.delete(f"/resumes/{first['id']}")).status_code == 204
    assert (await client.get(f"/resumes/{third['id']}")).json()["is_main"] is True
    assert (await client.get(f"/resumes/{second['id']}")).json()["is_main"] is False
    assert (await client.get(f"/resumes/{first['id']}")).json()["is_main"] is False
    # Deleting a resume that is not main changes nothing.
    assert (await client.delete(f"/resumes/{second['id']}")).status_code == 204
    assert (await client.get(f"/resumes/{third['id']}")).json()["is_main"] is True
    assert (await client.delete(f"/resumes/{third['id']}")).status_code == 204
    assert await mains(sessionmaker) == 0
    again = await add_resume(client, fake_fixtures, "again.txt")
    assert again["is_main"] is True


async def test_rm2_main_is_per_user_and_deleted_resumes_cannot_be_main(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """RM-2: another user's resume or a deleted one answers 404."""
    await sign_in(client)
    mine = await add_resume(client, fake_fixtures, "mine.txt")
    other = await add_resume(client, fake_fixtures, "other.txt")
    await client.delete(f"/resumes/{other['id']}")
    assert (await client.post(f"/resumes/{other['id']}/main")).status_code == 404
    await sign_in(client, "someone@example.com")
    assert (await client.post(f"/resumes/{mine['id']}/main")).status_code == 404
