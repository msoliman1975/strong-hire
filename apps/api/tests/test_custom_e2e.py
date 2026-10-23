"""Custom interview end to end (docs/custom-interview-spec.md): API, brief job, controller, scorer.

A text session (PL-7) runs the same controller and interviewer as voice, so it covers the whole
path: the setup is stored (CU-1), the worker builds the brief from it (CU-12), the controller
asks every must-ask question (CU-4) and the debrief marks the candidate's own questions (CU-6).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import InterviewSession
from strong_core.db.models import Turn as TurnRow
from strong_core.schemas import InterviewerBrief, Phase, QuestionSource

from .test_sessions_api import ready_job

OWN = [
    ("Tell me about a time you disagreed with your manager.", "behavioral", ["conflict_handling"]),
    ("How would you make a payment API idempotent?", "technical_qa", ["technical_depth"]),
]


def custom_body(job_id: str) -> dict[str, Any]:
    return {
        "job_target_id": job_id,
        "channel": "text",
        "config": {
            "interview_type": "custom",
            "difficulty": "realistic",
            "mode": "realistic",
            "duration_min": 30,
            "level": "senior",
            "custom": {
                "categories": [
                    {"category": "behavioral", "share": 0.5, "focus": ["conflict"]},
                    {"category": "technical_qa", "share": 0.5, "focus": ["APIs"]},
                ],
                "questions": [
                    {"text": t, "category": c, "competencies": comps, "must_ask": True}
                    for t, c, comps in OWN
                ],
            },
        },
    }


async def test_cu1_cu4_cu6_custom_text_session_end_to_end(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    queue: Any,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """CU-1, CU-4, CU-6, CU-11, CU-12: a free account runs a 30-minute Custom session while
    Custom is open to everyone; every must-ask question is asked, and the debrief marks them."""
    job = await ready_job(client, fake_fixtures)
    resp = await client.post("/sessions", json=custom_body(job["id"]))
    assert resp.status_code == 201, resp.text
    sid = resp.json()["id"]
    assert resp.json()["config"]["custom"]["questions"][0]["must_ask"] is True

    async with sessionmaker() as db:
        row = await db.get(InterviewSession, uuid.UUID(sid))
        assert row is not None and row.brief_json is not None
        brief = InterviewerBrief.model_validate(row.brief_json)
    own = [q for q in brief.questions if q.source == QuestionSource.CANDIDATE]
    assert [q.text for q in own] == [t for t, _, _ in OWN]
    assert all(q.must_ask and q.category is not None for q in own)
    assert {q.category for q in brief.questions} == {c for _, c, _ in OWN}

    await client.post(f"/sessions/{sid}/text/open")
    queue.run_jobs = False  # the scorer job is checked as queued, not run
    ended = False
    for _ in range(120):
        out = (await client.post(f"/sessions/{sid}/text/turn", json={"text": "No."})).json()
        if out["ended"]:
            ended = True
            break
    assert ended
    assert [name for name, _, _ in queue.enqueued][-1] == "score_session"

    async with sessionmaker() as db:
        refs = set(
            await db.scalars(
                select(TurnRow.question_ref).where(
                    TurnRow.session_id == uuid.UUID(sid), TurnRow.phase == Phase.CORE
                )
            )
        )
    assert {q.id for q in own} <= refs, "every must-ask question is asked (CU-4)"

    debrief = await client.get(f"/sessions/{sid}/debrief")
    assert debrief.status_code == 200, debrief.text
    questions = debrief.json()["questions"]
    by_ref = {q["question_ref"]: q for q in questions}
    for q in own:
        assert by_ref[q.id]["source"] == "candidate"
        assert by_ref[q.id]["category"] == q.category.value  # type: ignore[union-attr]
