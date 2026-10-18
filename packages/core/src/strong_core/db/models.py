"""SQLAlchemy 2 models for every entity in the spec's data model section.

Rules:
- Every user-owned table has org_id (B2B tenancy later is a feature flag, not a migration).
- Enums are stored as their string values in VARCHAR columns with CHECK constraints.
- JSON columns hold the matching Pydantic contract from strong_core.schemas.
- Schema changes go through a new Alembic migration in packages/core/migrations/versions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Double,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from strong_core.schemas.enums import (
    AlertAggregation,
    AlertComparator,
    AlertEventKind,
    AlertSeverity,
    AlertState,
    AuthProvider,
    Competency,
    Difficulty,
    ErrorGroupStatus,
    GapStatus,
    GrantKind,
    HireSignal,
    InterviewType,
    Level,
    Mode,
    OrgType,
    Phase,
    ProfileStatus,
    SessionChannel,
    SessionStatus,
    Speaker,
    SubscriptionStatus,
    TriageState,
    UsageComponent,
)

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


def str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _org_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True, nullable=False)


# User-owned tables. A test checks that each one has a non-null org_id column.
USER_OWNED_TABLES = (
    "users",
    "subscriptions",
    "resumes",
    "job_targets",
    "gap_analyses",
    "sessions",
    "turns",
    "scorecards",
    "progress_snapshots",
    "usage_events",
    "company_requests",
    "exit_surveys",
    "interviewer_traces",
    "minute_grants",
    "voice_turn_timings",
)

# Platform tables: no org_id, not owned by one user. A test checks that every table is in
# exactly one of the two lists, so each new table is classified on purpose.
PLATFORM_TABLES = (
    "orgs",
    "companies",
    "company_profiles",
    "stripe_events",
    "audit_logs",
    "admin_users",
    "admin_sessions",
    "error_groups",
    "error_events",
    "ops_samples",
    "alert_rules",
    "alert_events",
    "runtime_settings",
    "company_request_triage",
)


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[OrgType] = mapped_column(str_enum(OrgType, "org_type"), default=OrgType.PERSONAL)
    plan: Mapped[str] = mapped_column(String(50), default="free")
    created_at: Mapped[datetime] = _created_at()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    auth_provider: Mapped[AuthProvider] = mapped_column(str_enum(AuthProvider, "auth_provider"))
    training_consent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="AC-2: off by default"
    )
    created_at: Mapped[datetime] = _created_at()
    last_sign_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Set at each sign-in (admin users page)"
    )
    # AC-4: email and password sign-in. NULL for users who only use a magic link or Google.
    password_hash: Mapped[str | None] = mapped_column(
        String(255), comment="AC-4: Argon2id hash. NULL: no password set"
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="AC-4: when the user proved they own the email. NULL: not confirmed yet",
    )
    # AC-3: profile asked for at the first sign-in. No payment details here.
    full_name: Mapped[str | None] = mapped_column(String(120), comment="AC-3")
    current_title: Mapped[str | None] = mapped_column(String(120), comment="AC-3: optional")
    years_experience: Mapped[int | None] = mapped_column(Integer, comment="AC-3: 0 to 50")
    target_level: Mapped[Level | None] = mapped_column(
        str_enum(Level, "target_level"), comment="AC-3: default level for new sessions"
    )
    country: Mapped[str | None] = mapped_column(String(100), comment="AC-3: optional")
    time_zone: Mapped[str | None] = mapped_column(String(64), comment="AC-3: IANA name, optional")
    linkedin_url: Mapped[str | None] = mapped_column(String(300), comment="AC-3: optional")
    profile_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="AC-3: NULL until the user saves the profile once"
    )
    # AU-7 and AU-8: admin support actions.
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="AU-7: requests get 403 while set. NULL: active"
    )
    suspended_reason: Mapped[str | None] = mapped_column(
        Text, comment="AU-7: the admin's reason, shown in the admin app only"
    )
    session_epoch: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="AU-8: carried in the session cookie; bumping it signs the user out everywhere",
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(100), comment="The current Stripe subscription. A new one replaces a canceled one."
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        str_enum(SubscriptionStatus, "subscription_status")
    )
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    minutes_cap: Mapped[int] = mapped_column(Integer, default=0)
    minutes_used: Mapped[int] = mapped_column(Integer, default=0)
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="Canceled; ends at period_end"
    )
    created_at: Mapped[datetime] = _created_at()


class StripeEvent(Base):
    """Stripe webhook events already handled (BL-1). The primary key makes handling idempotent.

    Only the id and type are kept: the payload holds personal data such as the email.
    """

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(100), primary_key=True, comment="Stripe event id")
    type: Mapped[str] = mapped_column(String(100))
    received_at: Mapped[datetime] = _created_at()


class ExitSurvey(Base):
    """Answers to the cancellation exit survey: why the user leaves, and did they get the job."""

    __tablename__ = "exit_surveys"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(String(50))
    reason_detail: Mapped[str | None] = mapped_column(Text)
    got_job: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = _created_at()


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    parsed_json: Mapped[dict[str, Any] | None] = mapped_column(comment="schemas.Resume")
    file_ref: Mapped[str | None] = mapped_column(
        String(500), comment="Object storage key of the encrypted original file"
    )
    name: Mapped[str | None] = mapped_column(
        String(120), comment="R1: name in the CV library. NULL after delete"
    )
    content_hash: Mapped[str | None] = mapped_column(
        String(64), index=True, comment="R1: SHA-256 of the uploaded file or pasted text"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="R1: soft delete. Content is cleared; gap reports that used it stay",
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="When the user checked and saved the extracted CV. NULL: not confirmed",
    )
    uploaded_at: Mapped[datetime] = _created_at()


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class CompanyProfile(Base):
    __tablename__ = "company_profiles"
    __table_args__ = (
        UniqueConstraint("company_id", "version"),
        # At most one Published version per company (AD-1). Publish archives the old one first.
        Index(
            "uq_company_profiles_one_published",
            "company_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
            sqlite_where=text("status = 'published'"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[ProfileStatus] = mapped_column(str_enum(ProfileStatus, "profile_status"))
    profile_json: Mapped[dict[str, Any]] = mapped_column(comment="schemas.CompanyProfile")
    sources_json: Mapped[list[Any]] = mapped_column(comment="schemas.Source list")
    reviewed_by: Mapped[str | None] = mapped_column(String(200))
    imported_at: Mapped[datetime] = _created_at()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobTarget(Base):
    __tablename__ = "job_targets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), comment="NULL means generic mode"
    )
    source_url: Mapped[str | None] = mapped_column(String(2000))
    raw_text: Mapped[str | None] = mapped_column(Text)
    parsed_json: Mapped[dict[str, Any] | None] = mapped_column(comment="schemas.JobPosting")
    level: Mapped[Level | None] = mapped_column(str_enum(Level, "level"))
    stage: Mapped[str | None] = mapped_column(String(100))
    context_notes: Mapped[str | None] = mapped_column(Text, comment="IN-4 optional context")
    name: Mapped[str | None] = mapped_column(
        String(120), comment="R1: name in the job library. NULL means the default name"
    )
    text_hash: Mapped[str | None] = mapped_column(
        String(64), index=True, comment="R1: SHA-256 of the normalized posting text"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="R1: soft delete. Content is cleared; reports, sessions and progress stay",
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="LB-2: hidden from pickers but kept, for a job that has reports. NULL: active",
    )
    created_at: Mapped[datetime] = _created_at()


class GapAnalysis(Base):
    __tablename__ = "gap_analyses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    # R1: job targets and resumes are soft deleted, so these keys do not cascade.
    job_target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_targets.id"), index=True)
    resume_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resumes.id"), index=True)
    status: Mapped[GapStatus] = mapped_column(
        str_enum(GapStatus, "gap_status"), default=GapStatus.READY, server_default="ready"
    )
    error: Mapped[str | None] = mapped_column(Text, comment="Plain reason when status is failed")
    input_hash: Mapped[str | None] = mapped_column(
        String(64), comment="Hash of the posting, resume and profile version it was built from"
    )
    profile_version: Mapped[int | None] = mapped_column(Integer, comment="NULL in generic mode")
    match_score: Mapped[int | None] = mapped_column(Integer, comment="NULL until ready")
    breakdown_json: Mapped[dict[str, Any] | None] = mapped_column(comment="schemas.GapAnalysis")
    session_plan_json: Mapped[list[Any] | None] = mapped_column(
        comment="schemas.PlannedSession list"
    )
    model_version: Mapped[str | None] = mapped_column(
        String(200), comment="Gateway alias + prompt ref"
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InterviewSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    job_target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_targets.id"), index=True)
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resumes.id"),
        index=True,
        comment="PR-3: the CV of the job's latest gap analysis when the session was created",
    )
    type: Mapped[InterviewType] = mapped_column(str_enum(InterviewType, "interview_type"))
    difficulty: Mapped[Difficulty] = mapped_column(str_enum(Difficulty, "difficulty"))
    mode: Mapped[Mode] = mapped_column(str_enum(Mode, "mode"))
    duration_min: Mapped[int] = mapped_column(Integer)
    channel: Mapped[SessionChannel] = mapped_column(
        str_enum(SessionChannel, "session_channel"),
        default=SessionChannel.VOICE,
        server_default="voice",
        comment="PL-7: voice, or text behind a dev flag",
    )
    profile_version: Mapped[int | None] = mapped_column(Integer, comment="NULL in generic mode")
    brief_json: Mapped[dict[str, Any] | None] = mapped_column(comment="schemas.InterviewerBrief")
    model_profile: Mapped[str | None] = mapped_column(
        String(20), comment="PL-6: MODEL_PROFILE the session ran on"
    )
    interviewer_model_id: Mapped[str | None] = mapped_column(
        String(200), comment="PL-6: gateway alias that served the interviewer role"
    )
    prompt_version: Mapped[str | None] = mapped_column(
        String(200), comment="PL-6: interviewer prompt refs, comma separated"
    )
    status: Mapped[SessionStatus] = mapped_column(
        str_enum(SessionStatus, "session_status"), default=SessionStatus.CREATED
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    minutes_billed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created_at()


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (Index("ix_turns_session_start", "session_id", "start_ms"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    speaker: Mapped[Speaker] = mapped_column(str_enum(Speaker, "speaker"))
    phase: Mapped[Phase] = mapped_column(str_enum(Phase, "phase"))
    text: Mapped[str] = mapped_column(Text)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    question_ref: Mapped[str | None] = mapped_column(String(100))
    seq: Mapped[int | None] = mapped_column(
        Integer, comment="Order of the turn in its session, from 1 (strong_core.db.turns)"
    )


TRACE_RETENTION_DAYS = 90  # a worker cron job deletes older interviewer traces (R2)
OPS_SAMPLE_RETENTION_DAYS = 30  # OB-5: older ops_samples rows are deleted daily
ERROR_EVENT_RETENTION_DAYS = 30  # OB-4: older error_events rows go; error_groups stay
VOICE_TIMING_RETENTION_DAYS = 90  # OB-3: like traces


class InterviewerTrace(Base):
    """One interviewer model call (or fixed line) in a session, with the controller's reason.

    For the admin review of test interviews. Shown only when the user has training_consent on.
    A worker cron job deletes rows older than 90 days; the turns stay.
    """

    __tablename__ = "interviewer_traces"
    __table_args__ = (Index("ix_interviewer_traces_session_seq", "session_id", "seq"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer, comment="Order of the call in the session")
    turn_index: Mapped[int] = mapped_column(Integer, comment="Transcript length at the call")
    call: Mapped[str] = mapped_column(String(20), comment="say, decide, line or rollback")
    move: Mapped[str] = mapped_column(String(40), comment="Controller move or fixed line name")
    reason_json: Mapped[dict[str, Any] | None] = mapped_column(
        comment="Why: the ProbeDecision and the controller's reason"
    )
    phase: Mapped[Phase] = mapped_column(str_enum(Phase, "phase"))
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    phase_deadline_ms: Mapped[int | None] = mapped_column(Integer)
    question_ref: Mapped[str | None] = mapped_column(String(100))
    messages_json: Mapped[list[Any] | None] = mapped_column(comment="Prompt messages sent")
    raw_reply: Mapped[str | None] = mapped_column(Text)
    spoken_text: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(200), comment="Gateway alias")
    prompt_refs: Mapped[str | None] = mapped_column(String(500))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), comment="From the LiteLLM config prices; NULL when unknown"
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class Scorecard(Base):
    __tablename__ = "scorecards"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), unique=True
    )
    hire_signal: Mapped[HireSignal] = mapped_column(str_enum(HireSignal, "hire_signal"))
    rationale: Mapped[str] = mapped_column(Text)
    competency_scores_json: Mapped[list[Any]] = mapped_column(comment="schemas.CompetencyScore")
    value_scores_json: Mapped[list[Any]] = mapped_column(
        server_default="[]", comment="schemas.ValueScore list; empty in generic mode"
    )
    per_question_json: Mapped[list[Any]] = mapped_column(comment="schemas.QuestionScore list")
    scorer_model: Mapped[str] = mapped_column(String(200))
    rubric_version: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created_at()


class ProgressSnapshot(Base):
    __tablename__ = "progress_snapshots"
    __table_args__ = (Index("ix_progress_job_competency", "job_target_id", "competency", "at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    job_target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_targets.id"))
    competency: Mapped[Competency] = mapped_column(str_enum(Competency, "competency"))
    score: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    component: Mapped[UsageComponent] = mapped_column(str_enum(UsageComponent, "usage_component"))
    units: Mapped[Decimal] = mapped_column(Numeric(14, 4), comment="Tokens, seconds or characters")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    role: Mapped[str | None] = mapped_column(
        String(32),
        comment="OB-2: gateway role (strong_core.gateway.Role value). NULL: written before OB-2",
    )
    cost_known: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        comment="OB-2, D-12: false when the model has no price in config (cost_usd is then 0)",
    )
    created_at: Mapped[datetime] = _created_at()


class CompanyRequest(Base):
    """Every company name a user enters at job setup (IN-5), matched or not.

    Rows with matched_company_id NULL are requests for companies outside the curated list. Count
    them by normalized_name to choose the next profiles to research.
    """

    __tablename__ = "company_requests"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    job_target_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_targets.id", ondelete="SET NULL")
    )
    company_name: Mapped[str] = mapped_column(
        String(200), comment="As the user or posting wrote it"
    )
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    matched_company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), comment="NULL means not curated"
    )
    source_host: Mapped[str | None] = mapped_column(
        String(200), comment="Host of the posting URL, without www."
    )
    created_at: Mapped[datetime] = _created_at()


class AuditLog(Base):
    """Deletes, exports, consent changes, profile approvals. Kept after account deletion."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        index=True, comment="No FK: rows must survive org deletion"
    )
    actor: Mapped[str] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(100))
    entity: Mapped[str] = mapped_column(String(200))
    details_json: Mapped[dict[str, Any] | None] = mapped_column()
    at: Mapped[datetime] = _created_at()


