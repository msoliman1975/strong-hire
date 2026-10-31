"""Per-family facts for every role family (RF-2, `docs/role-families-spec.md` D-6).

This registry is the only place that maps a `RoleFamily` to data: its label, the title keywords
that back the extractor's choice, the competencies the gap analysis rates, who Strova plays for
each interview type, and the loop suggested in generic mode. Prose for a model never goes here;
it lives in `prompts/planner/family_<value>.v<N>.txt` (D-7).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from strong_core.schemas.enums import Competency, InterviewType, RoleFamily

COMMON_COMPETENCIES: Final[tuple[Competency, ...]] = (
    Competency.OWNERSHIP,
    Competency.IMPACT,
    Competency.COLLABORATION,
    Competency.COMMUNICATION,
    Competency.DEPTH_OF_EXPERIENCE,
    Competency.SCOPE_AT_LEVEL,
)
"""Rated in the gap analysis for every family."""

_BEH = InterviewType.BEHAVIORAL
_HM = InterviewType.HIRING_MANAGER
_TQA = InterviewType.TECHNICAL_QA
_CASE = InterviewType.CASE

TITLED_TYPES: Final[tuple[InterviewType, ...]] = (_BEH, _HM, _TQA, _CASE)
"""The types whose interviewer title depends on the family. Recruiter screen and Custom do not."""

FIXED_TITLES: Final[MappingProxyType[InterviewType, str]] = MappingProxyType(
    {InterviewType.RECRUITER_SCREEN: "Recruiter", InterviewType.CUSTOM: "Interviewer"}
)


@dataclass(frozen=True)
class FamilyInfo:
    family: RoleFamily
    label: str
    title_keywords: tuple[str, ...]
    """Lower-case words or phrases that, found in a job title, back this family (IN-2)."""
    extra_competencies: tuple[Competency, ...]
    """Rated by the gap analysis on top of COMMON_COMPETENCIES."""
    titles: MappingProxyType[InterviewType, str]
    """Who Strova plays for each of TITLED_TYPES when the profile names no interviewer."""
    generic_loop: tuple[InterviewType, ...]
    """TG-3 suggestion in generic mode, in order (D-9)."""

    @property
    def rated_competencies(self) -> tuple[Competency, ...]:
        return (*COMMON_COMPETENCIES, *self.extra_competencies)

    def interviewer_title(self, kind: InterviewType) -> str:
        return FIXED_TITLES.get(kind) or self.titles[kind]


def _info(
    family: RoleFamily,
    label: str,
    keywords: tuple[str, ...],
    extra: tuple[Competency, ...],
    titles: tuple[str, str, str, str],
    loop: tuple[InterviewType, ...],
) -> FamilyInfo:
    return FamilyInfo(
        family=family,
        label=label,
        title_keywords=keywords,
        extra_competencies=extra,
        titles=MappingProxyType(dict(zip(TITLED_TYPES, titles, strict=True))),
        generic_loop=loop,
    )


_C = Competency
_REGISTRY: Final[tuple[FamilyInfo, ...]] = (
    _info(
        RoleFamily.SWE,
        "Software engineering",
        ("engineer", "developer", "software", "full stack", "frontend", "backend", "mobile"),
        (_C.TECHNICAL_DEPTH, _C.TRADE_OFFS),
        ("Engineering Manager", "Hiring Manager", "Senior Engineer", "Product Lead"),
        (_BEH, _HM, _TQA),
    ),
    _info(
        RoleFamily.INFRA_SECURITY,
        "Infrastructure and security",
        (
            "sre",
            "site reliability",
            "devops",
            "infrastructure",
            "cloud",
            "platform",
            "network",
            "security",
            "systems administrator",
            "it",
        ),
        (_C.TECHNICAL_DEPTH, _C.TRADE_OFFS),
        (
            "Engineering Manager",
            "Hiring Manager",
            "Senior Infrastructure Engineer",
            "Engineering Manager",
        ),
        (_BEH, _HM, _TQA),
    ),
    _info(
        RoleFamily.DATA_ML,
        "Data science and ML",
        (
            "data scientist",
            "machine learning",
            "ml",
            "data engineer",
            "ai",
            "research scientist",
        ),
        (_C.TECHNICAL_DEPTH, _C.TRADE_OFFS),
        ("Data Science Manager", "Hiring Manager", "Senior Data Scientist", "Product Lead"),
        (_BEH, _HM, _TQA),
    ),
    _info(
        RoleFamily.DATA_ANALYTICS,
        "Data analytics",
        ("analyst", "analytics", "business intelligence", "bi", "insights", "reporting"),
        (_C.TECHNICAL_DEPTH, _C.PROBLEM_FRAMING),
        ("Analytics Manager", "Hiring Manager", "Senior Data Analyst", "Analytics Manager"),
        (_BEH, _TQA, _CASE),
    ),
    _info(
        RoleFamily.PM,
        "Product management",
        ("product manager", "product lead", "product owner"),
        (_C.USER_AND_BUSINESS_SENSE, _C.PRIORITIZATION),
        ("Product Lead", "Hiring Manager", "Engineering Lead", "Product Lead"),
        (_BEH, _HM, _CASE),
    ),
    _info(
        RoleFamily.DESIGN,
        "Design",
        ("designer", "design", "ux", "researcher"),
        (_C.USER_AND_BUSINESS_SENSE, _C.PROBLEM_FRAMING),
        ("Design Manager", "Hiring Manager", "Design Lead", "Product Lead"),
        (_BEH, _HM, _CASE),
    ),
    _info(
        RoleFamily.TPM,
        "Technical program management",
        ("technical program manager", "tpm"),
        (_C.TECHNICAL_DEPTH, _C.PRIORITIZATION),
        ("Engineering Manager", "Hiring Manager", "Senior Engineer", "Program Lead"),
        (_BEH, _HM, _TQA),
    ),
    _info(
        RoleFamily.ENG_MANAGEMENT,
        "Engineering management",
        (
            "engineering manager",
            "manager of engineering",
            "director of engineering",
            "head of engineering",
            "vp engineering",
            "vp of engineering",
        ),
        (_C.JUDGMENT, _C.PRIORITIZATION),
        (
            "Director of Engineering",
            "VP of Engineering",
            "Principal Engineer",
            "Director of Engineering",
        ),
        (_BEH, _HM, _TQA),
    ),
    _info(
        RoleFamily.FINANCE,
        "Finance",
        (
            "finance",
            "financial",
            "fp&a",
            "accountant",
            "accounting",
            "controller",
            "treasury",
            "investment banking",
        ),
        (_C.TECHNICAL_DEPTH, _C.PROBLEM_FRAMING),
        ("Finance Manager", "Hiring Manager", "Senior Financial Analyst", "Finance Director"),
        (_BEH, _TQA, _CASE),
    ),
    _info(
        RoleFamily.CONSULTING_STRATEGY,
        "Consulting and strategy",
        (
            "consultant",
            "consulting",
            "strategy",
            "bizops",
            "business operations",
            "corporate development",
            "chief of staff",
        ),
        (_C.PROBLEM_FRAMING, _C.USER_AND_BUSINESS_SENSE),
        ("Senior Manager", "Hiring Manager", "Senior Consultant", "Engagement Manager"),
        (_CASE, _BEH, _HM),
    ),
    _info(
        RoleFamily.PROJECT_PROGRAM,
        "Project and program management",
        ("project manager", "program manager", "pmo", "delivery manager", "scrum master"),
        (_C.PRIORITIZATION, _C.JUDGMENT),
        ("Program Director", "Hiring Manager", "Senior Program Manager", "Program Director"),
        (_BEH, _HM, _CASE),
    ),
    _info(
        RoleFamily.OTHER,
        "Other",
        (),
        (),
        ("Hiring Manager", "Hiring Manager", "Subject Expert", "Hiring Manager"),
        (_BEH, _HM, _TQA),
    ),
)

ROLE_FAMILIES: Final[MappingProxyType[RoleFamily, FamilyInfo]] = MappingProxyType(
    {info.family: info for info in _REGISTRY}
)


def family_info(family: RoleFamily) -> FamilyInfo:
    return ROLE_FAMILIES[family]


def family_prompt_name(family: RoleFamily) -> str:
    """The planner prompt with this family's guidance for the models (D-7)."""
    return f"family_{family.value}"
