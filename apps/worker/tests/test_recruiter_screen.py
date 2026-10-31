"""Recruiter screen, the fifth interview type (RS-1, RS-2).

Its own competencies (RS-1), and its own brief, question and rubric prompts, chosen by type and
never by model (RS-2). Its questions never ask about salary history or a protected
characteristic, in the prompts or in the brief code builds.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from strong_core.config import get_settings
from strong_core.gateway import ModelGateway
from strong_core.gateway.fake import messages_hash, read_recording
from strong_core.gateway.registry import CapabilityTier, fake_models_config
from strong_core.profiles import generic_profile
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    BriefDraft,
    Competency,
    InterviewType,
    JobPosting,
    Mode,
    Resume,
    SessionConfig,
)
from strong_worker.gap.brief import (
    OFF_LIMITS,
    assemble,
    brief_prompt,
    build_brief,
    build_messages,
    off_limits,
)
from strong_worker.scoring.scorer import SessionScorer, rubric_prompt
from strong_worker.scoring.testing import (
    RATIONALE,
    ScriptedBackend,
    load_scripted,
    scorecard_reply,
)

ROOT = get_settings().repo_root
INPUTS = ROOT / "evals/fixtures/inputs"
FIXTURES = ROOT / "packages/core/src/strong_core/gateway/fixtures"
POSTING = JobPosting.model_validate_json(
    (INPUTS / "postings/swe-stripe-backend.json").read_text(encoding="utf-8")
)
RESUME = Resume.model_validate_json(
    (INPUTS / "resumes/backend-senior.json").read_text(encoding="utf-8")
)
RS = InterviewType.RECRUITER_SCREEN
RS_COMPETENCIES = {
    Competency.MOTIVATION,
    Competency.ROLE_FIT,
    Competency.COMMUNICATION,
    Competency.LOGISTICS_AND_EXPECTATIONS,
}
PROMPTS = (
    ("planner", "interviewer_brief_recruiter_screen", None),
    ("interviewer", "turn_recruiter_screen", None),
    ("interviewer", "turn_recruiter_screen", CapabilityTier.SMALL),
    ("scorer", "rubric_recruiter_screen", None),
)

# Questions a recruiter must never ask, and close ones that are fine.
FORBIDDEN = (
    "What is your current salary?",
    "How much do you make now?",
    "Can you share your salary history?",
    "What was your bonus at your last job?",
    "How old are you?",
    "Where were you born?",
    "What is your citizenship?",
    "Are you married?",
    "Do you have kids, or plan to?",
    "Do you have any disability we should know about?",
    "What religion do you practice?",
    "Have you ever been arrested?",
)
ALLOWED = (
    "What pay range are you targeting for this role?",
    "Are you authorized to work here, or do you need visa sponsorship?",
    "When could you start, and what is your notice period?",
    "Walk me through your background.",
    "Why are you looking to move now?",
    "Where would you like to be based?",
)


def config(**changes: Any) -> SessionConfig:
    base: dict[str, Any] = {
        "interview_type": RS.value,
        "difficulty": "realistic",
        "mode": "realistic",
        "duration_min": 30,
        "level": "senior",
    }
    return SessionConfig.model_validate(base | changes)


def recruiter_draft() -> BriefDraft:
    """The fake planner's recorded reply for the recruiter brief of config()."""
    key = messages_hash(build_messages(config(), POSTING, RESUME, generic_profile(), None))
    path = FIXTURES / "planner" / f"{key}.json"
    assert path.exists(), f"record the recruiter brief fixture as planner/{key}.json"
    recorded = read_recording(path)
    assert recorded is not None
    return BriefDraft.model_validate(recorded.output)


# --- RS-1: a fifth type with its own competencies --------------------------------------------


def test_rs1_recruiter_screen_scores_its_own_competencies() -> None:
    """RS-1: motivation, role fit, communication, logistics and expectations."""
    assert set(COMPETENCIES_BY_TYPE[RS]) == RS_COMPETENCIES


@pytest.mark.parametrize("mode", list(Mode))
def test_rs1_brief_targets_only_recruiter_competencies_in_both_modes(mode: Mode) -> None:
    """RS-1: a 30-minute recruiter screen in Coach or Realistic mode gets a valid brief."""
    brief, flags = assemble(recruiter_draft(), config(mode=mode), POSTING, generic_profile(), None)
    assert set(brief.target_competencies) == RS_COMPETENCIES
    assert all(set(q.competencies) <= RS_COMPETENCIES for q in brief.questions)
    assert sum(t.minutes for t in brief.time_plan) == 30
    assert brief.coach_help == (mode == Mode.COACH)
    assert not [f for f in flags if f.startswith(("competency_reassigned", "off_limits"))]


