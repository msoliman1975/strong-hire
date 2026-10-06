"""Stripe webhook handling (BL-1): signature check, idempotency, and Subscription sync.

- The signature is checked with the endpoint secret (STRIPE_WEBHOOK_SECRET) before anything else.
- Each event id is stored in stripe_events in the same transaction as its changes. A repeated
  event finds its id and changes nothing.
- Events can arrive out of order. Rules that keep the row correct:
  * a canceled subscription stays canceled (Stripe never reopens one);
  * an event about an older billing period than the stored one is ignored;
  * a new subscription id replaces the stored one only when the stored one is not active.
- A new period start resets minutes_used to 0 (usage resets each period).
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import stripe
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.billing.entitlements import PAID_STATUSES, as_utc
from strong_api.billing.settings import BillingSettings
from strong_api.billing.stripe_gateway import StripeGateway
from strong_core.db.models import Org, StripeEvent, Subscription
from strong_core.schemas import SubscriptionStatus

log = logging.getLogger(__name__)

SIGNATURE_TOLERANCE_S = 300

# Stripe statuses we do not store map to the nearest one we act on.
STATUS_MAP: dict[str, SubscriptionStatus] = {
    "trialing": SubscriptionStatus.TRIALING,
    "active": SubscriptionStatus.ACTIVE,
    "past_due": SubscriptionStatus.PAST_DUE,
    "unpaid": SubscriptionStatus.PAST_DUE,
    "canceled": SubscriptionStatus.CANCELED,
    "incomplete_expired": SubscriptionStatus.CANCELED,
    "paused": SubscriptionStatus.CANCELED,
    "incomplete": SubscriptionStatus.INCOMPLETE,
}

SUBSCRIPTION_EVENTS = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
    }
)


class InvalidSignatureError(Exception):
    pass


def verify_event(payload: bytes, signature: str | None, secret: str) -> dict[str, Any]:
    """Check the Stripe-Signature header and return the event as a dict."""
    try:
        stripe.WebhookSignature.verify_header(
            payload, signature, secret, tolerance=SIGNATURE_TOLERANCE_S
        )
    except stripe.SignatureVerificationError as exc:
        raise InvalidSignatureError(str(exc)) from exc
    try:
        event = json.loads(payload)
    except ValueError as exc:
        raise InvalidSignatureError("The payload is not JSON") from exc
    if not isinstance(event, dict) or not isinstance(event.get("id"), str):
        raise InvalidSignatureError("The payload is not a Stripe event")
    return event


@dataclass(frozen=True)
class WebhookResult:
    event_id: str
    type: str
    duplicate: bool = False
    applied: bool = False


def _ts(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value), UTC) if isinstance(value, int | float) else None


def subscription_period(sub: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    """The current period. Newer Stripe API versions keep it on the subscription items."""
    start, end = sub.get("current_period_start"), sub.get("current_period_end")
    if start is None or end is None:
        items = (sub.get("items") or {}).get("data") or []
        if items:
            start = items[0].get("current_period_start")
            end = items[0].get("current_period_end")
    return _ts(start), _ts(end)


def _id(value: Any) -> str | None:
    """Stripe fields can hold an id or an expanded object."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("id"), str):
        return str(value["id"])
    return None


def _invoice_subscription_id(invoice: dict[str, Any]) -> str | None:
    found = _id(invoice.get("subscription"))
    if found:
        return found
    parent = invoice.get("parent") or {}
    return _id((parent.get("subscription_details") or {}).get("subscription"))


async def _row_for_customer(db: AsyncSession, customer_id: str | None) -> Subscription | None:
    if not customer_id:
        return None
    return await db.scalar(
        select(Subscription).where(Subscription.stripe_customer_id == customer_id)
    )


