"""Deep story crafting SC07: light Markdown kept out of everything that needs plain text (SC-18),
and the lighter voice flow on the same engine (SC-16). On the fake model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from strong_api.coach import craft, engine
from strong_api.coach import router as coach_router
from strong_api.markdown import strip_markdown
from strong_api.stories import flow
from strong_core.gateway import ModelGateway
from strong_core.gateway.fake import FakeBackend
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import StoryOutline, StorySection, StoryStyle

from .conftest import sign_in

S = StorySection
INTERNAL = {"x-internal-token": "dev-internal-token"}


def use_fixtures(monkeypatch: pytest.MonkeyPatch, folder: Path) -> None:
    gateway = ModelGateway(fake_models_config(), fake=FakeBackend(folder))
    monkeypatch.setattr(coach_router, "get_gateway", lambda: gateway)
    monkeypatch.setattr(flow, "get_gateway", lambda: gateway)


def set_reply(folder: Path, reply: dict[str, Any]) -> None:
    (folder / "coach" / "CraftReply.json").write_text(json.dumps(reply), encoding="utf-8")


# --- SC-18: plain text where it matters --------------------------------------------------------


def test_sc18_strip_markdown_keeps_the_words() -> None:
    """SC-18, D-14: bold, italic and list marks go; the words and the numbers stay."""
    text = "**I** led the *rollout*:\n- split by country\n1. cut errors from 2% to 0.3%"
    assert strip_markdown(text) == "I led the rollout: split by country cut errors from 2% to 0.3%"


def test_sc18_quotes_match_on_plain_text() -> None:
    """SC-18: a quote matches the candidate's words whatever formatting either side carries."""
    said = engine.normal("**I** split the rollout _by country_ instead of one big switch")
    assert engine.quote_found("I split the rollout by country", said)
    assert engine.quote_found("**I split** the rollout by country", said)


