"""Coach sessions, text (CO-2, CO-3, CO-4, CO-5) on the fake model.

The scripted conversation in SCRIPT has exact recordings in
`packages/core/src/strong_core/gateway/fixtures/coach/<hash>.json`, one per coach reply. A change
to the coach prompts changes the hashes: the conversation test then fails on the first reply's
message, and the recordings need writing again: RECORD_COACH_SCRIPT=1 pytest -k test_record_script.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.coach import engine
from strong_api.coach import router as coach_router  # the module
from strong_api.coach.schemas import AskFor
from strong_core.db.models import CoachSession, CoachTurn
from strong_core.db.models import Story as StoryRow
from strong_core.gateway import ModelGateway, Role
from strong_core.gateway.fake import FakeBackend
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import CoachReply, StoryPart, StoryPartUpdate

from .conftest import sign_in

T1 = (
    "Last year at Acme I was the backend lead when we were moving checkout to the new payments "
    "provider, and the rollout was already two weeks late. Black Friday was a month out and "
    "checkout could not break."
)
T2 = (
    "I took over the cutover plan myself. I split the rollout by country instead of one big "
    "switch, because a full switch could not be rolled back fast."
)
T3 = (
    "We shipped a week before Black Friday and checkout errors dropped from 2% to 0.3%. "
    "I learned to cut big launches into small reversible steps."
)
SCRIPT = (T1, T2, T3)


async def start(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    response = await client.post("/coach/sessions", json=body)
    assert response.status_code == 201, response.text
    out: dict[str, Any] = response.json()
    return out


async def turn(client: httpx.AsyncClient, sid: str, text: str) -> dict[str, Any]:
    response = await client.post(f"/coach/sessions/{sid}/turns", json={"text": text})
    assert response.status_code == 200, response.text
    out: dict[str, Any] = response.json()
    return out


def use_fixtures(monkeypatch: pytest.MonkeyPatch, folder: Path) -> None:
    """The coach API uses a fake gateway that reads fixtures from `folder`."""
    gateway = ModelGateway(fake_models_config(), fake=FakeBackend(folder))
    monkeypatch.setattr(coach_router, "get_gateway", lambda: gateway)


def set_reply(folder: Path, reply: dict[str, Any]) -> None:
    (folder / "coach" / "CoachReply.json").write_text(json.dumps(reply), encoding="utf-8")


# --- CO-2: a text coach session builds one story -----------------------------------------


async def test_co2_scripted_conversation_builds_one_story(client: httpx.AsyncClient) -> None:
    """CO-2, CO-3, CO-4: three turns fill the five parts from the candidate's words, and the
    coach asks for one missing thing each time."""
    await sign_in(client)
    started = await start(client, target_skill="ownership")
    sid = started["session"]["id"]
    assert started["story"]["source"] == "coach"
    assert started["story"]["status"] == "draft"
    assert started["story"]["skills"] == ["ownership"]
    assert started["missing"] == [p.value for p in StoryPart]
    assert started["asking_for"] == "concrete_example"
    [opener] = started["turns"]
    assert opener["speaker"] == "coach"
    assert opener["text"].startswith("Let's build one story that shows ownership")

    one = await turn(client, sid, T1)
    assert one["conduct"] == "ok" and not one["ended"]
    assert one["reply"]["message"] == "Thanks, that sets the scene. What did you do yourself?"
    assert {p["part"] for p in one["reply"]["parts"]} == {"context", "stakes"}
    assert one["story"]["context"] and one["story"]["stakes"]
    assert one["reply"]["missing"] == ["action", "result", "reflection"]
    assert one["asking_for"] == "own_role"
    assert [t["speaker"] for t in one["turns"]] == ["candidate", "coach"]

    two = await turn(client, sid, T2)
    assert [p["part"] for p in two["reply"]["parts"]] == ["action"]
    assert two["asking_for"] == "measurable_result"

    three = await turn(client, sid, T3)
    assert {p["part"] for p in three["reply"]["parts"]} == {"result", "reflection"}
    assert three["reply"]["missing"] == []
    assert three["asking_for"] == "nothing"
    story = three["story"]
    assert all(story[p.value] for p in StoryPart)
    assert "ownership" in story["skills"]

    ended = (await client.post(f"/coach/sessions/{sid}/end")).json()
    assert ended["session"]["status"] == "ended"
    assert ended["session"]["minutes"] >= 0
    assert ended["story"]["id"] == story["id"]
    assert len(ended["turns"]) == 7

    listed = (await client.get(f"/stories/{story['id']}/coach-sessions")).json()
    assert [s["id"] for s in listed] == [sid]


async def test_co2_existing_story_and_session_reads(client: httpx.AsyncClient) -> None:
    """CO-2: a session on an existing story asks for what that story is missing."""
    await sign_in(client)
    first = await start(client)
    sid = first["session"]["id"]
    await turn(client, sid, T1)
    await client.post(f"/coach/sessions/{sid}/end")
    story_id = first["story"]["id"]

    again = await start(client, story_id=story_id, style="direct")
    assert again["story"]["id"] == story_id
    assert again["turns"][0]["text"] == 'Let\'s work on "Untitled story". What did you do yourself?'
    read = (await client.get(f"/coach/sessions/{again['session']['id']}")).json()
    assert read["session"]["style"] == "direct"
    assert read["asking_for"] == "own_role"
    listed = (await client.get(f"/stories/{story_id}/coach-sessions")).json()
    assert len(listed) == 2


async def test_co2_ending_without_a_part_drops_the_new_story(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """CO-2: a new story that got no part is not left in the library."""
    await sign_in(client)
    started = await start(client)
    ended = (await client.post(f"/coach/sessions/{started['session']['id']}/end")).json()
    assert ended["session"]["status"] == "ended"
    assert ended["story"] is None
    async with sessionmaker() as db:
        assert await db.get(StoryRow, uuid.UUID(started["story"]["id"])) is None
    again = await client.post(f"/coach/sessions/{started['session']['id']}/end")
    assert again.status_code == 200  # ending twice is harmless


async def test_co2_turn_after_end_and_other_users(client: httpx.AsyncClient) -> None:
    """CO-2: an ended session takes no turns; another user cannot see the session or story."""
    await sign_in(client)
    started = await start(client)
    sid = started["session"]["id"]
    await turn(client, sid, T1)
    await client.post(f"/coach/sessions/{sid}/end")
    late = await client.post(f"/coach/sessions/{sid}/turns", json={"text": "One more thing."})
    assert late.status_code == 409

    await sign_in(client, "other@example.com")
    assert (await client.get(f"/coach/sessions/{sid}")).status_code == 404
    story_id = started["story"]["id"]
    assert (await client.get(f"/stories/{story_id}/coach-sessions")).status_code == 404
    assert (await client.post("/coach/sessions", json={"story_id": story_id})).status_code == 404
    unknown_job = {"job_target_id": str(uuid.uuid4()), "target_skill": "impact"}
    assert (await client.post("/coach/sessions", json=unknown_job)).status_code == 404


async def test_co2_records_minutes_and_coach_provenance(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """CO-2, PL-6: the session records its model profile, alias, prompt refs and minutes."""
    await sign_in(client)
    started = await start(client)
    sid = started["session"]["id"]
    await turn(client, sid, T1)
    async with sessionmaker() as db:
        row = await db.get(CoachSession, uuid.UUID(sid))
        assert row is not None
        assert row.model_profile == "fake"
        assert row.model_id
        refs = set((row.prompt_version or "").split(","))
        assert {"coach/turn.v1", "coach/turn_input.v1", "coach/style_gentle.v1"} <= refs
        turns = (
            await db.scalars(select(CoachTurn).where(CoachTurn.coach_session_id == row.id))
        ).all()
        assert sorted(t.seq for t in turns) == [1, 2, 3]
    assert engine.session_minutes([CoachTurn(start_ms=0, end_ms=61_000)]) == 2


async def test_co2_internal_turns_need_the_token(client: httpx.AsyncClient) -> None:
    """CO-2, CO-6: the voice agent's endpoints share the turn logic and need the token."""
    await sign_in(client)
    sid = (await start(client, channel="voice"))["session"]["id"]
    url = f"/internal/coach/sessions/{sid}/turns"
    assert (await client.post(url, json={"text": T1})).status_code == 403
    headers = {"x-internal-token": "dev-internal-token"}
    ok = await client.post(url, json={"text": T1}, headers=headers)
    assert ok.status_code == 200
    assert {p["part"] for p in ok.json()["reply"]["parts"]} == {"context", "stakes"}
    end = await client.post(f"/internal/coach/sessions/{sid}/end", headers=headers)
    assert end.json()["session"]["status"] == "ended"


