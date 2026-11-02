"""Deep story crafting SC06: the flow check (SC-9) and skill hints (SC-8). Both are advisory.
On the fake model: coach/FlowCheck.json has one flag of each type, citing the checkout story."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.coach import router as coach_router
from strong_api.stories import flow
from strong_core.db.models import JobTarget, RoleStoryFit
from strong_core.db.models import Story as StoryRow
from strong_core.gateway import ModelGateway
from strong_core.gateway.fake import FakeBackend
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import Competency, FlowFlagType, SkillHint

from .conftest import sign_in
from .test_story_crafting_api import CRAFT_SCRIPT, start, turn
from .test_story_page_api import organized

FLAG_TYPES = {t.value for t in FlowFlagType}


def use_fixtures(monkeypatch: pytest.MonkeyPatch, folder: Path) -> None:
    gateway = ModelGateway(fake_models_config(), fake=FakeBackend(folder))
    monkeypatch.setattr(flow, "get_gateway", lambda: gateway)


async def check(client: httpx.AsyncClient, sid: str) -> dict[str, Any]:
    response = await client.post(f"/stories/{sid}/flow-check")
    assert response.status_code == 200, response.text
    out: dict[str, Any] = response.json()
    return out


# --- SC-9: the flow check ---------------------------------------------------------------------


async def test_sc9_each_flag_type_round_trips(client: httpx.AsyncClient) -> None:
    """SC-9: the check returns flags of all five types, each citing slots and asking a question;
    the story keeps them, and every read shows them."""
    await sign_in(client)
    story = await organized(client)
    out = await check(client, story["id"])
    assert {f["type"] for f in out["flow_flags"]} == FLAG_TYPES
    assert all(f["slots"] and f["question"] for f in out["flow_flags"])
    again = (await client.get(f"/stories/{story['id']}")).json()
    assert again["flow_flags"] == out["flow_flags"]


async def test_sc9_flags_never_change_the_status(client: httpx.AsyncClient) -> None:
    """SC-9, D-9: flags are advisory; the status is the same before and after a check."""
    await sign_in(client)
    story = await organized(client)
    assert story["display_status"] == "ready"
    out = await check(client, story["id"])
    assert out["flow_flags"] and out["display_status"] == "ready" and out["status"] == "draft"


async def test_sc9_a_dismissed_flag_returns_only_when_its_slot_changes(
    client: httpx.AsyncClient,
) -> None:
    """SC-9: Dismiss hides a flag through later checks; editing a slot it cites brings it back."""
    await sign_in(client)
    story = await organized(client)
    sid = story["id"]
    await check(client, sid)
    key = "loose_end:situation.problem"
    out = (await client.post(f"/stories/{sid}/flow-flags/{key}/dismiss")).json()
    assert key not in {f["key"] for f in out["flow_flags"]}
    out = await check(client, sid)
    assert key not in {f["key"] for f in out["flow_flags"]}
    edit = {"slots": [{"section": "situation", "slot": "role", "text": "I led checkout."}]}
    out = (await client.patch(f"/stories/{sid}/outline", json=edit)).json()
    assert key not in {f["key"] for f in out["flow_flags"]}  # it cites the problem, not the role
    edit = {"slots": [{"section": "situation", "slot": "problem", "text": "We were late."}]}
    out = (await client.patch(f"/stories/{sid}/outline", json=edit)).json()
    assert key in {f["key"] for f in out["flow_flags"]}
    missing = await client.post(f"/stories/{sid}/flow-flags/nope/dismiss")
    assert missing.status_code == 404


async def test_sc9_flags_on_empty_slots_or_with_new_numbers_are_dropped(
    client: httpx.AsyncClient, fake_fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-9, D-9: a flag must cite slots with text, and its question never adds a number."""
    use_fixtures(monkeypatch, fake_fixtures)
    question = "Your result and your problem disagree. Which is right?"
    flags = [
        {
            "key": "loose_end:learning.since",
            "type": "loose_end",
            "slots": [{"section": "learning", "slot": "since"}],
            "question": question,
        },
        {
            "key": "number_conflict:result.metric",
            "type": "number_conflict",
            "slots": [{"section": "result", "slot": "metric"}],
            "question": "Was it really 17 percent?",
        },
        {
            "key": "result_vs_problem:situation.problem:result.metric",
            "type": "result_vs_problem",
            "slots": [
                {"section": "situation", "slot": "problem"},
                {"section": "result", "slot": "metric"},
            ],
            "question": question,
        },
    ]
    (fake_fixtures / "coach" / "FlowCheck.json").write_text(
        json.dumps({"flags": flags}), encoding="utf-8"
    )
    await sign_in(client)
    story = await organized(client)
    out = await check(client, story["id"])
    assert [f["key"] for f in out["flow_flags"]] == [
        "result_vs_problem:situation.problem:result.metric"
    ]


async def test_sc9_a_classic_story_has_no_flow_check(client: httpx.AsyncClient) -> None:
    """SC-9: the flow check is for organized stories; a classic one is 409."""
    await sign_in(client)
    plain = (await client.post("/stories", json={"title": "x", "context": "y"})).json()
    response = await client.post(f"/stories/{plain['id']}/flow-check")
    assert response.status_code == 409 and plain["flow_flags"] == [] and plain["hints"] == []