async def test_sc18_a_formatted_answer_fills_slots_and_strova_speaks_plain_text(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-18: a reply typed with Markdown backs plain quotes; Strova's line is stored and sent
    to speech without Markdown; the legacy columns are plain text."""
    use_fixtures(monkeypatch, fake_fixtures)
    set_reply(
        fake_fixtures,
        {
            "message": "**Thank you.** What was the *problem*?",
            "slot_updates": [
                {
                    "section": "situation",
                    "slot": "role",
                    "text": "I was the **tech lead** on checkout.",
                    "quotes": ["I was the tech lead on checkout"],
                }
            ],
        },
    )
    await sign_in(client)
    sid = (await client.post("/coach/sessions", json={"story_style": "star"})).json()
    out = await client.post(
        f"/coach/sessions/{sid['session']['id']}/turns",
        json={"text": "**I was the tech lead** on _checkout_ at Acme."},
    )
    body = out.json()
    assert body["reply"]["message"] == "Thank you. What was the problem?"
    assert body["turns"][1]["text"] == "Thank you. What was the problem?"
    role = body["story"]["outline"]["sections"][0]["slots"]["role"]
    assert role["text"] == "I was the **tech lead** on checkout."  # kept as formatted
    assert body["story"]["context"] == "I was the tech lead on checkout."  # legacy is plain


async def test_sc18_a_typed_slot_with_lists_renders_plain_legacy(client: httpx.AsyncClient) -> None:
    """SC-18, SC-14: a slot typed with bullets and bold keeps its Markdown in the outline and
    renders plain text into the legacy column the scorer and interviewer read."""
    await sign_in(client)
    story = (await client.post("/coach/sessions", json={"story_style": "carl"})).json()["story"]
    text = "**Constraints:**\n- a hard Black Friday date\n- no new budget"
    edit = {"slots": [{"section": "challenge", "slot": "constraints", "text": text}]}
    got = (await client.patch(f"/stories/{story['id']}/outline", json=edit)).json()
    assert got["outline"]["sections"][0]["slots"]["constraints"]["text"] == text
    assert got["context"] == "Constraints: a hard Black Friday date no new budget."


# --- SC-16: the lighter voice flow -----------------------------------------------------------


def test_sc16_voice_follows_up_only_on_required_slots() -> None:
    """SC-16, D-13: on a voice call the engine asks for the required slots only; the context
    slots that text sessions press for are left to each section's open question."""
    o = StoryOutline.empty(StoryStyle.STAR)
    assert [r.slot for r in craft.asks(o, S.SITUATION, voice=True)] == ["role", "problem"]
    assert len(craft.asks(o, S.SITUATION)) == 6
    assert craft.asks(o, S.ACTION, voice=True) == craft.asks(o, S.ACTION)
    assert [r.slot for r in craft.asks(o, S.RESULT, voice=True)] == ["metric"]
    order = []
    section = craft.next_section(o, None, voice=True)
    while section is not None:
        order.append(section)
        section = craft.next_section(o, section, voice=True)
    assert order == [S.SITUATION, S.TASK, S.ACTION, S.RESULT, S.LEARNING]


HEARD = (
    "I was the tech lead on checkout and the payments migration was two weeks late. "
    "I split the rollout by country because a full switch could not be rolled back fast. "
    "Checkout errors dropped from 2% to 0.3% and I learned to cut big launches into small steps."
)


def _q(section: str, slot: str, quote: str, step: int | None = None) -> dict[str, Any]:
    update: dict[str, Any] = {"section": section, "slot": slot, "text": quote, "quotes": [quote]}
    if step is not None:
        update["step"] = step
    return update


async def test_sc16_a_voice_call_crafts_with_a_fake_transcript(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-16, CO-6: the voice agent sends transcribed turns to the internal endpoint; a styled
    voice session runs the same engine, asks for required slots only, skips the flow check
    during the call, and runs it when the call ends."""
    use_fixtures(monkeypatch, fake_fixtures)
    set_reply(
        fake_fixtures,
        {
            "message": "Thank you. Is there anything you want to sharpen?",
            "slot_updates": [
                _q("situation", "role", "I was the tech lead on checkout"),
                _q("situation", "problem", "the payments migration was two weeks late"),
                _q("action", "did", "I split the rollout by country", 0),
                _q("action", "why", "a full switch could not be rolled back fast", 0),
                _q("result", "metric", "Checkout errors dropped from 2% to 0.3%"),
                _q("learning", "lesson", "I learned to cut big launches into small steps"),
            ],
        },
    )
    await sign_in(client)
    body = {"story_style": "star", "channel": "voice", "target_skill": "ownership"}
    started = (await client.post("/coach/sessions", json=body)).json()
    sid = started["session"]["id"]
    assert [s["slot"] for s in started["asking"]["slots"]] == ["role", "problem"]
    url = f"/internal/coach/sessions/{sid}/turns"
    assert (await client.post(url, json={"text": HEARD})).status_code == 403
    response = await client.post(url, json={"text": HEARD}, headers=INTERNAL)  # the transcript
    assert response.status_code == 200, response.text
    out = response.json()
    assert len(out["craft"]["slot_updates"]) == 6
    assert out["flow_flags"] == []  # no flow check during the call
    ended = await client.post(f"/internal/coach/sessions/{sid}/end", headers=INTERNAL)
    assert ended.json()["session"]["status"] == "ended"
    assert ended.json()["flow_flags"], "the flow check runs after the call"


async def test_sc16_classic_voice_sessions_keep_working(client: httpx.AsyncClient) -> None:
    """SC-16, CO-6: a classic voice session keeps the five-part turn."""
    await sign_in(client)
    sid = (await client.post("/coach/sessions", json={"channel": "voice"})).json()["session"]["id"]
    out = await client.post(
        f"/internal/coach/sessions/{sid}/turns",
        json={"text": "At Acme I led the checkout move to the new payments provider."},
        headers=INTERNAL,
    )
    assert out.status_code == 200 and out.json()["craft"] is None
