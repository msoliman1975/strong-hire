"""Text-only interview sessions: a session controller, an interviewer and a simulated candidate.

    result = await run_text_session(config, persona)

P7 and P8 plug in here: pass `interviewer=` (P7) and score `result.turns` with their scorer (P8).
The brief comes from the real planner (P6, strong_evals.gap.GapPlanner) unless `planner=` or
`brief=` is passed.
The controller owns the phases and the clock (spec, Conversation state machine); the interviewer
only decides what to say and whether to probe. The probe cap is enforced here, in code (IV-3).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from strong_core.config import Settings
from strong_core.db.models import UsageEvent
from strong_core.gateway import ModelGateway, build_gateway
from strong_core.schemas import InterviewerBrief, Phase, SessionConfig, Speaker, Turn
from strong_evals.candidate import Persona, SimulatedCandidate
from strong_evals.gap import GapPlanner
from strong_evals.interfaces import Interviewer, InterviewState, Planner
from strong_evals.stubs import StubInterviewer
from strong_evals.usage import MeteredGateway, load_prices

MS_PER_WORD = 400  # about 150 spoken words per minute
GAP_MS = 700
RESERVE_MS = 5 * 60 * 1000  # time kept for candidate questions and wrap-up


@dataclass
class TextSession:
    session_id: uuid.UUID
    config: SessionConfig
    persona: Persona
    brief: InterviewerBrief
    turns: list[Turn] = field(default_factory=list)
    usage: list[UsageEvent] = field(default_factory=list)
    prompt_refs: list[str] = field(default_factory=list)

    @property
    def elapsed_ms(self) -> int:
        return self.turns[-1].end_ms if self.turns else 0


class _Controller:
    def __init__(self, session: TextSession) -> None:
        self.session = session

    def add(self, speaker: Speaker, phase: Phase, text: str, ref: str | None = None) -> Turn:
        start = self.session.elapsed_ms + (GAP_MS if self.session.turns else 0)
        end = start + max(1, len(text.split())) * MS_PER_WORD
        turn = Turn(
            speaker=speaker,
            phase=phase,
            text=text or "...",
            start_ms=start,
            end_ms=end,
            question_ref=ref,
        )
        self.session.turns.append(turn)
        return turn


async def run_text_session(
    config: SessionConfig,
    persona: Persona,
    *,
    gateway: ModelGateway | None = None,
    interviewer: Interviewer | None = None,
    planner: Planner | None = None,
    brief: InterviewerBrief | None = None,
    max_questions: int | None = None,
    session_id: uuid.UUID | None = None,
) -> TextSession:
    """Run one text interview end to end and return its transcript and UsageEvent records.

    Every model call goes through `gateway` (default: built from MODEL_PROFILE) and is metered.
    """
    sid = session_id or uuid.uuid4()
    base = gateway or build_gateway(Settings())
    metered = base if isinstance(base, MeteredGateway) else MeteredGateway(base, load_prices(), sid)
    if brief is None:
        brief = await (planner or GapPlanner(metered)).brief(config, persona)
    interviewer = interviewer or StubInterviewer(metered)
    candidate = SimulatedCandidate(
        persona, metered, level=config.level, interview_type=config.interview_type
    )
    session = TextSession(sid, config, persona, brief, usage=metered.events)
    ctl = _Controller(session)
    state = InterviewState(brief=brief, phase=Phase.INTRO, turns=session.turns)

    async def interviewer_turn(phase: Phase, ref: str | None = None) -> None:
        state.phase = phase
        ctl.add(Speaker.INTERVIEWER, phase, await interviewer.speak(state), ref)

    async def candidate_turn(phase: Phase, ref: str | None = None) -> None:
        ctl.add(Speaker.CANDIDATE, phase, await candidate.reply(session.turns), ref)

    await interviewer_turn(Phase.INTRO)
    await candidate_turn(Phase.INTRO)
    await interviewer_turn(Phase.SMALL_TALK)
    await candidate_turn(Phase.SMALL_TALK)
    await interviewer_turn(Phase.AGENDA)

    budget_ms = config.duration_min * 60 * 1000 - RESERVE_MS
    questions = sorted(brief.questions, key=lambda q: q.priority)
    if max_questions is not None:
        questions = questions[:max_questions]
    for question in questions:
        if session.elapsed_ms >= budget_ms:
            break
        state.question, state.probes_used = question, 0
        await interviewer_turn(Phase.CORE, question.id)
        await candidate_turn(Phase.CORE, question.id)
        while state.probes_used < brief.max_probes_per_question:
            probe = await interviewer.follow_up(state)
            if not probe:
                break
            state.probes_used += 1
            ctl.add(Speaker.INTERVIEWER, Phase.CORE, probe, question.id)
            await candidate_turn(Phase.CORE, question.id)
    state.question = None

    await interviewer_turn(Phase.CANDIDATE_QUESTIONS)
    await candidate_turn(Phase.CANDIDATE_QUESTIONS)
    await interviewer_turn(Phase.CANDIDATE_QUESTIONS)
    await interviewer_turn(Phase.WRAP_UP)
    await candidate_turn(Phase.WRAP_UP)

    candidate_words = sum(
        len(t.text.split()) for t in session.turns if t.speaker == Speaker.CANDIDATE
    )
    interviewer_chars = sum(len(t.text) for t in session.turns if t.speaker == Speaker.INTERVIEWER)
    metered.add_voice_estimate(candidate_words, interviewer_chars)
    session.prompt_refs = list(metered.prompt_refs)
    return session
