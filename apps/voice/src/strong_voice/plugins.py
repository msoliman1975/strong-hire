"""LiveKit Agents STT, LLM and TTS adapters that call the model gateway by role (PL-1).

The voice agent never talks to a model server directly. Each adapter asks the gateway for one
role (stt, interviewer, tts), so MODEL_PROFILE alone decides which models answer.

- GatewaySTT is non-streaming. AgentSession wraps it in a StreamAdapter, so Silero VAD cuts the
  audio and only the final speech segment goes to the gateway.
- GatewayLLM streams the interviewer role's text deltas.
- GatewayTTS streams. It splits the text into phrases as it arrives (split_phrases) and renders
  them one after another, so the first phrase plays while the next ones render. The first phrase
  may end at a comma, so the candidate hears the interviewer sooner; later phrases end at
  sentences, which sound more natural. Each phrase streams raw PCM from the gateway.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from typing import Any

from livekit import rtc
from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    LanguageCode,
    NotGivenOr,
    llm,
    stt,
    tts,
    utils,
)
from livekit.agents.llm import ChatContext, Tool, ToolChoice

from strong_core.gateway import Message, ModelGateway, Role
from strong_core.prompts import load_prompt

PROVIDER = "strong-gateway"

# A phrase ends after . ! ? (a sentence) or , ; : (a clause), followed by a space.
_SENTENCE_END = re.compile(r"[.!?]+[\"')\]]*\s")
_CLAUSE_END = re.compile(r"[,;:]\s")
# The first phrase may end at a clause once it has this many characters, to start audio sooner.
FIRST_PHRASE_MIN_CHARS = 12
# A later phrase ends at a clause only when no sentence end comes within this many characters.
LONG_PHRASE_CHARS = 140


def split_phrases(buffer: str, *, first: bool) -> tuple[list[str], str]:
    """Complete phrases at the start of `buffer`, and the rest (not complete yet).

    `first` is True until the first phrase of the reply is out.
    """
    phrases: list[str] = []
    rest = buffer
    while True:
        cut = None
        sentence = _SENTENCE_END.search(rest)
        if first or (sentence is None and len(rest) > LONG_PHRASE_CHARS):
            for clause in _CLAUSE_END.finditer(rest):
                if clause.end() >= FIRST_PHRASE_MIN_CHARS:
                    cut = clause.end()
                    break
        if sentence is not None and (cut is None or sentence.end() < cut):
            cut = sentence.end()
        if cut is None:
            return phrases, rest
        phrase, rest = rest[:cut].strip(), rest[cut:]
        if phrase:
            phrases.append(phrase)
            first = False


class GatewaySTT(stt.STT[None]):
    """on_recognized(seconds) reports each transcription's duration, for the latency CSV."""

    def __init__(
        self, gateway: ModelGateway, on_recognized: Callable[[float], None] | None = None
    ) -> None:
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))
        self._gw = gateway
        self._on_recognized = on_recognized

    @property
    def model(self) -> str:
        return self._gw.config.alias_for(Role.STT)

    @property
    def provider(self) -> str:
        return PROVIDER

    async def _recognize_impl(
        self,
        buffer: utils.AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        wav = rtc.combine_audio_frames(buffer).to_wav_bytes()
        start = time.perf_counter()
        text = await self._gw.transcribe(wav)
        if self._on_recognized is not None:
            self._on_recognized(time.perf_counter() - start)
        lang = self._gw.capabilities(Role.STT).options.get("language", "en")
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(language=LanguageCode(lang), text=text)],
        )


def to_gateway_messages(chat_ctx: ChatContext) -> list[Message]:
    """LiveKit chat items to gateway messages. Developer and system text become system."""
    messages: list[Message] = []
    for item in chat_ctx.items:
        if item.type != "message":
            continue
        text = (item.text_content or "").strip()
        if not text:
            continue
        role = "system" if item.role in ("system", "developer") else item.role
        messages.append(Message(role=role, content=text))
    if not messages or messages[-1].role != "user":
        # The agent speaks first (greeting) or continues; the gateway needs a user turn last.
        messages.append(load_prompt(Role.INTERVIEWER, "spike_continue").message("user"))
    return messages


