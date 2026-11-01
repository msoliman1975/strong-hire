"""RF-1 and RF-2: the wave 1 role families and the per-family registry."""

from __future__ import annotations

import re

import pytest

from strong_core.config import find_repo_root
from strong_core.role_families import (
    COMMON_COMPETENCIES,
    ROLE_FAMILIES,
    TITLED_TYPES,
    family_info,
    family_prompt_name,
)
from strong_core.schemas import Competency, InterviewType, RoleFamily

WAVE_1 = {
    "infra_security",
    "data_analytics",
    "eng_management",
    "finance",
    "consulting_strategy",
    "project_program",
}
ORIGINAL = {"swe", "data_ml", "pm", "design", "tpm", "other"}


def test_rf1_enum_keeps_original_values_and_adds_wave_1() -> None:
    """RF-1 / D-4: splits narrow a value's meaning; no value is renamed or removed."""
    assert {f.value for f in RoleFamily} == ORIGINAL | WAVE_1


def test_rf2_every_family_has_exactly_one_registry_entry() -> None:
    """RF-2 / D-6: a RoleFamily value without an entry fails here."""
    assert set(ROLE_FAMILIES) == set(RoleFamily)
    for family, info in ROLE_FAMILIES.items():
        assert info.family is family


@pytest.mark.parametrize("family", list(RoleFamily))
def test_rf2_entry_is_complete(family: RoleFamily) -> None:
    """RF-2: label, rated competencies, a title per type and a generic loop for every family."""
    info = family_info(family)
    assert info.label.strip()
    assert info.rated_competencies[: len(COMMON_COMPETENCIES)] == COMMON_COMPETENCIES
    assert len(set(info.rated_competencies)) == len(info.rated_competencies)
    assert set(info.titles) == set(TITLED_TYPES)
    for kind in InterviewType:
        assert info.interviewer_title(kind).strip()
    assert info.interviewer_title(InterviewType.RECRUITER_SCREEN) == "Recruiter"
    assert info.interviewer_title(InterviewType.CUSTOM) == "Interviewer"
    assert 2 <= len(info.generic_loop) <= 4
    assert len(set(info.generic_loop)) == len(info.generic_loop)
    assert set(info.generic_loop) <= set(TITLED_TYPES)
    for kw in info.title_keywords:
        assert kw == kw.lower().strip() and kw


def test_rf2_only_other_has_no_title_keywords() -> None:
    """RF-2: every real family can back the extractor's choice with title words (IN-2)."""
    assert [f for f, i in ROLE_FAMILIES.items() if not i.title_keywords] == [RoleFamily.OTHER]


def test_rf2_splits_move_keywords_out_of_the_old_family() -> None:
    """RF-2 / D-1, D-2: SRE and security leave swe; plain analytics leaves data_ml."""
    swe = family_info(RoleFamily.SWE).title_keywords
    assert "sre" not in swe and "security" not in swe
    assert "sre" in family_info(RoleFamily.INFRA_SECURITY).title_keywords
    data = family_info(RoleFamily.DATA_ML).title_keywords
    assert "analytics" not in data and "data" not in data
    assert "analytics" in family_info(RoleFamily.DATA_ANALYTICS).title_keywords


def test_rf2_family_specific_defaults_from_the_spec() -> None:
    """RF-2 / RF-9: consulting leads with a case; design's technical interviewer is a designer."""
    consulting = family_info(RoleFamily.CONSULTING_STRATEGY).generic_loop
    assert consulting[0] == InterviewType.CASE
    assert InterviewType.TECHNICAL_QA not in consulting
    assert family_info(RoleFamily.DESIGN).interviewer_title(InterviewType.TECHNICAL_QA) == (
        "Design Lead"
    )
    assert family_info(RoleFamily.ENG_MANAGEMENT).extra_competencies == (
        Competency.JUDGMENT,
        Competency.PRIORITIZATION,
    )
    assert family_info(RoleFamily.OTHER).rated_competencies == COMMON_COMPETENCIES


def test_rf2_family_prompt_name() -> None:
    """D-7: the guidance prompt name for a family."""
    assert family_prompt_name(RoleFamily.FINANCE) == "family_finance"


