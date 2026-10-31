"""RF-9: generic-mode suggestions and "acting as" titles follow the job's role family."""

from __future__ import annotations

from typing import Any

import pytest

from strong_api.plan.interviews import acting_as, suggested
from strong_core.db.models import JobTarget
from strong_core.profiles import generic_profile
from strong_core.role_families import family_info
from strong_core.schemas import InterviewType, RoleFamily


def target(family: RoleFamily | None) -> JobTarget:
    parsed: dict[str, Any] | None = None
    if family is not None:
        parsed = {
            "company_name": "Unknown",
            "title": "A role",
            "role_family": family.value,
            "must_have_skills": [],
            "nice_to_have_skills": [],
            "responsibilities": [],
        }
    return JobTarget(raw_text="posting", parsed_json=parsed)


@pytest.mark.parametrize("family", list(RoleFamily))
def test_rf9_generic_mode_suggests_the_familys_loop(family: RoleFamily) -> None:
    """RF-9 / D-9: usual interviews are the family's generic loop, in order."""
    items = suggested(generic_profile(), target(family)).items
    usual = [i.interview_type for i in items if i.usual]
    assert usual == list(family_info(family).generic_loop)
    assert len(items) == 5


def test_rf9_consulting_leads_with_a_case_and_finance_has_no_engineers() -> None:
    """RF-9: the spec's family defaults reach the plan screen."""
    usual = [
        i.interview_type
        for i in suggested(generic_profile(), target(RoleFamily.CONSULTING_STRATEGY)).items
        if i.usual
    ]
    assert usual[0] == InterviewType.CASE
    finance = target(RoleFamily.FINANCE)
    tqa = acting_as(generic_profile(), finance, InterviewType.TECHNICAL_QA)
    assert tqa.text == "Strova is acting as a Senior Financial Analyst"
    assert "Engineer" not in acting_as(generic_profile(), finance, InterviewType.BEHAVIORAL).title


def test_rf9_unparsed_posting_reads_as_other() -> None:
    """RF-9: before the posting is parsed, the plan uses the other family's defaults."""
    assert acting_as(generic_profile(), target(None), InterviewType.CASE).title == (
        family_info(RoleFamily.OTHER).interviewer_title(InterviewType.CASE)
    )
    assert acting_as(generic_profile(), target(None), InterviewType.RECRUITER_SCREEN).title == (
        "Recruiter"
    )
