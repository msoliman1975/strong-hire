"""Arq jobs for the alert engine: the evaluator cron (every minute, AL-2), the optional daily
digest (AL-7) and a startup step that seeds the default rules."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.config import get_settings
from strong_core.db import get_sessionmaker
from strong_core.email import EmailSender, make_email_sender
from strong_core.ops.alerts import seed_default_rules
from strong_worker.alerts.digest import build_digest
from strong_worker.alerts.engine import run_tick

log = logging.getLogger(__name__)

CTX_KEY = "alerts"
TICK_TIMEOUT_S = 55


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class AlertsContext:
    sessionmaker: async_sessionmaker[AsyncSession]
    sender: EmailSender
    clock: Callable[[], datetime] = field(default=_utcnow)


def _context(ctx: dict[str, Any]) -> AlertsContext:
    found = ctx.get(CTX_KEY)
    if isinstance(found, AlertsContext):
        return found
    made = AlertsContext(sessionmaker=get_sessionmaker(), sender=make_email_sender())
    ctx[CTX_KEY] = made
    return made


async def startup(ctx: dict[str, Any]) -> None:
    """Seed the default rules that are missing (by name). Edited rules are left alone."""
    alerts = _context(ctx)
    try:
        async with alerts.sessionmaker() as db:
            added = await seed_default_rules(db)
    except Exception:  # a missing table must not stop the worker; the next start retries
        log.exception("could not seed the default alert rules")
        return
    if added:
        log.info("seeded %d default alert rules", added)


async def evaluate_alerts(ctx: dict[str, Any]) -> dict[str, Any]:
    """The cron job (every minute)."""
    alerts = _context(ctx)
    settings = get_settings()
    result = await run_tick(
        alerts.sessionmaker,
        alerts.sender,
        now=alerts.clock(),
        to=settings.alert_email,
        admin_base_url=settings.admin_base_url,
    )
    return {
        "skipped": result.skipped,
        "evaluated": result.evaluated,
        "events": result.events,
        "sent": result.sent,
        "failed": result.failed,
        "errors": result.errors,
    }


async def alert_digest(ctx: dict[str, Any]) -> dict[str, Any]:
    """AL-7: the daily digest. Does nothing unless ALERT_DIGEST=true and ALERT_EMAIL is set."""
    settings = get_settings()
    if not settings.alert_digest or not settings.alert_email:
        return {"sent": False}
    alerts = _context(ctx)
    async with alerts.sessionmaker() as db:
        subject, body = await build_digest(db, alerts.clock(), settings.admin_base_url)
    await alerts.sender.send(settings.alert_email, subject, body)
    return {"sent": True}
