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
    """The four v1 interview types (IV-2), plus Custom (CU-1) and Recruiter screen (RS-1).

    A Custom session mixes 1 to 3 of the four standard types as question categories
    (`SessionConfig.custom`). Custom is never a question category itself and has no entry in
    COMPETENCIES_BY_TYPE; use `session_competencies(config)` for a session's competency pool.
    """

    BEHAVIORAL = "behavioral"
    HIRING_MANAGER = "hiring_manager"
    TECHNICAL_QA = "technical_qa"
    CASE = "case"
    CUSTOM = "custom"
    RECRUITER_SCREEN = "recruiter_screen"


STANDARD_INTERVIEW_TYPES: tuple[InterviewType, ...] = (
    InterviewType.BEHAVIORAL,
    InterviewType.HIRING_MANAGER,
    InterviewType.TECHNICAL_QA,
    InterviewType.CASE,
)
"""The types that are also question categories in a Custom session (CU-1). Recruiter screen
(RS-1) is not one: it has its own brief, questions and rubric (RS-2)."""


class QuestionSource(StrEnum):
    """Who wrote a brief question: the planner, or the candidate in a Custom session (CU-3)."""

    PLANNER = "planner"
    CANDIDATE = "candidate"


class QuestionRefusal(StrEnum):
    """CU-5: why a candidate's own question or focus chip is refused."""

    NOT_A_QUESTION = "not_a_question"
    INAPPROPRIATE = "inappropriate"  # abuse, harassment, threats, hate or sexual content (IV-12)
    INSTRUCTIONS = "instructions"  # text that tries to instruct the interviewer


class Difficulty(StrEnum):
    """IV-4."""

    FRIENDLY = "friendly"
    REALISTIC = "realistic"
    TOUGH = "tough"


class Mode(StrEnum):
    """IV-8. Only Realistic sessions count toward progress trends (PR-1)."""

    COACH = "coach"
    REALISTIC = "realistic"


class Tone(StrEnum):
    """TN-1: how the interviewer sounds. `as_company` uses the company profile's persona tone,
    or a neutral tone in generic mode. Old sessions read as `as_company`."""

    AS_COMPANY = "as_company"
    WARM = "warm"
    NEUTRAL = "neutral"
    DIRECT = "direct"


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
    # Recruiter screen (RS-1); it also scores motivation, role fit and communication
    LOGISTICS_AND_EXPECTATIONS = "logistics_and_expectations"


# The four standard types and Recruiter screen. Custom sessions take the union over their
# categories.
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
    InterviewType.RECRUITER_SCREEN: (
        Competency.MOTIVATION,
        Competency.ROLE_FIT,
        Competency.COMMUNICATION,
        Competency.LOGISTICS_AND_EXPECTATIONS,
    ),
}


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class StoryPart(StrEnum):
    """ST-1: the five parts of a story, in the order the workbench and prompts show them."""

    CONTEXT = "context"
    STAKES = "stakes"
    ACTION = "action"
    RESULT = "result"
    REFLECTION = "reflection"


class StoryStatus(StrEnum):
    """ST-1, ST-7: a story is a draft until a Realistic answer that used it scores 3 or more."""

    DRAFT = "draft"
    PROVEN = "proven"


class StorySource(StrEnum):
    """ST-1: where a story came from."""

    DEBRIEF_ANSWER = "debrief_answer"  # ST-2: "Save as a story" on a debrief answer
    MANUAL = "manual"
    COACH = "coach"


class StoryFitStrength(StrEnum):
    """ST-5: how well the best story covers one skill the interview will test."""

    STRONG = "strong"
    THIN = "thin"
    MISSING = "missing"


class CoachStyle(StrEnum):
    """CO-5: how the coach talks, picked by the candidate."""

    GENTLE = "gentle"
    DIRECT = "direct"


class CoachSessionStatus(StrEnum):
    """CO-2: state of one coach session."""

    ACTIVE = "active"
    ENDED = "ended"
    FAILED = "failed"


class CoachSpeaker(StrEnum):
    """CO-2: who said a coach turn."""

    COACH = "coach"
    CANDIDATE = "candidate"


class ReadinessStatus(StrEnum):
    """RD-1: whether a skill has enough Realistic sessions for a readiness score."""

    SCORED = "scored"
    NOT_ENOUGH_DATA = "not_enough_data"


class PlanStyle(StrEnum):
    """PS-2: how the personal plan is shown. NULL on the user until chosen in onboarding."""

    WEEKLY = "weekly"
    CHECKLIST = "checklist"


class PlanItemKind(StrEnum):
    """PS-1: the three kinds of personal plan items, each with its own chip."""

    REHEARSAL = "rehearsal"
    STORY = "story"
    RESUME = "resume"


class PlanItemStatus(StrEnum):
    """PS-1: done is computed from the user's data, never ticked by hand."""

    DONE = "done"
    NEXT = "next"
    TODO = "todo"


class SuggestionKind(StrEnum):
    """SG-1: what a suggestion from Strova proposes (ux-spec section 8)."""

    TUNE_STORY = "tune_story"
    NEW_STORY = "new_story"
    MISSING_SKILL = "missing_skill"
    TAILOR_ROLE = "tailor_role"
    IMPROVE_RESUME_LINE = "improve_resume_line"
    STORY_IDEA = "story_idea"
    REVIEW = "review"


class SuggestionStatus(StrEnum):
    """SG-1, SG-8: a suggestion is open until accepted or dismissed. Dismissed ones never return."""

    OPEN = "open"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


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


