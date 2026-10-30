"""RM-4: story ideas from a resume. One idea per achievement no story uses and the user did not
dismiss, with what it still needs, and likely skills once the worker job has run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import Suggestion as SuggestionRow
from strong_worker.inputs.story_ideas import missing_parts
from strong_worker.inputs.testing import set_extractor_output

from .conftest import sign_in
from .test_library_api import add_resume

# The achievements of evals/fixtures/inputs/resumes/backend-senior.json.
PAYOUTS = "Led the redesign of the payout service, cutting failed payouts by 38%"
LATENCY = "Reduced p99 API latency from 900 ms to 180 ms by adding caching and query fixes"
MENTORED = "Mentored 4 engineers; two were promoted"
INVOICING = "Built the invoicing API used by 3,000 business customers"
CRON = "Migrated 25 cron jobs to a queue-based worker system"

SKILLS = {
    "items": [
        {"achievement": PAYOUTS, "skills": ["ownership", "impact"]},
        {"achievement": LATENCY, "skills": ["technical_depth"]},
        {"achievement": MENTORED, "skills": ["collaboration"]},
        {"achievement": INVOICING, "skills": ["impact"]},
        {"achievement": CRON, "skills": ["technical_depth", "ownership"]},
        {"achievement": "Not on this resume", "skills": ["judgment"]},
    ]
}


async def ideas(client: httpx.AsyncClient, resume_id: str) -> dict[str, Any]:
    resp = await client.get(f"/resumes/{resume_id}/story-ideas")
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


async def test_rm4_one_idea_per_achievement_with_skills_after_the_job(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """RM-4: every achievement is an idea, with its role, place, skills and missing parts."""
    await sign_in(client)
    set_extractor_output(fake_fixtures, "StoryIdeas", SKILLS)
    resume = await add_resume(client, fake_fixtures)
    data = await ideas(client, resume["id"])
    assert data["skills"] == "ready"
    assert data["used"] == []
    assert [i["achievement"] for i in data["ideas"]] == [
        PAYOUTS,
        LATENCY,
        MENTORED,
        INVOICING,
        CRON,
    ]
    first = data["ideas"][0]
    assert first["role"] == "Senior Software Engineer, Fernhill Payments"
    assert first["resume_line_ref"] == "roles[0].achievements[0]"
    assert first["skills"] == ["ownership", "impact"]
    assert first["missing_parts"] == ["stakes", "reflection"]
    assert data["ideas"][4]["resume_line_ref"] == "roles[1].achievements[1]"


def test_rm4_missing_parts_are_rule_based() -> None:
    """RM-4: stakes and reflection always; action too without a first-person past-tense verb."""
    assert missing_parts("Led the payout redesign") == ["stakes", "reflection"]
    assert missing_parts("Reduced latency by 80%") == ["stakes", "reflection"]
    assert missing_parts("Payout service redesign") == ["action", "stakes", "reflection"]
    assert missing_parts("Responsible for payouts, where I rebuilt the retries") == [
        "stakes",
        "reflection",
    ]


async def test_rm4_ideas_list_without_skills_when_the_job_fails(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """RM-4: no skills fixture means the model call fails; the ideas still list, with none."""
    await sign_in(client)
    (fake_fixtures / "extractor" / "StoryIdeas.json").unlink()
    resume = await add_resume(client, fake_fixtures)
    data = await ideas(client, resume["id"])
    assert len(data["ideas"]) == 5
    assert all(i["skills"] == [] for i in data["ideas"])
    assert data["skills"] == "pending"


async def test_rm4_ideas_leave_out_achievements_a_story_uses(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """RM-4: an achievement a story tells is listed under used, linking to the story."""
    await sign_in(client)
    set_extractor_output(fake_fixtures, "StoryIdeas", SKILLS)
    resume = await add_resume(client, fake_fixtures)
    story = await client.post(
        "/stories",
        json={"title": "Payout redesign", "action": f"{PAYOUTS}. I owned the rollout plan."},
    )
    assert story.status_code in (200, 201), story.text
    data = await ideas(client, resume["id"])
    assert PAYOUTS not in [i["achievement"] for i in data["ideas"]]
    assert data["used"] == [
        {
            "achievement": PAYOUTS,
            "resume_line_ref": "roles[0].achievements[0]",
            "story_id": story.json()["id"],
            "story_title": "Payout redesign",
        }
    ]


async def test_rm4_dismissed_ideas_do_not_return(
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """RM-4, SG-8: "Not a story" is stored as a dismissed suggestion and stays dismissed when the
    skills job runs again after an edit."""
    await sign_in(client)
    set_extractor_output(fake_fixtures, "StoryIdeas", SKILLS)
    resume = await add_resume(client, fake_fixtures)
    resp = await client.post(
        f"/resumes/{resume['id']}/story-ideas/dismiss",
        json={"resume_line_ref": "roles[0].achievements[2]"},
    )
    assert resp.status_code == 204, resp.text
    assert MENTORED not in [i["achievement"] for i in (await ideas(client, resume["id"]))["ideas"]]
    # Editing the resume runs the skills job again; the dismissal holds.
    edited = await client.put(f"/resumes/{resume['id']}", json={"resume": resume["resume"]})
    assert edited.status_code == 200, edited.text
    assert MENTORED not in [i["achievement"] for i in (await ideas(client, resume["id"]))["ideas"]]
    async with sessionmaker() as db:
        rows = list(await db.scalars(select(SuggestionRow)))
    dismissed = [r for r in rows if r.status == "dismissed"]
    assert [r.payload["achievement"] for r in dismissed] == [MENTORED]
    assert dismissed[0].resolved_at is not None
    assert len(rows) == 5
    # Safe to repeat; a bad place is 404, a bad format 422.
    again = await client.post(
        f"/resumes/{resume['id']}/story-ideas/dismiss",
        json={"resume_line_ref": "roles[0].achievements[2]"},
    )
    assert again.status_code == 204
    missing = await client.post(
        f"/resumes/{resume['id']}/story-ideas/dismiss",
        json={"resume_line_ref": "roles[9].achievements[0]"},
    )
    assert missing.status_code == 404
    bad = await client.post(
        f"/resumes/{resume['id']}/story-ideas/dismiss", json={"resume_line_ref": "x"}
    )
    assert bad.status_code == 422


async def test_rm4_story_ideas_are_per_user(client: httpx.AsyncClient, fake_fixtures: Path) -> None:
    await sign_in(client)
    resume = await add_resume(client, fake_fixtures)
    await sign_in(client, "someone@example.com")
    assert (await client.get(f"/resumes/{resume['id']}/story-ideas")).status_code == 404
