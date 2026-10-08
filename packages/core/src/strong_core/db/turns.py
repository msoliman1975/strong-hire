"""The order of transcript turns.

Two turns can have the same start_ms and end_ms (text turns, or a fixed line said right after a
reply), and ids are random. So each turn gets `seq`, its place in the session, when it is saved,
and readers order by `seq` first. Each session has one writer at a time (the voice agent or the
text session API), so max + 1 inside the insert's transaction is enough.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import Turn

# Use with .order_by(*TURN_ORDER). The other columns order rows saved before seq existed.
TURN_ORDER = (Turn.seq, Turn.start_ms, Turn.end_ms, Turn.id)


async def next_turn_seq(db: AsyncSession, session_id: uuid.UUID) -> int:
    current = await db.scalar(select(func.max(Turn.seq)).where(Turn.session_id == session_id))
    return int(current or 0) + 1
