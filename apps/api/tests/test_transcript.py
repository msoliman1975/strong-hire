"""The transcript view (v2 S13). Requirement IDs: TR-1 (the candidate reads the transcript of any
finished session, owner only), TR-2 (the transcript is in the AC-1 export and removed by
delete)."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.reports.transcript import TranscriptTurn, group_turns
from strong_core.db.models import Turn
from strong_core.schemas import Phase, SessionStatus, Speaker
from strong_worker.scoring.testing import load_scripted

from .accounts_support import FakeStripe, fill_every_user_table, sign_up
from .conftest import sign_in
from .test_scoring_api import make_session, make_target

Maker = async_sessionmaker[AsyncSession]


# ---------------------------------------------------------------- TR-1 read


async def test_tr1_owner_reads_the_turns_in_order_grouped_by_question(
    client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    session_id = await make_session(sessionmaker, await make_target(sessionmaker))
    brief, turns = load_scripted("beh-01")

    r = await client.get(f"/sessions/{session_id}/transcript")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == str(session_id)
    assert body["ended_at"] is not None

    got = [t for g in body["groups"] for t in g["turns"]]
    assert [t["text"] for t in got] == [t.text for t in turns]
    assert [t["speaker"] for t in got] == [t.speaker.value for t in turns]
    assert [t["phase"] for t in got] == [t.phase.value for t in turns]
    assert [t["start_ms"] for t in got] == [t.start_ms for t in turns]

    # Every question the candidate answered has its group, with the planned question text.
    texts = {q.id: q.text for q in brief.questions}
    refs = [g["question_ref"] for g in body["groups"] if g["question_ref"]]
    assert set(refs) == {t.question_ref for t in turns if t.question_ref}
    for group in body["groups"]:
        if group["question_ref"]:
            assert group["question_text"] == texts.get(group["question_ref"])


async def test_tr1_only_the_owner_can_read_it(
    client: httpx.AsyncClient, anon_client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    session_id = await make_session(sessionmaker, await make_target(sessionmaker))
    assert (await anon_client.get(f"/sessions/{session_id}/transcript")).status_code == 401
    await sign_in(anon_client, "other@example.com")
    r = await anon_client.get(f"/sessions/{session_id}/transcript")
    assert r.status_code == 404
    assert (await client.get(f"/sessions/{uuid.uuid4()}/transcript")).status_code == 404


async def test_tr1_a_session_that_has_not_ended_has_no_transcript_yet(
    client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    live = await make_session(
        sessionmaker, await make_target(sessionmaker), status=SessionStatus.IN_PROGRESS
    )
    r = await client.get(f"/sessions/{live}/transcript")
    assert r.status_code == 409
    assert r.json()["detail"] == "not_ended"


def _t(speaker: Speaker, phase: Phase, text: str, at: int) -> TranscriptTurn:
    return TranscriptTurn(
        id=uuid.uuid4(), speaker=speaker, phase=phase, text=text, start_ms=at, end_ms=at + 1
    )


def test_tr1_grouping_by_question_and_phase() -> None:
    i, c = Speaker.INTERVIEWER, Speaker.CANDIDATE
    turns = [
        (_t(i, Phase.INTRO, "Hi, I am Sam.", 0), None),
        (_t(c, Phase.INTRO, "Hi.", 1), None),
        (_t(i, Phase.CORE, "Tell me about a conflict.", 2), None),  # asked before matched
        (_t(c, Phase.CORE, "We disagreed on a design.", 3), "q1"),
        (_t(i, Phase.CORE, "What did you do next?", 4), None),  # a probe stays with q1
        (_t(i, Phase.CORE, "Tell me about a failure.", 5), "q2"),
        (_t(c, Phase.CORE, "A launch slipped.", 6), "q2"),
        (_t(i, Phase.WRAP_UP, "Thanks.", 7), None),
    ]
    groups = group_turns(turns, {"q1": "Conflict question", "q2": "Failure question"})
    assert [(g.question_ref, g.phase, len(g.turns)) for g in groups] == [
        (None, Phase.INTRO, 2),
        ("q1", Phase.CORE, 3),
        ("q2", Phase.CORE, 2),
        (None, Phase.WRAP_UP, 1),
    ]
    assert [g.question_text for g in groups] == [
        None,
        "Conflict question",
        "Failure question",
        None,
    ]


# ---------------------------------------------------------------- TR-2 export and delete


@pytest.fixture
def account_app(app: FastAPI) -> FastAPI:
    app.state.stripe = FakeStripe()
    return app


async def test_tr2_export_has_the_turns_and_delete_removes_them(
    account_app: FastAPI, client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    user: dict[str, Any] = await sign_up(client)
    org_id, user_id = uuid.UUID(user["org_id"]), uuid.UUID(user["id"])
    async with sessionmaker() as db:
        await fill_every_user_table(db, org_id, user_id, file_ref=None)
        texts = list(await db.scalars(select(Turn.text).where(Turn.org_id == org_id)))
    assert texts

    export = (await client.post("/account/export")).json()
    resp = await client.get(f"/account/export/{export['id']}/download")
    assert resp.status_code == 200
    data = json.loads(zipfile.ZipFile(io.BytesIO(resp.content)).read("data.json"))
    rows = data["tables"]["turns"]
    assert sorted(r["text"] for r in rows) == sorted(texts)
    assert {"speaker", "phase", "start_ms", "end_ms", "question_ref"} <= set(rows[0])

    assert (await client.delete("/account")).status_code == 202
    async with sessionmaker() as db:
        left = await db.scalar(select(func.count()).select_from(Turn).where(Turn.org_id == org_id))
    assert left == 0
