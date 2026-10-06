"""Text sessions with the simulated candidate (IV-3, IV-7, PL-1)."""

from __future__ import annotations

from strong_core.config import Settings
from strong_core.gateway import build_gateway
from strong_core.schemas import (
    Difficulty,
    InterviewType,
    Level,
    Mode,
    Phase,
    SessionConfig,
    Speaker,
    UsageComponent,
)
from strong_evals.candidate import Persona, SimulatedCandidate, resume_text
from strong_evals.interfaces import InterviewState
from strong_evals.session import run_text_session
from strong_evals.stubs import GatewayScorer, StubPlanner
from strong_evals.transcripts import PHASE_ORDER, Quality

CONFIG = SessionConfig(
    interview_type=InterviewType.BEHAVIORAL,
    difficulty=Difficulty.FRIENDLY,
    mode=Mode.REALISTIC,
    duration_min=30,
    level=Level.SENIOR,
)


def _persona(quality: Quality = Quality.WEAK) -> Persona:
    return Persona.from_resume_fixture("backend-senior", quality, "Sam Ortega")


def test_persona_is_built_from_a_resume_fixture() -> None:
    persona = _persona(Quality.STRONG)
    assert persona.resume.roles[0].company == "Fernhill Payments"
    candidate = SimulatedCandidate(
        persona,
        build_gateway(Settings()),
        level=Level.SENIOR,
        interview_type=InterviewType.BEHAVIORAL,
    )
    assert candidate.system.prompt_ref == "evals/sim_candidate.v1"
    assert "Fernhill Payments" in candidate.system.content
    assert "strong candidate" in candidate.system.content
    assert "payout service" in resume_text(persona.resume)


async def test_run_text_session_on_fake() -> None:
    """IV-7: phases in order; IV-3: vague answers get probes, capped per question."""
    session = await run_text_session(CONFIG, _persona(), max_questions=2)
    phases = [PHASE_ORDER.index(t.phase) for t in session.turns]
    assert phases == sorted(phases)
    assert session.turns[0].phase == Phase.INTRO
    assert session.turns[-1].phase == Phase.WRAP_UP
    core = [t for t in session.turns if t.phase == Phase.CORE]
    asks = [t for t in core if t.speaker == Speaker.INTERVIEWER]
    first_two = sorted(session.brief.questions, key=lambda q: q.priority)[:2]
    assert {t.question_ref for t in core} == {q.id for q in first_two}
    # The brief comes from the real planner (P6): gap analysis, then the brief.
    assert "planner/interviewer_brief.v1" in session.prompt_refs
    # The fake candidate is vague, so each question gets the Friendly probe cap.
    assert len(asks) == 2 * (1 + session.brief.max_probes_per_question)
    pairs = zip(session.turns, session.turns[1:], strict=False)
    assert all(a.end_ms <= b.start_ms for a, b in pairs)
    components = {e.component for e in session.usage}
    assert components == {UsageComponent.LLM, UsageComponent.STT, UsageComponent.TTS}
    assert all(e.session_id == session.session_id for e in session.usage)
    assert "evals/sim_candidate.v1" in session.prompt_refs


class _SilentInterviewer:
    """A plug-in interviewer, like P7 will provide: asks the brief question, never probes."""

    async def speak(self, state: InterviewState) -> str:
        return state.question.text if state.question else f"({state.phase.value})"

    async def follow_up(self, state: InterviewState) -> str | None:
        return None


async def test_a_custom_interviewer_plugs_in() -> None:
    session = await run_text_session(CONFIG, _persona(), interviewer=_SilentInterviewer())
    asks = [t for t in session.turns if t.phase == Phase.CORE and t.speaker == Speaker.INTERVIEWER]
    assert [t.text for t in asks] == [q.text for q in session.brief.questions]


async def test_stub_planner_brief_and_scorer() -> None:
    """FB-1: the scorer interface returns a Scorecard with the model alias and rubric ref."""
    brief = await StubPlanner().brief(CONFIG, _persona())
    assert brief.max_probes_per_question == 2
    assert len(brief.target_competencies) == 6
    session = await run_text_session(CONFIG, _persona(), brief=brief, max_questions=1)
    card = await GatewayScorer(build_gateway(Settings())).score(brief, session.turns)
    assert card.scorer_model == "fake-scorer"
    assert card.rubric_version == "evals/stub_scorer.v1"
