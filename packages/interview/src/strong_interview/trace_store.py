"""SqlTraceSink: saves interviewer traces (R2) to the interviewer_traces table in the background.

`write` returns at once: each record is inserted by a background task, one at a time and in
order (a lock), so the interview never waits for the database. Errors are logged and dropped.
Call `flush()` at the end of a session (or in tests) to wait for the pending inserts.

Every insert has a time limit (`timeout_s`, for the shared lock, the database connection and the
insert together). On Postgres it also sets `lock_timeout`, so a row lock wait fails with an
error instead of waiting forever. A trace that is not saved in time is logged and dropped, and
the lock is always released.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import InterviewerTrace
from strong_interview.trace import TraceRecord

log = logging.getLogger(__name__)

DB_WRITE_TIMEOUT_S = 10.0  # the most one trace insert or turn save may wait for the database


async def limit_lock_waits(db: AsyncSession, timeout_s: float) -> None:
    """On Postgres: in this transaction, a lock wait fails after half of `timeout_s`
    (lock_timeout) and a statement after 90% of it (statement_timeout). They are shorter than
    the caller's own time limit, so Postgres names the cause in the error. Other databases are
    left as they are."""
    if db.get_bind().dialect.name != "postgresql":
        return
    lock_ms = max(1, int(timeout_s * 500))
    statement_ms = max(1, int(timeout_s * 900))
    await db.execute(text(f"SET LOCAL lock_timeout = {lock_ms}"))
    await db.execute(text(f"SET LOCAL statement_timeout = {statement_ms}"))


def trace_row(org_id: uuid.UUID, session_id: uuid.UUID, record: TraceRecord) -> InterviewerTrace:
    return InterviewerTrace(
        org_id=org_id,
        session_id=session_id,
        seq=record.seq,
        turn_index=record.turn_index,
        call=record.call,
        move=record.move[:40],
        reason_json=record.reason,
        phase=record.phase,
        elapsed_ms=record.elapsed_ms,
        phase_deadline_ms=record.phase_deadline_ms,
        question_ref=record.question_ref,
        messages_json=record.messages,
        raw_reply=record.raw_reply,
        spoken_text=record.spoken_text,
        model=record.model,
        prompt_refs=",".join(record.prompt_refs)[:500] or None,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        cost_usd=None if record.cost_usd is None else Decimal(f"{record.cost_usd:.6f}"),
        latency_ms=record.latency_ms,
        error=record.error,
        created_at=record.at,
    )


class SqlTraceSink:
    def __init__(
        self,
        maker: async_sessionmaker[AsyncSession],
        org_id: uuid.UUID,
        session_id: uuid.UUID,
        *,
        timeout_s: float = DB_WRITE_TIMEOUT_S,
    ) -> None:
        self._maker = maker
        self.timeout_s = timeout_s
        self._org_id = org_id
        self._session_id = session_id
        # Other writers of the same session may share this lock (the text channel's turn saver),
        # so their transactions never interleave with a trace insert.
        self.lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()

    def write(self, record: TraceRecord) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.warning(
                "no event loop; trace %s of session %s dropped", record.seq, self._session_id
            )
            return
        task = loop.create_task(self._insert(record))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _insert(self, record: TraceRecord) -> None:
        try:
            async with asyncio.timeout(self.timeout_s), self.lock, self._maker() as db:
                await limit_lock_waits(db, self.timeout_s)
                db.add(trace_row(self._org_id, self._session_id, record))
                await db.commit()
        except TimeoutError:
            log.error(
                "trace %s of session %s not saved: the database wait was over %.0f s",
                record.seq,
                self._session_id,
                self.timeout_s,
            )
        except Exception:
            log.warning(
                "could not save trace %s of session %s", record.seq, self._session_id, exc_info=True
            )

    async def flush(self, timeout_s: float | None = None) -> bool:
        """Wait for the inserts that are still running, at most `timeout_s` when given.

        Returns False when some were still running at the limit. They are not cancelled; they
        go on in the background, each within its own time limit.
        """
        loop = asyncio.get_running_loop()
        deadline = None if timeout_s is None else loop.time() + timeout_s
        while self._tasks:
            left = None if deadline is None else deadline - loop.time()
            if left is not None and left <= 0:
                return False
            await asyncio.wait(list(self._tasks), timeout=left)
        return True
