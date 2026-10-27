"""Tone, end to end (TN-1, TN-2, TN-3).

The tone the user picks shapes how the interviewer sounds. It never changes what the planner
writes, how hard the interviewer probes, or how the session is scored.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from strong_core.config import get_settings
from strong_core.gateway import ModelGateway, Role
from strong_core.gateway.registry import CapabilityTier, fake_models_config
from strong_core.profiles import ResolvedProfile, generic_profile
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    BriefDraft,
    CompanyProfile,
    Difficulty,
    InterviewerBrief,
    JobPosting,
    Resume,
    SessionConfig,
    Tone,
)
from strong_worker.gap.brief import (
    TONE_BY_DIFFICULTY,
    assemble,
    build_brief,
    build_messages,
    effective_tone,
    fixed_tones,
)
from strong_worker.scoring.scorer import SessionScorer
from strong_worker.scoring.testing import (
    RATIONALE,
    ScriptedBackend,
    load_scripted,
    scorecard_reply,
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
FIXED = (Tone.WARM, Tone.NEUTRAL, Tone.DIRECT)


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


def brief_for(tone: Tone, profile: ResolvedProfile, **changes: Any) -> InterviewerBrief:
    brief, _ = assemble(draft(), config(tone=tone, **changes), POSTING, profile, None)
    return brief


# --- TN-1: the four tones --------------------------------------------------------------------


def test_tn1_default_tone_is_as_company() -> None:
    """TN-1: a setup without a tone (an old client) gets "As the company"."""
    assert config().tone == Tone.AS_COMPANY


def test_tn1_every_fixed_tone_has_a_line_in_the_prompt_file() -> None:
    lines, ref = fixed_tones()
    assert set(lines) == set(FIXED)
    assert all(lines.values())
    assert ref == "planner/interviewer_brief_tones.v1"


@pytest.mark.parametrize("tone", FIXED)
def test_tn1_a_fixed_tone_replaces_the_persona_tone_line(tone: Tone) -> None:
    """TN-1: Warm, Neutral and Direct use the fixed line, not the profile's or the planner's."""
    profile = company()
    brief = brief_for(tone, profile)
    assert brief.session.tone == tone
    assert brief.persona.tone == fixed_tones()[0][tone]
    assert profile.persona.tone not in brief.persona.tone
    # The rest of the persona stays the company's.
    assert brief.persona.closing_style == profile.persona.closing_style
    assert brief.persona.pushback_style == profile.persona.pushback_style


def test_tn1_as_company_keeps_the_profile_persona_tone() -> None:
    """TN-1: "As the company" keeps the v1 line: the profile's tone, then the difficulty's."""
    profile = company()
    for difficulty in Difficulty:
        brief = brief_for(Tone.AS_COMPANY, profile, difficulty=difficulty)
        assert brief.persona.tone == f"{profile.persona.tone}. {TONE_BY_DIFFICULTY[difficulty]}"


async def test_tn1_built_brief_records_the_tone_prompt(gateway: ModelGateway) -> None:
    built = await build_brief(gateway, config(tone=Tone.DIRECT), POSTING, RESUME, company())
    assert "planner/interviewer_brief.v3" in built.model_version
    assert "planner/interviewer_brief_tones.v1" in built.model_version
    plain = await build_brief(gateway, config(), POSTING, RESUME, company())
    assert "interviewer_brief_tones" not in plain.model_version


# --- TN-2: tone changes the voice, not the probes, the questions or the score ----------------


@pytest.mark.parametrize("profile", [company(), generic_profile()], ids=["company", "generic"])
def test_tn2_tone_never_reaches_the_planner(profile: ResolvedProfile) -> None:
    """TN-2: the planner prompt is the same for every tone, so the questions cannot depend on
    it."""
    for kind in ("behavioral", "custom"):
        extra: dict[str, Any] = {}
        if kind == "custom":
            extra = {
                "interview_type": "custom",
                "custom": {
                    "categories": [{"category": "behavioral", "share": 1.0, "focus": []}],
                    "questions": [],
                },
            }
        messages = [
            [
                m.content
                for m in build_messages(config(tone=t, **extra), POSTING, RESUME, profile, None)
            ]
            for t in Tone
        ]
        assert all(m == messages[0] for m in messages)
        for line in fixed_tones()[0].values():
            assert line not in "\n".join(messages[0])


@pytest.mark.parametrize("difficulty", list(Difficulty))
def test_tn2_difficulty_still_controls_probes_and_pushback(difficulty: Difficulty) -> None:
    """TN-2 (IV-4): for one difficulty, every tone gives the same questions, probe limit,
    pushback, curveball and time plan. Only the tone line differs."""
    profile = company()
    briefs = [brief_for(t, profile, difficulty=difficulty) for t in Tone]
    strip = {"session": {"tone"}, "persona": {"tone"}}
    dumps = [b.model_dump(exclude=strip) for b in briefs]
    assert all(d == dumps[0] for d in dumps)
    assert len({b.persona.tone for b in briefs}) == len(Tone)


def test_tn2_a_fixed_tone_does_not_change_with_difficulty() -> None:
    """TN-2: a picked tone sounds the same at every difficulty; difficulty keeps the pushback."""
    profile = company()
    friendly = brief_for(Tone.WARM, profile, difficulty="friendly")
    tough = brief_for(Tone.WARM, profile, difficulty="tough")
    assert friendly.persona.tone == tough.persona.tone
    assert friendly.persona.pushback_style != tough.persona.pushback_style
    assert (friendly.pushback, tough.pushback) == (False, True)
    assert friendly.max_probes_per_question < tough.max_probes_per_question


@pytest.mark.parametrize("tier", [None, CapabilityTier.SMALL], ids=["default", "small"])
def test_tn2_the_tone_reaches_the_live_interviewer(tier: CapabilityTier | None) -> None:
    """TN-2: the interviewer's system prompt carries the tone line, in its own tone section."""
    brief = brief_for(Tone.DIRECT, company())
    prompt = load_prompt(Role.INTERVIEWER, "turn", tier=tier)
    assert prompt.version == (3 if tier else 4)
    text = prompt.render(
        interviewer_name="Alex",
        interview_type="behavioral",
        level="senior",
        company_line="The company is Example Corp.",
        tone=brief.persona.tone,
        pushback_style=brief.persona.pushback_style,
        closing_style=brief.persona.closing_style,
        seniority_bar=brief.seniority_bar,
        max_words="40",
        facts="(none)",
    )
    assert brief.persona.tone in text
    # Tone words live only in the tone section: no move asks for a friendly or calm voice.
    for word in ("friendly", "politely", "calm tone"):
        assert word not in text.lower()


