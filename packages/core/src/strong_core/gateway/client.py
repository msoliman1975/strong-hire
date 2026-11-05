"""The model gateway client. strong_core.gateway is the only code allowed to call models.

    gateway = get_gateway()
    done = await gateway.complete(Role.EXTRACTOR, messages, output_type=JobPosting)
    done.output  # a validated JobPosting

Structured outputs go through Pydantic AI with schema validation and one automatic retry, so a
weak model fails loudly. The output mode follows the capability registry: tool calls if the
model supports them, else native JSON mode, else a prompted JSON schema.
"""

from __future__ import annotations

import io
import os
import wave
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, TypeVar, overload

import httpx
from pydantic import BaseModel
from pydantic_ai import Agent, NativeOutput, PromptedOutput, ToolOutput
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from strong_core.config import ModelProfile, Settings, get_settings
from strong_core.gateway import prices
from strong_core.gateway.fake import FakeBackend
from strong_core.gateway.registry import (
    ModelCapabilities,
    ModelsConfig,
    fake_models_config,
    load_models_config,
)
from strong_core.gateway.types import CHAT_ROLES, Completion, Message, Role, TokenUsage
from strong_core.gateway.usage import current_usage_context, report_usage
from strong_core.tracing import (
    NO_CALL,
    GatewayCall,
    content_of,
    current_trace_tags,
    messages_of,
    start_gateway_call,
)

OutputT = TypeVar("OutputT", bound=BaseModel)
OUTPUT_RETRIES = 1


class GatewayError(RuntimeError):
    pass


ModelFactory = Callable[[str, ModelsConfig], Model]


def openai_compatible_model(
    alias: str, config: ModelsConfig, *, base_url: str, api_key: str
) -> Model:
    provider = OpenAIProvider(base_url=base_url, api_key=api_key)
    return OpenAIChatModel(alias, provider=provider)


