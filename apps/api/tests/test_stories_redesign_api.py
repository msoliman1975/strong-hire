"""Career Stories redesign (docs/stories-redesign/spec.md): recommendations pooled across resume
versions without duplicates (CS-1 to CS-4, CS-11), and rename, archive, soft delete and restore
of a story (CS-12 to CS-15)."""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import JobTarget
from strong_core.db.models import Story as StoryRow
from strong_core.db.models import Suggestion as SuggestionRow
from strong_core.schemas import MissingSkillPayload, SuggestionKind, SuggestionStatus
from strong_worker.inputs.testing import set_extractor_output

from .conftest import sign_in
from .test_library_api import add_job, fixture
from .test_story_ideas_api import CRON, INVOICING, LATENCY, MENTORED, PAYOUTS, SKILLS, ideas

REWORDED = "Shipped an invoicing API now serving 3,000 business customers"
"""INVOICING (roles[1].achievements[0], Tidewater Billing) as a newer resume words it."""
COACHED = "Coached 4 engineers to promotion"
"""MENTORED (roles[0].achievements[2], Fernhill Payments) as a newer resume words it."""

Maker = async_sessionmaker[AsyncSession]


async def upload(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    *,
    version: int,
    swap: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Upload the backend-senior resume as another version: different file bytes, and lines in
    `swap` reworded."""
    text, resume = fixture("resumes", "backend-senior")
    resume = copy.deepcopy(resume)
    for role in resume["roles"]:
        role["achievements"] = [(swap or {}).get(a, a) for a in role["achievements"]]
    items = [
        *SKILLS["items"],
        {"achievement": REWORDED, "skills": ["impact"]},
        {"achievement": COACHED, "skills": ["collaboration"]},
    ]
    set_extractor_output(fake_fixtures, "StoryIdeas", {"items": items})
    set_extractor_output(fake_fixtures, "Resume", resume)
    body = f"{text}\nVersion {version}".encode()
    resp = await client.post("/resumes", files={"file": (f"CV v{version}.txt", body)})
    assert resp.status_code == 202, resp.text
    out: dict[str, Any] = resp.json()["resume"]
    return out


async def recommendations(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get("/stories/recommendations")
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


# --- CS-1 to CS-4: no duplicate recommendations across resume versions ------------------------


async def test_cs1_cs4_the_same_lines_on_two_resumes_are_one_recommendation_each(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """CS-1, CS-4: pooled across resumes, one row per achievement, from the newest resume."""
    await sign_in(client)
    await upload(client, fake_fixtures, version=1)
    newer = await upload(client, fake_fixtures, version=2)
    data = await recommendations(client)
    assert [i["achievement"] for i in data["ideas"]] == [
        PAYOUTS,
        LATENCY,
        MENTORED,
        INVOICING,
        CRON,
    ]
    assert {i["resumes"] for i in data["ideas"]} == {2}
    assert {i["resume_id"] for i in data["ideas"]} == {newer["id"]}
    assert data["ideas"][0]["skills"] == ["ownership", "impact"]


async def test_cs2_a_reworded_line_the_matcher_links_is_one_recommendation(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """CS-2: the matcher says the reworded line is the same work; the row shows the newest
    wording and counts both resumes."""
    await sign_in(client)
    await upload(client, fake_fixtures, version=1)
    # The only new line is REWORDED; the earlier Tidewater ideas are INVOICING (0) and CRON (1).
    set_extractor_output(fake_fixtures, "IdeaMatches", {"items": [{"line": 0, "same_as": 0}]})
    await upload(client, fake_fixtures, version=2, swap={INVOICING: REWORDED})
    data = await recommendations(client)
    texts = [i["achievement"] for i in data["ideas"]]
    assert INVOICING not in texts
    assert texts.count(REWORDED) == 1
    row = next(i for i in data["ideas"] if i["achievement"] == REWORDED)
    assert row["resumes"] == 2
    assert len(texts) == 5


async def test_cs2_a_reworded_line_the_matcher_does_not_link_stays_separate(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """CS-2: different work (no match) is a recommendation of its own."""
    await sign_in(client)
    await upload(client, fake_fixtures, version=1)
    set_extractor_output(fake_fixtures, "IdeaMatches", {"items": [{"line": 0, "same_as": None}]})
    await upload(client, fake_fixtures, version=2, swap={INVOICING: REWORDED})
    texts = [i["achievement"] for i in (await recommendations(client))["ideas"]]
    assert INVOICING in texts and REWORDED in texts


async def test_cs2_the_matcher_never_links_lines_at_different_companies(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """CS-2: a match to an idea at another employer is ignored; one at the same employer
    holds."""
    await sign_in(client)
    await upload(client, fake_fixtures, version=1)
    # New lines: 0 = COACHED (Fernhill), 1 = REWORDED (Tidewater). Earlier ideas, in resume
    # order: 0 PAYOUTS, 1 LATENCY, 2 MENTORED (Fernhill), 3 INVOICING, 4 CRON (Tidewater).
    matches = {"items": [{"line": 0, "same_as": 2}, {"line": 1, "same_as": 0}]}
    set_extractor_output(fake_fixtures, "IdeaMatches", matches)
    await upload(client, fake_fixtures, version=2, swap={MENTORED: COACHED, INVOICING: REWORDED})
    texts = [i["achievement"] for i in (await recommendations(client))["ideas"]]
    assert COACHED in texts and MENTORED not in texts
    assert REWORDED in texts and INVOICING in texts


async def test_cs3_dismissed_on_one_resume_is_dismissed_on_every_version(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """CS-3: "Not a story" on the old resume hides the idea on the new one too."""
    await sign_in(client)
    older = await upload(client, fake_fixtures, version=1)
    newer = await upload(client, fake_fixtures, version=2)
    resp = await client.post(
        f"/resumes/{older['id']}/story-ideas/dismiss",
        json={"resume_line_ref": "roles[0].achievements[2]"},
    )
    assert resp.status_code == 204, resp.text
    assert MENTORED not in [i["achievement"] for i in (await ideas(client, newer["id"]))["ideas"]]
    assert MENTORED not in [i["achievement"] for i in (await recommendations(client))["ideas"]]


async def test_cs3_a_story_from_an_old_resume_line_counts_on_the_new_resume(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """CS-3: a story that tells the line is listed under used on every version."""
    await sign_in(client)
    await upload(client, fake_fixtures, version=1)
    story = await client.post("/stories", json={"title": "Payouts", "action": f"{PAYOUTS}."})
    assert story.status_code == 201, story.text
    newer = await upload(client, fake_fixtures, version=2)
    data = await ideas(client, newer["id"])
    assert [u["story_id"] for u in data["used"]] == [story.json()["id"]]
    assert PAYOUTS not in [i["achievement"] for i in (await recommendations(client))["ideas"]]


async def test_cs3_a_matched_reworded_line_inherits_the_dismissal(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """CS-2, CS-3: dismiss the old wording; the matched new wording does not come back."""
    await sign_in(client)
    older = await upload(client, fake_fixtures, version=1)
    resp = await client.post(
        f"/resumes/{older['id']}/story-ideas/dismiss",
        json={"resume_line_ref": "roles[1].achievements[0]"},
    )
    assert resp.status_code == 204, resp.text
    set_extractor_output(fake_fixtures, "IdeaMatches", {"items": [{"line": 0, "same_as": 0}]})
    await upload(client, fake_fixtures, version=2, swap={INVOICING: REWORDED})
    texts = [i["achievement"] for i in (await recommendations(client))["ideas"]]
    assert REWORDED not in texts and INVOICING not in texts


async def test_cs11_a_missing_skill_is_a_recommendation_tagged_with_its_job(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """CS-11: open missing-skill suggestions show once per skill and job, with the company."""
    await sign_in(client)
    job = await add_job(client, fake_fixtures)
    async with sessionmaker() as db:
        target = await db.get(JobTarget, uuid.UUID(job["id"]))
        assert target is not None
        for _ in range(2):  # a repeat is shown once
            db.add(
                SuggestionRow(
                    org_id=target.org_id,
                    user_id=target.user_id,
                    kind=SuggestionKind.MISSING_SKILL,
                    status=SuggestionStatus.OPEN,
                    job_target_id=target.id,
                    payload=MissingSkillPayload(competency="conflict_handling").model_dump(
                        mode="json"
                    ),
                    reason="The interview tests conflict handling and no story shows it.",
                )
            )
        await db.commit()
    data = await recommendations(client)
    assert len(data["skills"]) == 1
    skill = data["skills"][0]
    assert skill["competency"] == "conflict_handling"
    assert skill["job_target_id"] == job["id"]
    assert skill["company"]


# --- CS-12 to CS-15: rename, archive, delete, restore -------------------------------------------


async def _story(client: httpx.AsyncClient, title: str = "Payout redesign") -> str:
    resp = await client.post("/stories", json={"title": title, "skills": ["ownership"]})
    assert resp.status_code == 201, resp.text
    story_id: str = resp.json()["id"]
    return story_id


async def _titles(client: httpx.AsyncClient, query: str = "") -> list[str]:
    resp = await client.get(f"/stories{query}")
    assert resp.status_code == 200, resp.text
    return [s["title"] for s in resp.json()]


async def test_cs12_rename_changes_the_title_and_refuses_an_empty_one(
    client: httpx.AsyncClient,
) -> None:
    """CS-12: rename uses PATCH /stories/{id}."""
    await sign_in(client)
    story_id = await _story(client)
    resp = await client.patch(f"/stories/{story_id}", json={"title": "  Payouts v2  "})
    assert resp.status_code == 200 and resp.json()["title"] == "Payouts v2"
    resp = await client.patch(f"/stories/{story_id}", json={"title": "   "})
    assert resp.status_code == 422


async def test_cs13_cs14_archive_hides_a_story_until_unarchived(
    client: httpx.AsyncClient,
) -> None:
    """CS-13: archived stories leave the default list and show with ?include=archived.
    CS-14: they keep their status."""
    await sign_in(client)
    keep = await _story(client, "Kept")
    gone = await _story(client, "Old internship")
    resp = await client.post(f"/stories/{gone}/archive")
    assert resp.status_code == 200 and resp.json()["archived_at"] is not None
    assert await _titles(client) == ["Kept"]
    assert sorted(await _titles(client, "?include=archived")) == ["Kept", "Old internship"]
    assert (await client.get(f"/stories/{gone}")).status_code == 200  # still openable
    resp = await client.post(f"/stories/{gone}/unarchive")
    assert resp.status_code == 200 and resp.json()["archived_at"] is None
    assert sorted(await _titles(client)) == ["Kept", "Old internship"]
    assert keep


async def test_cs14_an_archived_story_is_left_out_of_the_day_plan_story_ids(
    client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """CS-14: archived and deleted stories are not in prep."""
    from strong_api.plan.day_plan import live_story_ids

    await sign_in(client)
    kept = await _story(client, "Kept")
    archived = await _story(client, "Archived")
    deleted = await _story(client, "Deleted")
    await client.post(f"/stories/{archived}/archive")
    await client.delete(f"/stories/{deleted}")
    async with sessionmaker() as db:
        row = await db.get(StoryRow, uuid.UUID(kept))
        assert row is not None
        assert await live_story_ids(db, row.user_id) == {uuid.UUID(kept)}


async def test_cs15_delete_hides_a_story_and_restore_brings_it_back(
    client: httpx.AsyncClient,
) -> None:
    """CS-15: delete is soft: 404 at once, listed with ?include=deleted, restorable."""
    await sign_in(client)
    story_id = await _story(client)
    assert (await client.delete(f"/stories/{story_id}")).status_code == 204
    assert (await client.get(f"/stories/{story_id}")).status_code == 404
    assert await _titles(client) == []
    resp = await client.get("/stories?include=deleted")
    assert [s["deleted_at"] is not None for s in resp.json()] == [True]
    resp = await client.post(f"/stories/{story_id}/restore")
    assert resp.status_code == 200 and resp.json()["deleted_at"] is None
    assert await _titles(client) == ["Payout redesign"]


async def test_cs15_restore_after_30_days_is_not_found(
    client: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """CS-15: the restore window is 30 days."""
    await sign_in(client)
    story_id = await _story(client)
    await client.delete(f"/stories/{story_id}")
    async with sessionmaker() as db:
        await db.execute(
            update(StoryRow)
            .where(StoryRow.id == uuid.UUID(story_id))
            .values(deleted_at=datetime.now(UTC) - timedelta(days=31))
        )
        await db.commit()
    assert (await client.post(f"/stories/{story_id}/restore")).status_code == 404
    assert (await client.get("/stories?include=deleted")).json() == []


async def test_cs15_a_live_story_cannot_be_restored(client: httpx.AsyncClient) -> None:
    """CS-15: restore is only for deleted stories."""
    await sign_in(client)
    story_id = await _story(client)
    assert (await client.post(f"/stories/{story_id}/restore")).status_code == 404
