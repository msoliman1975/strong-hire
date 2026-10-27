"""Sessions API: the tone the user picks is stored and reaches the brief (TN-1, TN-2, TN-3)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import InterviewSession
from strong_core.schemas import InterviewerBrief, Tone
from strong_worker.gap.brief import fixed_tones

from .test_sessions_api import config, create, ready_job


async def _row(sessionmaker: async_sessionmaker[AsyncSession], session_id: str) -> InterviewSession:
    async with sessionmaker() as db:
        row = await db.get(InterviewSession, uuid.UUID(session_id))
        assert row is not None
        return row


async def test_tn1_tone_is_stored_and_shapes_the_brief(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: Any,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """TN-1, TN-2: the picked tone is stored on the session, returned, and sets the brief's
    tone line."""
    job = await ready_job(client, fake_fixtures)
    resp = await create(client, job["id"], tone="direct")
    assert resp.status_code == 201, resp.text
    record = resp.json()
    assert record["config"]["tone"] == "direct"
    row = await _row(sessionmaker, record["id"])
    assert row.tone == Tone.DIRECT
    assert row.brief_json is not None
    brief = InterviewerBrief.model_validate(row.brief_json)
    assert brief.persona.tone == fixed_tones()[0][Tone.DIRECT]
    repeat = (await client.post(f"/sessions/{record['id']}/repeat")).json()
    assert repeat["config"]["tone"] == "direct"


async def test_tn1_old_clients_get_the_default_tone(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: Any,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """TN-1, TN-3: a body without a tone stores as_company; with no company profile the brief
    uses the Neutral line."""
    job = await ready_job(client, fake_fixtures)
    body = {"job_target_id": job["id"], "config": config(), "channel": "voice"}
    assert "tone" not in body["config"]
    record = (await client.post("/sessions", json=body)).json()
    assert record["config"]["tone"] == "as_company"
    row = await _row(sessionmaker, record["id"])
    assert row.tone == Tone.AS_COMPANY
    assert row.brief_json is not None
    brief = InterviewerBrief.model_validate(row.brief_json)
    assert brief.generic_mode is True
    assert brief.persona.tone == fixed_tones()[0][Tone.NEUTRAL]


async def test_tn1_an_unknown_tone_is_refused(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    job = await ready_job(client, fake_fixtures)
    resp = await create(client, job["id"], tone="sarcastic")
    assert resp.status_code == 422