class ModelGateway:
    def __init__(
        self,
        config: ModelsConfig,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        fake: FakeBackend | None = None,
        model_factory: ModelFactory | None = None,
    ) -> None:
        self.config = config
        self.base_url = (base_url or config.gateway.base_url).rstrip("/")
        env_key = os.environ.get(config.gateway.api_key_env) if config.gateway.api_key_env else None
        self._api_key = api_key or env_key or "not-needed"
        self._fake = fake
        self._model_factory = model_factory

    def with_api_key(self, api_key: str) -> ModelGateway:
        """The same models through another LiteLLM key, for example one with its own budget."""
        return ModelGateway(
            self.config,
            base_url=self.base_url,
            api_key=api_key,
            fake=self._fake,
            model_factory=self._model_factory,
        )

    @property
    def profile(self) -> str:
        return self.config.profile

    @property
    def is_fake(self) -> bool:
        return self._fake is not None

    def capabilities(self, role: Role) -> ModelCapabilities:
        return self.config.capabilities(role)

    # --- chat -------------------------------------------------------------------------------

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
        _require_chat_role(role)
        _require_messages(messages)
        alias = self.config.alias_for(role)
        refs = tuple(dict.fromkeys(m.prompt_ref for m in messages if m.prompt_ref))
        call = self._start_chat(role, alias, refs, messages, output_type)
        try:
            if self._fake is not None:
                output, usage = self._fake.complete(role, messages, output_type)
                retried = False
            else:
                instructions, history, prompt = _split(messages)
                agent: Agent[None, Any] = Agent(
                    self._model(alias),
                    output_type=self._output_spec(role, output_type),
                    instructions=instructions,
                    retries=OUTPUT_RETRIES,
                )
                result = await agent.run(prompt, message_history=history)
                run_usage = result.usage
                usage = TokenUsage(run_usage.input_tokens or 0, run_usage.output_tokens or 0)
                output = result.output
                retried = _needed_retry(result.all_messages())
        except BaseException as exc:
            call.fail(exc)
            raise
        cost = await self._report_chat(role, alias, usage, traced=call is not NO_CALL)
        call.finish(
            _output_for_span(output, call),
            structured_retry=retried if output_type is not None else None,
            **_usage_attributes(usage, cost),
        )
        return Completion(output, role, alias, self.profile, refs, usage)

    async def stream(self, role: Role, messages: Sequence[Message]) -> AsyncIterator[str]:
        """Yield text deltas as they arrive. Used by the live interviewer loop."""
        _require_chat_role(role)
        _require_messages(messages)
        alias = self.config.alias_for(role)
        refs = tuple(dict.fromkeys(m.prompt_ref for m in messages if m.prompt_ref))
        call = self._start_chat(role, alias, refs, messages, None, stream=True)
        parts: list[str] = []
        finished = False
        try:
            if self._fake is not None:
                async for chunk in self._fake.stream(role, messages):
                    call.first_token()
                    parts.append(chunk)
                    yield chunk
                usage = TokenUsage()
            else:
                instructions, history, prompt = _split(messages)
                agent: Agent[None, str] = Agent(self._model(alias), instructions=instructions)
                async with agent.run_stream(prompt, message_history=history) as result:
                    async for delta in result.stream_text(delta=True):
                        call.first_token()
                        parts.append(delta)
                        yield delta
                    run_usage = result.usage
                usage = TokenUsage(run_usage.input_tokens or 0, run_usage.output_tokens or 0)
            finished = True
        except GeneratorExit:
            # A stream the caller stops early (barge-in) is not reported as usage.
            call.finish(_output_for_span("".join(parts), call), stopped_early=True)
            raise
        except BaseException as exc:
            call.fail(exc)
            raise
        if finished:
            cost = await self._report_chat(role, alias, usage, traced=call is not NO_CALL)
            call.finish(_output_for_span("".join(parts), call), **_usage_attributes(usage, cost))

    # --- audio ------------------------------------------------------------------------------

    async def transcribe(self, audio: bytes, *, filename: str = "audio.wav") -> str:
        """Speech to text through the gateway's OpenAI-compatible /audio/transcriptions."""
        alias = self.config.alias_for(Role.STT)
        seconds = _wav_seconds(audio)
        call = self._start_speech(
            Role.STT, alias, {"audio_bytes": len(audio), "audio_seconds": seconds}
        )
        try:
            if self._fake is not None:
                text = self._fake.transcribe(audio)
            else:
                data = {"model": alias, **self.capabilities(Role.STT).options}
                async with self._http() as http:
                    resp = await http.post(
                        "/audio/transcriptions", data=data, files={"file": (filename, audio)}
                    )
                _raise_for(resp, Role.STT)
                text = str(resp.json()["text"]).strip()
        except BaseException as exc:
            call.fail(exc)
            raise
        cost = await self._report_speech(Role.STT, alias, seconds=seconds)
        call.finish(content_of(text, call.content), **_cost_attributes(cost))
        return text

    async def synthesize(self, text: str) -> bytes:
        """Text to speech through the gateway's OpenAI-compatible /audio/speech. Returns WAV."""
        alias = self.config.alias_for(Role.TTS)
        call = self._start_speech(Role.TTS, alias, None, text=text)
        try:
            if self._fake is not None:
                wav = self._fake.synthesize(text)
            else:
                # stream=False: a streamed WAV has no real length in its header.
                body: dict[str, Any] = {
                    "model": alias,
                    "input": text,
                    "response_format": "wav",
                    "stream": False,
                }
                body.update(self.capabilities(Role.TTS).options)
                async with self._http() as http:
                    resp = await http.post("/audio/speech", json=body)
                _raise_for(resp, Role.TTS)
                wav = resp.content
        except BaseException as exc:
            call.fail(exc)
            raise
        cost = await self._report_speech(Role.TTS, alias, characters=len(text))
        call.finish({"audio_bytes": len(wav)}, **_cost_attributes(cost))
        return wav

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Text to speech as raw 16-bit mono PCM at `capabilities(Role.TTS).sample_rate`.

        Chunks arrive as the server renders them when the TTS model has `streaming: true`, so
        the voice loop can play the first chunk before the sentence is finished. A provider that
        only returns WAV can set `response_format: wav` in the model's options: the WAV header
        is removed here, and its sample rate must match the capability registry.
        """
        caps = self.capabilities(Role.TTS)
        if caps.sample_rate is None:
            raise GatewayError("tts model needs sample_rate in the capability registry")
        alias = self.config.alias_for(Role.TTS)
        call = self._start_speech(Role.TTS, alias, None, text=text, stream=True)
        sent = 0
        cost: float | None = None
        try:
            if self._fake is not None:
                cost = await self._report_speech(Role.TTS, alias, characters=len(text))
                for chunk in self._fake.synthesize_pcm(text, caps.sample_rate):
                    call.first_token("first_chunk_ms")
                    sent += len(chunk)
                    yield chunk
            else:
                body: dict[str, Any] = {
                    "model": alias,
                    "input": text,
                    "response_format": "pcm",
                    "stream": caps.streaming,
                }
                body.update(caps.options)
                carry = b""
                wav = _WavHeader(caps.sample_rate)
                async with (
                    self._http() as http,
                    http.stream("POST", "/audio/speech", json=body) as resp,
                ):
                    if resp.is_error:
                        await resp.aread()
                        _raise_for(resp, Role.TTS)
                    # TTS is billed by input characters, so the call counts once the provider
                    # accepts it.
                    cost = await self._report_speech(Role.TTS, alias, characters=len(text))
                    async for chunk in resp.aiter_bytes():
                        data = carry + wav.strip(chunk)
                        cut = len(data) - len(data) % 2  # never split a 16-bit sample
                        carry = data[cut:]
                        if cut:
                            call.first_token("first_chunk_ms")
                            sent += cut
                            yield data[:cut]
        except GeneratorExit:
            call.finish({"audio_bytes": sent}, stopped_early=True, **_cost_attributes(cost))
            raise
        except BaseException as exc:
            call.fail(exc)
            raise
        call.finish({"audio_bytes": sent}, **_cost_attributes(cost))

    # --- usage (OB-2) and tracing (LT-2) ----------------------------------------------------

    async def _report_chat(
        self, role: Role, alias: str, usage: TokenUsage, *, traced: bool = False
    ) -> float | None:
        """Report the call as usage and return its cost (None when the alias has no price)."""
        if current_usage_context() is None and not traced:
            return None
        cost = prices.cost_usd(self.profile, alias, usage)
        if current_usage_context() is not None:
            await report_usage(
                role=role,
                model=alias,
                profile=self.profile,
                units=usage.input_tokens + usage.output_tokens,
                cost_usd=cost,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
        return cost

    async def _report_speech(
        self, role: Role, alias: str, *, seconds: float | None = None, characters: int | None = None
    ) -> float | None:
        cost = prices.speech_cost_usd(self.profile, alias, seconds=seconds, characters=characters)
        if current_usage_context() is not None:
            units = seconds if seconds is not None else characters
            await report_usage(
                role=role, model=alias, profile=self.profile, units=units or 0, cost_usd=cost
            )
        return cost

    def _call_attributes(self, role: Role, alias: str) -> dict[str, Any]:
        tier = self.config.capabilities(role).tier
        return {
            "role": role.value,
            "alias": alias,
            "tier": getattr(tier, "value", tier),
            "model_profile": self.profile,
        }

    def _start_chat(
        self,
        role: Role,
        alias: str,
        refs: tuple[str, ...],
        messages: Sequence[Message],
        output_type: type[BaseModel] | None,
        *,
        stream: bool = False,
    ) -> GatewayCall:
        tags = current_trace_tags()
        if tags is None:
            return NO_CALL
        attributes = self._call_attributes(role, alias)
        attributes.update(
            prompt_refs=list(refs),
            output_type=output_type.__name__ if output_type is not None else None,
            stream=stream or None,
            inputs={"messages": messages_of(messages, tags.content)},
        )
        return start_gateway_call(f"gateway.{role.value}", "CHAT_MODEL", attributes)

    def _start_speech(
        self,
        role: Role,
        alias: str,
        inputs: dict[str, Any] | None,
        *,
        text: str | None = None,
        stream: bool = False,
    ) -> GatewayCall:
        tags = current_trace_tags()
        if tags is None:
            return NO_CALL
        attributes = self._call_attributes(role, alias)
        if text is not None:
            inputs = {"text": content_of(text, tags.content), "characters": len(text)}
        attributes.update(stream=stream or None, inputs=inputs)
        return start_gateway_call(f"gateway.{role.value}", "LLM", attributes)

    # --- internals --------------------------------------------------------------------------

    def _model(self, alias: str) -> Model:
        if self._model_factory is not None:
            return self._model_factory(alias, self.config)
        return openai_compatible_model(
            alias, self.config, base_url=self.base_url, api_key=self._api_key
        )

    def _output_spec(self, role: Role, output_type: type[BaseModel] | None) -> Any:
        if output_type is None:
            return str
        caps = self.capabilities(role)
        if caps.supports_tools:
            return ToolOutput(output_type)
        if caps.json_mode:
            return NativeOutput(output_type)
        return PromptedOutput(output_type)

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self.config.gateway.timeout_s,
        )


def _require_chat_role(role: Role) -> None:
    if role not in CHAT_ROLES:
        raise GatewayError(f"{role.value} is not a chat role; use transcribe() or synthesize()")


def _require_messages(messages: Sequence[Message]) -> None:
    if not messages or messages[-1].role != "user":
        raise GatewayError("messages must end with a user message")


def _split(messages: Sequence[Message]) -> tuple[str | None, list[ModelMessage], str]:
    """System messages become instructions; earlier turns become history; the last is the prompt."""
    system = [m.content for m in messages if m.role == "system"]
    convo = [m for m in messages if m.role != "system"]
    history: list[ModelMessage] = []
    for m in convo[:-1]:
        if m.role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=m.content)]))
        else:
            history.append(ModelResponse(parts=[TextPart(content=m.content)]))
    return ("\n\n".join(system) or None), history, convo[-1].content


def _needed_retry(messages: Sequence[ModelMessage]) -> bool:
    """True when Pydantic AI had to ask the model again (invalid structured output)."""
    return any(
        isinstance(part, RetryPromptPart)
        for m in messages
        if isinstance(m, ModelRequest)
        for part in m.parts
    )


def _output_for_span(output: Any, call: GatewayCall) -> Any:
    if call is NO_CALL:
        return None
    value = output.model_dump(mode="json") if isinstance(output, BaseModel) else output
    return content_of(value, call.content)


def _cost_attributes(cost: float | None) -> dict[str, Any]:
    return {"cost_usd": round(cost, 6) if cost is not None else 0.0, "cost_known": cost is not None}


def _usage_attributes(usage: TokenUsage, cost: float | None) -> dict[str, Any]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        **_cost_attributes(cost),
    }


def _wav_seconds(audio: bytes) -> float | None:
    """Length of a WAV clip in seconds, or None when the bytes are not WAV."""
    try:
        with wave.open(io.BytesIO(audio), "rb") as w:
            rate = w.getframerate()
            return w.getnframes() / rate if rate else None
    except (wave.Error, EOFError):
        return None


def _raise_for(resp: httpx.Response, role: Role) -> None:
    if resp.is_error:
        raise GatewayError(f"{role.value} call failed: HTTP {resp.status_code} {resp.text[:200]}")


def build_gateway(settings: Settings) -> ModelGateway:
    if settings.model_profile == ModelProfile.FAKE:
        return ModelGateway(fake_models_config(), fake=FakeBackend(settings.fake_fixtures_dir))
    config = load_models_config(settings.resolved_config_dir, settings.model_profile.value)
    return ModelGateway(
        config, base_url=settings.model_gateway_url, api_key=settings.model_gateway_api_key
    )


_gateway: ModelGateway | None = None


def get_gateway() -> ModelGateway:
    """Process-wide gateway built from settings (MODEL_PROFILE picks the config file)."""
    global _gateway
    if _gateway is None:
        _gateway = build_gateway(get_settings())
    return _gateway


class _WavHeader:
    """Removes a WAV header from the start of a byte stream; other streams pass through.

    Buffers only until the "data" chunk starts. Raises GatewayError when the WAV is not 16-bit
    mono PCM at the expected sample rate, because the voice loop would play it wrong.
    """

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self._head = b""
        self._done = False

    def strip(self, chunk: bytes) -> bytes:
        if self._done:
            return chunk
        self._head += chunk
        if len(self._head) < 12:
            return b""
        if self._head[:4] != b"RIFF" or self._head[8:12] != b"WAVE":
            self._done = True
            return self._head
        pos = 12
        while pos + 8 <= len(self._head):
            chunk_id = self._head[pos : pos + 4]
            size = int.from_bytes(self._head[pos + 4 : pos + 8], "little")
            if chunk_id == b"data":
                self._done = True
                return self._head[pos + 8 :]
            if chunk_id == b"fmt ":
                if pos + 24 > len(self._head):
                    return b""  # wait for the whole fmt chunk
                self._check_format(self._head[pos + 8 : pos + 24])
            pos += 8 + size + (size % 2)
        return b""

    def _check_format(self, fmt: bytes) -> None:
        audio_format = int.from_bytes(fmt[0:2], "little")
        channels = int.from_bytes(fmt[2:4], "little")
        rate = int.from_bytes(fmt[4:8], "little")
        bits = int.from_bytes(fmt[14:16], "little")
        if (audio_format, channels, rate, bits) != (1, 1, self.sample_rate, 16):
            raise GatewayError(
                f"tts returned WAV with format {audio_format}, {channels} channel(s), {rate} Hz, "
                f"{bits} bit; expected 16-bit mono PCM at {self.sample_rate} Hz"
            )
