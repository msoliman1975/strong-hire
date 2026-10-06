"""Seniority expectations for the rubric (IV-6). Level changes the bar, not the scale.

The scorer prompt gets the expectation for the candidate's level: the generic text below, plus
the company's own level bar from the profile (`bar_by_level`) in company mode.
"""

from __future__ import annotations

from strong_core.profiles import ResolvedProfile
from strong_core.schemas import Level

GENERIC_LEVEL_BARS: dict[Level, str] = {
    Level.NEW_GRAD: (
        "New grad: a 3 needs a clear personal role in a school, internship or side project, a "
        "concrete result, and some reflection. Scope inside one task or one small team is enough."
    ),
    Level.MID: (
        "Mid level: a 3 needs ownership of a feature or project inside one team, measurable "
        "results, and trade-offs the candidate weighed. Work led by others counts only for the "
        "candidate's own part."
    ),
    Level.SENIOR: (
        "Senior: a 3 needs ownership of a system or a multi-month project, influence on other "
        "teams, decisions made under ambiguity, and results the business can measure. "
        "Single-team scope with no cross-team influence is a 2."
    ),
    Level.STAFF_PRINCIPAL: (
        "Staff or principal: a 3 needs direction set across several teams or an organization, "
        "long-term technical or product strategy, and other leaders who changed course because of "
        "the candidate. Strong single-team work is a 2 at this level."
    ),
}


def level_expectations(level: Level, profile: ResolvedProfile) -> str:
    lines = [GENERIC_LEVEL_BARS[level]]
    if profile.profile is not None:
        name = profile.company_name or profile.profile.company_name
        for bar in profile.profile.bar_by_level:
            if bar.normalized_level == level:
                family = f", {bar.role_family.value}" if bar.role_family else ""
                lines.append(f"{name} {bar.level_name}{family}: {bar.scope_expectation}")
    return "\n".join(lines)
