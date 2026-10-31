"""Role families in the prompts (role-families spec D-7, RF-3, RF-5 to RF-8)."""

from __future__ import annotations

from typing import Any

import pytest

from strong_core.config import get_settings
from strong_core.gateway import ModelGateway, Role
from strong_core.gateway.registry import fake_models_config
from strong_core.profiles import generic_profile
from strong_core.prompts import load_prompt
from strong_core.role_families import ROLE_FAMILIES, family_prompt_name
from strong_core.schemas import (
    BriefDraft,
    InterviewType,
    JobPosting,
    Resume,
    RoleFamily,
    SessionConfig,
)
from strong_worker.family import family_guidance
from strong_worker.gap.analysis import build_messages as gap_messages
from strong_worker.gap.brief import assemble, build_messages
from strong_worker.scoring.scorer import SessionScorer
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
FINANCE = POSTING.model_copy(update={"role_family": RoleFamily.FINANCE, "title": "FP&A Manager"})
MAX_WORDS = 220


def config(**changes: Any) -> SessionConfig:
    base: dict[str, Any] = {
        "interview_type": "technical_qa",
        "difficulty": "realistic",
        "mode": "realistic",
        "duration_min": 30,
        "level": "senior",
    }
    return SessionConfig.model_validate(base | changes)


# --- D-7: one guidance prompt per family ------------------------------------------------------


@pytest.mark.parametrize("family", list(RoleFamily))
def test_d7_every_family_has_a_guidance_prompt_that_renders(family: RoleFamily) -> None:
    """D-7: a RoleFamily value without prompts/planner/family_<value> fails here. The prompt has
    no placeholders, so a stray $ (money in finance text) fails too."""
    prompt = load_prompt(Role.PLANNER, family_prompt_name(family))
    text = prompt.render().strip()
    assert len(text.split()) <= MAX_WORDS
    for section in ("Technical Q&A:", "Case:", "Levels:", "Words to use:"):
        assert section in text, f"{prompt.ref} lacks {section}"
    assert family_guidance(family) == text


# --- RF-3: the extractor knows every family ---------------------------------------------------


def test_rf3_job_posting_prompt_lists_every_family_and_family_level_titles() -> None:
    """RF-3: all twelve values, the boundary rules and the family level mappings."""
    prompt = load_prompt(Role.EXTRACTOR, "job_posting")
    assert prompt.version == 2
    text = prompt.text
    for family in RoleFamily:
        assert f"  {family.value}:" in text, family.value
    assert "A tech lead with no direct reports is swe." in text
    for words in ("engagement\n    manager is senior", "vice\n    president is senior"):
        assert words in text


# --- RF-5: the brief gets the family and its guidance ------------------------------------------


@pytest.mark.parametrize("kind", ["technical_qa", "recruiter_screen"])
def test_rf5_brief_input_has_the_family_and_its_guidance(kind: str) -> None:
    """RF-5: the planner sees the job's family and its guidance, in the trusted part."""
    msgs = build_messages(config(interview_type=kind), FINANCE, RESUME, generic_profile(), None)
    user = msgs[1].content
    trusted = user.split("<untrusted_input>", 1)[0]
    assert "Role family: finance" in trusted
    assert family_guidance(RoleFamily.FINANCE) in trusted
    assert msgs[1].prompt_ref == "planner/interviewer_brief_input.v3"


def test_rf5_custom_brief_input_has_the_family_and_its_guidance() -> None:
    """RF-5: the Custom planner prompt gets the same family block."""
    custom = {
        "categories": [
            {"category": "behavioral", "share": 0.5, "focus": []},
            {"category": "technical_qa", "share": 0.5, "focus": []},
        ],
        "questions": [],
    }
    cfg = config(interview_type="custom", custom=custom)
    msgs = build_messages(cfg, FINANCE, RESUME, generic_profile(), None)
    trusted = msgs[1].content.split("<untrusted_input>", 1)[0]
    assert "Role family: finance" in trusted
    assert family_guidance(RoleFamily.FINANCE) in trusted
    assert msgs[1].prompt_ref == "planner/interviewer_brief_custom_input.v2"


def test_rf5_assembled_brief_records_the_postings_family() -> None:
    """RF-5: the family on the brief comes from the posting, never from the model's draft."""
    draft = BriefDraft.model_validate_json(
        (FIXTURES / "planner/BriefDraft.json").read_text(encoding="utf-8")
    )
    brief, _ = assemble(
        draft, config(interview_type="behavioral"), FINANCE, generic_profile(), None
    )
    assert brief.role_family == RoleFamily.FINANCE


# --- RF-6: the scorer gets the family's guidance ----------------------------------------------


async def test_rf6_scorer_input_has_the_family_guidance() -> None:
    """RF-6: the rubric input carries the family and its level notes; the rubric is unchanged."""
    base, turns = load_scripted("beh-03")
    brief = base.model_copy(update={"role_family": RoleFamily.CONSULTING_STRATEGY})
    backend = ScriptedBackend([scorecard_reply(brief, turns, 3), RATIONALE])
    scorer = SessionScorer(ModelGateway(fake_models_config(), fake=backend))
    await scorer.score(brief, turns, generic_profile())
    rubric_input = backend.calls[0][0][1].content
    assert rubric_input.startswith("Interview type:")
    assert "Role family: consulting_strategy" in rubric_input
    assert family_guidance(RoleFamily.CONSULTING_STRATEGY) in rubric_input
    assert backend.calls[0][0][1].prompt_ref == "scorer/rubric_input.v3"


# --- RF-7: generic mode is not a tech-industry bar --------------------------------------------


def test_rf7_generic_gap_analysis_no_longer_says_tech_industry() -> None:
    """RF-7: the generic bar is the role family's, not the tech industry's."""
    user = gap_messages(FINANCE, RESUME, generic_profile())[1].content
    assert "tech-industry" not in user
    assert "typical bar for this role family at a large North American employer" in user


# --- RF-8: recruiter screen is not only for engineers ------------------------------------------


@pytest.mark.parametrize(
    ("role", "name"),
    [
        (Role.PLANNER, "interviewer_brief_recruiter_screen"),
        (Role.INTERVIEWER, "turn_recruiter_screen"),
        (Role.SCORER, "rubric_recruiter_screen"),
    ],
)
def test_rf8_recruiter_screen_prompts_do_not_assume_an_engineer(role: Role, name: str) -> None:
    """RF-8: the recruiter is not a specialist in the role, whatever the family."""
    text = load_prompt(role, name, tier=None).text.lower()
    assert "engineer" not in text
    assert "technical depth" not in text


def test_rf2_registry_covers_every_family_used_by_the_worker() -> None:
    """RF-2: the worker's per-family tables come from the registry, so nothing is missing."""
    from strong_worker.gap.analysis import RATED_COMPETENCIES
    from strong_worker.inputs.confidence import FAMILY_KEYWORDS

    assert set(RATED_COMPETENCIES) == set(ROLE_FAMILIES) == set(FAMILY_KEYWORDS)
    assert InterviewType.CASE in ROLE_FAMILIES[RoleFamily.FINANCE].generic_loop
