"""U11: the personal plan (PS-1, PS-3, PS-4, PS-5) and the debrief's plan line (DB-6)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import httpx

from strong_api.plan.personal import groups, schedule, week_start
from strong_core.schemas import PlanItem, PlanItemKind, PlanItemStatus

from .conftest import sign_in
from .test_interviews_api import Maker, keep, role_with_resume
from .test_library_api import add_resume

FULL = {
    "context": "Our checkout ran on a payments service three teams depended on.",
    "stakes": "About 2 percent of checkouts failed every week.",
    "action": "I wrote the migration plan.",
    "result": "Checkout errors dropped 40 percent.",
    "reflection": "I would bring the platform team in earlier.",
}


async def plan(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get("/me/plan")
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


async def with_issues(client: httpx.AsyncClient, resume: dict[str, Any]) -> None:
    """Give the resume open issues: no summary, and a role with one achievement (RM-5)."""
    edited = dict(resume["resume"], summary=None)
    edited["roles"] = [dict(edited["roles"][0], achievements=["Wrote docs"]), *edited["roles"][1:]]
    resp = await client.put(f"/resumes/{resume['id']}", json={"resume": edited})
    assert resp.status_code == 200, resp.text


async def checklist(client: httpx.AsyncClient) -> None:
    """The checklist style lists every item (the weekly style shows one a day)."""
    resp = await client.patch("/account/profile", json={"plan_style": "checklist"})
    assert resp.status_code == 200, resp.text


def kinds(data: dict[str, Any]) -> set[str]:
    return {i["kind"] for i in data["plan"]["items"]}


async def test_ps5_before_any_role_the_plan_has_only_story_and_resume_items(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """PS-5: no rehearsal items before the first target role; story ideas and resume issues
    come from the main resume."""
    await sign_in(client)
    await with_issues(client, await add_resume(client, fake_fixtures))
    await checklist(client)
    data = await plan(client)
    assert data["has_roles"] is False
    assert kinds(data) == {"story", "resume"}
    rehearsals = next(g for g in data["groups"] if g["kind"] == "rehearsal")
    assert rehearsals == {
        "kind": "rehearsal",
        "title": "Rehearsals",
        "done": 0,
        "total": 0,
        "status": "Added when you add a target role",
    }
    ideas = [i for i in data["plan"]["items"] if i["key"].startswith("idea:")]
    assert ideas and ideas[0]["action_label"] == "Build on it"
    assert ideas[0]["action_target"].startswith("/coach/new?resume=")


async def test_ps1_rehearsal_story_and_resume_items_with_the_next_one_marked(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """PS-1: one rehearsal item per interview below 75, one story item per tested story skill
    (done with a Ready story), started drafts, and resume issues. The first open item is next,
    and Home's next step comes from it."""
    job, resume = await role_with_resume(client, fake_fixtures, sessionmaker)
    await with_issues(client, resume)
    interviews = await keep(client, job["id"], "behavioral")
    await checklist(client)
    resp = await client.post(
        "/stories", json={"title": "Checkout migration", "skills": ["ownership"], **FULL}
    )
    assert resp.status_code == 201
    draft = await client.post(
        "/stories",
        json={"title": "Pushback", "skills": ["conflict_handling"], "action": "We talked it out."},
    )
    data = await plan(client)
    assert data["has_roles"] is True
    items = {i["key"]: i for i in data["plan"]["items"]}
    rehearsal = items[f"interview:{interviews[0]['id']}"]
    assert rehearsal["kind"] == "rehearsal"
    assert rehearsal["title"].endswith("· Behavioral: readiness 75 or more")
    assert rehearsal["sub"] == "Not started"
    assert rehearsal["action_target"] == f"/interviews/{interviews[0]['id']}"
    assert items["skill:ownership"]["status"] == "done"
    assert items["skill:ownership"]["title"] == "Ownership: a Ready story"
    conflict = items["skill:conflict_handling"]
    assert conflict["status"] == "todo" and "has 1 of 5 parts" in conflict["sub"]
    assert conflict["action_target"] == f"/stories/{draft.json()['id']}/review"
    assert items["skill:learning_from_failure"]["action_label"] == "Craft with Strova"
    assert any(i["kind"] == "resume" for i in items.values())
    assert data["next_key"] == rehearsal["key"] and rehearsal["status"] == "next"
    assert [i["status"] for i in data["plan"]["items"]].count("next") == 1
    step = data["next_step"]
    assert step["action_target"] == rehearsal["action_target"]
    assert step["role_target"] == f"/roles/{job['id']}"


