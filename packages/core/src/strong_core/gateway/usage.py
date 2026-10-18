"""Usage reporting for every gateway call (admin spec OB-2).

Code that knows whose work a call is sets a usage context; the gateway then reports each
finished call to the usage sink, so no caller can skip it:

    with usage_context(org_id, session_id=session.id):
        done = await gateway.complete(Role.SCORER, messages, output_type=Scorecard)

Without a context nothing is reported, so callers that do not set one behave as before. The
default sink writes one UsageEvent row (with its role) in its own transaction; tests and
special callers replace it with `set_usage_sink`. A failing sink is logged, never raised: usage
reporting must not break an interview.

Cost: chat calls use the token prices in config/litellm.<profile>.yaml. Speech uses
`input_cost_per_second` (stt) or `input_cost_per_character` (tts) from the same model_info
when the provider is metered. No price means cost 0 with cost_known false (D-12).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from strong_core.gateway.types import CHAT_ROLES, Role

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class UsageContext:
    org_id: uuid.UUID
    session_id: uuid.UUID | None = None


@dataclass(frozen=True)
class UsageRecord:
    """One finished gateway call.

    `units` is tokens (input + output) for chat, seconds of audio for stt and characters for
    tts, matching UsageEvent.units. `component` is a UsageComponent value: llm, stt or tts.
    """

    org_id: uuid.UUID
    session_id: uuid.UUID | None
    role: Role
    component: str
    model: str
    profile: str
    units: Decimal
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    cost_known: bool


UsageSink = Callable[[UsageRecord], Awaitable[None]]

_context: ContextVar[UsageContext | None] = ContextVar("strong_usage_context", default=None)


@contextmanager
def usage_context(org_id: uuid.UUID, session_id: uuid.UUID | None = None) -> Iterator[UsageContext]:
    """Report gateway calls made inside this block for `org_id` (and `session_id`, if any)."""
    ctx = UsageContext(org_id, session_id)
    token = _context.set(ctx)
    try:
        yield ctx
    finally:
        _context.reset(token)


def current_usage_context() -> UsageContext | None:
    return _context.get()


def component_for(role: Role) -> str:
    if role == Role.STT:
        return "stt"
    if role == Role.TTS:
        return "tts"
    if role in CHAT_ROLES:
        return "llm"
    raise ValueError(f"no usage component for role {role.value}")


def make_db_usage_sink(maker: async_sessionmaker[AsyncSession]) -> UsageSink:
    """A sink that writes one UsageEvent per call, in its own transaction."""

    async def sink(record: UsageRecord) -> None:
        from strong_core.db.models import UsageEvent
        from strong_core.schemas.enums import UsageComponent

        async with maker() as db:
            db.add(
                UsageEvent(
                    org_id=record.org_id,
                    session_id=record.session_id,
                    component=UsageComponent(record.component),
                    units=record.units,
                    cost_usd=record.cost_usd,
                    role=record.role.value,
                    cost_known=record.cost_known,
                )
            )
            await db.commit()

    return sink


async def db_usage_sink(record: UsageRecord) -> None:
    """The default sink: UsageEvent rows through strong_core.db.get_sessionmaker()."""
    from strong_core.db.engine import get_sessionmaker

    await make_db_usage_sink(get_sessionmaker())(record)


_sink: UsageSink | None = db_usage_sink


def set_usage_sink(sink: UsageSink | None) -> UsageSink | None:
    """Replace the sink (None turns reporting off). Returns the previous one."""
    global _sink
    previous, _sink = _sink, sink
    return previous


def get_usage_sink() -> UsageSink | None:
    return _sink


def _money(value: float) -> Decimal:
    return Decimal(f"{value:.6f}")


async def report_usage(
    *,
    role: Role,
    model: str,
    profile: str,
    units: float,
    cost_usd: float | None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """Send one call to the sink when a usage context is set. Never raises."""
    ctx = _context.get()
    sink = _sink
    if ctx is None or sink is None:
        return
    record = UsageRecord(
        org_id=ctx.org_id,
        session_id=ctx.session_id,
        role=role,
        component=component_for(role),
        model=model,
        profile=profile,
        units=Decimal(str(units)),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=_money(cost_usd or 0.0),
        cost_known=cost_usd is not None,
    )
    try:
        await sink(record)
    except Exception:
        log.warning("usage sink failed for %s", role.value, exc_info=True)
