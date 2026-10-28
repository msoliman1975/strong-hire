"""Delivery metrics per answer (DM-1): pace and fillers from fixed turn data, no audio."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import InterviewSession, JobTarget
from strong_core.db.models import Scorecard as ScorecardRow
from strong_core.db.models import Turn as TurnRow
from strong_core.gateway import ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import (
    Competency,
    CompetencyScore,
    HireSignal,
    Mode,
    Phase,
    QuestionScore,
    Scorecard,
    SessionChannel,
    SessionStatus,
    Speaker,
    Turn,
)
from strong_worker.scoring import jobs
from strong_worker.scoring.delivery import (
    FILLERS,
    answer_metrics,
    count_fillers,
    delivery_by_question,
    with_delivery,
)
from strong_worker.scoring.testing import RATIONALE, ScriptedBackend, load_scripted, scorecard_reply


def turn(speaker: Speaker, text: str, start_s: float, end_s: float, ref: str | None) -> Turn:
    return Turn(
        speaker=speaker,
        phase=Phase.CORE,
        text=text,
        start_ms=int(start_s * 1000),
        end_ms=int(end_s * 1000),
        question_ref=ref,
    )


def _words(n: int) -> str:
    return " ".join(["word"] * n)


# Fixed turns: q1 has two candidate turns of 30 s each (120 words, 3 fillers), q2 one 60 s turn.
TURNS = [
    turn(Speaker.INTERVIEWER, "Tell me about a hard project.", 0, 5, "q1"),
    turn(Speaker.CANDIDATE, "Um, so " + _words(58), 5, 35, "q1"),
    turn(Speaker.INTERVIEWER, "What was your role?", 40, 42, "q1"),
    turn(Speaker.CANDIDATE, "I, uh, basically " + _words(57), 45, 75, "q1"),
    turn(Speaker.INTERVIEWER, "Walk me through a design.", 80, 85, "q2"),
    turn(Speaker.CANDIDATE, _words(100), 85, 145, "q2"),
    turn(Speaker.CANDIDATE, "Thanks for your time.", 150, 152, None),
]


def card(refs: list[str]) -> Scorecard:
    score = CompetencyScore(
        competency=Competency.OWNERSHIP, score=3, justification="ok", quotes=["word"]
    )
    return Scorecard(
        hire_signal=HireSignal.HIRE,
        rationale="Fine.",
        competency_scores=[score],
        per_question=[
            QuestionScore(question_ref=r, question_text="Q?", scores=[score]) for r in refs
        ],
        scorer_model="scorer",
        rubric_version="scorer/rubric.v1",
    )


def test_dm1_filler_list_is_fixed() -> None:
    assert FILLERS == ("um", "uh", "like", "you know", "basically", "sort of")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Um, I think, uh, we basically shipped it.", 3),
        ("You know, it was sort of slow.", 2),
        ("It was, like, slow. Like, really slow.", 2),
        ("I like Go and it looks like a race condition.", 0),
        ("Umbrella and uhura are words, not fillers; so is sorted.", 0),
        ("UM. Uh. YOU KNOW.", 3),
    ],
)
def test_dm1_counts_fillers(text: str, expected: int) -> None:
    assert count_fillers(text) == expected


def test_dm1_pace_and_fillers_per_answer_from_candidate_turns_only() -> None:
    metrics = delivery_by_question(TURNS)
    assert set(metrics) == {"q1", "q2"}  # the closing turn has no question
    q1 = metrics["q1"]
    assert q1.duration_seconds == 60.0  # 2 x 30 s; interviewer turns and gaps do not count
    assert q1.words_per_minute == 120.0
    assert q1.fillers_per_minute == 3.0
    q2 = metrics["q2"]
    assert (q2.words_per_minute, q2.fillers_per_minute, q2.duration_seconds) == (100.0, 0, 60.0)


def test_dm1_no_speaking_time_gives_no_metrics() -> None:
    assert answer_metrics([]) is None
    assert answer_metrics([turn(Speaker.CANDIDATE, "hello", 10, 10, "q1")]) is None


def test_dm1_scorecard_gets_delivery_for_voice_sessions() -> None:
    out = with_delivery(card(["q1", "q2", "q3"]), TURNS, SessionChannel.VOICE)
    by_ref = {q.question_ref: q.delivery for q in out.per_question}
    assert by_ref["q1"] is not None and by_ref["q1"].words_per_minute == 120.0
    assert by_ref["q2"] is not None
    assert by_ref["q3"] is None  # scored but never answered aloud


def test_dm1_pl7_text_channel_sessions_are_skipped() -> None:
    out = with_delivery(card(["q1", "q2"]), TURNS, SessionChannel.TEXT)
    assert all(q.delivery is None for q in out.per_question)


async def _session(
    maker: async_sessionmaker[AsyncSession],
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    channel: SessionChannel,
) -> InterviewSession:
    brief, turns = load_scripted("beh-01")
    async with maker() as db:
        target = JobTarget(org_id=org_id, user_id=user_id)
        db.add(target)
        await db.flush()
        session = InterviewSession(
            org_id=org_id,
            job_target_id=target.id,
            type=brief.session.interview_type,
            difficulty=brief.session.difficulty,
            mode=Mode.REALISTIC,
            duration_min=30,
            channel=channel,
            profile_version=brief.profile_version,
            brief_json=brief.model_dump(mode="json"),
            status=SessionStatus.SCORING,
            started_at=datetime.now(UTC) - timedelta(minutes=30),
            ended_at=datetime.now(UTC),
        )
        db.add(session)
        await db.flush()
        db.add_all(TurnRow(org_id=org_id, session_id=session.id, **t.model_dump()) for t in turns)
        await db.commit()
        return session


@pytest.mark.parametrize("channel", [SessionChannel.VOICE, SessionChannel.TEXT])
async def test_dm1_scoring_job_stores_delivery_per_question(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    channel: SessionChannel,
) -> None:
    org_id, user_id = account
    session = await _session(sessionmaker, org_id, user_id, channel)
    brief, turns = load_scripted("beh-01")
    backend = ScriptedBackend([scorecard_reply(brief, turns, 3), RATIONALE])
    gateway = ModelGateway(fake_models_config(), fake=backend)
    ctx = {jobs.CTX_KEY: jobs.ScoringContext(sessionmaker=sessionmaker, gateway=gateway)}
    result = await jobs.score_session(ctx, str(session.id), str(org_id))
    assert result["outcome"] == "scored"
    async with sessionmaker() as db:
        row = await db.scalar(select(ScorecardRow).where(ScorecardRow.session_id == session.id))
        assert row is not None and row.per_question_json
        deliveries = [q["delivery"] for q in row.per_question_json]
    if channel == SessionChannel.TEXT:
        assert all(d is None for d in deliveries)
    else:
        assert all(d is not None and d["words_per_minute"] > 0 for d in deliveries)