@pytest.mark.parametrize("app", ["web", "admin"])
def test_rf10_ui_labels_match_the_registry(app: str) -> None:
    """RF-10: the web and admin role family labels are the registry's labels."""
    text = (find_repo_root() / "apps" / app / "src" / "labels.ts").read_text(encoding="utf-8")
    block = re.search(r"roleFamilyLabel: Record<RoleFamily, string> = \{(.*?)\n\};", text, re.S)
    assert block is not None
    labels = dict(re.findall(r'^\s*(\w+): "([^"]*)",', block.group(1), re.M))
    assert labels == {f.value: i.label for f, i in ROLE_FAMILIES.items()}


def test_rf5_brief_carries_the_role_family_and_old_briefs_read_as_other() -> None:
    """RF-5: the brief records the job's family; a brief stored before RF-5 reads as other."""
    from strong_core.schemas import InterviewerBrief

    field = InterviewerBrief.model_fields["role_family"]
    assert field.default == RoleFamily.OTHER
    assert not field.is_required()


def test_rf10_site_waitlist_roles_match_the_registry() -> None:
    """RF-10: the marketing site's waitlist form lists every family with the registry's labels,
    in the registry's order."""
    text = (find_repo_root() / "apps/site/src/components/WaitlistForm.astro").read_text("utf-8")
    block = re.search(r"const ROLES = \[(.*?)\n\] as const;", text, re.S)
    assert block is not None
    roles = re.findall(r'\["(\w+)", "([^"]*)"\]', block.group(1))
    assert roles == [(f.value, i.label) for f, i in ROLE_FAMILIES.items()]


def test_rf10_site_guides_name_every_family_but_other() -> None:
    """RF-10: a guide page exists only for a family with a noun label; other has no guides."""
    text = (find_repo_root() / "apps/site/src/data/guides.ts").read_text("utf-8")
    block = re.search(r"ROLE_LABELS: Record<string, string> = \{(.*?)\n\};", text, re.S)
    assert block is not None
    names = set(re.findall(r"^\s*(\w+): \"", block.group(1), re.M))
    assert names == {f.value for f in RoleFamily} - {"other"}


def test_rf12_question_bank_covers_every_wave_1_family() -> None:
    """RF-12: at least 15 general questions per wave 1 family, at least 3 for each standard type
    (consulting may skip technical Q&A and has at least 6 cases)."""
    from collections import Counter

    from strong_core.schemas import GeneralQuestionBank

    path = find_repo_root() / "questions" / "general.json"
    bank = GeneralQuestionBank.model_validate_json(path.read_text(encoding="utf-8"))
    wave_1 = {
        RoleFamily.INFRA_SECURITY,
        RoleFamily.DATA_ANALYTICS,
        RoleFamily.ENG_MANAGEMENT,
        RoleFamily.FINANCE,
        RoleFamily.CONSULTING_STRATEGY,
        RoleFamily.PROJECT_PROGRAM,
    }
    for family in wave_1:
        own = [q for q in bank.questions if family in q.role_families]
        by_type = Counter(q.interview_type for q in own)
        assert len(own) >= 15, (family, len(own))
        if family == RoleFamily.CONSULTING_STRATEGY:
            assert by_type[InterviewType.CASE] >= 6
            needed = (InterviewType.BEHAVIORAL, InterviewType.HIRING_MANAGER)
        else:
            needed = (
                InterviewType.BEHAVIORAL,
                InterviewType.HIRING_MANAGER,
                InterviewType.TECHNICAL_QA,
                InterviewType.CASE,
            )
        for kind in needed:
            assert by_type[kind] >= 3, (family, kind, by_type)


def test_rf14_beta_families_are_the_wave_1_families_without_5_gold_transcripts() -> None:
    """RF-14: a wave 1 family is labeled Beta until evals/transcripts has 5 of its transcripts."""
    import json
    from collections import Counter

    root = find_repo_root()
    counts = Counter(
        json.loads(p.read_text(encoding="utf-8")).get("role_family")
        for p in (root / "evals" / "transcripts").glob("*.json")
    )
    wave_1 = {
        "infra_security",
        "data_analytics",
        "eng_management",
        "finance",
        "consulting_strategy",
        "project_program",
    }
    expected = {f for f in wave_1 if counts[f] < 5}
    text = (root / "apps/web/src/labels.ts").read_text(encoding="utf-8")
    block = re.search(r"betaRoleFamilies[^=]*= new Set<RoleFamily>\(\[(.*?)\]\);", text, re.S)
    assert block is not None
    assert set(re.findall(r'"(\w+)"', block.group(1))) == expected
