"""IN-12: the CV check issues a user accepted (PUT /resumes/{id}/accepted-issues)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.inputs.deps import CurrentUser, current_user
from strong_core.config import get_settings
from strong_core.db.models import Org, User
from strong_core.schemas import ACCEPTED_ISSUES_MAX, AuthProvider
from strong_worker.inputs.testing import set_extractor_output

FIXTURES = get_settings().repo_root / "evals/fixtures/inputs"
KEY = "dates.overlap:lumen-pay/senior-pm+northwind/pm"


async def _resume(client: httpx.AsyncClient, fake_fixtures: Path) -> dict[str, Any]:
    expected = json.loads((FIXTURES / "resumes" / "backend-senior.json").read_text("utf-8"))
    set_extractor_output(fake_fixtures, "Resume", expected)
    text = (FIXTURES / "resumes" / "backend-senior.txt").read_text("utf-8")
    resp = await client.post("/resumes", data={"text": text})
    assert resp.status_code == 202, resp.text
    resume: dict[str, Any] = resp.json()["resume"]
    assert resume["accepted_issues"] == []
    return resume


async def _set(
    client: httpx.AsyncClient, resume_id: str, key: str, accepted: bool
) -> httpx.Response:
    return await client.put(
        f"/resumes/{resume_id}/accepted-issues", json={"key": key, "accepted": accepted}
    )


async def test_in12_accept_and_clear_an_issue(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """IN-12: accepting stores the key with a time; repeating keeps the first time; clearing
    removes it. GET /resumes/{id} returns the list."""
    resume = await _resume(client, fake_fixtures)
    first = await _set(client, resume["id"], KEY, True)
    assert first.status_code == 200, first.text
    [issue] = first.json()["accepted_issues"]
    assert issue["key"] == KEY
    again = (await _set(client, resume["id"], KEY, True)).json()["accepted_issues"]
    assert again == [issue]
    await _set(client, resume["id"], "detail.summary-short", True)
    got = (await client.get(f"/resumes/{resume['id']}")).json()["accepted_issues"]
    assert [i["key"] for i in got] == [KEY, "detail.summary-short"]

    cleared = (await _set(client, resume["id"], KEY, False)).json()["accepted_issues"]
    assert [i["key"] for i in cleared] == ["detail.summary-short"]
    # Clearing a key that is not there is fine.
    assert (await _set(client, resume["id"], KEY, False)).status_code == 200


async def test_in12_accepted_issues_survive_editing_the_cv(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """IN-12: saving the CV (PUT /resumes/{id}) keeps the accepted issues."""
    resume = await _resume(client, fake_fixtures)
    await _set(client, resume["id"], KEY, True)
    put = await client.put(f"/resumes/{resume['id']}", json={"resume": resume["resume"]})
    assert [i["key"] for i in put.json()["accepted_issues"]] == [KEY]


async def test_in12_at_most_100_accepted_issues_and_valid_keys(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """IN-12: a CV keeps at most 100 accepted issues; keys are 1 to 200 characters."""
    resume = await _resume(client, fake_fixtures)
    for n in range(ACCEPTED_ISSUES_MAX):
        assert (await _set(client, resume["id"], f"k{n}", True)).status_code == 200
    over = await _set(client, resume["id"], "one-more", True)
    assert over.status_code == 422
    assert over.json()["detail"]["code"] == "accepted_issues_limit"
    # Re-accepting a stored key and clearing still work at the limit.
    assert (await _set(client, resume["id"], "k0", True)).status_code == 200
    assert (await _set(client, resume["id"], "k0", False)).status_code == 200
    assert (await _set(client, resume["id"], "one-more", True)).status_code == 200

    for bad in ({"key": "", "accepted": True}, {"key": "x" * 201, "accepted": True}, {"key": "k"}):
        resp = await client.put(f"/resumes/{resume['id']}/accepted-issues", json=bad)
        assert resp.status_code == 422


async def test_in12_only_the_owner_and_not_after_delete(
    app: FastAPI,
    client: httpx.AsyncClient,
    fake_fixtures: Path,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """IN-12: another org gets 404; a deleted CV gets 404 and loses its accepted issues."""
    resume = await _resume(client, fake_fixtures)
    await _set(client, resume["id"], KEY, True)

    async with sessionmaker() as db:
        org = Org(name="Other org")
        db.add(org)
        await db.flush()
        user = User(org_id=org.id, email="other@example.com", auth_provider=AuthProvider.DEV)
        db.add(user)
        await db.commit()
        other = CurrentUser(user_id=user.id, org_id=org.id)
    app.dependency_overrides[current_user] = lambda: other
    assert (await _set(client, resume["id"], "x", True)).status_code == 404
    del app.dependency_overrides[current_user]

    assert (await client.delete(f"/resumes/{resume['id']}")).status_code == 204
    assert (await _set(client, resume["id"], "x", True)).status_code == 404
    assert (await client.get(f"/resumes/{resume['id']}")).json()["accepted_issues"] == []
