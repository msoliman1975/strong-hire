"""Interviewer brief builder (spec: Interviewer brief; IV-3, IV-4, IV-5, IV-6, IV-7, IV-8).

Briefs for the same inputs must differ by difficulty and level in the expected ways.
"""

from __future__ import annotations

import itertools
import json
import uuid
from typing import Any

import pytest

from strong_core.config import get_settings
from strong_core.gateway import ModelGateway
from strong_core.profiles import ResolvedProfile, generic_profile
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    BriefDraft,
    CompanyProfile,
    Competency,
    Difficulty,
    GapAnalysis,
    InterviewType,
    JobPosting,
    Level,
    Mode,
    Phase,
    Resume,
    SessionConfig,
)
from strong_worker.gap.analysis import run_gap_analysis
from strong_worker.gap.brief import (
    GENERIC_BARS,
    MAX_BRIEF_TOKENS,
    BriefError,
    assemble,
    brief_tokens,
    build_brief,
    build_messages,
)

ROOT = get_settings().repo_root
INPUTS = ROOT / "evals/fixtures/inputs"
DRAFT = ROOT / "packages/core/src/strong_core/gateway/fixtures/planner/BriefDraft.json"
POSTING = JobPosting.model_validate_json(
    (INPUTS / "postings/swe-stripe-backend.json").read_text(encoding="utf-8")
)
RESUME = Resume.model_validate_json(
    (INPUTS / "resumes/backend-senior.json").read_text(encoding="utf-8")
)


def config(**changes: Any) -> SessionConfig:
    base: dict[str, Any] = {
        "interview_type": "behavioral",
        "difficulty": "realistic",
        "mode": "realistic",
        "duration_min": 30,
        "level": "senior",
    }
    return SessionConfig.model_validate(base | changes)


def draft() -> BriefDraft:
    return BriefDraft.model_validate_json(DRAFT.read_text(encoding="utf-8"))


def company() -> ResolvedProfile:
    profile = CompanyProfile.model_validate_json(
        (ROOT / "profiles/examples/example-corp.json").read_text(encoding="utf-8")
    )
    return ResolvedProfile.from_profile(profile, company_id=uuid.uuid4(), version=3)


@pytest.fixture
async def gap(gateway: ModelGateway) -> GapAnalysis:
    return (await run_gap_analysis(gateway, POSTING, RESUME, generic_profile())).analysis


async def test_brief_has_the_required_parts(gateway: ModelGateway, gap: GapAnalysis) -> None:
    built = await build_brief(gateway, config(), POSTING, RESUME, generic_profile(), gap=gap)
    brief = built.brief
    assert 4 <= len(brief.target_competencies) <= 6
    assert set(brief.target_competencies) <= set(COMPETENCIES_BY_TYPE[InterviewType.BEHAVIORAL])
    assert 6 <= len(brief.questions) <= 10
    assert [q.priority for q in brief.questions] == list(range(1, len(brief.questions) + 1))
    assert all(set(q.competencies) <= set(brief.target_competencies) for q in brief.questions)
    covered = {c for q in brief.questions for c in q.competencies}
    assert covered == set(brief.target_competencies)
    assert brief.probe_areas and brief.probe_areas[0] == gap.probe_areas[0]
    assert brief.persona.tone
    assert brief.seniority_bar == GENERIC_BARS[Level.SENIOR]
    assert [p.phase for p in brief.time_plan] == list(Phase)
    assert sum(p.minutes for p in brief.time_plan) == 30
    assert built.model_version.startswith("fake-planner planner/interviewer_brief.v1")


def test_brief_stays_under_the_token_limit() -> None:
    """Keep the brief under 1,500 tokens so the live loop stays fast, for every setup."""
    for itype, diff, level, minutes, mode in itertools.product(
        InterviewType, Difficulty, Level, (10, 30, 45), Mode
    ):
        cfg = config(
            interview_type=itype, difficulty=diff, level=level, duration_min=minutes, mode=mode
        )
        for profile in (generic_profile(), company()):
            brief, _ = assemble(draft(), cfg, POSTING, profile, None)
            assert brief_tokens(brief) <= MAX_BRIEF_TOKENS, (itype, diff, level, minutes)


