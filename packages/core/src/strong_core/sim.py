"""The AI candidate's own model budget (P13, docs/sim-candidate.md).

Sessions of the sim user run on their own LiteLLM key (SIM_LITELLM_KEY), which has its own daily
budget, so AI-to-AI tests never use the budget of real users. The api, the worker and the voice
agent call gateway_for_org() wherever they build a gateway for one org's work.

Nothing changes when SIM_ENABLED is false or SIM_LITELLM_KEY is empty.

check_sim_gate() is the rule for starting an admin-started run (SM-3, docs/admin-spec.md). The api
checks it when the admin clicks Start, and the sim service again when the run begins.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core import runtime_settings as rs
from strong_core.config import get_settings
from strong_core.db.models import InterviewSession, User
from strong_core.gateway import ModelGateway
from strong_core.schemas.enums import SessionStatus

log = logging.getLogger("strong_core.sim")

_sim_orgs: set[uuid.UUID] = set()


async def is_sim_org(db: AsyncSession, org_id: uuid.UUID) -> bool:
    """True when sim is on and the org belongs to the sim user.

    Only a yes is cached: a no costs one indexed lookup each time, so an org whose sim user is
    created later is still found.
    """
    settings = get_settings()
    if not settings.sim_enabled:
        return False
    if org_id in _sim_orgs:
        return True
    email = settings.sim_email.strip().lower()
    found = await db.scalar(
        select(User.id).where(User.org_id == org_id, func.lower(User.email) == email)
    )
    if found is not None:
        _sim_orgs.add(org_id)
    return found is not None


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


# --- starting an admin-started run (SM-3) ---------------------------------------------------

STUCK_AFTER_MIN = 15  # AI-1: in progress this long past its length, a session is stuck


async def sim_org_id(db: AsyncSession) -> uuid.UUID | None:
    """The sim user's org, or None when there is no sim user yet."""
    email = get_settings().sim_email.strip().lower()
    found: uuid.UUID | None = await db.scalar(
        select(User.org_id).where(func.lower(User.email) == email)
    )
    return found


async def live_real_sessions(db: AsyncSession, now: datetime | None = None) -> int:
    """Sessions of real users in progress now. Stuck sessions (AI-1) and the sim org's own
    sessions do not count."""
    now = now or datetime.now(UTC)
    sim_org = await sim_org_id(db)
    query = select(InterviewSession.started_at, InterviewSession.duration_min).where(
        InterviewSession.status == SessionStatus.IN_PROGRESS
    )
    if sim_org is not None:
        query = query.where(InterviewSession.org_id != sim_org)
    count = 0
    for started_at, duration_min in (await db.execute(query)).all():
        if started_at is None:
            count += 1
            continue
        if started_at.tzinfo is None:  # SQLite in tests
            started_at = started_at.replace(tzinfo=UTC)
        if now - started_at < timedelta(minutes=duration_min + STUCK_AFTER_MIN):
            count += 1
    return count


@dataclass(frozen=True)
class SimGate:
    """Whether a sim run may start now. `retry`: only the live-sessions limit is in the way,
    so the run waits and checks again; any other reason fails it."""

    ok: bool
    retry: bool = False
    reason: str | None = None


async def check_sim_gate(db: AsyncSession, need_usd: float, base: ModelGateway) -> SimGate:
    """SM-3: SIM_ENABLED, not paused, the live-sessions limit, and today's sim budget."""
    if not get_settings().sim_enabled:
        return SimGate(ok=False, reason="AI candidate runs are off on this server (SIM_ENABLED)")
    current = await rs.get_all(db)
    if current.sim_paused:
        return SimGate(ok=False, reason="AI candidate runs are paused (Controls)")
    limit = current.sim_max_live_sessions
    if limit:
        live = await live_real_sessions(db)
        if live >= limit:
            return SimGate(
                ok=False,
                retry=True,
                reason=f"{live} real interviews are live; runs start below {limit}",
            )
    key = await sim_key_budget(base)
    if key is not None and key.max_budget_usd is not None:
        left = key.max_budget_usd - key.spend_usd
        if left < need_usd:
            return SimGate(
                ok=False,
                reason=f"today's AI candidate budget has ${max(0.0, left):.2f} left; "
                f"this run needs about ${need_usd:.2f}",
            )
    return SimGate(ok=True)
