"""AC-3: the profile asked for at the first sign-in, and edited later under Account."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import AuditLog

PROFILE: dict[str, Any] = {
    "full_name": "  Ana Lopez ",
    "years_experience": 7,
    "target_level": "senior",
    "current_title": "Backend engineer",
    "country": "",
    "time_zone": "Europe/Berlin",
    "linkedin_url": "www.linkedin.com/in/ana-lopez",
}


async def test_ac3_new_user_has_no_profile_yet(client: httpx.AsyncClient) -> None:
    me = (await client.get("/auth/me")).json()
    assert me["user"]["profile_complete"] is False and me["user"]["full_name"] is None
    profile = (await client.get("/account/profile")).json()
    assert profile["complete"] is False and profile["full_name"] is None


async def test_ac3_first_save_completes_the_profile(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    saved = await client.put("/account/profile", json=PROFILE)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["complete"] is True
    assert body["full_name"] == "Ana Lopez"
    assert body["country"] is None  # blank optional fields are stored as empty
    assert body["linkedin_url"] == "https://www.linkedin.com/in/ana-lopez"

    me = (await client.get("/auth/me")).json()["user"]
    assert me["profile_complete"] is True and me["full_name"] == "Ana Lopez"

    # A later edit keeps the profile complete and logs the first save only.
    edited = await client.put("/account/profile", json={**PROFILE, "years_experience": 8})
    assert edited.json()["years_experience"] == 8 and edited.json()["complete"] is True
    async with sessionmaker() as db:
        logs = await db.scalars(
            select(AuditLog).where(AuditLog.action == "account.profile_completed")
        )
        assert len(list(logs)) == 1


async def test_ac3_required_fields_and_limits(client: httpx.AsyncClient) -> None:
    for change in (
        {"full_name": "   "},
        {"years_experience": -1},
        {"years_experience": 51},
        {"target_level": "intern"},
        {"linkedin_url": "https://example.com/ana"},
        {"card_number": "4242"},  # no payment details here; unknown fields are refused
    ):
        resp = await client.put("/account/profile", json={**PROFILE, **change})
        assert resp.status_code == 422, change
    missing = {k: v for k, v in PROFILE.items() if k != "target_level"}
    assert (await client.put("/account/profile", json=missing)).status_code == 422
    assert (await client.get("/account/profile")).json()["complete"] is False


async def test_ac3_profile_needs_sign_in(anon_client: httpx.AsyncClient) -> None:
    assert (await anon_client.get("/account/profile")).status_code == 401
    assert (await anon_client.put("/account/profile", json=PROFILE)).status_code == 401
