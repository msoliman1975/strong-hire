"""The Stripe calls the API makes. Tests swap in FakeStripe; nothing else imports `stripe`.

Objects come back as plain dicts, the same shape as the `data.object` of a webhook event.
"""

from __future__ import annotations

from typing import Any, Protocol

import stripe

from strong_api.billing.settings import BillingSettings


class StripeNotConfiguredError(RuntimeError):
    """STRIPE_SECRET_KEY or STRIPE_PRICE_ID is not set."""


class StripeGateway(Protocol):
    async def create_customer(self, *, email: str, user_id: str, org_id: str) -> str:
        """Return the new customer id (cus_...)."""

    async def create_checkout_session(
        self, *, customer_id: str, user_id: str, success_url: str, cancel_url: str
    ) -> str:
        """Return the Checkout URL for the one monthly plan."""

    async def create_portal_session(
        self, *, customer_id: str, return_url: str, cancel_subscription_id: str | None = None
    ) -> str:
        """Return the Customer Portal URL. With a subscription id, open its cancel flow."""

    async def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]: ...

    async def delete_customer(self, customer_id: str) -> None:
        """Delete the customer. Stripe cancels its subscriptions at once."""


class StripeSdkGateway:
    def __init__(self, settings: BillingSettings) -> None:
        if not settings.stripe_enabled:
            raise StripeNotConfiguredError("Set STRIPE_SECRET_KEY and STRIPE_PRICE_ID")
        assert settings.stripe_secret_key is not None and settings.stripe_price_id is not None
        self._client = stripe.StripeClient(settings.stripe_secret_key.get_secret_value())
        self._price_id = settings.stripe_price_id

    async def create_customer(self, *, email: str, user_id: str, org_id: str) -> str:
        customer = await self._client.v1.customers.create_async(
            params={"email": email, "metadata": {"user_id": user_id, "org_id": org_id}}
        )
        return str(customer.id)

    async def create_checkout_session(
        self, *, customer_id: str, user_id: str, success_url: str, cancel_url: str
    ) -> str:
        session = await self._client.v1.checkout.sessions.create_async(
            params={
                "mode": "subscription",
                "customer": customer_id,
                "client_reference_id": user_id,
                "line_items": [{"price": self._price_id, "quantity": 1}],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "subscription_data": {"metadata": {"user_id": user_id}},
            }
        )
        if not session.url:
            raise RuntimeError("Stripe returned a Checkout session without a URL")
        return str(session.url)

    async def create_portal_session(
        self, *, customer_id: str, return_url: str, cancel_subscription_id: str | None = None
    ) -> str:
        params: dict[str, Any] = {"customer": customer_id, "return_url": return_url}
        if cancel_subscription_id:
            params["flow_data"] = {
                "type": "subscription_cancel",
                "subscription_cancel": {"subscription": cancel_subscription_id},
                "after_completion": {
                    "type": "redirect",
                    "redirect": {"return_url": return_url},
                },
            }
        session = await self._client.v1.billing_portal.sessions.create_async(
            params=params  # type: ignore[arg-type]
        )
        return str(session.url)

    async def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        sub = await self._client.v1.subscriptions.retrieve_async(subscription_id)
        data: dict[str, Any] = sub.to_dict()
        return data

    async def delete_customer(self, customer_id: str) -> None:
        try:
            await self._client.v1.customers.delete_async(customer_id)
        except stripe.InvalidRequestError as exc:
            if getattr(exc, "code", None) != "resource_missing":
                raise


def build_stripe_gateway(settings: BillingSettings) -> StripeGateway | None:
    return StripeSdkGateway(settings) if settings.stripe_enabled else None
