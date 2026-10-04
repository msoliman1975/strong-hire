"""LiveKit Agents STT, LLM and TTS adapters that call the model gateway by role (PL-1).

The voice agent never talks to a model server directly. Each adapter asks the gateway for one
role (stt, interviewer, tts), so MODEL_PROFILE alone decides which models answer.

- GatewaySTT is non-streaming. AgentSession wraps it in a StreamAdapter, so Silero VAD cuts the
  audio and only the final speech segment goes to the gateway.
- GatewayLLM streams the interviewer role's text deltas.
- GatewayTTS is non-streaming per call. AgentSession wraps it in a StreamAdapter that splits the
  reply into sentences, so the first sentence is spoken while the rest is still generated.
  Each sentence streams raw PCM from the gateway as it is rendered.
"""

from __future__ import annotations

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


class GatewaySTT(stt.STT[None]):
    def __init__(self, gateway: ModelGateway) -> None:
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))
        self._gw = gateway

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
        text = await self._gw.transcribe(wav)
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
            capabilities=tts.TTSCapabilities(streaming=False), sample_rate=rate, num_channels=1
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
