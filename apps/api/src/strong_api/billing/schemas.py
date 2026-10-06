"""Request and response bodies for the billing endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from strong_core.schemas import SubscriptionStatus


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanOut(BaseModel):
    """The one paid plan. Every number comes from the API config."""

    name: str
    price_usd_month: float
    minutes_cap: int = Field(description="Interview minutes per billing period.")
    free_interviews: int = Field(description="BL-2: interviews on the free plan.")
    billing_enabled: bool = Field(description="False until Stripe keys are set.")


class UsageOut(BaseModel):
    """BL-1 usage meter and BL-2 free interview, as the API counts them."""

    plan: Literal["free", "paid"]
    status: SubscriptionStatus | None = Field(description="Stripe status; null if never paid.")
    minutes_used: int
    minutes_cap: int = Field(description="0 on the free plan.")
    minutes_left: int
    period_start: datetime | None
    period_end: datetime | None
    cancel_at_period_end: bool
    free_interviews_total: int
    free_interviews_left: int
    can_start_session: bool
    block_code: Literal["upgrade_required", "minutes_exhausted"] | None = Field(
        description="Why a new session is blocked. Null when it is allowed."
    )
    has_billing_account: bool = Field(description="True when the Customer Portal can open.")


class RedirectOut(BaseModel):
    url: str


class PortalRequest(_Body):
    flow: Literal["manage", "cancel"] = Field(
        default="manage", description="cancel opens the portal at the cancellation step."
    )


ExitReason = Literal[
    "got_the_job",
    "interview_over",
    "too_expensive",
    "not_helpful",
    "technical_problems",
    "missing_feature",
    "other",
]
GotJob = Literal["yes", "no", "still_interviewing", "prefer_not_to_say"]


class ExitSurveyIn(_Body):
    """The cancellation exit survey: two questions. Both are required, the detail is not."""

    reason: ExitReason = Field(description="Why are you leaving?")
    reason_detail: str | None = Field(default=None, max_length=1000)
    got_job: GotJob = Field(description="Did you get the job?")


class ExitSurveyOut(BaseModel):
    id: str
    created_at: datetime


class WebhookOut(BaseModel):
    received: bool
    duplicate: bool


class DevUsageIn(_Body):
    minutes: int = Field(ge=1, le=600)