# --- Admin app (docs/admin-spec.md, "Data model changes") ------------------------------------


class AdminUser(Base):
    """AA-1: who may use the admin app. Seeded once from ADMIN_EMAILS when the table is empty."""

    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, comment="Stored lower case")
    added_by: Mapped[str | None] = mapped_column(
        String(320), comment="Admin email, 'ADMIN_EMAILS' for the seed, or 'strongctl'"
    )
    added_at: Mapped[datetime] = _created_at()
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Removed admin. NULL: active"
    )


class AdminSession(Base):
    """AA-3: a server-side admin session. The sh_admin cookie holds a random token; the row
    stores only its SHA-256, so a database leak does not leak live sessions."""

    __tablename__ = "admin_sessions"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, comment="SHA-256 hex of the sh_admin cookie token"
    )
    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = _created_at()
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="AA-3: idle timeout 2 h from here"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="AA-3: absolute timeout, created_at + 12 h"
    )
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Sign-out or AA-8 revoke. NULL: live"
    )


class MinuteGrant(Base):
    """AU-3..AU-5: support grants on top of the plan. Never written into subscriptions.

    Removing a grant sets revoked_at; rows are not deleted, so the ledger keeps the history.
    """

    __tablename__ = "minute_grants"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[GrantKind] = mapped_column(str_enum(GrantKind, "grant_kind"))
    amount: Mapped[int] = mapped_column(
        Integer,
        comment="minutes: minutes (negative removes); free_interviews: count; "
        "comp_plan: the minutes cap of the comp",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="NULL: does not expire. Required for comp_plan"
    )
    reason: Mapped[str] = mapped_column(Text, comment="AA-6: the reason the admin gave")
    granted_by: Mapped[str] = mapped_column(String(320), comment="Admin email")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(String(320), comment="Admin email")
    created_at: Mapped[datetime] = _created_at()


