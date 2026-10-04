"""Voice agent entry point.

python -m strong_voice                  run the worker (joins every new LiveKit room)
python -m strong_voice download-files   fetch the VAD and turn detector model files
"""

from __future__ import annotations

import asyncio
import io
import logging
import sys
import time
import wave
from collections.abc import AsyncIterator, Awaitable, Callable

from livekit.agents import AgentServer
from livekit.agents.plugin import Plugin

from strong_core.gateway import ModelGateway, Role, get_gateway
from strong_core.prompts import load_prompt
from strong_voice.agent import entrypoint, prewarm
from strong_voice.devserver import start_devserver
from strong_voice.settings import get_voice_settings


def download_files() -> int:
    import livekit.plugins.silero
    import livekit.plugins.turn_detector  # noqa: F401  (registers the plugin)

    for plugin in Plugin.registered_plugins:
        print(f"downloading files for {plugin.package}", flush=True)
        plugin.download_files()
    return 0


def _silence_wav(seconds: float = 0.5, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(int(seconds * rate) * 2))
    return buf.getvalue()


async def warm_up(gw: ModelGateway) -> None:
    """Load the interviewer, TTS and STT models before the first room, so turn 1 is not cold.

    The interviewer call sends the spike's system prompt, which also fills the model server's
    prompt cache for it. Failures are logged, not raised: the worker still starts.
    """
    log = logging.getLogger("strong_voice")
    system = load_prompt(Role.INTERVIEWER, "spike").message("system")
    user = load_prompt(Role.INTERVIEWER, "spike_continue").message("user")
    steps: dict[str, Callable[[], Awaitable[object]]] = {
        "interviewer": lambda: _drain(gw.stream(Role.INTERVIEWER, [system, user])),
        "tts": lambda: _drain(gw.synthesize_stream("Hello.")),
        "stt": lambda: gw.transcribe(_silence_wav()),
    }
    for name, step in steps.items():
        start = time.perf_counter()
        try:
            await step()
            log.info("warm-up %s: %.0f ms", name, (time.perf_counter() - start) * 1000)
        except Exception as exc:
            log.warning("warm-up %s failed: %s", name, exc)


async def _drain(stream: AsyncIterator[object]) -> None:
    async for _ in stream:
        pass


def build_server() -> AgentServer:
    settings = get_voice_settings()
    server = AgentServer(
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
        port=settings.voice_worker_port,
        setup_fnc=prewarm,
        num_idle_processes=1,
        initialize_process_timeout=60.0,
    )
    server.rtc_session(entrypoint)
    return server


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args[:1] == ["download-files"]:
        return download_files()
    settings = get_voice_settings()
    gateway = get_gateway()
    profile = gateway.profile
    if not gateway.is_fake:
        asyncio.run(warm_up(gateway))
    start_devserver(settings, profile)
    logging.getLogger("strong_voice").info(
        "voice agent: profile=%s livekit=%s health=:%d",
        profile,
        settings.livekit_url,
        settings.voice_health_port,
    )
    asyncio.run(build_server().run(devmode=settings.env == "dev"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
