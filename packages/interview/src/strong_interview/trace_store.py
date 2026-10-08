"""SqlTraceSink: saves interviewer traces (R2) to the interviewer_traces table in the background.

`write` returns at once: each record is inserted by a background task, one at a time and in
order (a lock), so the interview never waits for the database. Errors are logged and dropped.
Call `flush()` at the end of a session (or in tests) to wait for the pending inserts.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import InterviewerTrace
from strong_interview.trace import TraceRecord

log = logging.getLogger(__name__)


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
    ) -> None:
        self._maker = maker
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
            async with self.lock, self._maker() as db:
                db.add(trace_row(self._org_id, self._session_id, record))
                await db.commit()
        except Exception:
            log.warning(
                "could not save trace %s of session %s", record.seq, self._session_id, exc_info=True
            )

    async def flush(self) -> None:
        """Wait for the inserts that are still running."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