# --- CO-3: parts only from the candidate's words -----------------------------------------


async def test_co3_a_part_is_never_filled_without_a_quote_from_the_candidate(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CO-3: a part whose quote the candidate never said is dropped; the backed one is kept."""
    use_fixtures(monkeypatch, fake_fixtures)
    set_reply(
        fake_fixtures,
        {
            "message": "What did you do yourself?",
            "parts": [
                {
                    "part": "context",
                    "text": "I led the move of checkout to a new payments provider at Acme.",
                    "quotes": ["we were moving checkout to the new payments provider"],
                },
                {
                    "part": "result",
                    "text": "Revenue grew 40% after the launch.",
                    "quotes": ["revenue grew forty percent"],
                },
            ],
            "missing": ["stakes", "action", "reflection"],
            "skills": ["ownership"],
        },
    )
    await sign_in(client)
    sid = (await start(client))["session"]["id"]
    out = await turn(client, sid, T1)
    assert [p["part"] for p in out["reply"]["parts"]] == ["context"]
    assert out["story"]["context"]
    assert out["story"]["result"] is None
    assert "result" in out["reply"]["missing"]


async def test_co3_every_kept_part_quotes_the_candidate(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CO-3: quotes from the coach's own lines, too-short quotes and unquoted numbers fail."""
    use_fixtures(monkeypatch, fake_fixtures)
    set_reply(
        fake_fixtures,
        {
            "message": "Why did it matter?",
            "parts": [
                {  # the coach's opener, not the candidate's words
                    "part": "context",
                    "text": "A specific time at work.",
                    "quotes": ["Tell me about one specific time at work"],
                },
                {  # too short to prove anything
                    "part": "stakes",
                    "text": "Checkout mattered.",
                    "quotes": ["checkout"],
                },
                {  # a number the quote does not have
                    "part": "action",
                    "text": "I moved 3 teams to the new payments provider.",
                    "quotes": ["moving checkout to the new payments provider"],
                },
            ],
            "missing": [],
            "skills": [],
        },
    )
    await sign_in(client)
    sid = (await start(client))["session"]["id"]
    out = await turn(client, sid, T1)
    assert out["reply"]["parts"] == []
    assert all(out["story"][p.value] is None for p in StoryPart)
    assert out["reply"]["missing"] == [p.value for p in StoryPart]


def test_co3_quote_matching() -> None:
    """CO-3: quotes match the candidate's words whatever the case, curly quotes and spacing."""
    said = engine._normal(
        "I" + chr(0x2019) + "d   rolled it back, and Checkout errors dropped to 0.3%."
    )
    assert engine.quote_found("I'd rolled it back", said)
    assert engine.quote_found("checkout errors dropped to 0.3%.", said)
    assert not engine.quote_found("errors dropped", said)  # too short
    assert not engine.quote_found("checkout errors dropped to zero", said)
    update = StoryPartUpdate(
        part=StoryPart.RESULT, text="Errors fell to 0.3%.", quotes=["errors dropped to 0.3%"]
    )
    assert engine.backed(update, said) is None
    bad = update.model_copy(update={"text": "Errors fell to 0.1%."})
    assert engine.backed(bad, said) == "number not in the quotes: 0.1"


def test_co3_contract_rejects_a_part_without_quotes() -> None:
    """CO-3: CoachReply cannot even carry a part without a quote."""
    with pytest.raises(ValueError):
        CoachReply.model_validate(
            {"message": "Hi", "parts": [{"part": "context", "text": "x", "quotes": []}]}
        )


# --- CO-4: one missing thing at a time, by the IV-3 rules --------------------------------


def _story(**parts: str | None) -> StoryRow:
    return StoryRow(title="t", skills=[], **{p.value: parts.get(p.value) for p in StoryPart})


def test_co4_asks_follow_the_iv3_rules() -> None:
    """CO-4: own role, a measurable result, a concrete example, trade-offs, in order."""
    assert engine.asks(_story())[0] == AskFor.CONCRETE_EXAMPLE
    full = {
        "context": "At Acme checkout was late.",
        "stakes": "Black Friday was close.",
        "action": "I split the rollout by country instead of one switch.",
        "result": "Errors dropped from 2% to 0.3%.",
        "reflection": "I learned to ship in small steps.",
    }
    assert engine.asks(_story(**full)) == [AskFor.NOTHING]
    assert engine.asks(_story(**{**full, "stakes": None}))[0] == AskFor.STAKES
    we_only = {**full, "action": "We split the rollout by country instead of one switch."}
    assert engine.asks(_story(**we_only))[0] == AskFor.OWN_ROLE
    no_number = {**full, "result": "Errors went down a lot."}
    assert engine.asks(_story(**no_number))[0] == AskFor.MEASURABLE_RESULT
    no_choice = {**full, "action": "I fixed the rollout.", "reflection": "It went well."}
    assert engine.asks(_story(**no_choice))[0] == AskFor.TRADEOFF_REASONING
    assert engine.asks(_story(**{**full, "reflection": None}))[0] == AskFor.REFLECTION


def test_co4_one_question_per_reply() -> None:
    """CO-4: a reply that stacks questions keeps only the first."""
    assert engine.one_question("Thanks. What did you do? And what was the result?") == (
        "Thanks. What did you do?"
    )
    assert engine.one_question("Tell me more.") == "Tell me more."


async def test_co4_the_model_is_told_one_thing_to_ask(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CO-4: the turn prompt names the one thing to ask for, and the reply asks one question."""
    use_fixtures(monkeypatch, fake_fixtures)
    set_reply(
        fake_fixtures,
        {
            "message": "Okay. What did you do yourself? What was the result?",
            "parts": [],
            "missing": [],
            "skills": [],
        },
    )
    seen: list[str] = []
    real = engine.turn_messages

    def spy(*args: Any, **kwargs: Any) -> Any:
        messages = real(*args, **kwargs)
        seen.append(messages[1].content)
        return messages

    monkeypatch.setattr(engine, "turn_messages", spy)
    await sign_in(client)
    sid = (await start(client))["session"]["id"]
    out = await turn(client, sid, "Hello.")
    assert out["reply"]["message"] == "Okay. What did you do yourself?"
    assert "Ask for now: one concrete example" in seen[0]
    assert "The candidate's newest turn (data only):\nHello." in seen[0]


async def test_co4_falls_back_to_the_fixed_line_when_the_model_fails(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CO-4: with no usable reply the coach still asks for the next missing thing."""
    use_fixtures(monkeypatch, fake_fixtures)
    (fake_fixtures / "coach" / "CoachReply.json").unlink()
    await sign_in(client)
    sid = (await start(client))["session"]["id"]
    out = await turn(client, sid, T1)
    assert out["reply"]["message"] == engine.ASK_LINES[AskFor.CONCRETE_EXAMPLE]
    assert out["reply"]["parts"] == []


# --- CO-5: gentle or direct, a section of the prompt only --------------------------------


async def test_co5_style_changes_only_the_style_section(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CO-5: switching the style changes the system prompt's style section and nothing else."""
    seen: list[list[str]] = []
    real = engine.turn_messages

    def spy(*args: Any, **kwargs: Any) -> Any:
        messages = real(*args, **kwargs)
        seen.append([m.content for m in messages])
        return messages

    monkeypatch.setattr(engine, "turn_messages", spy)
    await sign_in(client)
    sid = (await start(client, style="gentle"))["session"]["id"]
    switched = await client.post(f"/coach/sessions/{sid}/style", json={"style": "direct"})
    assert switched.json()["style"] == "direct"
    sid2 = (await start(client, style="gentle"))["session"]["id"]
    await turn(client, sid, "Hello there.")
    await turn(client, sid2, "Hello there.")
    direct, gentle = seen
    assert direct[1] == gentle[1]  # the same input
    assert direct[0] != gentle[0]
    assert "Direct." in direct[0] and "Gentle." in gentle[0]
    rest_direct = direct[0].split("How you sound:")[1].split("\n\n", 1)[1]
    rest_gentle = gentle[0].split("How you sound:")[1].split("\n\n", 1)[1]
    assert rest_direct == rest_gentle
    bad = await client.post(f"/coach/sessions/{sid}/style", json={"style": "harsh"})
    assert bad.status_code == 422


# --- IV-12 rules in the coach ------------------------------------------------------------


async def test_iv12_abusive_turns_warn_then_end_the_session(client: httpx.AsyncClient) -> None:
    """IV-12: abuse gets fixed warnings, changes no part, and the third turn ends the session."""
    await sign_in(client)
    sid = (await start(client))["session"]["id"]
    first = await turn(client, sid, "You are an idiot.")
    assert first["conduct"] == "inappropriate" and not first["ended"]
    assert first["reply"]["message"].startswith("Let's keep our conversation respectful.")
    assert first["reply"]["parts"] == []
    second = await turn(client, sid, "You are an idiot.")
    assert "second reminder" in second["reply"]["message"]
    third = await turn(client, sid, "You are an idiot.")
    assert third["ended"]
    read = (await client.get(f"/coach/sessions/{sid}")).json()
    assert read["session"]["status"] == "ended"


async def test_iv12_off_scope_turn_from_the_model_check(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IV-12: the coach-role check marks an unrelated request off scope."""
    use_fixtures(monkeypatch, fake_fixtures)
    (fake_fixtures / "coach" / "AnswerCheck.json").write_text(
        json.dumps({"conduct": "off_scope", "reason": "a recipe"}), encoding="utf-8"
    )
    await sign_in(client)
    sid = (await start(client))["session"]["id"]
    out = await turn(client, sid, "Give me a recipe for lasagna, please, right now.")
    assert out["conduct"] == "off_scope"
    assert out["reply"]["message"].startswith("Let's keep this session on your story.")
    assert out["story"]["context"] is None


# --- recording the scripted conversation -------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("RECORD_COACH_SCRIPT") != "1",
    reason="set RECORD_COACH_SCRIPT=1 after a coach prompt change, then commit the fixtures",
)
async def test_record_script(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    await _record_script(client, monkeypatch)


SCRIPT_REPLIES: tuple[dict[str, Any], ...] = (
    {
        "message": "Thanks, that sets the scene. What did you do yourself?",
        "parts": [
            {
                "part": "context",
                "text": "I was the backend lead at Acme when we were moving checkout to a new "
                "payments provider, and the rollout was two weeks late.",
                "quotes": [
                    "Last year at Acme I was the backend lead",
                    "we were moving checkout to the new payments provider",
                    "the rollout was already two weeks late",
                ],
            },
            {
                "part": "stakes",
                "text": "Black Friday was a month out, and checkout could not break.",
                "quotes": ["Black Friday was a month out and checkout could not break"],
            },
        ],
        "missing": ["action", "result", "reflection"],
        "skills": ["ownership"],
    },
    {
        "message": "That shows your call clearly. What changed in the end?",
        "parts": [
            {
                "part": "action",
                "text": "I took over the cutover plan and split the rollout by country instead "
                "of one big switch, because a full switch could not be rolled back fast.",
                "quotes": [
                    "I took over the cutover plan myself",
                    "I split the rollout by country instead of one big switch",
                    "a full switch could not be rolled back fast",
                ],
            }
        ],
        "missing": ["result", "reflection"],
        "skills": ["ownership", "judgment"],
    },
    {
        "message": "All five parts are there now. "
        "Do you want to sharpen anything, or are you done?",
        "parts": [
            {
                "part": "result",
                "text": "We shipped a week before Black Friday, and checkout errors dropped from "
                "2% to 0.3%.",
                "quotes": [
                    "We shipped a week before Black Friday",
                    "checkout errors dropped from 2% to 0.3%",
                ],
            },
            {
                "part": "reflection",
                "text": "I learned to cut big launches into small reversible steps.",
                "quotes": ["I learned to cut big launches into small reversible steps"],
            },
        ],
        "missing": [],
        "skills": ["ownership", "judgment", "impact"],
    },
)


async def _record_script(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Write SCRIPT_REPLIES as exact recordings for the scripted conversation's coach turns."""
    from strong_core.gateway.fake import DEFAULT_FIXTURES_DIR, Recording, messages_hash

    replies = iter(SCRIPT_REPLIES)
    real = engine.turn_messages

    def record(*args: Any, **kwargs: Any) -> Any:
        messages = real(*args, **kwargs)
        recording = Recording(
            role=Role.COACH,
            profile="scripted",  # written by hand for this test, not by a model
            model="scripted",
            output_type="CoachReply",
            messages=messages,
            prompt_refs=[m.prompt_ref for m in messages if m.prompt_ref],
            output=CoachReply.model_validate(next(replies)).model_dump(mode="json"),
            recorded_at="2026-10-27T00:00:00+00:00",
        )
        path = DEFAULT_FIXTURES_DIR / Role.COACH.value / f"{messages_hash(messages)}.json"
        path.write_text(recording.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return messages

    monkeypatch.setattr(engine, "turn_messages", record)
    await sign_in(client)
    sid = (await start(client, target_skill="ownership"))["session"]["id"]
    for text in SCRIPT:
        await turn(client, sid, text)
