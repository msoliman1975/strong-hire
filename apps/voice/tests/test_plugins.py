"""IV-1 and PL-1: the voice agent's STT, LLM and TTS go through the gateway by role."""

from __future__ import annotations

import pytest
from livekit import rtc
from livekit.agents import AgentSession, llm

from strong_core.config import Settings
from strong_core.gateway import ModelGateway, Role, build_gateway
from strong_voice.agent import SpikeInterviewer
from strong_voice.plugins import GatewayLLM, GatewaySTT, GatewayTTS, to_gateway_messages


@pytest.fixture
def fake() -> ModelGateway:
    return build_gateway(Settings(model_profile="fake"))


def _ctx(*items: tuple[str, str]) -> llm.ChatContext:
    ctx = llm.ChatContext.empty()
    for role, text in items:
        ctx.add_message(role=role, content=text)  # type: ignore[arg-type]
    return ctx


def test_messages_map_roles_and_end_with_user() -> None:
    msgs = to_gateway_messages(_ctx(("system", "be brief"), ("user", "hi")))
    assert [m.role for m in msgs] == ["system", "user"]
    greeting = to_gateway_messages(_ctx(("developer", "be brief")))
    assert [m.role for m in greeting] == ["system", "user"]
    assert greeting[-1].prompt_ref == "interviewer/spike_continue.v1"


async def test_stt_transcribes_the_final_segment(fake: ModelGateway) -> None:
    frame = rtc.AudioFrame(bytes(3200), 16000, 1, 1600)
    stt = GatewaySTT(fake)
    assert stt.capabilities.streaming is False
    ev = await stt.recognize(frame)
    assert "migration" in ev.alternatives[0].text


async def test_llm_streams_interviewer_text(fake: ModelGateway) -> None:
    gateway_llm = GatewayLLM(fake)
    assert gateway_llm.model == fake.config.alias_for(Role.INTERVIEWER)
    parts: list[str] = []
    async with gateway_llm.chat(chat_ctx=_ctx(("user", "hello"))) as stream:
        async for chunk in stream:
            if chunk.delta and chunk.delta.content:
                parts.append(chunk.delta.content)
    assert len(parts) > 1
    assert "".join(parts).startswith("Thanks for joining today.")


async def test_tts_streams_pcm_at_registry_rate(fake: ModelGateway) -> None:
    tts = GatewayTTS(fake)
    assert tts.sample_rate == fake.capabilities(Role.TTS).sample_rate
    samples = 0
    async with tts.synthesize("Hello there.") as stream:
        async for ev in stream:
            samples += ev.frame.samples_per_channel
    expected = len("Hello there.") * tts.sample_rate // 100
    # The emitter may pad the last frame with up to one 50 ms frame of silence.
    assert expected <= samples <= expected + tts.sample_rate // 20


async def test_spike_agent_answers_a_text_turn(fake: ModelGateway) -> None:
    async with AgentSession(llm=GatewayLLM(fake)) as session:
        await session.start(SpikeInterviewer())
        result = await session.run(user_input="Hi, I am ready.")
        result.expect.next_event().is_message(role="assistant")


def test_spike_prompt_has_two_questions() -> None:
    agent = SpikeInterviewer()
    assert agent.prompt_ref == "interviewer/spike.v1"
    assert "1. " in agent.instructions
    assert "2. " in agent.instructions
