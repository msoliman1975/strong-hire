"""Voice agent entry point.

python -m strong_voice                  run the worker (joins every new LiveKit room)
python -m strong_voice download-files   fetch the VAD and turn detector model files
"""

from __future__ import annotations

import asyncio
import logging
import sys

from livekit.agents import AgentServer
from livekit.agents.plugin import Plugin

from strong_core.gateway import get_gateway
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
    profile = get_gateway().profile
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
