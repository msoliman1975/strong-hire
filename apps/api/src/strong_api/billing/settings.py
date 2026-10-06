"""Billing settings (BL-1, BL-2), read from environment variables.

The plan price, the monthly minute cap and the number of free interviews live here only. The web
app reads them from GET /billing/plan and GET /billing/usage, so it never hard-codes them.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BillingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Stripe, test mode until launch. With no secret key, checkout and the portal return 503.
    stripe_secret_key: SecretStr | None = Field(
        default=None, description="sk_test_... from the Stripe dashboard (Developers, API keys)."
    )
    stripe_webhook_secret: SecretStr | None = Field(
        default=None, description="whsec_... from `stripe listen` or the webhook endpoint page."
    )
    stripe_price_id: str | None = Field(
        default=None, description="price_... of the one monthly plan (recurring, monthly)."
    )
    stripe_allow_live: bool = Field(
        default=False, description="Live keys (sk_live_) are refused until this is true at launch."
    )

    # The one plan. Keep billing_price_usd_month equal to the Stripe price.
    billing_plan_name: str = "Strong Hire monthly"
    billing_price_usd_month: Decimal = Decimal("29")
    billing_minutes_cap: int = Field(default=300, ge=1, description="Interview minutes per period.")
    billing_free_interviews: int = Field(default=1, ge=0, description="BL-2: free interviews.")

    @field_validator("stripe_secret_key", "stripe_webhook_secret", "stripe_price_id", mode="before")
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        """Compose passes unset keys as empty strings."""
        return None if value == "" else value

    @model_validator(mode="after")
    def _test_mode_until_launch(self) -> BillingSettings:
        key = self.stripe_secret_key.get_secret_value() if self.stripe_secret_key else ""
        if key.startswith(("sk_live_", "rk_live_")) and not self.stripe_allow_live:
            raise ValueError("STRIPE_SECRET_KEY is a live key. Use a test key (sk_test_).")
        return self

    @property
    def stripe_enabled(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_price_id)


@lru_cache
def get_billing_settings() -> BillingSettings:
    return BillingSettings()