class VoiceTurnTiming(Base):
    """OB-3: latency of one voice turn, by component. Deleted after 90 days, like traces."""

    __tablename__ = "voice_turn_timings"
    __table_args__ = (Index("ix_voice_turn_timings_session_turn", "session_id", "turn_index"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    turn_index: Mapped[int] = mapped_column(Integer, comment="Order of the turn in the session")
    e2e_ms: Mapped[int | None] = mapped_column(
        Integer, comment="End of candidate speech to first interviewer audio"
    )
    turn_detection_ms: Mapped[int | None] = mapped_column(Integer)
    stt_ms: Mapped[int | None] = mapped_column(Integer)
    llm_ttft_ms: Mapped[int | None] = mapped_column(Integer, comment="LLM time to first token")
    tts_ttfb_ms: Mapped[int | None] = mapped_column(Integer, comment="TTS time to first byte")
    other_ms: Mapped[int | None] = mapped_column(Integer, comment="e2e minus the parts above")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class ErrorGroup(Base):
    """OB-4: errors grouped by fingerprint. Groups are kept; their events go after 30 days."""

    __tablename__ = "error_groups"

    id: Mapped[uuid.UUID] = _uuid_pk()
    fingerprint: Mapped[str] = mapped_column(
        String(64), unique=True, comment="Hash of exception type + top in-app frames"
    )
    service: Mapped[str] = mapped_column(String(20), comment="api, worker or voice")
    exception_type: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, comment="PII scrubbed before writing")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[ErrorGroupStatus] = mapped_column(
        str_enum(ErrorGroupStatus, "error_group_status"),
        default=ErrorGroupStatus.OPEN,
        server_default="open",
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(320), comment="Admin email")
    sample_stack: Mapped[str | None] = mapped_column(Text, comment="One scrubbed stack trace")
    release: Mapped[str | None] = mapped_column(String(100), comment="Latest release seen")


class ErrorEvent(Base):
    """OB-4: one occurrence of an error group. Deleted after 30 days."""

    __tablename__ = "error_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("error_groups.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    service: Mapped[str] = mapped_column(String(20))
    release: Mapped[str | None] = mapped_column(String(100))
    request_id: Mapped[str | None] = mapped_column(String(64))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        comment="Interview session, if any. No FK: errors outlive deleted sessions"
    )


