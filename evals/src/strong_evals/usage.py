"""Usage metering: every gateway call in an eval session becomes a UsageEvent record.

The records are the same SQLAlchemy UsageEvent objects the app stores (spec, Data model), kept in
memory here. Cost per session is the sum of their cost_usd, like the AD-2 admin view will do.
Prices are planning estimates per gateway alias in evals/config/prices.yaml, never vendor ids.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar, overload

import yaml
from pydantic import BaseModel

from strong_core.db.models import UsageEvent
from strong_core.gateway import Completion, Message, ModelGateway, Role, TokenUsage
from strong_core.schemas import UsageComponent
from strong_evals import EVALS_DIR

OutputT = TypeVar("OutputT", bound=BaseModel)
PRICES_FILE = EVALS_DIR / "config" / "prices.yaml"
EVAL_ORG_ID = uuid.UUID("00000000-0000-4000-8000-0000000e7a15")
WORDS_PER_MINUTE = 150
MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Prices:
    llm_per_mtok: dict[str, tuple[Decimal, Decimal]] = field(default_factory=dict)
    stt_per_minute: dict[str, Decimal] = field(default_factory=dict)
    tts_per_mchar: dict[str, Decimal] = field(default_factory=dict)

    def llm(self, alias: str, usage: TokenUsage) -> Decimal:
        price_in, price_out = self.llm_per_mtok.get(alias, (Decimal(0), Decimal(0)))
        return (usage.input_tokens * price_in + usage.output_tokens * price_out) / MILLION

    def stt(self, alias: str, minutes: Decimal) -> Decimal:
        return minutes * self.stt_per_minute.get(alias, Decimal(0))

    def tts(self, alias: str, chars: int) -> Decimal:
        return chars * self.tts_per_mchar.get(alias, Decimal(0)) / MILLION


def load_prices(path: Path = PRICES_FILE) -> Prices:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Prices(
        llm_per_mtok={
            alias: (Decimal(str(p[0])), Decimal(str(p[1])))
            for alias, p in (data.get("llm_per_mtok") or {}).items()
        },
        stt_per_minute={a: Decimal(str(v)) for a, v in (data.get("stt_per_minute") or {}).items()},
        tts_per_mchar={a: Decimal(str(v)) for a, v in (data.get("tts_per_mchar") or {}).items()},
    )


def usage_event(
    session_id: uuid.UUID, component: UsageComponent, units: Decimal, cost: Decimal
) -> UsageEvent:
    return UsageEvent(
        id=uuid.uuid4(),
        org_id=EVAL_ORG_ID,
        session_id=session_id,
        component=component,
        units=units,
        cost_usd=cost.quantize(Decimal("0.000001")),
    )


class MeteredGateway(ModelGateway):
    """Passes calls to `inner` and appends one UsageEvent per chat call to `events`."""

    def __init__(
        self,
        inner: ModelGateway,
        prices: Prices,
        session_id: uuid.UUID,
        events: list[UsageEvent] | None = None,
    ) -> None:
        super().__init__(inner.config, base_url=inner.base_url)
        self.inner = inner
        self.prices = prices
        self.session_id = session_id
        self.events: list[UsageEvent] = [] if events is None else events
        self.prompt_refs: dict[str, None] = {}

    @property
    def is_fake(self) -> bool:
        return self.inner.is_fake

    @overload
    async def complete(
        self, role: Role, messages: Sequence[Message], output_type: None = None
    ) -> Completion[str]: ...

    @overload
    async def complete(
        self, role: Role, messages: Sequence[Message], output_type: type[OutputT]
    ) -> Completion[OutputT]: ...

    async def complete(
        self,
        role: Role,
        messages: Sequence[Message],
        output_type: type[BaseModel] | None = None,
    ) -> Completion[Any]:
        done: Completion[Any] = await self.inner.complete(role, messages, output_type)
        self._add_llm(done.model, done.usage)
        self.prompt_refs.update(dict.fromkeys(done.prompt_refs))
        return done

    async def stream(self, role: Role, messages: Sequence[Message]) -> AsyncIterator[str]:
        chunks: list[str] = []
        async for chunk in self.inner.stream(role, messages):
            chunks.append(chunk)
            yield chunk
        # Streams report no usage; estimate about 4 characters per token.
        usage = TokenUsage(sum(len(m.content) for m in messages) // 4, len("".join(chunks)) // 4)
        self._add_llm(self.config.alias_for(role), usage)

    async def transcribe(self, audio: bytes, *, filename: str = "audio.wav") -> str:
        return await self.inner.transcribe(audio, filename=filename)

    async def synthesize(self, text: str) -> bytes:
        return await self.inner.synthesize(text)

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        async for chunk in self.inner.synthesize_stream(text):
            yield chunk

    def _add_llm(self, alias: str, usage: TokenUsage) -> None:
        units = Decimal(usage.input_tokens + usage.output_tokens)
        cost = self.prices.llm(alias, usage)
        self.events.append(usage_event(self.session_id, UsageComponent.LLM, units, cost))

    def add_voice_estimate(self, candidate_words: int, interviewer_chars: int) -> None:
        """Text sessions have no audio. Add the STT and TTS a voice session would have used."""
        minutes = Decimal(candidate_words) / WORDS_PER_MINUTE
        stt_alias = self.config.alias_for(Role.STT)
        tts_alias = self.config.alias_for(Role.TTS)
        self.events.append(
            usage_event(
                self.session_id,
                UsageComponent.STT,
                minutes.quantize(Decimal("0.0001")),
                self.prices.stt(stt_alias, minutes),
            )
        )
        self.events.append(
            usage_event(
                self.session_id,
                UsageComponent.TTS,
                Decimal(interviewer_chars),
                self.prices.tts(tts_alias, interviewer_chars),
            )
        )
