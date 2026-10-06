"""Billing (P9): one Stripe plan with a monthly minute cap (BL-1) and the free tier (BL-2).

`install_billing(app)` adds the /billing routes. Other workstreams use:
- `ensure_can_start_session(db, org_id)` in POST /sessions (HTTP 402 when blocked),
- `record_session_minutes(db, session)` when a session ends.

Gap analyses are free; their fair-use rate limit lives in strong_api.gap (P6, GA-4).

See README.md in this folder for the Stripe setup and the local test steps.
"""

from __future__ import annotations

from fastapi import FastAPI

from strong_api.auth.settings import AuthSettings, get_auth_settings
from strong_api.billing.entitlements import (
    Entitlement,
    ensure_can_start_session,
    get_entitlement,
    record_session_minutes,
)
from strong_api.billing.router import build_router
from strong_api.billing.settings import BillingSettings, get_billing_settings
from strong_api.billing.stripe_gateway import StripeGateway, build_stripe_gateway


def install_billing(
    app: FastAPI,
    settings: BillingSettings | None = None,
    *,
    auth_settings: AuthSettings | None = None,
    stripe: StripeGateway | None = None,
) -> None:
    settings = settings or get_billing_settings()
    app.state.billing_settings = settings
    app.state.stripe = stripe if stripe is not None else build_stripe_gateway(settings)
    app.include_router(build_router(auth_settings or get_auth_settings()))


__all__ = [
    "BillingSettings",
    "Entitlement",
    "ensure_can_start_session",
    "get_entitlement",
    "install_billing",
    "record_session_minutes",
]