async def test_tn2_tone_never_reaches_the_scorer() -> None:
    """TN-2: the scorer's input is the same for every tone, and so is the scorecard."""
    base, turns = load_scripted("beh-03")
    lines = fixed_tones()[0]
    cards = []
    for tone in Tone:
        brief = base.model_copy(
            update={
                "session": base.session.model_copy(update={"tone": tone}),
                "persona": base.persona.model_copy(
                    update={"tone": lines.get(tone, base.persona.tone)}
                ),
            }
        )
        backend = ScriptedBackend([scorecard_reply(brief, turns, 3), RATIONALE])
        gateway = ModelGateway(fake_models_config(), fake=backend)
        outcome = await SessionScorer(gateway).score(brief, turns, company())
        sent = "\n".join(m.content for messages, _ in backend.calls for m in messages)
        assert brief.persona.tone not in sent
        assert all(line not in sent for line in lines.values())
        assert tone.value not in sent.lower().split()
        cards.append(outcome.scorecard)
    assert all(c == cards[0] for c in cards)


# --- TN-3: generic mode is Neutral by default -------------------------------------------------


def test_tn3_generic_mode_uses_neutral_by_default() -> None:
    """TN-3: "As the company" without a company profile is Neutral."""
    profile = generic_profile()
    assert effective_tone(config(), profile) == Tone.NEUTRAL
    for difficulty in Difficulty:
        brief = brief_for(Tone.AS_COMPANY, profile, difficulty=difficulty)
        assert brief.persona.tone == fixed_tones()[0][Tone.NEUTRAL]
        assert brief.session.tone == Tone.AS_COMPANY  # the user's pick is kept as stored


def test_tn3_a_picked_tone_wins_in_generic_mode() -> None:
    profile = generic_profile()
    assert effective_tone(config(tone=Tone.WARM), profile) == Tone.WARM
    assert brief_for(Tone.DIRECT, profile).persona.tone == fixed_tones()[0][Tone.DIRECT]
    assert effective_tone(config(), company()) == Tone.AS_COMPANY
