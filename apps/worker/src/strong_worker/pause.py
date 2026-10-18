"""OC-5: pause background jobs by kind, for incidents with a model provider.

While a kind is in the runtime setting `jobs_paused`, its jobs wait in the queue instead of
running: the job entry point calls `wait_if_paused` first, which raises arq `Retry` with a 60 s
defer. Paused jobs register with `PAUSED_MAX_TRIES` tries, so they can wait about a day; a job
on its last try runs anyway, so it ends (ready or failed) instead of being dropped by Arq.
"""

from __future__ import annotations

import logging
from typing import Any

from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core import runtime_settings as rs

log = logging.getLogger(__name__)

PAUSED_DEFER_S = 60
PAUSED_MAX_TRIES = 24 * 60  # about a day of 60 s waits


async def is_paused(maker: async_sessionmaker[AsyncSession], kind: rs.JobKind) -> bool:
    try:
        async with maker() as db:
            paused: list[rs.JobKind] = await rs.get(db, rs.SettingKey.JOBS_PAUSED)
    except Exception:
        # The setting cannot be read: run the job rather than hold it.
        log.warning("could not read jobs_paused; running the %s job", kind.value, exc_info=True)
        return False
    return kind in paused


async def wait_if_paused(
    ctx: dict[str, Any], maker: async_sessionmaker[AsyncSession], kind: rs.JobKind
) -> None:
    """Raise Retry(defer=60 s) while `kind` is paused (OC-5)."""
    if not await is_paused(maker, kind):
        return
    job_try = int(ctx.get("job_try") or 1)
    if job_try >= PAUSED_MAX_TRIES:
        log.warning("%s job paused for its whole wait; running it now", kind.value)
        return
    log.info("%s jobs are paused; job %s waits %d s", kind.value, ctx.get("job_id"), PAUSED_DEFER_S)
    raise Retry(defer=PAUSED_DEFER_S)