def test_long_drafts_are_trimmed_to_fit() -> None:
    data = json.loads(DRAFT.read_text(encoding="utf-8"))
    for q in data["questions"]:
        q["text"] = ("Tell me about a hard project you led, with numbers and trade-offs. " * 4)[
            :230
        ] + q["id"]
        q["probe_hints"] = ["Ask for the measurable result of the work, in numbers " + q["id"]] * 3
    brief, flags = assemble(
        BriefDraft.model_validate(data), config(duration_min=45), POSTING, company(), None
    )
    assert brief_tokens(brief) <= MAX_BRIEF_TOKENS
    assert "trimmed_probe_hints" in flags
    assert len(brief.questions) >= 6


# --- difficulty (IV-3, IV-4) -----------------------------------------------------------------


def test_briefs_differ_by_difficulty() -> None:
    """Friendly probes less and never pushes back; Tough pushes back and adds one curveball."""
    friendly, _ = assemble(draft(), config(difficulty="friendly"), POSTING, generic_profile(), None)
    realistic, _ = assemble(
        draft(), config(difficulty="realistic"), POSTING, generic_profile(), None
    )
    tough, _ = assemble(draft(), config(difficulty="tough"), POSTING, generic_profile(), None)

    probes = [b.max_probes_per_question for b in (friendly, realistic, tough)]
    assert probes == [1, 2, 3]  # IV-3: at most 3, fewer in Friendly; matches P07
    assert (friendly.pushback, realistic.pushback, tough.pushback) == (False, False, True)
    assert friendly.curveball is None and realistic.curveball is None
    assert tough.curveball == draft().curveball
    assert len({friendly.persona.tone, realistic.persona.tone, tough.persona.tone}) == 3
    assert "simpler option" in tough.persona.pushback_style
    assert "does not challenge" in friendly.persona.pushback_style
    # The questions, competencies and time plan stay the same.
    assert friendly.questions == realistic.questions == tough.questions
    assert friendly.time_plan == tough.time_plan


def test_tough_brief_gets_a_curveball_even_if_the_model_gives_none() -> None:
    data = draft().model_copy(update={"curveball": None})
    tough, _ = assemble(data, config(difficulty="tough"), POSTING, generic_profile(), None)
    assert tough.curveball


def test_difficulty_reaches_the_planner_prompt() -> None:
    tough = build_messages(config(difficulty="tough"), POSTING, RESUME, generic_profile(), None)
    easy = build_messages(config(difficulty="friendly"), POSTING, RESUME, generic_profile(), None)
    assert "Difficulty: tough" in tough[1].content and "Write one curveball." in tough[1].content
    assert "Difficulty: friendly" in easy[1].content and "curveball to null" in easy[1].content


# --- level (IV-6) ----------------------------------------------------------------------------


def test_briefs_differ_by_level() -> None:
    """Level changes the bar, not the scale: each level gets its own seniority bar."""
    bars = {
        level: assemble(draft(), config(level=level), POSTING, generic_profile(), None)[
            0
        ].seniority_bar
        for level in Level
    }
    assert len(set(bars.values())) == len(Level)
    assert bars[Level.NEW_GRAD] is not None and "guidance" in bars[Level.NEW_GRAD]
    assert (
        bars[Level.STAFF_PRINCIPAL] is not None and "several teams" in bars[Level.STAFF_PRINCIPAL]
    )


def test_senior_hiring_manager_brief_targets_scope() -> None:
    """IV-6: senior and staff hiring manager briefs always probe scope at level."""
    senior, _ = assemble(
        draft(), config(interview_type="hiring_manager", level="senior"), POSTING, company(), None
    )
    assert Competency.SCOPE_AT_LEVEL in senior.target_competencies


def test_level_reaches_the_planner_prompt() -> None:
    new_grad = build_messages(config(level="new_grad"), POSTING, RESUME, generic_profile(), None)
    staff = build_messages(
        config(level="staff_principal"), POSTING, RESUME, generic_profile(), None
    )
    assert "Level: new_grad" in new_grad[1].content
    assert GENERIC_BARS[Level.STAFF_PRINCIPAL] in staff[1].content


def test_company_bar_by_level_is_used() -> None:
    """IV-5, IV-6: company mode uses the profile's level names and scope."""
    brief, _ = assemble(draft(), config(level="senior"), POSTING, company(), None)
    assert brief.seniority_bar is not None and brief.seniority_bar.startswith("E5 (senior)")


# --- mode, duration, company persona ---------------------------------------------------------


def test_mode_flags() -> None:
    """IV-8: Coach mode allows pause, hint and redo; Realistic does not."""
    coach, _ = assemble(draft(), config(mode="coach"), POSTING, generic_profile(), None)
    real, _ = assemble(draft(), config(mode="realistic"), POSTING, generic_profile(), None)
    assert coach.coach_help is True and real.coach_help is False