class OpsSample(Base):
    """OB-5: one metric value from the sampler cron (every minute). Deleted after 30 days."""

    __tablename__ = "ops_samples"
    __table_args__ = (Index("ix_ops_samples_metric_ts", "metric", "ts"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metric: Mapped[str] = mapped_column(String(100), comment="For example probe.postgres.ok")
    value: Mapped[float] = mapped_column(Double)
    labels_json: Mapped[dict[str, Any] | None] = mapped_column(
        comment="Small string map, for example {'service': 'api'}"
    )


class AlertRule(Base):
    """AL-1: a threshold rule the alert cron checks every minute (AL-2)."""

    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(100), unique=True)
    metric: Mapped[str] = mapped_column(
        String(100), comment="An ops_samples metric or a domain metric the engine knows"
    )
    labels_json: Mapped[dict[str, Any] | None] = mapped_column(
        comment="Only samples with these labels count. NULL: all"
    )
    aggregation: Mapped[AlertAggregation] = mapped_column(
        str_enum(AlertAggregation, "alert_aggregation")
    )
    window_s: Mapped[int] = mapped_column(Integer, comment="Samples from the last window_s count")
    comparator: Mapped[AlertComparator] = mapped_column(
        str_enum(AlertComparator, "alert_comparator")
    )
    threshold: Mapped[float] = mapped_column(Double)
    min_samples: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", comment="Fewer samples: the rule stays as it is"
    )
    for_s: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="Pending this long before firing"
    )
    severity: Mapped[AlertSeverity] = mapped_column(str_enum(AlertSeverity, "alert_severity"))
    renotify_s: Mapped[int | None] = mapped_column(
        Integer, comment="Re-send while firing. NULL: never (AL-3)"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    muted_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="No email until then; state still changes"
    )
    state: Mapped[AlertState] = mapped_column(
        str_enum(AlertState, "alert_state"), default=AlertState.OK, server_default="ok"
    )
    state_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_value: Mapped[float | None] = mapped_column(Double, comment="At the last evaluation")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertEvent(Base):
    """AL-4: alert history. A row with notified false is retried on the next tick (AL-5)."""

    __tablename__ = "alert_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[AlertEventKind] = mapped_column(str_enum(AlertEventKind, "alert_event_kind"))
    value: Mapped[float | None] = mapped_column(Double)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    notified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    notify_error: Mapped[str | None] = mapped_column(Text, comment="Last send failure")


class RuntimeSetting(Base):
    """OC: one ops control. Read through strong_core.runtime_settings (10 s cache)."""

    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_json: Mapped[Any] = mapped_column(
        JSONB, nullable=True, comment="Validated by strong_core.runtime_settings"
    )
    updated_by: Mapped[str] = mapped_column(String(320), comment="Admin email")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CompanyRequestTriage(Base):
    """AT-5: admin triage of a requested company name. company_requests rows are not edited."""

    __tablename__ = "company_request_triage"

    normalized_name: Mapped[str] = mapped_column(
        String(200), primary_key=True, comment="company_requests.normalized_name"
    )
    state: Mapped[TriageState] = mapped_column(
        str_enum(TriageState, "triage_state"), default=TriageState.NEW, server_default="new"
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), comment="Set when state is added"
    )
    note: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(String(320), comment="Admin email")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
