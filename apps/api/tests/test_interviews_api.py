"""TG-3, RH-1, RH-2: suggested interviews, interviews per role (role x resume x type) and
readiness per interview."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.plan.interviews import RehearsalItem, recommend
from strong_core.db.models import InterviewSession, Subscription, TargetInterview, User
from strong_core.db.models import Scorecard as ScorecardRow
from strong_core.schemas import SessionStatus, SubscriptionStatus

from .conftest import sign_in
from .test_library_api import SESSION_CONFIG, add_job, add_resume, gap_for
from .test_plan_api import publish_stripe

Maker = async_sessionmaker[AsyncSession]
BEHAVIORAL = [
    "ownership",
    "impact",
    "collaboration",
    "conflict_handling",
    "learning_from_failure",
    "communication",
]


async def subscribe(sessionmaker: Maker) -> None:
    """A paid plan, so full-length takes can start (BL-1)."""
    async with sessionmaker() as db:
        for user in await db.scalars(select(User)):
            db.add(
                Subscription(
                    org_id=user.org_id,
                    user_id=user.id,
                    status=SubscriptionStatus.ACTIVE,
                    minutes_cap=3000,
                    minutes_used=0,
                )
            )
        await db.commit()


async def role_with_resume(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> tuple[dict[str, Any], dict[str, Any]]:
    await sign_in(client)
    await subscribe(sessionmaker)
    job = await add_job(client, fake_fixtures)
    resume = await add_resume(client, fake_fixtures)
    await gap_for(client, job["id"], resume["id"])
    return job, resume


async def keep(client: httpx.AsyncClient, job_id: str, *types: str) -> list[dict[str, Any]]:
    resp = await client.post(f"/roles/{job_id}/interviews", json={"interview_types": list(types)})
    assert resp.status_code == 201, resp.text
    out: list[dict[str, Any]] = resp.json()
    return out


async def take(
    client: httpx.AsyncClient,
    sessionmaker: Maker,
    job_id: str,
    interview_id: str,
    scores: dict[str, int] | None,
    *,
    mode: str = "realistic",
    profile: str = "hosted",
    minutes_ago: int = 0,
) -> str:
    """A take of the interview, scored with `scores` (None: not scored yet)."""
    resp = await client.post(
        "/sessions",
        json={
            "job_target_id": job_id,
            "interview_id": interview_id,
            "config": {**SESSION_CONFIG, "interview_type": "case", "mode": mode},
        },
    )
    assert resp.status_code == 201, resp.text
    session_id = uuid.UUID(resp.json()["id"])
    async with sessionmaker() as db:
        row = await db.get(InterviewSession, session_id)
        assert row is not None
        row.status = SessionStatus.COMPLETED
        row.model_profile = profile
        row.started_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
        if scores is not None:
            db.add(
                ScorecardRow(
                    org_id=row.org_id,
                    session_id=row.id,
                    hire_signal="Lean Hire",
                    rationale="Fine.",
                    competency_scores_json=[
                        {"competency": c, "score": s, "justification": "x", "quotes": ["y"]}
                        for c, s in scores.items()
                    ],
                    per_question_json=[
                        {
                            "question_ref": "q1",
                            "question_text": "Tell me.",
                            "scores": [
                                {"competency": c, "score": s, "justification": "x", "quotes": ["y"]}
                                for c, s in scores.items()
                            ],
                        }
                    ],
                    scorer_model="scorer",
                    rubric_version="scorer/rubric.v1",
                )
            )
        await db.commit()
    return str(session_id)


async def test_tg3_generic_role_suggests_the_standard_loop(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """TG-3: generic mode suggests behavioral, hiring manager and technical Q&A as usual."""
    job, _ = await role_with_resume(client, fake_fixtures, sessionmaker)
    resp = await client.get(f"/roles/{job['id']}/suggested-interviews")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["company_mode"] == "generic"
    usual = [i["interview_type"] for i in data["items"] if i["usual"]]
    assert usual == ["behavioral", "hiring_manager", "technical_qa"]
    others = [i["interview_type"] for i in data["items"] if not i["usual"]]
    assert others == ["case", "recruiter_screen"]
    first = data["items"][0]
    assert first["description"]
    assert first["acting_as"] == {
        "title": "Engineering Manager",
        "company": None,
        "text": "Strova is acting as an Engineering Manager",
    }


async def test_tg3_curated_role_suggests_the_company_rounds(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """TG-3: a curated company's loop for the role family gives the usual rounds, in loop order,
    with the profile's interviewer for "acting as"."""
    await publish_stripe(sessionmaker)
    job, _ = await role_with_resume(client, fake_fixtures, sessionmaker)
    data = (await client.get(f"/roles/{job['id']}/suggested-interviews")).json()
    assert data["company_mode"] == "curated"
    usual = [(i["interview_type"], i["round_name"]) for i in data["items"] if i["usual"]]
    assert usual == [("technical_qa", "System design"), ("behavioral", "Behavioral and values")]
    behavioral = next(i for i in data["items"] if i["interview_type"] == "behavioral")
    assert behavioral["acting_as"]["text"] == (
        "Strova is acting as Hiring manager or senior engineer at Stripe"
    )
    case = next(i for i in data["items"] if i["interview_type"] == "case")
    assert case["usual"] is False
    assert case["acting_as"]["title"] == "Product Lead"


