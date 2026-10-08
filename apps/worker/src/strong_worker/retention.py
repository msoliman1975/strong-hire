"""Daily retention job (R2): delete interviewer traces older than TRACE_RETENTION_DAYS (90).

Runs as an Arq cron job (strong_worker.main.WorkerSettings.cron_jobs). Only the
interviewer_traces table is cleaned; transcripts (turns) are kept.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db import get_sessionmaker
from strong_core.db.models import TRACE_RETENTION_DAYS, InterviewerTrace

log = logging.getLogger(__name__)

CTX_KEY = "retention_sessionmaker"
RUN_AT_HOUR_UTC = 3
RUN_AT_MINUTE = 17


async def delete_old_traces(
    maker: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    days: int = TRACE_RETENTION_DAYS,
) -> int:
    """Delete traces created more than `days` days before `now`. Returns the rows deleted."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    async with maker() as db:
        result = await db.execute(
            delete(InterviewerTrace).where(InterviewerTrace.created_at < cutoff)
        )
        await db.commit()
    deleted = int(getattr(result, "rowcount", 0) or 0)
    log.info("trace retention: deleted %d traces older than %s", deleted, cutoff.isoformat())
    return deleted


async def trace_retention(ctx: dict[str, Any]) -> dict[str, int]:
    """The Arq cron job."""
    maker = ctx.get(CTX_KEY) or get_sessionmaker()
    return {"deleted": await delete_old_traces(maker)}