def test_rs1_mini_recruiter_screen_works() -> None:
    """RS-1: the 10-minute mini works as for the other types."""
    brief, _ = assemble(
        recruiter_draft(), config(duration_min=10), POSTING, generic_profile(), None
    )
    assert len(brief.questions) == 3 and len(brief.target_competencies) == 2


# --- RS-2: its own brief, question and rubric prompts ----------------------------------------


def test_rs2_prompts_are_chosen_by_type() -> None:
    """RS-2: the recruiter screen has its own planner and rubric prompts; others keep theirs."""
    assert brief_prompt(config()) == "interviewer_brief_recruiter_screen"
    assert brief_prompt(config(interview_type="behavioral")) == "interviewer_brief"
    system = build_messages(config(), POSTING, RESUME, generic_profile(), None)[0]
    assert "recruiter screen" in system.content


async def test_rs2_built_brief_records_the_recruiter_prompt(gateway: ModelGateway) -> None:
    """RS-2: on the fake model, the planner writes recruiter questions and the brief version
    records the recruiter brief prompt."""
    built = await build_brief(gateway, config(), POSTING, RESUME, generic_profile())
    assert "planner/interviewer_brief_recruiter_screen.v2" in built.model_version
    assert built.brief.questions[0].text == recruiter_draft().questions[0].text
    assert {c for q in built.brief.questions for c in q.competencies} == RS_COMPETENCIES


async def test_rs2_scorer_uses_the_recruiter_rubric() -> None:
    """RS-2: the scorecard's rubric_version is the recruiter rubric."""
    base, turns = load_scripted("beh-03")
    draft, _ = assemble(recruiter_draft(), config(), POSTING, generic_profile(), None)
    refs = [q.id for q in base.questions]
    questions = [
        q.model_copy(update={"id": ref}) for q, ref in zip(draft.questions, refs, strict=False)
    ]
    brief = draft.model_copy(update={"questions": questions})
    assert rubric_prompt(brief) == "rubric_recruiter_screen"
    assert rubric_prompt(base) == "rubric"
    backend = ScriptedBackend([scorecard_reply(brief, turns, 3), RATIONALE])
    gateway = ModelGateway(fake_models_config(), fake=backend)
    outcome = await SessionScorer(gateway).score(brief, turns, generic_profile())
    assert outcome.scorecard.rubric_version == "scorer/rubric_recruiter_screen.v2"
    assert "recruiter screen" in backend.calls[0][0][0].content
    assert {c.competency for c in outcome.scorecard.competency_scores} <= RS_COMPETENCIES


@pytest.mark.parametrize(("role", "name", "tier"), PROMPTS)
def test_rs2_every_recruiter_prompt_loads(
    role: str, name: str, tier: CapabilityTier | None
) -> None:
    prompt = load_prompt(role, name, tier=tier)
    # RF-8 made v2 of the default variants; the small turn prompt needed no change.
    assert prompt.version == (1 if tier is not None else 2)
    assert ("small" in prompt.ref) == (tier is not None)


# --- never salary history or protected characteristics ----------------------------------------


@pytest.mark.parametrize(("role", "name", "tier"), PROMPTS)
def test_rs2_prompts_forbid_salary_history_and_protected_questions(
    role: str, name: str, tier: CapabilityTier | None
) -> None:
    """Every recruiter prompt says not to ask about salary history or protected
    characteristics, and lets the expected range and work authorization through."""
    text = re.sub(r"\s+", " ", load_prompt(role, name, tier=tier).text.lower())
    assert "past pay" in text
    for word in ("age", "religion", "national origin", "disability", "citizenship"):
        assert word in text, word
    assert "range" in text


def test_rs2_off_limits_catches_forbidden_questions() -> None:
    for question in FORBIDDEN:
        assert off_limits(question), question
    for question in ALLOWED:
        assert not off_limits(question), question


def test_rs2_brief_drops_a_forbidden_question() -> None:
    """Code drops an off-limits question even when the planner writes one."""
    draft = recruiter_draft()
    bad = draft.questions[1].model_copy(update={"text": "What is your current salary?"})
    hint = draft.questions[2].model_copy(update={"probe_hints": ["Ask if they have kids"]})
    questions = [draft.questions[0], bad, hint, *draft.questions[3:]]
    brief, flags = assemble(
        draft.model_copy(update={"questions": questions}),
        config(),
        POSTING,
        generic_profile(),
        None,
    )
    texts = [q.text for q in brief.questions]
    assert bad.text not in texts and hint.text not in texts
    assert (
        sorted(f.split(":")[0] for f in flags if "off_limits" in f) == ["off_limits_question"] * 2
    )


def test_rs2_recorded_recruiter_questions_are_clean() -> None:
    draft = recruiter_draft()
    for q in draft.questions:
        assert not off_limits(" ".join([q.text, *q.probe_hints])), q.text
    assert len(OFF_LIMITS) >= 5