async def test_rh1_interviews_are_role_resume_type_unique_and_archivable(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """RH-1: kept types become interviews on the main resume; keeping one again reuses it;
    archiving hides it from the role."""
    job, resume = await role_with_resume(client, fake_fixtures, sessionmaker)
    created = await keep(client, job["id"], "behavioral", "hiring_manager", "behavioral")
    assert [i["interview_type"] for i in created] == ["behavioral", "hiring_manager"]
    assert {i["resume_id"] for i in created} == {resume["id"]}
    again = await keep(client, job["id"], "behavioral")
    assert again[0]["id"] == created[0]["id"]
    listed = (await client.get(f"/roles/{job['id']}/interviews")).json()
    assert [i["interview"]["id"] for i in listed] == [created[0]["id"], created[1]["id"]]

    assert (await client.delete(f"/interviews/{created[1]['id']}")).status_code == 204
    listed = (await client.get(f"/roles/{job['id']}/interviews")).json()
    assert [i["interview"]["interview_type"] for i in listed] == ["behavioral"]
    # Archived: kept a new one for the same type later.
    fresh = await keep(client, job["id"], "hiring_manager")
    assert fresh[0]["id"] != created[1]["id"]
    async with sessionmaker() as db:
        assert len(list(await db.scalars(select(TargetInterview)))) == 3
    # Custom needs its setup.
    bad = await client.post(f"/roles/{job['id']}/interviews", json={"interview_types": ["custom"]})
    assert bad.status_code == 422


async def test_rh1_creating_the_role_keeps_its_interviews_in_one_request(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """RH-1, TG-2: the add flow's confirm request ("Create the role") creates the interviews."""
    job, resume = await role_with_resume(client, fake_fixtures, sessionmaker)
    resp = await client.put(
        f"/job-targets/{job['id']}",
        json={"posting": job["posting"], "interview_types": ["behavioral", "technical_qa"]},
    )
    assert resp.status_code == 200, resp.text
    listed = (await client.get(f"/roles/{job['id']}/interviews")).json()
    assert [i["interview"]["interview_type"] for i in listed] == ["behavioral", "technical_qa"]
    assert all(i["interview"]["resume_id"] == resume["id"] for i in listed)


async def test_rh1_a_take_follows_its_interview_and_old_sessions_map_by_key(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """RH-1: a take created for an interview gets its type and resume; a session made before
    the interview existed (same job, resume and type) counts as its take too."""
    job, resume = await role_with_resume(client, fake_fixtures, sessionmaker)
    old = await client.post(
        "/sessions",
        json={"job_target_id": job["id"], "resume_id": resume["id"], "config": SESSION_CONFIG},
    )
    assert old.status_code == 201, old.text
    (interview,) = await keep(client, job["id"], "behavioral")
    session_id = await take(client, sessionmaker, job["id"], interview["id"], None)
    async with sessionmaker() as db:
        row = await db.get(InterviewSession, uuid.UUID(session_id))
        assert row is not None
        assert row.type == "behavioral"  # the request said case; the interview wins
        assert str(row.resume_id) == resume["id"]
    detail = (await client.get(f"/interviews/{interview['id']}")).json()
    assert [t["session_id"] for t in detail["takes"]] == [session_id, old.json()["id"]]
    assert [t["number"] for t in detail["takes"]] == [2, 1]
    # Another role's interview cannot be used.
    other = await add_job(client, fake_fixtures)
    wrong = await client.post(
        "/sessions",
        json={
            "job_target_id": other["id"],
            "interview_id": interview["id"],
            "config": SESSION_CONFIG,
        },
    )
    assert wrong.status_code == 422


async def test_rh2_readiness_formula_from_the_last_three_realistic_takes(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """RH-2: per competency, the most recent score from the last three counted takes; the score
    is round((mean - 1) / 3 * 100) over the competencies scored so far; goal 75."""
    job, _ = await role_with_resume(client, fake_fixtures, sessionmaker)
    (interview,) = await keep(client, job["id"], "behavioral")
    detail = (await client.get(f"/interviews/{interview['id']}")).json()
    ready = detail["readiness"]
    assert ready["score"] is None and ready["takes_counted"] == 0 and ready["goal"] == 75
    assert ready["kind"] == "practice_estimate"
    assert [c["competency"] for c in ready["competencies"]] == BEHAVIORAL

    # Oldest first: this one falls out once three newer counted takes exist.
    await take(
        client, sessionmaker, job["id"], interview["id"], {"communication": 4}, minutes_ago=40
    )
    await take(
        client,
        sessionmaker,
        job["id"],
        interview["id"],
        {"ownership": 1, "impact": 2},
        minutes_ago=30,
    )
    await take(client, sessionmaker, job["id"], interview["id"], {"ownership": 3}, minutes_ago=20)
    first = (await client.get(f"/interviews/{interview['id']}")).json()["readiness"]
    # ownership 3 (newest), impact 2, communication 4: mean 3 -> 67.
    assert first["score"] == 67
    await take(client, sessionmaker, job["id"], interview["id"], {"impact": 4}, minutes_ago=10)
    ready = (await client.get(f"/interviews/{interview['id']}")).json()["readiness"]
    scores = {c["competency"]: c["score"] for c in ready["competencies"]}
    # Last three: impact 4, ownership 3, (ownership 1, impact 2). Communication dropped out.
    assert scores == {
        "ownership": 3,
        "impact": 4,
        "collaboration": None,
        "conflict_handling": None,
        "learning_from_failure": None,
        "communication": None,
    }
    assert ready["score"] == round((3.5 - 1) / 3 * 100)  # 83
    assert ready["takes_counted"] == 3
    assert ready["change"] == ready["score"] - 67


async def test_rh2_only_realistic_scored_takes_on_real_models_count(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """RH-2: Practice takes, unscored takes and development-profile takes never count."""
    job, _ = await role_with_resume(client, fake_fixtures, sessionmaker)
    (interview,) = await keep(client, job["id"], "behavioral")
    await take(client, sessionmaker, job["id"], interview["id"], {"ownership": 4}, mode="coach")
    await take(client, sessionmaker, job["id"], interview["id"], {"ownership": 4}, profile="fake")
    await take(client, sessionmaker, job["id"], interview["id"], None)
    detail = (await client.get(f"/interviews/{interview['id']}")).json()
    assert detail["readiness"]["score"] is None
    assert detail["readiness"]["change"] is None
    assert [t["counts"] for t in detail["takes"]] == [False, False, False]
    assert detail["takes"][1]["met_bar"] == 1 and detail["takes"][1]["scored"] == 1
    await take(client, sessionmaker, job["id"], interview["id"], {"ownership": 2})
    ready = (await client.get(f"/interviews/{interview['id']}")).json()["readiness"]
    assert ready["score"] == 33
    assert ready["change"] is None  # no earlier counted take


async def test_rh2_roles_and_rehearsals_list_readiness_and_recommend_the_next_take(
    client: httpx.AsyncClient, fake_fixtures: Path, sessionmaker: Maker
) -> None:
    """RH-2, RH-4: GET /roles has one readiness per interview; GET /rehearsals lists every
    interview and recommends the lowest one below 75 (no dates set)."""
    job, _ = await role_with_resume(client, fake_fixtures, sessionmaker)
    behavioral, hiring = await keep(client, job["id"], "behavioral", "hiring_manager")
    await take(client, sessionmaker, job["id"], behavioral["id"], {"ownership": 4})
    roles = (await client.get("/roles")).json()
    assert [r["role"]["id"] for r in roles] == [job["id"]]
    assert [i["readiness"]["score"] for i in roles[0]["interviews"]] == [100, None]
    data = (await client.get("/rehearsals")).json()
    assert [i["interview"]["id"] for i in data["items"]] == [behavioral["id"], hiring["id"]]
    assert data["next_interview_id"] == hiring["id"]
    assert data["items"][0]["takes_count"] == 1
    assert data["items"][0]["last_signal"] == "Lean Hire"


def test_rh2_recommendation_puts_the_closest_date_first() -> None:
    """RH-4: closest interview date first, then the lowest readiness below the goal."""

    def item(score: int | None, when: date | None) -> RehearsalItem:
        iid = uuid.uuid4()
        return RehearsalItem.model_validate(
            {
                "interview": {
                    "id": iid,
                    "job_target_id": uuid.uuid4(),
                    "resume_id": uuid.uuid4(),
                    "interview_type": "behavioral",
                    "custom": None,
                    "created_at": datetime.now(UTC),
                    "archived_at": None,
                    "acting_as": {"title": "t", "company": None, "text": "x"},
                },
                "readiness": {
                    "interview_id": iid,
                    "score": score,
                    "takes_counted": 1 if score else 0,
                },
                "takes_count": 0,
                "last_signal": None,
                "role": {
                    "id": uuid.uuid4(),
                    "name": "r",
                    "title": None,
                    "company_name": None,
                    "company_mode": "generic",
                    "interview_date": when,
                    "days_left": None,
                    "archived": False,
                },
            }
        )

    soon = item(70, date(2026, 11, 2))
    later_low = item(10, date(2026, 12, 1))
    no_date = item(None, None)
    done = item(90, date(2026, 11, 1))
    assert recommend([later_low, no_date, soon, done]) == soon.interview.id
    assert recommend([no_date, item(40, None)]) == no_date.interview.id
    assert recommend([done]) is None