def test_duration_sets_the_time_plan_and_question_count() -> None:
    """IV-7: the phase minutes add up to 30 or 45, and 45 minutes gets more questions."""
    short, _ = assemble(draft(), config(duration_min=30), POSTING, generic_profile(), None)
    long, _ = assemble(draft(), config(duration_min=45), POSTING, generic_profile(), None)
    assert sum(p.minutes for p in short.time_plan) == 30
    assert sum(p.minutes for p in long.time_plan) == 45
    assert len(short.questions) == 8 and len(long.questions) == 10
    assert len(long.target_competencies) >= len(short.target_competencies)


@pytest.mark.parametrize("itype", list(InterviewType))
@pytest.mark.parametrize("difficulty", list(Difficulty))
def test_mini_brief_for_every_type(itype: InterviewType, difficulty: Difficulty) -> None:
    """IV-7 mini: 10 minutes, 3 questions, 2 competencies, 1 probe at most, no curveball,
    no small talk and no candidate questions in the time plan."""
    cfg = config(interview_type=itype, difficulty=difficulty, duration_min=10)
    for profile in (generic_profile(), company()):
        brief, _ = assemble(draft(), cfg, POSTING, profile, None)
        assert brief.session.duration_min == 10
        assert len(brief.questions) == 3
        assert len(brief.target_competencies) == 2
        covered = {c for q in brief.questions for c in q.competencies}
        assert set(brief.target_competencies) <= covered
        assert brief.max_probes_per_question <= 1
        assert brief.curveball is None
        assert brief.pushback is (difficulty == Difficulty.TOUGH)
        minutes = {p.phase: p.minutes for p in brief.time_plan}
        assert sum(minutes.values()) == 10
        assert minutes[Phase.CORE] == 8 and minutes[Phase.WRAP_UP] == 1
        assert minutes[Phase.SMALL_TALK] == 0 and minutes[Phase.CANDIDATE_QUESTIONS] == 0


def test_mini_asks_the_planner_for_3_questions_and_no_curveball() -> None:
    cfg = config(difficulty="tough", duration_min=10)
    messages = build_messages(cfg, POSTING, RESUME, generic_profile(), None)
    assert "curveball to null" in messages[1].content
    assert "Write one curveball." not in messages[1].content
    # BriefDraft needs 6 questions; the brief keeps the best 3.
    assert messages[1].content.startswith("Write 6 questions")
    assert "Length: 10 minutes" in messages[1].content


def test_mini_needs_only_3_usable_questions() -> None:
    data = draft().model_copy(update={"questions": draft().questions[:6]})
    brief, _ = assemble(data, config(duration_min=10), POSTING, generic_profile(), None)
    assert [q.priority for q in brief.questions] == [1, 2, 3]


def test_company_mode_uses_the_profile() -> None:
    """IV-5: persona tone, company values and the profile version come from the profile."""
    profile = company()
    brief, _ = assemble(draft(), config(), POSTING, profile, None)
    assert brief.generic_mode is False and brief.profile_version == 3
    assert brief.company_name == "Example Corp"
    assert brief.persona.tone.startswith(profile.persona.tone)
    assert brief.target_values[0] == "Own the outcome"
    # The heaviest weighted behavioral competency comes first.
    assert brief.target_competencies[0] == Competency.OWNERSHIP


def test_generic_mode_has_no_values() -> None:
    brief, _ = assemble(draft(), config(), POSTING, generic_profile(), None)
    assert brief.generic_mode is True and brief.profile_version is None
    assert brief.target_values == [] and brief.company_name is None


def test_gap_scores_rank_the_target_competencies(gap: GapAnalysis) -> None:
    """Gap-driven: in generic mode the weakest competencies from the gap analysis come first."""
    scores = {c.competency: c.score for c in gap.competency_breakdown}
    brief, _ = assemble(
        draft(), config(interview_type="hiring_manager"), POSTING, generic_profile(), gap
    )
    ranked = [c for c in brief.target_competencies if c in scores]
    assert [scores[c] for c in ranked] == sorted(scores[c] for c in ranked)


def test_too_few_questions_fail() -> None:
    data = json.loads(DRAFT.read_text(encoding="utf-8"))
    for q in data["questions"]:
        q["text"] = "Tell me about yourself."
    with pytest.raises(BriefError):
        assemble(BriefDraft.model_validate(data), config(), POSTING, generic_profile(), None)