async def test_ps3_checklist_groups_have_counts_and_a_status_naming_the_next_item(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """PS-3: three groups in order, each with done and total and a one-line status."""
    job, _ = await role_with_resume(client, fake_fixtures, sessionmaker)
    await keep(client, job["id"], "behavioral")
    resp = await client.patch("/account/profile", json={"plan_style": "checklist"})
    assert resp.status_code == 200, resp.text
    data = await plan(client)
    assert data["plan"]["style"] == "checklist"
    assert data["plan"]["week_start"] is None
    assert [g["title"] for g in data["groups"]] == [
        "Rehearsals",
        "Story completion",
        "Resume gaps and issues",
    ]
    reh = data["groups"][0]
    assert (reh["done"], reh["total"]) == (0, 1)
    assert reh["status"].startswith("Next: ") and reh["status"].endswith("Not started · 1 open")


async def test_ps4_weekly_plan_has_one_item_per_day_monday_to_saturday(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """PS-4: the weekly style gives the week's dates and at most one item per day."""
    job, _ = await role_with_resume(client, fake_fixtures, sessionmaker)
    await keep(client, job["id"], "behavioral", "hiring_manager")
    data = await plan(client)
    assert data["plan"]["style"] == "weekly"
    days = [i["due"] for i in data["plan"]["items"]]
    assert len(days) == len(set(days)) and len(days) <= 6
    start = date.fromisoformat(data["plan"]["week_start"])
    assert start.weekday() == 0
    assert date.fromisoformat(data["week_end"]).weekday() == 5


def _item(key: str, status: PlanItemStatus, kind: PlanItemKind = PlanItemKind.STORY) -> PlanItem:
    return PlanItem(key=key, kind=kind, title=key, status=status)


def test_ps4_scheduling_is_deterministic_done_before_today_open_from_today() -> None:
    """PS-4: done items fill the days before today, open items today onward, in plan order;
    on Sunday the plan shows the coming week."""
    wednesday = date(2026, 10, 28)
    assert week_start(wednesday) == date(2026, 10, 26)
    assert week_start(date(2026, 11, 1)) == date(2026, 11, 2)  # a Sunday
    items = [
        _item("a", PlanItemStatus.DONE),
        _item("b", PlanItemStatus.NEXT),
        _item("c", PlanItemStatus.TODO),
        _item("d", PlanItemStatus.TODO),
        _item("e", PlanItemStatus.TODO),
        _item("f", PlanItemStatus.TODO),
        _item("g", PlanItemStatus.TODO),
    ]
    out = schedule(items, wednesday)
    assert [(i.key, i.due) for i in out] == [
        ("a", date(2026, 10, 27)),
        ("b", date(2026, 10, 28)),
        ("c", date(2026, 10, 29)),
        ("d", date(2026, 10, 30)),
        ("e", date(2026, 10, 31)),
    ]
    assert schedule(items, wednesday) == out


def test_ps3_group_status_lines() -> None:
    items = [
        _item("x", PlanItemStatus.DONE, PlanItemKind.RESUME),
        _item("Add a second achievement", PlanItemStatus.TODO, PlanItemKind.RESUME),
    ]
    out = {g.kind: g for g in groups(items)}
    assert out[PlanItemKind.RESUME].status == "Next: Add a second achievement · 1 open"
    assert (out[PlanItemKind.RESUME].done, out[PlanItemKind.RESUME].total) == (1, 2)
    assert out[PlanItemKind.STORY].status == "Nothing to do here yet"


async def test_db6_the_debrief_plan_line_names_the_plans_next_item(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """DB-6: "Your plan updated: next is …" uses the personal plan's next item and its day."""
    from strong_api.plan.personal import PersonalPlan, plan_line

    job, _ = await role_with_resume(client, fake_fixtures, sessionmaker)
    await keep(client, job["id"], "behavioral")
    data = PersonalPlan.model_validate(await plan(client))
    item = next(i for i in data.plan.items if i.key == data.next_key)
    today = data.model_copy(
        update={
            "plan": data.plan.model_copy(
                update={"items": [item.model_copy(update={"due": data.today})]}
            )
        }
    )
    assert plan_line(today) == f"{item.title} today."
    later = data.model_copy(
        update={
            "plan": data.plan.model_copy(
                update={"items": [item.model_copy(update={"due": date(2026, 10, 31)})]}
            )
        }
    )
    assert plan_line(later) == f"{item.title} on Saturday."


async def test_ps6_the_workers_reminder_readiness_matches_the_api(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """PS-6: the reminder job (worker) reads readiness with the API's RH-2 rule."""
    import uuid as uuid_

    from strong_core.db.models import TargetInterview
    from strong_worker.reminders import _readiness

    from .test_interviews_api import take

    job, _ = await role_with_resume(client, fake_fixtures, sessionmaker)
    (iv,) = await keep(client, job["id"], "case")
    await take(client, sessionmaker, job["id"], iv["id"], {"structure": 2}, minutes_ago=30)
    await take(
        client,
        sessionmaker,
        job["id"],
        iv["id"],
        {"structure": 4, "estimation_logic": 3},
        minutes_ago=20,
    )
    await take(
        client, sessionmaker, job["id"], iv["id"], {"structure": 1}, mode="coach", minutes_ago=10
    )
    await take(
        client, sessionmaker, job["id"], iv["id"], {"structure": 1}, profile="fake", minutes_ago=5
    )
    api = (await client.get(f"/interviews/{iv['id']}")).json()["readiness"]["score"]
    async with sessionmaker() as db:
        row = await db.get(TargetInterview, uuid_.UUID(iv["id"]))
        assert row is not None
        assert await _readiness(db, row) == api
    assert api is not None
