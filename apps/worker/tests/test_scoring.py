"""Scorer, hire signal and quote checks (FB-1, FB-2), and the scoring job (FB-3, PR-1)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.config import find_repo_root
from strong_core.db.models import CompanyProfile as ProfileRow
from strong_core.db.models import InterviewSession, JobTarget
from strong_core.db.models import ProgressSnapshot as SnapshotRow
from strong_core.db.models import Scorecard as ScorecardRow
from strong_core.db.models import Turn as TurnRow
from strong_core.gateway import ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_core.profiles import ResolvedProfile, generic_profile, parse_profile
from strong_core.schemas import (
    Competency,
    HireSignal,
    Level,
    Mode,
    Phase,
    ProfileStatus,
    SessionStatus,
    Speaker,
    Turn,
)
from strong_worker.main import WorkerSettings
from strong_worker.scoring import jobs
from strong_worker.scoring.quotes import QuoteChecker
from strong_worker.scoring.scorer import (
    ScoringError,
    SessionScorer,
    check_rationale,
    named_signals,
    render_transcript,
)
from strong_worker.scoring.signal import (
    RULE_CAP_AT_ONE,
    RULE_STRONG_NEEDS_THREE,
    compute_hire_signal,
    rubric_point,
)
from strong_worker.scoring.testing import (
    RATIONALE,
    ScriptedBackend,
    first_answers,
    load_scripted,
    quote_from,
    scorecard_reply,
)

EXAMPLE_PROFILE = find_repo_root() / "profiles" / "examples" / "example-corp.json"
C = Competency


def example_profile() -> ResolvedProfile:
    profile = parse_profile(json.loads(EXAMPLE_PROFILE.read_text(encoding="utf-8")))
    return ResolvedProfile.from_profile(profile, company_id=uuid.uuid4(), version=1)


def gateway(backend: ScriptedBackend) -> ModelGateway:
    return ModelGateway(fake_models_config(), fake=backend)


# --- FB-1: hire signal, computed in code -----------------------------------------------------


@pytest.mark.parametrize(
    ("scores", "expected"),
    [
        ({C.OWNERSHIP: 4, C.IMPACT: 4, C.COLLABORATION: 3}, HireSignal.STRONG_HIRE),
        ({C.OWNERSHIP: 3, C.IMPACT: 3, C.COLLABORATION: 3}, HireSignal.HIRE),
        ({C.OWNERSHIP: 3, C.IMPACT: 3, C.COLLABORATION: 2}, HireSignal.LEAN_HIRE),
        ({C.OWNERSHIP: 2, C.IMPACT: 2, C.COLLABORATION: 3}, HireSignal.LEAN_NO_HIRE),
        ({C.OWNERSHIP: 2, C.IMPACT: 2, C.COLLABORATION: 1}, HireSignal.NO_HIRE),
    ],
)
def test_fb1_signal_bands(scores: dict[Competency, float], expected: HireSignal) -> None:
    assert compute_hire_signal(scores, generic_profile()).signal == expected


def test_fb1_hard_rule_any_competency_at_one_caps_at_lean_no_hire() -> None:
    scores = {C.OWNERSHIP: 4.0, C.IMPACT: 4.0, C.COLLABORATION: 4.0, C.COMMUNICATION: 1.0}
    result = compute_hire_signal(scores, generic_profile())
    assert result.band == HireSignal.HIRE  # average 3.25
    assert result.signal == HireSignal.LEAN_NO_HIRE
    assert RULE_CAP_AT_ONE in result.rules


def test_fb1_hard_rule_strong_hire_needs_every_competency_at_three() -> None:
    scores = {C.OWNERSHIP: 4.0, C.IMPACT: 4.0, C.COLLABORATION: 4.0, C.COMMUNICATION: 2.0}
    result = compute_hire_signal(scores, generic_profile())
    assert result.average == 3.5
    assert result.signal == HireSignal.HIRE
    assert RULE_STRONG_NEEDS_THREE in result.rules


def test_fb1_rules_use_the_rounded_score_the_candidate_sees() -> None:
    assert rubric_point(1.49) == 1
    assert rubric_point(1.5) == 2
    assert rubric_point(2.5) == 3
    # 1.5 shows as 2, so the cap at 1 does not apply.
    result = compute_hire_signal({C.OWNERSHIP: 4.0, C.IMPACT: 1.5}, generic_profile())
    assert RULE_CAP_AT_ONE not in result.rules


def test_fb1_profile_weights_change_the_average() -> None:
    scores = {C.OWNERSHIP: 4.0, C.COLLABORATION: 2.0}
    generic = compute_hire_signal(scores, generic_profile())
    company = compute_hire_signal(scores, example_profile())  # ownership weighs 1.5
    assert generic.average == 3.0
    assert company.average == pytest.approx((4 * 1.5 + 2 * 1.0) / 2.5)
    assert company.average > generic.average


def test_fb1_company_values_take_the_values_share() -> None:
    profile = example_profile()  # values_share 0.25; Own the outcome weighs 1.5
    comps = {C.OWNERSHIP: 3.0, C.IMPACT: 3.0}
    values = {"Customer first": 4.0, "Own the outcome": 2.0}
    result = compute_hire_signal(comps, profile, values)
    value_avg = (4 * 1.0 + 2 * 1.5) / 2.5
    assert result.value_average == pytest.approx(value_avg)
    assert result.values_share == 0.25
    assert result.average == pytest.approx(0.75 * 3.0 + 0.25 * value_avg, abs=1e-3)


def test_fb1_generic_mode_ignores_value_scores() -> None:
    result = compute_hire_signal({C.OWNERSHIP: 3.0}, generic_profile(), {"Customer first": 1.0})
    assert result.value_average is None
    assert result.values_share == 0
    assert result.average == 3.0


# --- FB-2: quotes must appear in the transcript ----------------------------------------------


def test_fb2_quote_checker() -> None:
    _, turns = load_scripted("beh-01")
    answer = first_answers(turns)["q1"]
    checker = QuoteChecker(turns)
    words = answer.split()
    assert checker.is_valid(" ".join(words[:6]))
    assert checker.is_valid(" ".join(words[:6]).upper() + "!!")  # case and punctuation
    assert checker.is_valid(f"{' '.join(words[:3])} ... {' '.join(words[8:11])}")  # ellipsis
    assert not checker.is_valid(f"{' '.join(words[8:11])} ... {' '.join(words[:3])}")  # order
    assert not checker.is_valid("I wrote the plan and ran the cutover myself.")  # invented
    assert not checker.is_valid(" ".join(words[:2]))  # too short
    interviewer = next(t.text for t in turns if t.speaker == Speaker.INTERVIEWER)
    assert not checker.is_valid(interviewer)  # interviewer lines are not evidence


def test_fb2_quotes_match_whole_words() -> None:
    turns = [
        Turn(
            speaker=Speaker.CANDIDATE,
            phase=Phase.CORE,
            text="I ran the cutover myself.",
            start_ms=0,
            end_ms=1,
            question_ref="q1",
        ),
    ]
    checker = QuoteChecker(turns)
    assert checker.is_valid("I ran the cutover")
    assert checker.is_valid("ran the cutover myself")
    assert not checker.is_valid("an the cutover")


async def test_fb2_scorer_returns_quote_backed_per_question_scores() -> None:
    brief, turns = load_scripted("beh-01")
    backend = ScriptedBackend([scorecard_reply(brief, turns, 3), RATIONALE])
    outcome = await SessionScorer(gateway(backend)).score(brief, turns, generic_profile())
    card = outcome.scorecard
    asked = list(first_answers(turns))
    assert [q.question_ref for q in card.per_question] == asked
    checker = QuoteChecker(turns)
    for q in card.per_question:
        assert q.strengths and q.misses
        for s in q.scores:
            assert 1 <= s.score <= 4
            assert s.quotes and all(checker.is_valid(x) for x in s.quotes)
    assert card.rubric_version == "scorer/rubric.v1"
    assert card.scorer_model == "fake-scorer"
    assert outcome.model_calls == 2
    assert not outcome.reasked


async def test_fb2_bad_quotes_are_dropped_and_the_scorer_asks_again() -> None:
    brief, turns = load_scripted("beh-01")
    bad = scorecard_reply(brief, turns, 3, quote="I single-handedly saved the company")
    good = scorecard_reply(brief, turns, 2)
    backend = ScriptedBackend([bad, good, RATIONALE])
    outcome = await SessionScorer(gateway(backend)).score(brief, turns, generic_profile())
    assert outcome.reasked
    assert "I single-handedly saved the company" in outcome.dropped_quotes
    assert outcome.dropped_scores == []
    assert all(c.score == 2 for c in outcome.scorecard.competency_scores)
    retry_messages, _ = backend.calls[1]
    assert retry_messages[-1].prompt_ref == "scorer/requote.v1"
    assert "I single-handedly saved the company" in retry_messages[-1].content


async def test_fb2_scores_without_a_valid_quote_after_the_retry_are_dropped() -> None:
    brief, turns = load_scripted("beh-01")
    reply = scorecard_reply(brief, turns, 3)
    # q1 keeps an invented quote in both replies; the other questions quote correctly.
    for item in reply["per_question"][0]["scores"]:
        item["quotes"] = ["Words the candidate never said"]
    backend = ScriptedBackend([reply, reply, RATIONALE])
    outcome = await SessionScorer(gateway(backend)).score(brief, turns, generic_profile())
    q1 = brief.questions[0]
    assert outcome.reasked
    assert {f"q1/{c.value}" for c in q1.competencies} <= set(outcome.dropped_scores)
    assert "q1" not in [q.question_ref for q in outcome.scorecard.per_question]


async def test_fb2_no_valid_quote_at_all_fails_loudly() -> None:
    brief, turns = load_scripted("beh-01")
    bad = scorecard_reply(brief, turns, 3, quote="Nothing like this was said")
    backend = ScriptedBackend([bad, bad])
    with pytest.raises(ScoringError, match="quote"):
        await SessionScorer(gateway(backend)).score(brief, turns, generic_profile())


async def test_fb2_scores_for_questions_or_competencies_outside_the_session_are_dropped() -> None:
    brief, turns = load_scripted("beh-01")
    reply = scorecard_reply(brief, turns, 3)
    answer = quote_from(first_answers(turns)["q1"])
    reply["per_question"].append(
        dict(reply["per_question"][0], question_ref="q99", question_text="Never asked")
    )
    reply["per_question"][0]["scores"].append(
        {"competency": "accuracy", "score": 1, "justification": "x", "quotes": [answer]}
    )
    backend = ScriptedBackend([reply, RATIONALE])
    card = (await SessionScorer(gateway(backend)).score(brief, turns, generic_profile())).scorecard
    assert "q99" not in [q.question_ref for q in card.per_question]
    assert C.ACCURACY not in [c.competency for c in card.competency_scores]


async def test_fb1_the_model_does_not_pick_the_signal() -> None:
    brief, turns = load_scripted("beh-01")
    reply = scorecard_reply(brief, turns, 2, hire_signal="Strong Hire")
    backend = ScriptedBackend([reply, RATIONALE])
    outcome = await SessionScorer(gateway(backend)).score(brief, turns, generic_profile())
    assert outcome.scorecard.hire_signal == HireSignal.LEAN_NO_HIRE
    assert outcome.signal.average == 2.0


async def test_fb1_competency_score_is_the_mean_of_question_scores() -> None:
    brief, turns = load_scripted("beh-01")  # ownership is on q1 and q3
    reply = scorecard_reply(brief, turns, 3)
    for q in reply["per_question"]:
        for s in q["scores"]:
            if s["competency"] == "ownership":
                s["score"] = 4 if q["question_ref"] == "q1" else 2
    backend = ScriptedBackend([reply, RATIONALE])
    outcome = await SessionScorer(gateway(backend)).score(brief, turns, generic_profile())
    assert outcome.competency_averages[C.OWNERSHIP] == 3.0
    ownership = next(c for c in outcome.scorecard.competency_scores if c.competency == C.OWNERSHIP)
    assert ownership.score == 3


# --- FB-1: rationale ------------------------------------------------------------------------


async def test_fb1_rationale_is_written_for_the_computed_signal() -> None:
    brief, turns = load_scripted("beh-01")
    backend = ScriptedBackend([scorecard_reply(brief, turns, 3), RATIONALE])
    outcome = await SessionScorer(gateway(backend)).score(brief, turns, generic_profile())
    assert outcome.scorecard.rationale == RATIONALE
    assert outcome.rationale_source == "model"
    messages, output_type = backend.calls[-1]
    assert output_type is None
    assert "Hire signal: Hire" in messages[-1].content
    assert messages[0].prompt_ref == "scorer/rationale.v1"


async def test_fb1_rationale_that_names_another_signal_is_replaced() -> None:
    brief, turns = load_scripted("beh-01")
    wrong = "This is a Strong Hire. The candidate was great. Every answer was perfect."
    backend = ScriptedBackend([scorecard_reply(brief, turns, 3), wrong])
    outcome = await SessionScorer(gateway(backend)).score(brief, turns, generic_profile())
    assert outcome.rationale_source == "code"
    rationale = outcome.scorecard.rationale
    assert named_signals(rationale) == {HireSignal.HIRE}
    assert 3 <= rationale.count(". ") + 1 <= 5


def test_fb1_rationale_checks() -> None:
    three = "One thing. Two things. Three things."
    assert check_rationale(three, HireSignal.HIRE) == three
    assert check_rationale("Too short. Only two.", HireSignal.HIRE) is None
    six = " ".join(f"Sentence {i}." for i in range(6))
    assert check_rationale(six, HireSignal.HIRE) == " ".join(f"Sentence {i}." for i in range(5))
    lean = "The signal is Lean No Hire. Scope was small. Results were vague."
    assert check_rationale(lean, HireSignal.LEAN_NO_HIRE) == lean
    assert check_rationale(lean, HireSignal.NO_HIRE) is None
    assert named_signals("Lean No Hire") == {HireSignal.LEAN_NO_HIRE}


# --- level and company values in the prompt -------------------------------------------------


async def test_iv6_level_expectations_reach_the_rubric_prompt() -> None:
    brief, turns = load_scripted("beh-03")  # mid level, Example Corp
    backend = ScriptedBackend([scorecard_reply(brief, turns, 3), RATIONALE])
    await SessionScorer(gateway(backend)).score(brief, turns, example_profile())
    first, _ = backend.calls[0]
    assert first[0].prompt_ref == "scorer/rubric.v1"
    user = first[-1].content
    assert brief.session.level == Level.MID
    assert "Mid level: a 3 needs" in user
    assert "Example Corp E4" in user  # the company's own bar for this level
    assert "Customer first" in user


async def test_values_scored_in_company_mode() -> None:
    brief, turns = load_scripted("beh-03")
    reply = scorecard_reply(brief, turns, {"Customer first": 4, "Own the outcome": 2})
    backend = ScriptedBackend([reply, RATIONALE])
    outcome = await SessionScorer(gateway(backend)).score(brief, turns, example_profile())
    card = outcome.scorecard
    assert {v.value for v in card.value_scores} == {"Customer first", "Own the outcome"}
    assert any(q.value_scores for q in card.per_question)
    assert outcome.signal.values_share == 0.25
    assert outcome.signal.value_average == pytest.approx((4 + 2 * 1.5) / 2.5)


async def test_values_dropped_in_generic_mode() -> None:
    brief, turns = load_scripted("beh-03")
    generic_brief = brief.model_copy(
        update={
            "generic_mode": True,
            "profile_version": None,
            "company_name": None,
            "target_values": [],
            "questions": [q.model_copy(update={"values": []}) for q in brief.questions],
        }
    )
    # The model returns value scores anyway; the scorer drops them.
    backend = ScriptedBackend([scorecard_reply(brief, turns, 3), RATIONALE])
    outcome = await SessionScorer(gateway(backend)).score(generic_brief, turns, generic_profile())
    assert outcome.scorecard.value_scores == []
    assert all(q.value_scores == [] for q in outcome.scorecard.per_question)
    assert "generic mode" in backend.calls[0][0][-1].content


def test_long_transcripts_drop_small_talk_first() -> None:
    _, turns = load_scripted("beh-01")
    full = render_transcript(turns)
    short = render_transcript(turns, max_chars=len(full) - 10)
    assert len(short) < len(full)
    assert "final semester" not in short  # small talk
    assert all(a in short for a in first_answers(turns).values())


# --- the job: FB-3 and PR-1 -----------------------------------------------------------------


async def _make_session(
    maker: async_sessionmaker[AsyncSession],
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    transcript: str = "beh-01",
    mode: Mode = Mode.REALISTIC,
    company: bool = False,
    duration_min: int = 30,
) -> InterviewSession:
    brief, turns = load_scripted(transcript)
    brief = brief.model_copy(update={"session": brief.session.model_copy(update={"mode": mode})})
    async with maker() as db:
        company_id = None
        if company:
            from strong_core.db.models import Company

            company_row = Company(slug="example-corp", name="Example Corp")
            db.add(company_row)
            await db.flush()
            company_id = company_row.id
            data = json.loads(EXAMPLE_PROFILE.read_text(encoding="utf-8"))
            db.add(
                ProfileRow(
                    company_id=company_id,
                    version=1,
                    status=ProfileStatus.PUBLISHED,
                    profile_json=data,
                    sources_json=data["sources"],
                )
            )
        target = JobTarget(org_id=org_id, user_id=user_id, company_id=company_id)
        db.add(target)
        await db.flush()
        session = InterviewSession(
            org_id=org_id,
            job_target_id=target.id,
            type=brief.session.interview_type,
            difficulty=brief.session.difficulty,
            mode=mode,
            duration_min=duration_min,
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


def _job_ctx(maker: async_sessionmaker[AsyncSession], backend: ScriptedBackend) -> dict[str, Any]:
    return {jobs.CTX_KEY: jobs.ScoringContext(sessionmaker=maker, gateway=gateway(backend))}


def test_score_session_is_registered() -> None:
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert "score_session" in names


async def test_fb3_pr1_realistic_session_is_scored_within_budget(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, user_id = account
    session = await _make_session(sessionmaker, org_id, user_id)
    brief, turns = load_scripted("beh-01")
    backend = ScriptedBackend([scorecard_reply(brief, turns, 3), RATIONALE])
    result = await jobs.score_session(_job_ctx(sessionmaker, backend), str(session.id), str(org_id))

    assert result["outcome"] == "scored"
    assert result["hire_signal"] == "Hire"
    assert result["within_budget"] is True
    assert result["ready_after_s"] < jobs.DEBRIEF_BUDGET_S  # FB-3
    async with sessionmaker() as db:
        row = await db.scalar(select(ScorecardRow).where(ScorecardRow.session_id == session.id))
        assert row is not None and row.hire_signal == HireSignal.HIRE
        assert row.value_scores_json == []
        snaps = (
            await db.scalars(select(SnapshotRow).where(SnapshotRow.session_id == session.id))
        ).all()
        assert len(snaps) == result["snapshots"] == len(row.competency_scores_json)
        assert all(float(s.score) == 3.0 for s in snaps)
        stored = await db.get(InterviewSession, session.id)
        assert stored is not None and stored.status == SessionStatus.COMPLETED

    again = await jobs.score_session(_job_ctx(sessionmaker, backend), str(session.id), str(org_id))
    assert again["outcome"] == "exists"


async def test_pr1_coach_sessions_write_no_snapshots(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, user_id = account
    session = await _make_session(sessionmaker, org_id, user_id, mode=Mode.COACH)
    brief, turns = load_scripted("beh-01")
    backend = ScriptedBackend([scorecard_reply(brief, turns, 3), RATIONALE])
    result = await jobs.score_session(_job_ctx(sessionmaker, backend), str(session.id), str(org_id))
    assert result["outcome"] == "scored"
    assert result["snapshots"] == 0
    async with sessionmaker() as db:
        assert await db.scalar(select(ScorecardRow).where(ScorecardRow.session_id == session.id))
        assert (await db.scalars(select(SnapshotRow))).all() == []


async def test_pr1_mini_sessions_get_a_debrief_but_no_snapshots(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """A 10-minute Realistic session is scored, but stays out of the progress trends."""
    org_id, user_id = account
    session = await _make_session(sessionmaker, org_id, user_id, duration_min=10)
    brief, turns = load_scripted("beh-01")
    backend = ScriptedBackend([scorecard_reply(brief, turns, 3), RATIONALE])
    result = await jobs.score_session(_job_ctx(sessionmaker, backend), str(session.id), str(org_id))
    assert result["outcome"] == "scored"
    assert result["snapshots"] == 0
    async with sessionmaker() as db:
        assert await db.scalar(select(ScorecardRow).where(ScorecardRow.session_id == session.id))
        assert (await db.scalars(select(SnapshotRow))).all() == []
        stored = await db.get(InterviewSession, session.id)
        assert stored is not None and stored.status == SessionStatus.COMPLETED


async def test_company_session_uses_its_profile_version_and_stores_value_scores(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, user_id = account
    session = await _make_session(sessionmaker, org_id, user_id, "beh-03", company=True)
    brief, turns = load_scripted("beh-03")
    backend = ScriptedBackend([scorecard_reply(brief, turns, 3), RATIONALE])
    result = await jobs.score_session(_job_ctx(sessionmaker, backend), str(session.id), str(org_id))
    assert result["outcome"] == "scored"
    async with sessionmaker() as db:
        row = await db.scalar(select(ScorecardRow).where(ScorecardRow.session_id == session.id))
        assert row is not None
        assert {v["value"] for v in row.value_scores_json} == {"Customer first", "Own the outcome"}


async def test_failed_scoring_marks_the_session_failed(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, user_id = account
    session = await _make_session(sessionmaker, org_id, user_id)
    brief, turns = load_scripted("beh-01")
    bad = scorecard_reply(brief, turns, 3, quote="Nothing like this was said")
    result = await jobs.score_session(
        _job_ctx(sessionmaker, ScriptedBackend([bad])), str(session.id), str(org_id)
    )
    assert result["outcome"] == "failed"
    async with sessionmaker() as db:
        stored = await db.get(InterviewSession, session.id)
        assert stored is not None and stored.status == SessionStatus.FAILED
        assert await db.scalar(select(ScorecardRow)) is None


async def test_other_orgs_cannot_score_a_session(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, user_id = account
    session = await _make_session(sessionmaker, org_id, user_id)
    result = await jobs.score_session(
        _job_ctx(sessionmaker, ScriptedBackend([])), str(session.id), str(uuid.uuid4())
    )
    assert result == {"outcome": "failed", "reason": "session not found"}
