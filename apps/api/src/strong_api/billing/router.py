"""Billing endpoints (BL-1, BL-2).

GET  /billing/plan          the one plan: name, price, minute cap, free interviews (config)
GET  /billing/usage         the usage meter and what the user may start now
POST /billing/checkout      Stripe Checkout URL for the plan
POST /billing/portal        Stripe Customer Portal URL (manage, or go straight to cancel)
POST /billing/exit-survey   the two cancellation questions
POST /billing/webhook       Stripe events (signature checked, idempotent)
POST /billing/dev/usage     local only: use plan minutes without a voice session
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from strong_api.auth import CurrentUser
from strong_api.auth.deps import DbSession
from strong_api.auth.settings import AuthSettings
from strong_api.billing.entitlements import get_entitlement, get_subscription, is_paid
from strong_api.billing.schemas import (
    DevUsageIn,
    ExitSurveyIn,
    ExitSurveyOut,
    PlanOut,
    PortalRequest,
    RedirectOut,
    UsageOut,
    WebhookOut,
)
from strong_api.billing.settings import BillingSettings
from strong_api.billing.stripe_gateway import StripeGateway
from strong_api.billing.webhooks import InvalidSignatureError, handle_event, verify_event
from strong_core.db.models import AuditLog, ExitSurvey, Subscription
from strong_core.schemas import SubscriptionStatus

log = logging.getLogger(__name__)


def billing_settings(request: Request) -> BillingSettings:
    settings: BillingSettings = request.app.state.billing_settings
    return settings


def stripe_gateway(request: Request) -> StripeGateway | None:
    gateway: StripeGateway | None = request.app.state.stripe
    return gateway


Settings = Annotated[BillingSettings, Depends(billing_settings)]
Stripe = Annotated[StripeGateway | None, Depends(stripe_gateway)]


def _require_stripe(gateway: StripeGateway | None) -> StripeGateway:
    if gateway is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "billing_not_configured", "message": "Payments are not set up yet."},
        )
    return gateway


def build_router(auth_settings: AuthSettings) -> APIRouter:
    router = APIRouter(prefix="/billing", tags=["billing"])
    web = auth_settings.web_base_url.rstrip("/")

    @router.get("/plan")
    async def plan(settings: Settings, gateway: Stripe) -> PlanOut:
        return PlanOut(
            name=settings.billing_plan_name,
            price_usd_month=float(settings.billing_price_usd_month),
            minutes_cap=settings.billing_minutes_cap,
            free_interviews=settings.billing_free_interviews,
            billing_enabled=gateway is not None,
        )

    @router.get("/usage")
    async def usage(db: DbSession, user: CurrentUser, settings: Settings) -> UsageOut:
        ent = await get_entitlement(db, user.org_id, settings)
        sub = await get_subscription(db, user.org_id)
        return UsageOut(
            plan=ent.plan,
            status=ent.status,
            minutes_used=ent.minutes_used,
            minutes_cap=ent.minutes_cap,
            minutes_left=ent.minutes_left,
            period_start=ent.period_start,
            period_end=ent.period_end,
            cancel_at_period_end=ent.cancel_at_period_end,
            free_interviews_total=ent.free_interviews_total,
            free_interviews_left=ent.free_interviews_left,
            can_start_session=ent.can_start_session,
            full_interviews_allowed=ent.full_interviews_allowed,
            block_code=ent.block_code,
            has_billing_account=bool(sub and sub.stripe_customer_id),
        )

    @router.post("/checkout")
    async def checkout(db: DbSession, user: CurrentUser, gateway: Stripe) -> RedirectOut:
        """Start Stripe Checkout for the plan. The webhook turns the plan on after payment."""
        stripe = _require_stripe(gateway)
        sub = await get_subscription(db, user.org_id)
        if is_paid(sub):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"code": "already_subscribed", "message": "Your plan is already active."},
            )
        if sub is None:
            sub = Subscription(
                org_id=user.org_id,
                user_id=user.id,
                status=SubscriptionStatus.INCOMPLETE,
                minutes_cap=0,
                minutes_used=0,
            )
            db.add(sub)
        if not sub.stripe_customer_id:
            sub.stripe_customer_id = await stripe.create_customer(
                email=user.email, user_id=str(user.id), org_id=str(user.org_id)
            )
        await db.commit()
        url = await stripe.create_checkout_session(
            customer_id=sub.stripe_customer_id,
            user_id=str(user.id),
            success_url=f"{web}/?upgraded=1",
            cancel_url=f"{web}/upgrade",
        )
        return RedirectOut(url=url)

    @router.post("/portal")
    async def portal(
        db: DbSession, user: CurrentUser, gateway: Stripe, body: PortalRequest | None = None
    ) -> RedirectOut:
        """Open the Stripe Customer Portal to change the card, see invoices or cancel."""
        stripe = _require_stripe(gateway)
        sub = await get_subscription(db, user.org_id)
        if sub is None or not sub.stripe_customer_id:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                {"code": "no_billing_account", "message": "You have no plan to manage."},
            )
        cancel_id = None
        if body is not None and body.flow == "cancel":
            if not is_paid(sub) or not sub.stripe_subscription_id:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    {"code": "not_subscribed", "message": "You have no active plan to cancel."},
                )
            cancel_id = sub.stripe_subscription_id
        url = await stripe.create_portal_session(
            customer_id=sub.stripe_customer_id,
            return_url=f"{web}/account",
            cancel_subscription_id=cancel_id,
        )
        return RedirectOut(url=url)

    @router.post("/exit-survey", status_code=status.HTTP_201_CREATED)
    async def exit_survey(db: DbSession, user: CurrentUser, body: ExitSurveyIn) -> ExitSurveyOut:
        """The cancellation exit survey: why the user leaves, and did they get the job."""
        row = ExitSurvey(
            org_id=user.org_id,
            user_id=user.id,
            reason=body.reason,
            reason_detail=(body.reason_detail or "").strip() or None,
            got_job=body.got_job,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return ExitSurveyOut(id=str(row.id), created_at=row.created_at)

    @router.post("/webhook")
    async def webhook(
        request: Request,
        db: DbSession,
        settings: Settings,
        gateway: Stripe,
        stripe_signature: Annotated[str | None, Header()] = None,
    ) -> WebhookOut:
        """Stripe calls this. The Stripe-Signature header must match STRIPE_WEBHOOK_SECRET."""
        if settings.stripe_webhook_secret is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Webhooks are not set up")
        payload = await request.body()
        try:
            event = verify_event(
                payload, stripe_signature, settings.stripe_webhook_secret.get_secret_value()
            )
        except InvalidSignatureError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature") from exc
        result = await handle_event(db, event, settings, gateway)
        log.info(
            "stripe event %s %s applied=%s duplicate=%s",
            result.event_id,
            result.type,
            result.applied,
            result.duplicate,
        )
        return WebhookOut(received=True, duplicate=result.duplicate)

    if auth_settings.is_local:

        @router.post("/dev/usage")
        async def dev_usage(
            db: DbSession, user: CurrentUser, settings: Settings, body: DevUsageIn
        ) -> UsageOut:
            """Local only (APP_ENV=local). Uses plan minutes as if a session had ended, so the
            subscribe, use, cancel flow can be checked before voice sessions exist."""
            sub = await get_subscription(db, user.org_id)
            if not is_paid(sub):
                raise HTTPException(status.HTTP_409_CONFLICT, "No active plan")
            assert sub is not None
            sub.minutes_used += body.minutes
            db.add(
                AuditLog(
                    org_id=user.org_id,
                    actor=f"user:{user.id}",
                    action="billing.dev_usage",
                    entity=f"subscription:{sub.id}",
                    details_json={"minutes": body.minutes},
                )
            )
            await db.commit()
            return await usage(db, user, settings)

    return router