class AutoProfileStatus(StrEnum):
    """AP-1, AP-3: review state of an auto-generated company profile. A pending one is already
    used in briefs, labeled "auto-generated"; an admin approves or retires it."""

    PENDING = "pending"
    APPROVED = "approved"
    RETIRED = "retired"


class OrgType(StrEnum):
    PERSONAL = "personal"
    BUSINESS = "business"


class AuthProvider(StrEnum):
    GOOGLE = "google"
    EMAIL = "email"
    PASSWORD = "password"
    DEV = "dev"


class SubscriptionStatus(StrEnum):
    """Mirrors the Stripe subscription statuses we act on."""

    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"


class ProbeTrigger(StrEnum):
    """IV-3 follow-up rules: what an answer lacks, so the interviewer probes."""

    OWN_ROLE = "own_role"
    MEASURABLE_RESULT = "measurable_result"
    CONCRETE_EXAMPLE = "concrete_example"
    TRADEOFF_REASONING = "tradeoff_reasoning"
    OFF_TOPIC = "off_topic"


class AnswerConduct(StrEnum):
    """IV-12: whether a candidate turn belongs in the interview.

    `off_scope` is not a weak or off-topic answer (IV-3 probes those). It is a turn about
    something outside the interview, such as an unrelated subject or a request for an unrelated
    task. `inappropriate` is abuse, harassment, threats, hate or sexual content.
    """

    OK = "ok"
    OFF_SCOPE = "off_scope"
    INAPPROPRIATE = "inappropriate"


class DocumentKind(StrEnum):
    """IN-6, IN-7: what kind of document a job description or CV input looks like."""

    JOB_POSTING = "job_posting"
    JOB_LIST = "job_list"  # a careers page or search results with many jobs
    RESUME = "resume"
    COVER_LETTER = "cover_letter"
    COMPANY_PAGE = "company_page"
    ARTICLE = "article"
    ERROR_PAGE = "error_page"  # a sign-in page, an error or an empty page
    OTHER = "other"


class SessionChannel(StrEnum):
    """PL-7. How the candidate and the interviewer talk. Text runs the same controller and
    interviewer logic with typed input. It is a dev flag; the simulated-candidate tests use it."""

    VOICE = "voice"
    TEXT = "text"


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


# --- Admin app (docs/admin-spec.md). Stored in the database only; no contract uses them. ---


class GrantKind(StrEnum):
    """AU-3..AU-5: what a minute_grants row gives the user. L01: top_up is a paid top-up."""

    MINUTES = "minutes"
    FREE_INTERVIEWS = "free_interviews"
    COMP_PLAN = "comp_plan"
    TOP_UP = "top_up"


class SimRunStatus(StrEnum):
    """SM-4: an admin-started AI candidate run (docs/admin-spec.md, Simulations)."""

    QUEUED = "queued"
    WAITING = "waiting"  # SM-3: too many real sessions live; checked again every 60 s
    STARTING = "starting"
    INTERVIEWING = "interviewing"
    JUDGING = "judging"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def finished(self) -> bool:
        return self in (SimRunStatus.DONE, SimRunStatus.FAILED, SimRunStatus.CANCELLED)


class ErrorGroupStatus(StrEnum):
    """OB-12: a resolved group that happens again reopens."""

    OPEN = "open"
    RESOLVED = "resolved"


class AlertAggregation(StrEnum):
    """AL-1: how an alert rule reduces the samples in its window to one value."""

    LAST = "last"
    AVG = "avg"
    P95 = "p95"
    RATE = "rate"
    COUNT = "count"


class AlertComparator(StrEnum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"


class AlertSeverity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"


class AlertState(StrEnum):
    """AL-2: ok -> pending -> firing -> ok."""

    OK = "ok"
    PENDING = "pending"
    FIRING = "firing"


class AlertEventKind(StrEnum):
    """AL-4, AL-6."""

    FIRED = "fired"
    RESOLVED = "resolved"
    TEST = "test"


class TriageState(StrEnum):
    """AT-5: admin triage of a requested company name."""

    NEW = "new"
    PLANNED = "planned"
    DECLINED = "declined"
    ADDED = "added"


class InterviewWithin(StrEnum):
    """L04 waitlist: when the person's real interview is, as they told us."""

    TWO_WEEKS = "two_weeks"
    MONTH = "month"
    LATER = "later"
    NOT_YET = "not_yet"


class PlanCode(StrEnum):
    """L01, L03: the paid plan a subscription is on."""

    MONTHLY = "monthly"
    JOB_HUNT_3M = "job_hunt_3m"


class EmailKind(StrEnum):
    """L01, L06: the lifecycle emails. EmailLog keeps one row per user, kind and ref."""

    WELCOME = "welcome"
    FINISH_SETUP = "finish_setup"
    FREE_INTERVIEW_NUDGE = "free_interview_nudge"
    DEBRIEF_READY = "debrief_ready"
    PAYWALL_FOLLOWUP = "paywall_followup"
    INTERVIEW_COUNTDOWN_7 = "interview_countdown_7"
    INTERVIEW_COUNTDOWN_2 = "interview_countdown_2"
    INTERVIEW_DAY = "interview_day"
    AFTER_INTERVIEW = "after_interview"
    MINUTES_LOW = "minutes_low"
    WINBACK = "winback"
    PLAN_REMINDER = "plan_reminder"  # PS-6: Strova's weekly-plan reminder, at most one a day
