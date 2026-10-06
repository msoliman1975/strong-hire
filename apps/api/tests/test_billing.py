"""Billing (P9). Requirement IDs: BL-1 (Stripe plan, minute cap, usage meter), BL-2 (free tier:
one free interview; the gap analysis rate limit is tested in P6). Webhooks use Stripe-format fixtures with
signatures computed in the test; no Stripe account is used."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.billing import (
    ensure_can_start_session,
    get_entitlement,
    record_session_minutes,
)
from strong_api.billing.settings import BillingSettings
from strong_api.billing.webhooks import subscription_period
from strong_core.db.models import ExitSurvey, Org, StripeEvent, Subscription
from strong_core.schemas import SessionStatus, SubscriptionStatus

from .accounts_support import (
    CUSTOMER_ID,
    SUBSCRIPTION_ID,
    WEBHOOK_SECRET,
    FakeStripe,
    add_session,
    load_event,
    post_event,
    sign,
    sign_up,
)

Maker = async_sessionmaker[AsyncSession]


def billing_settings(**overrides: Any) -> BillingSettings:
    values: dict[str, Any] = {
        "stripe_secret_key": "sk_test_unused",
        "stripe_webhook_secret": WEBHOOK_SECRET,
        "stripe_price_id": "price_TEST123",
        "billing_price_usd_month": "29",
        "billing_minutes_cap": 300,
        "billing_free_interviews": 1,
    }
    values.update(overrides)
    return BillingSettings(**values)


@pytest.fixture
def stripe() -> FakeStripe:
    return FakeStripe()


@pytest.fixture
def billing_app(app: FastAPI, stripe: FakeStripe) -> FastAPI:
    app.state.billing_settings = billing_settings()
    app.state.stripe = stripe
    return app


@pytest.fixture
async def user(billing_app: FastAPI, client: httpx.AsyncClient) -> dict[str, Any]:
    return await sign_up(client)


async def subscribe(client: httpx.AsyncClient, user: dict[str, Any]) -> None:
    """Checkout, then the webhooks Stripe sends after a successful payment."""
    assert (await client.post("/billing/checkout")).status_code == 200
    for name in ("customer_subscription_created", "checkout_session_completed"):
        resp = await post_event(client, load_event(name, user["id"]))
        assert resp.status_code == 200, resp.text


async def subscription_row(maker: Maker, org_id: str) -> Subscription:
    async with maker() as db:
        row = await db.scalar(select(Subscription).where(Subscription.org_id == uuid.UUID(org_id)))
        assert row is not None
        return row


# ---------------------------------------------------------------- plan and usage (config)


async def test_bl1_plan_numbers_come_from_config(
    billing_app: FastAPI, client: httpx.AsyncClient
) -> None:
    billing_app.state.billing_settings = billing_settings(
        billing_price_usd_month="39", billing_minutes_cap=240, billing_free_interviews=2
    )
    plan = (await client.get("/billing/plan")).json()
    assert plan == {
        "name": "Strong Hire monthly",
        "price_usd_month": 39.0,
        "minutes_cap": 240,
        "free_interviews": 2,
        "billing_enabled": True,
    }


async def test_plan_says_when_stripe_is_not_configured(
    billing_app: FastAPI, client: httpx.AsyncClient, user: dict[str, Any]
) -> None:
    billing_app.state.stripe = None
    assert (await client.get("/billing/plan")).json()["billing_enabled"] is False
    resp = await client.post("/billing/checkout")
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "billing_not_configured"


def test_bl1_settings_refuse_live_keys_and_treat_empty_as_unset() -> None:
    with pytest.raises(ValueError, match="live key"):
        BillingSettings(stripe_secret_key="sk_live_abc", stripe_price_id="price_1")
    assert BillingSettings(
        stripe_secret_key="sk_live_abc", stripe_price_id="price_1", stripe_allow_live=True
    ).stripe_enabled
    empty = BillingSettings(stripe_secret_key="", stripe_webhook_secret="", stripe_price_id="")
    assert empty.stripe_enabled is False
    assert empty.stripe_webhook_secret is None


async def test_usage_needs_sign_in(billing_app: FastAPI, client: httpx.AsyncClient) -> None:
    assert (await client.get("/billing/usage")).status_code == 401


async def test_bl2_new_user_has_one_free_interview(
    client: httpx.AsyncClient, user: dict[str, Any]
) -> None:
    usage = (await client.get("/billing/usage")).json()
    assert usage["plan"] == "free"
    assert usage["free_interviews_total"] == 1
    assert usage["free_interviews_left"] == 1
    assert usage["can_start_session"] is True
    assert usage["minutes_cap"] == 0
    assert usage["block_code"] is None


async def test_bl2_free_interview_is_used_once_then_upgrade_required(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    org_id, user_id = uuid.UUID(user["org_id"]), uuid.UUID(user["id"])
    async with sessionmaker() as db:
        # A session that never started and a failed one do not use the free interview.
        await add_session(db, org_id, user_id, started=False, status=SessionStatus.CREATED)
        await add_session(db, org_id, user_id, status=SessionStatus.FAILED)
        assert (await ensure_can_start_session(db, org_id)).free_interviews_left == 1
        await add_session(db, org_id, user_id, status=SessionStatus.COMPLETED)

    usage = (await client.get("/billing/usage")).json()
    assert usage["free_interviews_left"] == 0
    assert usage["can_start_session"] is False
    assert usage["block_code"] == "upgrade_required"

    async with sessionmaker() as db:
        with pytest.raises(Exception) as caught:
            await ensure_can_start_session(db, org_id)
    exc: Any = caught.value
    assert exc.status_code == 402
    assert exc.detail["code"] == "upgrade_required"
    assert exc.detail["upgrade_url"] == "/upgrade"


# ---------------------------------------------------------------- checkout and portal


async def test_bl1_checkout_creates_customer_and_returns_stripe_url(
    client: httpx.AsyncClient, user: dict[str, Any], stripe: FakeStripe, sessionmaker: Maker
) -> None:
    resp = await client.post("/billing/checkout")
    assert resp.status_code == 200
    assert resp.json()["url"].startswith("https://checkout.stripe.com/")
    assert stripe.calls[0] == (
        "create_customer",
        {"email": "ana@example.com", "user_id": user["id"]},
    )
    assert stripe.calls[1][1]["success_url"] == "http://localhost:5180/?upgraded=1"
    row = await subscription_row(sessionmaker, user["org_id"])
    assert row.stripe_customer_id == CUSTOMER_ID
    assert row.status == SubscriptionStatus.INCOMPLETE
    # Still free until the webhook says the payment worked.
    assert (await client.get("/billing/usage")).json()["plan"] == "free"

    # A second checkout reuses the customer.
    assert (await client.post("/billing/checkout")).status_code == 200
    assert [c[0] for c in stripe.calls].count("create_customer") == 1


async def test_checkout_refused_when_already_paid(
    client: httpx.AsyncClient, user: dict[str, Any]
) -> None:
    await subscribe(client, user)
    resp = await client.post("/billing/checkout")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "already_subscribed"


async def test_portal_manage_and_cancel_flow(
    client: httpx.AsyncClient, user: dict[str, Any], stripe: FakeStripe
) -> None:
    assert (await client.post("/billing/portal")).status_code == 404
    await subscribe(client, user)
    resp = await client.post("/billing/portal", json={"flow": "manage"})
    assert resp.status_code == 200
    assert resp.json()["url"].startswith("https://billing.stripe.com/")
    assert stripe.calls[-1] == ("portal", {"customer_id": CUSTOMER_ID, "cancel": None})
    resp = await client.post("/billing/portal", json={"flow": "cancel"})
    assert resp.status_code == 200
    assert stripe.calls[-1] == ("portal", {"customer_id": CUSTOMER_ID, "cancel": SUBSCRIPTION_ID})


# ---------------------------------------------------------------- webhooks


async def test_bl1_webhooks_turn_the_plan_on_with_the_minute_cap(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    await subscribe(client, user)
    row = await subscription_row(sessionmaker, user["org_id"])
    assert row.status == SubscriptionStatus.ACTIVE
    assert row.stripe_subscription_id == SUBSCRIPTION_ID
    assert row.minutes_cap == 300
    assert row.period_start is not None and row.period_end is not None
    async with sessionmaker() as db:
        org = await db.get(Org, uuid.UUID(user["org_id"]))
        assert org is not None and org.plan == "paid"

    usage = (await client.get("/billing/usage")).json()
    assert usage["plan"] == "paid"
    assert usage["minutes_used"] == 0
    assert usage["minutes_cap"] == 300
    assert usage["minutes_left"] == 300
    assert usage["period_end"].startswith("2026-10-21")  # 1792592000
    assert usage["has_billing_account"] is True


async def test_bl1_webhook_rejects_a_bad_signature(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    await client.post("/billing/checkout")
    event = load_event("customer_subscription_created", user["id"])
    payload = json.dumps(event).encode()
    for header in (
        sign(payload, "whsec_wrong"),
        sign(payload, timestamp=int(datetime.now(UTC).timestamp()) - 3600),  # too old
        "t=1,v1=deadbeef",
        None,
    ):
        headers = {"Stripe-Signature": header} if header else {}
        resp = await client.post("/billing/webhook", content=payload, headers=headers)
        assert resp.status_code == 400
    # A changed body with an old signature fails too.
    resp = await client.post(
        "/billing/webhook",
        content=payload.replace(b'"active"', b'"trialing"'),
        headers={"Stripe-Signature": sign(payload)},
    )
    assert resp.status_code == 400
    row = await subscription_row(sessionmaker, user["org_id"])
    assert row.status == SubscriptionStatus.INCOMPLETE
    async with sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(StripeEvent)) == 0


async def test_bl1_webhook_is_idempotent(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    await subscribe(client, user)
    async with sessionmaker() as db:
        row = await db.scalar(select(Subscription))
        assert row is not None
        row.minutes_used = 100
        await db.commit()

    # The renewal resets usage once. Stripe sends it again: nothing changes the second time.
    renewal = load_event("customer_subscription_updated_renewal", user["id"])
    first = await post_event(client, renewal)
    assert first.json() == {"received": True, "duplicate": False}
    async with sessionmaker() as db:
        row = await db.scalar(select(Subscription))
        assert row is not None and row.minutes_used == 0
        row.minutes_used = 40
        await db.commit()
    again = await post_event(client, renewal)
    assert again.status_code == 200
    assert again.json() == {"received": True, "duplicate": True}
    row = await subscription_row(sessionmaker, user["org_id"])
    assert row.minutes_used == 40
    async with sessionmaker() as db:
        ids = list(await db.scalars(select(StripeEvent.id)))
    assert sorted(ids) == sorted(
        ["evt_TEST_checkout", "evt_TEST_sub_created", "evt_TEST_sub_renewal"]
    )


async def test_bl1_cancel_at_period_end_then_deleted(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    await subscribe(client, user)
    await post_event(client, load_event("customer_subscription_updated_cancel", user["id"]))
    usage = (await client.get("/billing/usage")).json()
    assert usage["plan"] == "paid"  # paid until the period ends
    assert usage["cancel_at_period_end"] is True

    await post_event(client, load_event("customer_subscription_deleted", user["id"]))
    usage = (await client.get("/billing/usage")).json()
    assert usage["plan"] == "free"
    assert usage["status"] == "canceled"
    async with sessionmaker() as db:
        org = await db.get(Org, uuid.UUID(user["org_id"]))
        assert org is not None and org.plan == "free"


async def test_bl1_out_of_order_events_do_not_reopen_a_canceled_plan(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    await subscribe(client, user)
    await post_event(client, load_event("customer_subscription_deleted", user["id"]))
    # An older "updated (active)" event arrives late.
    late = load_event("customer_subscription_updated_cancel", user["id"])
    late["id"] = "evt_TEST_late"
    await post_event(client, late)
    row = await subscription_row(sessionmaker, user["org_id"])
    assert row.status == SubscriptionStatus.CANCELED


async def test_bl1_an_older_period_event_is_ignored(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    await subscribe(client, user)
    await post_event(client, load_event("customer_subscription_updated_renewal", user["id"]))
    renewed = await subscription_row(sessionmaker, user["org_id"])
    old = load_event("customer_subscription_created", user["id"])
    old["id"] = "evt_TEST_old_period"
    await post_event(client, old)
    row = await subscription_row(sessionmaker, user["org_id"])
    assert row.period_start == renewed.period_start


async def test_bl1_invoice_paid_syncs_the_renewal(
    client: httpx.AsyncClient, user: dict[str, Any], stripe: FakeStripe, sessionmaker: Maker
) -> None:
    await subscribe(client, user)
    async with sessionmaker() as db:
        row = await db.scalar(select(Subscription))
        assert row is not None
        row.minutes_used = 250
        await db.commit()
    renewed = load_event("customer_subscription_updated_renewal")["data"]["object"]
    stripe.subscriptions[SUBSCRIPTION_ID] = renewed
    await post_event(client, load_event("invoice_paid", user["id"]))
    row = await subscription_row(sessionmaker, user["org_id"])
    assert row.minutes_used == 0
    assert row.period_start is not None
    start, _ = subscription_period(renewed)
    assert row.period_start.replace(tzinfo=UTC) == start


async def test_resubscribe_after_cancel_uses_the_new_subscription(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    await subscribe(client, user)
    await post_event(client, load_event("customer_subscription_deleted", user["id"]))
    new = load_event("customer_subscription_created", user["id"], id="sub_TEST456")
    new["id"] = "evt_TEST_new_sub"
    await post_event(client, new)
    row = await subscription_row(sessionmaker, user["org_id"])
    assert row.stripe_subscription_id == "sub_TEST456"
    assert row.status == SubscriptionStatus.ACTIVE
    # A late event about the old, canceled subscription does not replace the new one.
    old = load_event("customer_subscription_deleted", user["id"])
    old["id"] = "evt_TEST_old_deleted_again"
    await post_event(client, old)
    row = await subscription_row(sessionmaker, user["org_id"])
    assert row.stripe_subscription_id == "sub_TEST456"
    assert row.status == SubscriptionStatus.ACTIVE


async def test_webhook_for_unknown_customer_is_recorded_and_ignored(
    client: httpx.AsyncClient, billing_app: FastAPI, sessionmaker: Maker
) -> None:
    event = load_event("customer_subscription_created", customer="cus_SOMEONE_ELSE")
    resp = await post_event(client, event)
    assert resp.status_code == 200
    async with sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(Subscription)) == 0
        assert await db.get(StripeEvent, "evt_TEST_sub_created") is not None


# ---------------------------------------------------------------- entitlements at the cap


async def test_bl1_minutes_at_the_cap_block_a_new_session(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    await subscribe(client, user)
    org_id = uuid.UUID(user["org_id"])
    async with sessionmaker() as db:
        row = await db.scalar(select(Subscription))
        assert row is not None
        row.minutes_used = 299
        await db.commit()
        ent = await ensure_can_start_session(db, org_id)
        assert ent.minutes_left == 1
        assert ent.max_minutes(45) == 1  # the session timer stops at the cap

        row.minutes_used = 300
        await db.commit()
        ent = await get_entitlement(db, org_id)
        assert ent.can_start_session is False
        assert ent.block_code == "minutes_exhausted"
        with pytest.raises(Exception) as caught:
            await ensure_can_start_session(db, org_id)
    exc: Any = caught.value
    assert exc.status_code == 402
    assert exc.detail["code"] == "minutes_exhausted"

    usage = (await client.get("/billing/usage")).json()
    assert usage["minutes_used"] == 300
    assert usage["minutes_left"] == 0
    assert usage["block_code"] == "minutes_exhausted"


async def test_bl1_usage_resets_at_the_new_period(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    await subscribe(client, user)
    async with sessionmaker() as db:
        row = await db.scalar(select(Subscription))
        assert row is not None
        row.minutes_used = 300
        await db.commit()
    assert (await client.get("/billing/usage")).json()["can_start_session"] is False

    # The same period again (for example a card update) does not reset usage.
    same = load_event("customer_subscription_created", user["id"])
    same["id"] = "evt_TEST_same_period"
    await post_event(client, same)
    assert (await client.get("/billing/usage")).json()["minutes_used"] == 300

    await post_event(client, load_event("customer_subscription_updated_renewal", user["id"]))
    usage = (await client.get("/billing/usage")).json()
    assert usage["minutes_used"] == 0
    assert usage["minutes_left"] == 300
    assert usage["can_start_session"] is True
    assert usage["period_end"].startswith("2026-11-21")  # 1795270400


async def test_bl1_record_session_minutes_bills_once(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    await subscribe(client, user)
    org_id, user_id = uuid.UUID(user["org_id"]), uuid.UUID(user["id"])
    async with sessionmaker() as db:
        session = await add_session(db, org_id, user_id, minutes=30)
        session.ended_at = session.started_at + timedelta(minutes=29, seconds=10)  # type: ignore[operator]
        assert await record_session_minutes(db, session) == 30  # rounded up
        await db.commit()
        assert await record_session_minutes(db, session) == 0  # called again: no double bill
        await db.commit()
        # A session never bills more than its chosen duration.
        long = await add_session(db, org_id, user_id, minutes=90)
        assert await record_session_minutes(db, long) == 45
        await db.commit()
    assert (await client.get("/billing/usage")).json()["minutes_used"] == 75


async def test_bl2_free_sessions_do_not_use_plan_minutes(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    org_id, user_id = uuid.UUID(user["org_id"]), uuid.UUID(user["id"])
    async with sessionmaker() as db:
        session = await add_session(db, org_id, user_id, minutes=30)
        assert await record_session_minutes(db, session) == 0
        assert session.minutes_billed == 30
        await db.commit()


async def test_dev_usage_uses_minutes_locally(
    client: httpx.AsyncClient, user: dict[str, Any]
) -> None:
    assert (await client.post("/billing/dev/usage", json={"minutes": 10})).status_code == 409
    await subscribe(client, user)
    resp = await client.post("/billing/dev/usage", json={"minutes": 45})
    assert resp.status_code == 200
    assert resp.json()["minutes_used"] == 45


# ---------------------------------------------------------------- exit survey


async def test_exit_survey_stores_both_answers(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    resp = await client.post(
        "/billing/exit-survey",
        json={"reason": "got_the_job", "got_job": "yes", "reason_detail": "  Thanks!  "},
    )
    assert resp.status_code == 201, resp.text
    async with sessionmaker() as db:
        row = await db.scalar(select(ExitSurvey))
    assert row is not None
    assert (row.reason, row.got_job, row.reason_detail) == ("got_the_job", "yes", "Thanks!")
    assert str(row.user_id) == user["id"]

    bad = await client.post("/billing/exit-survey", json={"reason": "bored", "got_job": "yes"})
    assert bad.status_code == 422
    missing = await client.post("/billing/exit-survey", json={"reason": "other"})
    assert missing.status_code == 422


async def test_webhook_answers_503_without_a_secret(
    billing_app: FastAPI, client: httpx.AsyncClient
) -> None:
    billing_app.state.billing_settings = billing_settings(stripe_webhook_secret=None)
    resp = await post_event(client, load_event("customer_subscription_created"))
    assert resp.status_code == 503


def test_stripe_gateway_is_built_only_with_keys() -> None:
    from strong_api.billing.stripe_gateway import StripeSdkGateway, build_stripe_gateway

    assert build_stripe_gateway(BillingSettings(stripe_secret_key=None)) is None
    gateway = build_stripe_gateway(billing_settings())
    assert isinstance(gateway, StripeSdkGateway)  # no network call at build time