class GatewayLLM(llm.LLM[None]):
    def __init__(self, gateway: ModelGateway, role: Role = Role.INTERVIEWER) -> None:
        super().__init__()
        self._gw = gateway
        self._role = role

    @property
    def model(self) -> str:
        return self._gw.config.alias_for(self._role)

    @property
    def provider(self) -> str:
        return PROVIDER

    def chat(
        self,
        *,
        chat_ctx: ChatContext,
        tools: list[Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> llm.LLMStream:
        return _GatewayLLMStream(
            self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options
        )


class _GatewayLLMStream(llm.LLMStream):
    async def _run(self) -> None:
        assert isinstance(self._llm, GatewayLLM)
        request_id = utils.shortuuid("gw_")
        messages = to_gateway_messages(self._chat_ctx)
        async for delta in self._llm._gw.stream(self._llm._role, messages):
            if delta:
                chunk = llm.ChatChunk(
                    id=request_id, delta=llm.ChoiceDelta(role="assistant", content=delta)
                )
                self._event_ch.send_nowait(chunk)


class GatewayTTS(tts.TTS[None]):
    def __init__(self, gateway: ModelGateway) -> None:
        rate = gateway.capabilities(Role.TTS).sample_rate
        if rate is None:
            raise ValueError("the tts model needs sample_rate in the capability registry")
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True), sample_rate=rate, num_channels=1
        )
        self._gw = gateway

    @property
    def model(self) -> str:
        return self._gw.config.alias_for(Role.TTS)

    @property
    def provider(self) -> str:
        return PROVIDER

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        return _GatewayChunkedStream(tts=self, input_text=text, conn_options=conn_options)

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.SynthesizeStream:
        return _GatewaySynthesizeStream(tts=self, conn_options=conn_options)


class _GatewayChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        assert isinstance(self._tts, GatewayTTS)
        output_emitter.initialize(
            request_id=utils.shortuuid("gw_"),
            sample_rate=self._tts.sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
            frame_size_ms=50,
        )
        async for chunk in self._tts._gw.synthesize_stream(self._input_text):
            output_emitter.push(chunk)
        output_emitter.flush()


class _GatewaySynthesizeStream(tts.SynthesizeStream):
    """Text in (in pieces), audio out by phrase. Phrases render in order, one at a time."""

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        assert isinstance(self._tts, GatewayTTS)
        gateway = self._tts._gw
        output_emitter.initialize(
            request_id=utils.shortuuid("gw_"),
            sample_rate=self._tts.sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
            frame_size_ms=50,
            stream=True,
        )
        output_emitter.start_segment(segment_id=utils.shortuuid())
        phrases: asyncio.Queue[str | None] = asyncio.Queue()

        async def read_text() -> None:
            buffer, first = "", True
            async for data in self._input_ch:
                if isinstance(data, self._FlushSentinel):
                    ready, buffer = split_phrases(buffer + " ", first=first)
                    ready += [buffer.strip()] if buffer.strip() else []
                    buffer = ""
                else:
                    ready, buffer = split_phrases(buffer + data, first=first)
                for phrase in ready:
                    first = False
                    phrases.put_nowait(phrase)
            ready, rest = split_phrases(buffer + " ", first=first)
            for phrase in [*ready, rest.strip()]:
                if phrase:
                    phrases.put_nowait(phrase)
            phrases.put_nowait(None)

        async def render() -> None:
            while (phrase := await phrases.get()) is not None:
                self._mark_started()
                async for chunk in gateway.synthesize_stream(phrase):
                    output_emitter.push(chunk)
                output_emitter.flush()

        tasks = [asyncio.create_task(read_text()), asyncio.create_task(render())]
        try:
            await asyncio.gather(*tasks)
        finally:
            await utils.aio.cancel_and_wait(*tasks)
