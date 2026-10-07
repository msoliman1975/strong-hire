"""The model gateway client. strong_core.gateway is the only code allowed to call models.

    gateway = get_gateway()
    done = await gateway.complete(Role.EXTRACTOR, messages, output_type=JobPosting)
    done.output  # a validated JobPosting

Structured outputs go through Pydantic AI with schema validation and one automatic retry, so a
weak model fails loudly. The output mode follows the capability registry: tool calls if the
model supports them, else native JSON mode, else a prompted JSON schema.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, TypeVar, overload

import httpx
from pydantic import BaseModel
from pydantic_ai import Agent, NativeOutput, PromptedOutput, ToolOutput
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from strong_core.config import ModelProfile, Settings, get_settings
from strong_core.gateway.fake import FakeBackend
from strong_core.gateway.registry import (
    ModelCapabilities,
    ModelsConfig,
    fake_models_config,
    load_models_config,
)
from strong_core.gateway.types import CHAT_ROLES, Completion, Message, Role, TokenUsage

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

        if self._fake is not None:
            output, usage = self._fake.complete(role, messages, output_type)
            return Completion(output, role, alias, self.profile, refs, usage)

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
        return Completion(result.output, role, alias, self.profile, refs, usage)

    async def stream(self, role: Role, messages: Sequence[Message]) -> AsyncIterator[str]:
        """Yield text deltas as they arrive. Used by the live interviewer loop."""
        _require_chat_role(role)
        _require_messages(messages)
        if self._fake is not None:
            async for chunk in self._fake.stream(role, messages):
                yield chunk
            return

        instructions, history, prompt = _split(messages)
        agent: Agent[None, str] = Agent(
            self._model(self.config.alias_for(role)), instructions=instructions
        )
        async with agent.run_stream(prompt, message_history=history) as result:
            async for delta in result.stream_text(delta=True):
                yield delta

    # --- audio ------------------------------------------------------------------------------

    async def transcribe(self, audio: bytes, *, filename: str = "audio.wav") -> str:
        """Speech to text through the gateway's OpenAI-compatible /audio/transcriptions."""
        if self._fake is not None:
            return self._fake.transcribe(audio)
        alias = self.config.alias_for(Role.STT)
        data = {"model": alias, **self.capabilities(Role.STT).options}
        async with self._http() as http:
            resp = await http.post(
                "/audio/transcriptions", data=data, files={"file": (filename, audio)}
            )
        _raise_for(resp, Role.STT)
        return str(resp.json()["text"]).strip()

    async def synthesize(self, text: str) -> bytes:
        """Text to speech through the gateway's OpenAI-compatible /audio/speech. Returns WAV."""
        if self._fake is not None:
            return self._fake.synthesize(text)
        alias = self.config.alias_for(Role.TTS)
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
        return resp.content

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
        if self._fake is not None:
            for chunk in self._fake.synthesize_pcm(text, caps.sample_rate):
                yield chunk
            return
        body: dict[str, Any] = {
            "model": self.config.alias_for(Role.TTS),
            "input": text,
            "response_format": "pcm",
            "stream": caps.streaming,
        }
        body.update(caps.options)
        carry = b""
        wav = _WavHeader(caps.sample_rate)
        async with self._http() as http, http.stream("POST", "/audio/speech", json=body) as resp:
            if resp.is_error:
                await resp.aread()
                _raise_for(resp, Role.TTS)
            async for chunk in resp.aiter_bytes():
                data = carry + wav.strip(chunk)
                cut = len(data) - len(data) % 2  # never split a 16-bit sample
                carry = data[cut:]
                if cut:
                    yield data[:cut]

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
