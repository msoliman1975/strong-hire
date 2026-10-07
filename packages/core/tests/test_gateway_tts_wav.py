"""synthesize_stream returns raw PCM even when the TTS provider only sends WAV."""

from __future__ import annotations

import io
import wave

import httpx
import pytest

from strong_core.gateway import ModelGateway
from strong_core.gateway.client import GatewayError, _WavHeader
from strong_core.gateway.registry import (
    GatewayEndpoint,
    ModelCapabilities,
    ModelKind,
    ModelsConfig,
)
from strong_core.gateway.types import Role

RATE = 24000
PCM = bytes(range(256)) * 4  # 1024 bytes, 512 samples


def wav_bytes(pcm: bytes = PCM, rate: int = RATE, channels: int = 1, extra: bytes = b"") -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    data = buf.getvalue()
    if not extra:
        return data
    # Put an extra chunk (for example LIST) between "fmt " and "data", as some servers do.
    at = data.index(b"data")
    return data[:at] + extra + data[at:]


def feed(stripper: _WavHeader, data: bytes, size: int) -> bytes:
    return b"".join(stripper.strip(data[i : i + size]) for i in range(0, len(data), size))


@pytest.mark.parametrize("size", [1, 7, 44, 1000])
def test_wav_header_is_removed_in_any_chunk_size(size: int) -> None:
    assert feed(_WavHeader(RATE), wav_bytes(), size) == PCM


def test_extra_chunks_before_data_are_skipped() -> None:
    extra = b"LIST" + (5).to_bytes(4, "little") + b"abcde" + b"\x00"  # odd size is padded
    assert feed(_WavHeader(RATE), wav_bytes(extra=extra), 13) == PCM


def test_raw_pcm_passes_through() -> None:
    assert feed(_WavHeader(RATE), PCM, 100) == PCM


@pytest.mark.parametrize(("rate", "channels"), [(16000, 1), (RATE, 2)])
def test_wrong_wav_format_is_an_error(rate: int, channels: int) -> None:
    with pytest.raises(GatewayError, match="expected 16-bit mono PCM at 24000 Hz"):
        feed(_WavHeader(RATE), wav_bytes(rate=rate, channels=channels), 50)


def _gateway(handler: httpx.MockTransport) -> ModelGateway:
    config = ModelsConfig(
        profile="hosted",
        gateway=GatewayEndpoint(base_url="http://litellm.test/v1"),
        roles={role: f"m-{role.value}" for role in Role},
        models={
            f"m-{role.value}": ModelCapabilities(
                kind=ModelKind.CHAT if role.value not in ("stt", "tts") else ModelKind(role.value),
                json_mode=role.value not in ("stt", "tts"),
                context_window=8192,
                streaming=role == Role.TTS,
                sample_rate=RATE if role == Role.TTS else None,
                options={"response_format": "wav", "voice": "troy"} if role == Role.TTS else {},
            )
            for role in Role
        },
    )
    gw = ModelGateway(config)
    gw._http = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        base_url="http://litellm.test/v1", transport=handler
    )
    return gw


async def test_synthesize_stream_returns_pcm_from_a_wav_response() -> None:
    seen: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, content=wav_bytes(), headers={"content-type": "audio/wav"})

    gw = _gateway(httpx.MockTransport(handle))
    audio = b"".join([chunk async for chunk in gw.synthesize_stream("Hello there.")])
    assert audio == PCM
    assert b'"response_format":"wav"' in seen["body"]  # type: ignore[operator]
