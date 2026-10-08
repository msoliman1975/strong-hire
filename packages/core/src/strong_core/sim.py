"""The AI candidate's own model budget (P13, docs/sim-candidate.md).

Sessions of the sim user run on their own LiteLLM key (SIM_LITELLM_KEY), which has its own daily
budget, so AI-to-AI tests never use the budget of real users. The api, the worker and the voice
agent call gateway_for_org() wherever they build a gateway for one org's work.

Nothing changes when SIM_ENABLED is false or SIM_LITELLM_KEY is empty.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.config import get_settings
from strong_core.db.models import User
from strong_core.gateway import ModelGateway

log = logging.getLogger("strong_core.sim")

_sim_orgs: dict[uuid.UUID, bool] = {}


async def is_sim_org(db: AsyncSession, org_id: uuid.UUID) -> bool:
    """True when sim is on and the org belongs to the sim user. Cached per org id."""
    settings = get_settings()
    if not settings.sim_enabled:
        return False
    if org_id not in _sim_orgs:
        email = settings.sim_email.strip().lower()
        found = await db.scalar(
            select(User.id).where(User.org_id == org_id, func.lower(User.email) == email)
        )
        _sim_orgs[org_id] = found is not None
    return _sim_orgs[org_id]


async def gateway_for_org(db: AsyncSession, org_id: uuid.UUID, base: ModelGateway) -> ModelGateway:
    """The gateway for one org's model calls: the sim key for the sim org, else `base`."""
    if not await is_sim_org(db, org_id):
        return base
    key = get_settings().sim_litellm_key
    if key is None or not key.get_secret_value():
        log.warning("sim org %s has no SIM_LITELLM_KEY; using the app key", org_id)
        return base
    return base.with_api_key(key.get_secret_value())


@dataclass(frozen=True)
class KeyBudget:
    spend_usd: float
    max_budget_usd: float | None
    resets_at: datetime | None


async def sim_key_budget(base: ModelGateway, timeout_s: float = 10.0) -> KeyBudget | None:
    """Spend and limit of the sim key in the current LiteLLM budget period, or None if unknown."""
    key = get_settings().sim_litellm_key
    if key is None or not key.get_secret_value() or base.is_fake:
        return None
    root = base.base_url.removesuffix("/v1")
    secret = key.get_secret_value()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as http:
            resp = await http.get(
                f"{root}/key/info",
                params={"key": secret},
                headers={"Authorization": f"Bearer {secret}"},
            )
        resp.raise_for_status()
        info = resp.json().get("info", {})
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("could not read the sim key budget: %s", exc)
        return None
    reset = info.get("budget_reset_at")
    return KeyBudget(
        spend_usd=float(info.get("spend") or 0.0),
        max_budget_usd=float(info["max_budget"]) if info.get("max_budget") is not None else None,
        resets_at=datetime.fromisoformat(reset) if isinstance(reset, str) else None,
    )
