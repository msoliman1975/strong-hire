"""Smoke test for all six roles against the profile in MODEL_PROFILE (PL-1).

    uv run python -m strong_core.gateway.smoke            # uses MODEL_PROFILE
    uv run python -m strong_core.gateway.smoke --profile hosted

Chat roles answer one structured question, so the output mode from the capability registry is
exercised. The interviewer role also streams. TTS speaks a sentence and STT must hear it back.
Exit code 0 when every role passes, 1 when one fails, 2 when the profile was skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import time
import wave
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from strong_core.config import ModelProfile, Settings
from strong_core.gateway.client import ModelGateway, build_gateway
from strong_core.gateway.types import CHAT_ROLES, Role

SPOKEN = "The quick brown fox jumps over the lazy dog."
HEARD_WORDS = ("fox", "dog")


class SmokeAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: int


@dataclass(frozen=True)
class RoleResult:
    role: Role
    ok: bool
    ms: float
    detail: str


async def _chat(gw: ModelGateway, role: Role) -> RoleResult:
    from strong_core.prompts import load_prompt  # late import: prompts imports the gateway

    system = load_prompt("smoke", "system")
    question = load_prompt("smoke", "check")
    messages = [system.message("system"), question.message("user", a=2, b=3)]
    start = time.perf_counter()
    try:
        done = await gw.complete(role, messages, output_type=SmokeAnswer)
        detail = f"answer={done.output.answer}"
        ok = gw.is_fake or done.output.answer == 5
        if ok and role == Role.INTERVIEWER:
            chunks = [c async for c in gw.stream(role, messages)]
            ok = bool("".join(chunks).strip())
            detail += f", streamed {len(chunks)} chunks"
    except Exception as exc:
        return RoleResult(role, False, _ms(start), f"{type(exc).__name__}: {exc}"[:300])
    return RoleResult(role, ok, _ms(start), detail)


async def _audio(gw: ModelGateway) -> list[RoleResult]:
    start = time.perf_counter()
    try:
        wav = await gw.synthesize(SPOKEN)
        seconds = _wav_seconds(wav)
    except Exception as exc:
        failed = RoleResult(Role.TTS, False, _ms(start), f"{type(exc).__name__}: {exc}"[:300])
        skipped = RoleResult(Role.STT, False, 0.0, "not run: tts failed")
        return [failed, skipped]
    tts = RoleResult(Role.TTS, seconds > 0.2, _ms(start), f"{seconds:.1f} s of audio")

    start = time.perf_counter()
    try:
        text = await gw.transcribe(wav)
    except Exception as exc:
        return [tts, RoleResult(Role.STT, False, _ms(start), f"{type(exc).__name__}: {exc}"[:300])]
    heard = gw.is_fake or all(w in text.lower() for w in HEARD_WORDS)
    return [tts, RoleResult(Role.STT, heard, _ms(start), f"heard {text[:80]!r}")]


async def run_smoke(gw: ModelGateway) -> list[RoleResult]:
    chat = [await _chat(gw, role) for role in sorted(CHAT_ROLES)]
    return chat + await _audio(gw)


def _wav_seconds(data: bytes) -> float:
    """Duration from the byte count, not the header: a streamed WAV header has no real length."""
    with wave.open(io.BytesIO(data)) as w:
        rate, width, channels = w.getframerate(), w.getsampwidth(), w.getnchannels()
    pcm_bytes = len(data) - 44  # canonical WAV header size
    return max(pcm_bytes, 0) / float(rate * width * channels)


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", choices=[p.value for p in ModelProfile])
    args = parser.parse_args(argv)
    settings = Settings(model_profile=args.profile) if args.profile else Settings()
    gw = build_gateway(settings)
    missing = gw.config.gateway.missing_env()
    if missing:
        print(f"SKIP profile={gw.profile}: set {', '.join(missing)} to run it")
        return 2
    results = asyncio.run(run_smoke(gw))
    print(f"profile={gw.profile} gateway={gw.base_url}")
    for r in results:
        alias = gw.config.alias_for(r.role)
        status = "PASS" if r.ok else "FAIL"
        print(f"  {status}  {r.role.value:<11} {alias:<22} {r.ms:8.0f} ms  {r.detail}")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
