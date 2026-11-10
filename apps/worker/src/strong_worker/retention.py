"""Daily retention job (R2, OB-3..OB-5).

Runs as an Arq cron job (strong_worker.main.WorkerSettings.cron_jobs) and deletes, in batches:

    interviewer_traces    older than TRACE_RETENTION_DAYS (90)
    voice_turn_timings    older than VOICE_TIMING_RETENTION_DAYS (90)
    ops_samples           older than OPS_SAMPLE_RETENTION_DAYS (30)
    error_events          older than ERROR_EVENT_RETENTION_DAYS (30); error_groups are kept
    stories               deleted more than STORY_RESTORE_DAYS (30) ago (CS-16), with their
                          takes and the suggestions about them (foreign keys cascade)

Transcripts (turns) are kept.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db import get_sessionmaker
from strong_core.db.models import (
    ERROR_EVENT_RETENTION_DAYS,
    OPS_SAMPLE_RETENTION_DAYS,
    STORY_RESTORE_DAYS,
    TRACE_RETENTION_DAYS,
    VOICE_TIMING_RETENTION_DAYS,
    ErrorEvent,
    InterviewerTrace,
    OpsSample,
    Story,
    VoiceTurnTiming,
)

log = logging.getLogger(__name__)

CTX_KEY = "retention_sessionmaker"
RUN_AT_HOUR_UTC = 3
RUN_AT_MINUTE = 17
BATCH_SIZE = 5000
MAX_BATCHES = 1000  # 5 M rows a night at most; the rest goes the next night


async def delete_in_batches(
    maker: async_sessionmaker[AsyncSession],
    model: Any,
    column: Any,
    cutoff: datetime,
    *,
    batch_size: int = BATCH_SIZE,
) -> int:
    """Delete rows of `model` with `column` < cutoff, `batch_size` rows per transaction."""
    total = 0
    for _ in range(MAX_BATCHES):
        async with maker() as db:
            ids = list(await db.scalars(select(model.id).where(column < cutoff).limit(batch_size)))
            if not ids:
                break
            await db.execute(delete(model).where(model.id.in_(ids)))
            await db.commit()
        total += len(ids)
        if len(ids) < batch_size:
            break
    return total


async def delete_old_traces(
    maker: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    days: int = TRACE_RETENTION_DAYS,
) -> int:
    """Delete traces created more than `days` days before `now`. Returns the rows deleted."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    deleted = await delete_in_batches(maker, InterviewerTrace, InterviewerTrace.created_at, cutoff)
    log.info("trace retention: deleted %d traces older than %s", deleted, cutoff.isoformat())
    return deleted


async def delete_old_ops_rows(
    maker: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    batch_size: int = BATCH_SIZE,
) -> dict[str, int]:
    """OB-3..OB-5: voice timings, ops samples and error events past their retention."""
    now = now or datetime.now(UTC)
    plan: tuple[tuple[str, Any, Any, int], ...] = (
        (
            "voice_turn_timings",
            VoiceTurnTiming,
            VoiceTurnTiming.created_at,
            VOICE_TIMING_RETENTION_DAYS,
        ),
        ("ops_samples", OpsSample, OpsSample.ts, OPS_SAMPLE_RETENTION_DAYS),
        ("error_events", ErrorEvent, ErrorEvent.at, ERROR_EVENT_RETENTION_DAYS),
    )
    out: dict[str, int] = {}
    for name, model, column, days in plan:
        cutoff = now - timedelta(days=days)
        out[name] = await delete_in_batches(maker, model, column, cutoff, batch_size=batch_size)
        log.info("retention: deleted %d %s older than %s", out[name], name, cutoff.isoformat())
    return out


async def purge_deleted_stories(
    maker: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    days: int = STORY_RESTORE_DAYS,
) -> int:
    """CS-16: remove stories deleted more than `days` days before `now`; until then they can be
    restored (CS-15). Returns the stories removed."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    purged = await delete_in_batches(maker, Story, Story.deleted_at, cutoff)
    log.info("story purge: removed %d stories deleted before %s", purged, cutoff.isoformat())
    return purged


PROD_CONTENT_RETENTION_DAYS = 30  # LT-27, D-14
PROD_METADATA_RETENTION_DAYS = 90


async def prune_production_traces() -> dict[str, int]:
    """LT-27: real users' LLM traces in MLflow, while production tracing is on.

    A failure is logged, never raised, so the database retention above still counts as done; the
    next night tries again.
    """
    from strong_core.config import get_settings
    from strong_core.tracing.prod import prune_prod

    settings = get_settings()
    if not (settings.llm_tracing_prod and settings.mlflow_tracking_uri):
        return {}
    try:
        counts = await asyncio.to_thread(
            prune_prod, PROD_CONTENT_RETENTION_DAYS, PROD_METADATA_RETENTION_DAYS
        )
    except Exception:
        log.warning("pruning production traces failed; trying again tomorrow", exc_info=True)
        return {"prod_traces_failed": 1}
    return {f"prod_traces_{k}": v for k, v in counts.items()}


async def trace_retention(ctx: dict[str, Any]) -> dict[str, int]:
    """The Arq cron job: traces (R2), then the ops tables (OB-3..OB-5), then deleted stories
    (CS-16), then real users' LLM traces in MLflow (LT-27)."""
    maker = ctx.get(CTX_KEY) or get_sessionmaker()
    return {
        "deleted": await delete_old_traces(maker),
        **await delete_old_ops_rows(maker),
        "stories": await purge_deleted_stories(maker),
        **await prune_production_traces(),
    }