async def test_sc9_the_check_runs_when_the_core_slots_fill_in_a_session(
    client: httpx.AsyncClient,
) -> None:
    """SC-9: the turn that makes the story Ready runs the check; its flags come back with it."""
    await sign_in(client)
    sid = (await start(client, target_skill="ownership", story_style="star"))["session"]["id"]
    out: dict[str, Any] = {}
    for text in CRAFT_SCRIPT[:-1]:
        out = await turn(client, sid, text)
        assert out["flow_flags"] == []
    out = await turn(client, sid, CRAFT_SCRIPT[-1])
    assert {f["type"] for f in out["flow_flags"]} == FLAG_TYPES
    detail = (await client.get(f"/coach/sessions/{sid}")).json()
    assert detail["flow_flags"] == out["flow_flags"]


async def test_sc9_review_runs_the_check(client: httpx.AsyncClient) -> None:
    """SC-9: Review with Strova also checks a Ready styled story's flow."""
    await sign_in(client)
    story = await organized(client)
    assert story["flow_flags"] == []
    assert (await client.post(f"/stories/{story['id']}/review")).status_code == 202
    got = (await client.get(f"/stories/{story['id']}")).json()
    assert {f["type"] for f in got["flow_flags"]} == FLAG_TYPES


# --- SC-8: skill hints ------------------------------------------------------------------------


def _row(**extra: Any) -> StoryRow:
    return StoryRow(id=uuid.uuid4(), skills=["ownership"], hints_json=None, **extra)


def _hint(skill: str, reason: str = "You brought the leads along.") -> SkillHint:
    return SkillHint(skill=Competency(skill), reason=reason)


def test_sc8_hints_are_ordered_by_gaps_and_capped_at_three() -> None:
    """SC-8, D-8: gap skills of the target roles first, in gap order; at most three; never a
    skill the story is tagged with; a reason that adds a number is dropped."""
    row = _row()
    new = [
        _hint("collaboration"),
        _hint("judgment"),
        _hint("ownership"),  # already tagged
        _hint("communication"),
        _hint("impact", "It saved 40 percent."),  # a number the user never gave
        _hint("conflict_handling"),
    ]
    gaps = [Competency.CONFLICT_HANDLING, Competency.COMMUNICATION]
    out = flow.merge_hints(row, new, gaps, said="we were late")
    assert [h.skill.value for h in out] == ["conflict_handling", "communication", "collaboration"]
    assert len(flow.open_hints(row)) == 3


def test_sc8_a_dismissed_hint_does_not_come_back() -> None:
    """SC-8: Not now is remembered; the same skill is not offered again."""
    row = _row()
    flow.merge_hints(row, [_hint("judgment")], [], said="")
    flow._set_hint(row, Competency.JUDGMENT, flow.HINT_DISMISSED)
    assert flow.merge_hints(row, [_hint("judgment")], [], said="") == []


async def test_sc8_hints_come_from_the_ready_turn_gaps_first(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """SC-8: once the core slots are filled, the craft turn's hints are stored, gap skills of
    the user's target roles first; Deepen tags the skill and Not now dismisses."""
    await sign_in(client)
    story = await organized(client)
    sid = story["id"]
    async with sessionmaker() as db:
        row = await db.get(StoryRow, uuid.UUID(sid))
        assert row is not None
        target = JobTarget(org_id=row.org_id, user_id=row.user_id, raw_text="Staff engineer")
        db.add(target)
        await db.flush()
        fit = {
            "items": [
                {
                    "competency": "collaboration",
                    "story_id": None,
                    "strength": "missing",
                    "reason": "No story shows it.",
                }
            ]
        }
        db.add(
            RoleStoryFit(
                org_id=row.org_id,
                user_id=row.user_id,
                job_target_id=target.id,
                input_hash="x" * 64,
                model_profile="fake",
                prompt_version="planner/story_fit.v1",
                computed_at=datetime.now(UTC),
                fit_json=fit,
            )
        )
        await db.commit()
    gateway = ModelGateway(fake_models_config(), fake=FakeBackend(fake_fixtures))
    monkeypatch.setattr(coach_router, "get_gateway", lambda: gateway)
    monkeypatch.setattr(flow, "get_gateway", lambda: gateway)
    reply = {
        "message": "Thank you. Do you want to sharpen anything, or are you done?",
        "hints": [
            {"skill": "judgment", "reason": "You chose a small slice first."},
            {"skill": "collaboration", "reason": "Three teams depended on checkout."},
        ],
    }
    (fake_fixtures / "coach" / "CraftReply.json").write_text(json.dumps(reply), encoding="utf-8")
    session = (await client.post("/coach/sessions", json={"story_id": sid})).json()
    out = (
        await client.post(
            f"/coach/sessions/{session['session']['id']}/turns",
            json={"text": "I think that is all of it."},
        )
    ).json()
    assert [h["skill"] for h in out["hints"]] == ["collaboration", "judgment"]
    assert [h["skill"] for h in out["craft"]["hints"]] == ["collaboration", "judgment"]
    deepened = (await client.post(f"/stories/{sid}/hints/collaboration/deepen")).json()
    assert "collaboration" in deepened["skills"]
    assert [h["skill"] for h in deepened["hints"]] == ["judgment"]
    dismissed = (await client.post(f"/stories/{sid}/hints/judgment/dismiss")).json()
    assert dismissed["hints"] == []
    assert (await client.post(f"/stories/{sid}/hints/impact/dismiss")).status_code == 404


async def test_sc8_deepen_opens_a_short_session_for_the_skill(client: httpx.AsyncClient) -> None:
    """SC-8: the Deepen session on the story opens by naming the skill."""
    await sign_in(client)
    story = await organized(client)
    started = (
        await client.post(
            "/coach/sessions", json={"story_id": story["id"], "target_skill": "judgment"}
        )
    ).json()
    assert started["turns"][0]["text"].startswith('Let\'s show judgment in "Checkout migration".')