async def sync_subscription(
    db: AsyncSession, row: Subscription, sub: dict[str, Any], settings: BillingSettings
) -> bool:
    """Copy a Stripe subscription onto our row. Return False when the data is stale."""
    sub_id = _id(sub.get("id"))
    new_status = STATUS_MAP.get(str(sub.get("status")), SubscriptionStatus.INCOMPLETE)
    start, end = subscription_period(sub)
    stored_start = as_utc(row.period_start)

    if row.stripe_subscription_id and sub_id != row.stripe_subscription_id:
        # A different subscription: accept it only if the stored one has ended (resubscribe),
        # and never let an old, canceled subscription overwrite the current one.
        if row.status in PAID_STATUSES or new_status == SubscriptionStatus.CANCELED:
            log.info("Ignoring subscription %s; %s is current", sub_id, row.stripe_subscription_id)
            return False
        stored_start = None
    elif row.stripe_subscription_id == sub_id:
        if row.status == SubscriptionStatus.CANCELED and new_status != SubscriptionStatus.CANCELED:
            return False  # canceled is final; this is an older event
        if stored_start and start and start < stored_start:
            return False  # an older billing period

    if start is not None and (stored_start is None or start > stored_start):
        row.minutes_used = 0  # a new period: usage resets
    row.stripe_subscription_id = sub_id
    row.status = new_status
    if start is not None:
        row.period_start = start
    if end is not None:
        row.period_end = end
    row.cancel_at_period_end = bool(sub.get("cancel_at_period_end") or sub.get("cancel_at"))
    if new_status in PAID_STATUSES:
        row.minutes_cap = settings.billing_minutes_cap
    org = await db.get(Org, row.org_id)
    if org is not None:
        org.plan = "paid" if new_status in PAID_STATUSES else "free"
    return True


async def _apply(
    db: AsyncSession,
    event: dict[str, Any],
    settings: BillingSettings,
    gateway: StripeGateway | None,
) -> bool:
    etype = str(event.get("type"))
    obj: dict[str, Any] = (event.get("data") or {}).get("object") or {}

    if etype == "checkout.session.completed":
        if obj.get("mode") != "subscription":
            return False
        row = await _row_for_customer(db, _id(obj.get("customer")))
        if row is None and obj.get("client_reference_id"):
            try:
                user_id = uuid.UUID(str(obj["client_reference_id"]))
            except ValueError:
                user_id = None
            if user_id is not None:
                row = await db.scalar(select(Subscription).where(Subscription.user_id == user_id))
        sub_id = _id(obj.get("subscription"))
        if row is None or sub_id is None:
            log.warning("checkout.session.completed %s matches no user", obj.get("id"))
            return False
        row.stripe_customer_id = row.stripe_customer_id or _id(obj.get("customer"))
        if gateway is not None:
            return await sync_subscription(
                db, row, await gateway.retrieve_subscription(sub_id), settings
            )
        if row.stripe_subscription_id is None:
            row.stripe_subscription_id = sub_id
        return True

    if etype in SUBSCRIPTION_EVENTS:
        row = await _row_for_customer(db, _id(obj.get("customer")))
        if row is None:
            log.warning("%s for unknown customer %s", etype, obj.get("customer"))
            return False
        return await sync_subscription(db, row, obj, settings)

    if etype == "invoice.paid":
        # A renewal. The subscription.updated event carries the new period too; this is a
        # second path in case that event is late.
        sub_id = _invoice_subscription_id(obj)
        row = await _row_for_customer(db, _id(obj.get("customer")))
        if row is None or sub_id is None or gateway is None:
            return False
        return await sync_subscription(
            db, row, await gateway.retrieve_subscription(sub_id), settings
        )

    return False


async def handle_event(
    db: AsyncSession,
    event: dict[str, Any],
    settings: BillingSettings,
    gateway: StripeGateway | None,
) -> WebhookResult:
    """Apply one verified event exactly once."""
    event_id, etype = str(event["id"]), str(event.get("type"))
    if await db.get(StripeEvent, event_id) is not None:
        return WebhookResult(event_id, etype, duplicate=True)
    applied = await _apply(db, event, settings, gateway)
    db.add(StripeEvent(id=event_id, type=etype[:100]))
    try:
        await db.commit()
    except IntegrityError:
        # The same event was handled at the same moment by another request.
        await db.rollback()
        return WebhookResult(event_id, etype, duplicate=True)
    return WebhookResult(event_id, etype, applied=applied)
