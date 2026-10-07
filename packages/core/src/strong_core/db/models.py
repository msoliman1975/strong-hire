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
    Boolean,
    DateTime,
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
    AuthProvider,
    Competency,
    Difficulty,
    GapStatus,
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
    created_at: Mapped[datetime] = _created_at()


class GapAnalysis(Base):
    __tablename__ = "gap_analyses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    job_target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_targets.id", ondelete="CASCADE"), index=True
    )
    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True
    )
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
    job_target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_targets.id", ondelete="CASCADE"), index=True
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
    job_target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_targets.id", ondelete="CASCADE")
    )
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
