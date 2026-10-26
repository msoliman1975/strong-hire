"""Response and request bodies for Users and support (AU-1..AU-10, docs/admin-spec.md).

D-8 / AA-11: nothing here carries resume or gap analysis content. Resumes and gap analyses are
metadata only (dates, status, an error flag); a test walks the OpenAPI document to check it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from strong_api.admin.actions import ActionIn
from strong_api.admin.schemas import AdminAuditEntry, AdminSession
from strong_core.schemas import AuthProvider, GapStatus, Level, OrgType, SubscriptionStatus
from strong_core.schemas.enums import GrantKind

UserStatus = Literal["active", "suspended"]
PlanName = Literal["free", "paid"]
StripeMode = Literal["test", "live"]


class AdminUser(BaseModel):
    """One row of the Users list (AU-1)."""

    id: uuid.UUID
    email: str
    full_name: str | None
    auth_provider: AuthProvider
    created_at: datetime
    last_sign_in_at: datetime | None
    plan: PlanName = Field(description="paid: an active subscription or an active comp grant.")
    subscription_status: SubscriptionStatus | None
    comp_until: datetime | None = Field(description="Set while a comp plan grant is active.")
    minutes_used: int
    minutes_cap: int = Field(description="Plan cap plus active minute grants. 0 on free.")
    minutes_left: int
    free_interviews_left: int
    training_consent: bool
    interviews: int
    is_admin: bool
    status: UserStatus
    suspended_at: datetime | None


class AdminUserPage(BaseModel):
    users: list[AdminUser]
    total: int = Field(description="Users that match the filters, on all pages.")
    page: int
    page_size: int


class AdminUserProfile(BaseModel):
    """The AC-3 profile. No resume data."""

    full_name: str | None
    current_title: str | None
    years_experience: int | None
    target_level: Level | None
    country: str | None
    time_zone: str | None
    linkedin_url: str | None
    profile_completed_at: datetime | None
    email_verified_at: datetime | None
    has_password: bool


class AdminOrg(BaseModel):
    id: uuid.UUID
    name: str
    type: OrgType
    plan: str
    created_at: datetime


class AdminSubscription(BaseModel):
    status: SubscriptionStatus
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    stripe_customer_url: str | None = Field(
        description="The customer in the Stripe dashboard (refunds are made there, D-7)."
    )
    stripe_mode: StripeMode | None = Field(description="From the API's Stripe key prefix.")
    period_start: datetime | None
    period_end: datetime | None
    minutes_cap: int
    minutes_used: int
    cancel_at_period_end: bool
    created_at: datetime


class AdminEntitlement(BaseModel):
    plan: PlanName
    minutes_used: int
    plan_minutes_cap: int = Field(description="From the subscription or the comp plan.")
    minutes_granted: int = Field(description="Active minute grants (0 on the free plan).")
    minutes_cap: int
    minutes_left: int
    free_interviews_total: int
    free_interviews_granted: int
    free_interviews_used: int
    free_interviews_left: int
    comp_until: datetime | None
    block_code: str | None


class AdminGrant(BaseModel):
    id: uuid.UUID
    kind: GrantKind
    amount: int
    expires_at: datetime | None
    reason: str
    granted_by: str
    created_at: datetime
    revoked_at: datetime | None
    revoked_by: str | None
    active: bool = Field(description="Not revoked and not expired.")


class AdminJobTarget(BaseModel):
    """Company, title and level only (AU-2). No posting text."""

    id: uuid.UUID
    company: str | None
    title: str | None
    level: Level | None
    created_at: datetime
    archived_at: datetime | None
    deleted_at: datetime | None


class AdminResumeMeta(BaseModel):
    """D-8: metadata only. Never the file, the text or the extracted fields."""

    id: uuid.UUID
    uploaded_at: datetime
    confirmed_at: datetime | None
    deleted_at: datetime | None
    status: Literal["reading", "to_confirm", "confirmed", "deleted"]


class AdminGapMeta(BaseModel):
    """D-8: metadata only. Never the findings, the scores or the brief."""

    id: uuid.UUID
    job_target_id: uuid.UUID
    resume_id: uuid.UUID
    status: GapStatus
    has_error: bool
    created_at: datetime
    updated_at: datetime | None


class AdminRefund(BaseModel):
    """AU-6: a refund made in the Stripe dashboard, from the charge.refunded webhook."""

    at: datetime
    charge_id: str | None
    amount_refunded: int | None = Field(description="In the currency's smallest unit (cents).")
    currency: str | None
    livemode: bool


class AdminUserDetail(BaseModel):
    """AU-2: everything support needs about one user."""

    user: AdminUser
    profile: AdminUserProfile
    org: AdminOrg | None
    suspended_reason: str | None
    session_epoch: int
    subscription: AdminSubscription | None
    entitlement: AdminEntitlement
    grants: list[AdminGrant]
    sessions: list[AdminSession]
    job_targets: list[AdminJobTarget]
    resume_count: int
    resumes: list[AdminResumeMeta]
    gap_analysis_count: int
    gap_analyses: list[AdminGapMeta]
    cost_to_date_usd: float = Field(description="All model usage of the account (usage_events).")
    cost_unknown_events: int = Field(description="Usage rows with no known price (D-12).")
    refunds: list[AdminRefund]
    privacy_actions: list[AdminAuditEntry] = Field(
        description="AU-10: the user's own exports and deletes. Admins see them, never run them."
    )
    audit: list[AdminAuditEntry] = Field(description="Audit entries about this user, newest first.")


# ---------------------------------------------------------------- actions (AA-5, AA-6)

MAX_MINUTES = 10_000
MAX_FREE_INTERVIEWS = 100


class GrantIn(ActionIn):
    """AU-3 minutes (negative removes), AU-4 free interviews, AU-5 comp plan (cap + end date)."""

    kind: GrantKind
    amount: int = Field(description="Minutes, free interviews, or the comp plan's minute cap.")
    expires_at: datetime | None = Field(default=None, description="Required for comp_plan.")

    @model_validator(mode="after")
    def _check(self) -> GrantIn:
        if self.kind == GrantKind.TOP_UP:
            raise ValueError("top-ups come from a Stripe purchase, not an admin grant")
        if self.kind == GrantKind.MINUTES:
            if self.amount == 0 or abs(self.amount) > MAX_MINUTES:
                raise ValueError(f"amount must be between -{MAX_MINUTES} and {MAX_MINUTES}, not 0")
        elif self.kind == GrantKind.FREE_INTERVIEWS:
            if not 1 <= self.amount <= MAX_FREE_INTERVIEWS:
                raise ValueError(f"amount must be between 1 and {MAX_FREE_INTERVIEWS}")
        else:
            if not 1 <= self.amount <= MAX_MINUTES:
                raise ValueError(f"the comp plan's minute cap must be 1 to {MAX_MINUTES}")
            if self.expires_at is None:
                raise ValueError("a comp plan needs an end date (expires_at)")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expires_at needs a time zone")
        return self


class AdminActionOut(BaseModel):
    action: str
    user_id: uuid.UUID
    details: dict[str, Any] = Field(default_factory=dict)
