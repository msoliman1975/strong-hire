"""Enumerations shared by the Pydantic schemas and the database models.

Values are stored as-is in Postgres and JSON, so never rename a value without a migration.
"""

from __future__ import annotations

from enum import StrEnum


class Level(StrEnum):
    """Normalized seniority (IV-6). Company-specific labels such as L5 or E5 map to these."""

    NEW_GRAD = "new_grad"
    MID = "mid"
    SENIOR = "senior"
    STAFF_PRINCIPAL = "staff_principal"


class RoleFamily(StrEnum):
    SWE = "swe"
    DATA_ML = "data_ml"
    PM = "pm"
    DESIGN = "design"
    TPM = "tpm"
    OTHER = "other"


class InterviewType(StrEnum):
    """The four v1 interview types (IV-2)."""

    BEHAVIORAL = "behavioral"
    HIRING_MANAGER = "hiring_manager"
    TECHNICAL_QA = "technical_qa"
    CASE = "case"


class Difficulty(StrEnum):
    """IV-4."""

    FRIENDLY = "friendly"
    REALISTIC = "realistic"
    TOUGH = "tough"


class Mode(StrEnum):
    """IV-8. Only Realistic sessions count toward progress trends (PR-1)."""

    COACH = "coach"
    REALISTIC = "realistic"


class Phase(StrEnum):
    """Session state machine phases (IV-7). The session controller moves phases, not the LLM."""

    INTRO = "intro"
    SMALL_TALK = "small_talk"
    AGENDA = "agenda"
    CORE = "core"
    CANDIDATE_QUESTIONS = "candidate_questions"
    WRAP_UP = "wrap_up"


class Speaker(StrEnum):
    INTERVIEWER = "interviewer"
    CANDIDATE = "candidate"


class HireSignal(StrEnum):
    """FB-1. Ordered from strongest to weakest."""

    STRONG_HIRE = "Strong Hire"
    HIRE = "Hire"
    LEAN_HIRE = "Lean Hire"
    LEAN_NO_HIRE = "Lean No Hire"
    NO_HIRE = "No Hire"

    @property
    def rank(self) -> int:
        """0 for Strong Hire up to 4 for No Hire. Used for 'within one band' comparisons."""
        return list(HireSignal).index(self)


class Competency(StrEnum):
    """Scored competencies from the spec, grouped by interview type in COMPETENCIES_BY_TYPE."""

    # Behavioral
    OWNERSHIP = "ownership"
    IMPACT = "impact"
    COLLABORATION = "collaboration"
    CONFLICT_HANDLING = "conflict_handling"
    LEARNING_FROM_FAILURE = "learning_from_failure"
    COMMUNICATION = "communication"
    # Hiring manager deep dive
    ROLE_FIT = "role_fit"
    DEPTH_OF_EXPERIENCE = "depth_of_experience"
    JUDGMENT = "judgment"
    MOTIVATION = "motivation"
    TEAM_FIT = "team_fit"
    SCOPE_AT_LEVEL = "scope_at_level"
    # Verbal technical Q&A
    TECHNICAL_DEPTH = "technical_depth"
    ACCURACY = "accuracy"
    REASONING = "reasoning"
    TRADE_OFFS = "trade_offs"
    CLARITY_OF_EXPLANATION = "clarity_of_explanation"
    # Case
    PROBLEM_FRAMING = "problem_framing"
    STRUCTURE = "structure"
    USER_AND_BUSINESS_SENSE = "user_and_business_sense"
    ESTIMATION_LOGIC = "estimation_logic"
    PRIORITIZATION = "prioritization"
    RECOMMENDATION = "recommendation"


COMPETENCIES_BY_TYPE: dict[InterviewType, tuple[Competency, ...]] = {
    InterviewType.BEHAVIORAL: (
        Competency.OWNERSHIP,
        Competency.IMPACT,
        Competency.COLLABORATION,
        Competency.CONFLICT_HANDLING,
        Competency.LEARNING_FROM_FAILURE,
        Competency.COMMUNICATION,
    ),
    InterviewType.HIRING_MANAGER: (
        Competency.ROLE_FIT,
        Competency.DEPTH_OF_EXPERIENCE,
        Competency.JUDGMENT,
        Competency.MOTIVATION,
        Competency.TEAM_FIT,
        Competency.SCOPE_AT_LEVEL,
    ),
    InterviewType.TECHNICAL_QA: (
        Competency.TECHNICAL_DEPTH,
        Competency.ACCURACY,
        Competency.REASONING,
        Competency.TRADE_OFFS,
        Competency.CLARITY_OF_EXPLANATION,
    ),
    InterviewType.CASE: (
        Competency.PROBLEM_FRAMING,
        Competency.STRUCTURE,
        Competency.USER_AND_BUSINESS_SENSE,
        Competency.ESTIMATION_LOGIC,
        Competency.PRIORITIZATION,
        Competency.RECOMMENDATION,
    ),
}


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class GapStatus(StrEnum):
    """State of one gap analysis run (GA-1 to GA-4)."""

    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProfileStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class OrgType(StrEnum):
    PERSONAL = "personal"
    BUSINESS = "business"


class AuthProvider(StrEnum):
    GOOGLE = "google"
    EMAIL = "email"
    DEV = "dev"


class SubscriptionStatus(StrEnum):
    """Mirrors the Stripe subscription statuses we act on."""

    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"


class SessionStatus(StrEnum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    INTERRUPTED = "interrupted"
    SCORING = "scoring"
    COMPLETED = "completed"
    FAILED = "failed"


class UsageComponent(StrEnum):
    STT = "stt"
    LLM = "llm"
    TTS = "tts"
