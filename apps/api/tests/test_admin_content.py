"""Admin Content routes (AT-1..AT-5, AD-1): companies, profile versions, import, workflow and
company requests. The profiles are the fictional example (profiles/examples/example-corp.json)."""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.auth.settings import get_auth_settings
from strong_api.main import create_app
from strong_core.config import get_settings
from strong_core.db.models import AuditLog, Company, CompanyRequest, CompanyRequestTriage
from strong_core.db.models import CompanyProfile as ProfileRow
from strong_core.schemas import ProfileStatus

from .conftest import InlineQueue, sign_in

Maker = async_sessionmaker[AsyncSession]
ADMIN = "boss@example.com"
H = {"X-Admin-Request": "1"}
EXAMPLE = get_settings().repo_root / "profiles/examples/example-corp.json"
SLUG = "example-corp"


def example() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return data


def variant(n: int) -> dict[str, Any]:
    data = copy.deepcopy(example())
    data["persona"]["pace"] = f"Pace {n}"
    return data


async def _ok() -> None:
    return None


@pytest.fixture
def app(
    sessionmaker: Maker, queue: InlineQueue, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FastAPI]:
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    get_auth_settings.cache_clear()
    yield create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)
    get_auth_settings.cache_clear()


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await sign_in(http, ADMIN)
        yield http


async def import_(
    admin: httpx.AsyncClient, data: dict[str, Any] | None = None, **extra: Any
) -> httpx.Response:
    body = {"reason": "new research", "profile": data or example(), "create_company": True}
    return await admin.post(f"/admin/companies/{SLUG}/profiles", json={**body, **extra}, headers=H)


async def move(admin: httpx.AsyncClient, version: int, to: str) -> httpx.Response:
    return await admin.post(
        f"/admin/companies/{SLUG}/profiles/{version}/transition",
        json={"to": to, "reason": "reviewed the sources"},
        headers=H,
    )


async def audits(maker: Maker, action: str) -> list[AuditLog]:
    async with maker() as db:
        return list(await db.scalars(select(AuditLog).where(AuditLog.action == action)))


# --- access ---------------------------------------------------------------------------------


async def test_at_routes_are_admin_only(
    anon_client: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    """AA-4: 404 for everyone who is not an admin."""
    for http in (anon_client, client):
        assert (await http.get("/admin/companies")).status_code == 404
        assert (await http.get("/admin/company-requests")).status_code == 404


async def test_at_writes_need_header_and_reason(admin: httpx.AsyncClient) -> None:
    """AA-5, AA-6."""
    body = {"active": False, "reason": "paused"}
    assert (await admin.patch("/admin/companies/google", json=body)).status_code == 403
    no_reason = {"active": False}
    assert (
        await admin.patch("/admin/companies/google", json=no_reason, headers=H)
    ).status_code == 422


# --- AT-1 -----------------------------------------------------------------------------------


async def test_at1_lists_companies_and_toggles_active_with_audit(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    rows = (await admin.get("/admin/companies")).json()
    google = next(c for c in rows if c["slug"] == "google")
    assert google["active"] is True and google["published_version"] is None
    assert google["draft_count"] == 0 and google["request_users"] == 0

    r = await admin.patch(
        "/admin/companies/google", json={"active": False, "reason": "profile is stale"}, headers=H
    )
    assert r.status_code == 200 and r.json()["active"] is False
    async with sessionmaker() as db:
        company = await db.scalar(select(Company).where(Company.slug == "google"))
    assert company is not None and company.active is False
    [row] = await audits(sessionmaker, "company.set_active")
    assert row.actor == ADMIN and row.entity == "company:google"
    assert row.details_json["before"] == {"active": True}
    assert row.details_json["reason"] == "profile is stale"
    assert (
        await admin.patch(
            "/admin/companies/nope", json={"active": True, "reason": "x" * 3}, headers=H
        )
    ).status_code == 404


async def test_at1_counts_drafts_reviews_and_requests(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    await import_(admin, variant(1))
    await import_(admin, variant(2))
    await move(admin, 2, "in_review")
    state = await sign_in(admin, "ana@example.com")
    await sign_in(admin, ADMIN)
    async with sessionmaker() as db:
        company = await db.scalar(select(Company).where(Company.slug == SLUG))
        assert company is not None
        user = state["user"]
        for _ in range(2):
            db.add(
                CompanyRequest(
                    org_id=uuid.UUID(user["org_id"]),
                    user_id=uuid.UUID(user["id"]),
                    company_name="Example Corp",
                    normalized_name="example",
                    matched_company_id=company.id,
                )
            )
        await db.commit()
    rows = {c["slug"]: c for c in (await admin.get("/admin/companies")).json()}
    mine = rows[SLUG]
    assert (mine["draft_count"], mine["in_review_count"], mine["version_count"]) == (1, 1, 2)
    assert mine["latest_version"] == 2 and mine["request_users"] == 1


# --- AT-3 -----------------------------------------------------------------------------------


async def test_at3_import_stores_draft_with_sources_and_new_company(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    r = await import_(admin)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["company_created"] is True and out["company"]["active"] is False
    assert out["version"]["version"] == 1 and out["version"]["status"] == "draft"
    assert out["version"]["source_count"] == len(example()["sources"]) > 0
    assert out["diff"]["a"] is None and out["diff"]["total"] > 0
    assert out["summary"][0] == "Company: Example Corp (example-corp)"
    async with sessionmaker() as db:
        row = await db.scalar(select(ProfileRow))
    assert row is not None and row.status is ProfileStatus.DRAFT
    assert row.sources_json == example()["sources"] and row.imported_at is not None
    [audit] = await audits(sessionmaker, "profile.import")
    assert audit.actor == ADMIN and audit.entity == f"company_profile:{SLUG}:v1"
    assert audit.details_json["reason"] == "new research"
    assert audit.details_json["company_created"] is True


async def test_at3_import_accepts_file_text_and_rejects_invalid_like_strongctl(
    admin: httpx.AsyncClient,
) -> None:
    ok = await admin.post(
        f"/admin/companies/{SLUG}/profiles",
        json={
            "reason": "upload",
            "profile_text": EXAMPLE.read_text("utf-8"),
            "create_company": True,
        },
        headers=H,
    )
    assert ok.status_code == 201

    broken = example()
    broken["values_framework"]["principles"][0]["name"] = ""
    del broken["persona"]
    r = await import_(admin, broken)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "invalid_profile"
    assert any(p.startswith("values_framework.principles[0].name") for p in detail["problems"])
    assert any(p.startswith("persona") for p in detail["problems"])

    r = await admin.post(
        f"/admin/companies/{SLUG}/profiles",
        json={"reason": "upload", "profile_text": "{not json"},
        headers=H,
    )
    assert r.status_code == 422
    assert r.json()["detail"]["problems"][0].startswith("not valid JSON")


async def test_at3_import_rules_slug_unknown_company_and_unchanged(
    admin: httpx.AsyncClient,
) -> None:
    r = await admin.post(
        "/admin/companies/google/profiles",
        json={"reason": "wrong one", "profile": example()},
        headers=H,
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "slug_mismatch"
    r = await import_(admin, create_company=False)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "unknown_company"
    assert (await import_(admin)).status_code == 201
    r = await import_(admin)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "unchanged"
    assert (await import_(admin, force=True)).status_code == 201
    both = {"reason": "x" * 5, "profile": example(), "profile_text": "{}"}
    r = await admin.post(f"/admin/companies/{SLUG}/profiles", json=both, headers=H)
    assert r.status_code == 422


# --- AT-2 -----------------------------------------------------------------------------------


async def test_at2_versions_json_sources_and_diff(admin: httpx.AsyncClient) -> None:
    await import_(admin, variant(1))
    await import_(admin, variant(2))
    listing = (await admin.get(f"/admin/companies/{SLUG}/profiles")).json()
    assert [v["version"] for v in listing["versions"]] == [1, 2]
    assert listing["company"]["slug"] == SLUG

    one = (await admin.get(f"/admin/companies/{SLUG}/profiles/1")).json()
    assert one["profile"]["persona"]["pace"] == "Pace 1"
    assert one["sources"] == example()["sources"] and one["problems"] == []

    diff = (await admin.get(f"/admin/companies/{SLUG}/profiles/diff?a=1&b=2")).json()
    assert diff["total"] == 1
    persona = next(f for f in diff["fields"] if f["field"] == "persona")
    assert persona["changes"] == [
        {"path": "persona.pace", "kind": "changed", "old": "Pace 1", "new": "Pace 2"}
    ]
    assert all(f["field"] != "meta" for f in diff["fields"])
    assert (await admin.get(f"/admin/companies/{SLUG}/profiles/9")).status_code == 404
    assert (await admin.get(f"/admin/companies/{SLUG}/profiles/diff?a=1&b=9")).status_code == 404


# --- AT-4 -----------------------------------------------------------------------------------


async def test_at4_workflow_publish_records_reviewer_and_archives_previous(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    await import_(admin, variant(1))
    await import_(admin, variant(2))
    # A draft cannot skip review.
    r = await move(admin, 1, "published")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "transition_not_allowed"

    assert (await move(admin, 1, "in_review")).status_code == 200
    assert (await move(admin, 1, "draft")).status_code == 200  # sent back
    assert (await move(admin, 1, "in_review")).status_code == 200
    r = await move(admin, 1, "published")
    assert r.status_code == 200
    out = r.json()
    assert out["version"]["reviewed_by"] == ADMIN and out["archived_version"] is None
    assert out["from_status"] == "in_review" and out["version"]["published_at"]

    await move(admin, 2, "in_review")
    out = (await move(admin, 2, "published")).json()
    assert out["archived_version"] == 1
    versions = (await admin.get(f"/admin/companies/{SLUG}/profiles")).json()["versions"]
    assert [v["status"] for v in versions] == ["archived", "published"]
    stored = (await admin.get(f"/admin/companies/{SLUG}/profiles/2")).json()["profile"]["meta"]
    assert stored["status"] == "published" and stored["reviewed_by"] == ADMIN

    audit = (await audits(sessionmaker, "profile.published"))[-1]
    assert audit.entity == f"company_profile:{SLUG}:v2"
    assert audit.details_json["before"] == {"status": "in_review"}
    assert audit.details_json["archived_version"] == 1


async def test_at4_rollback_republishes_archived_and_keeps_one_published(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    """Rollback = archived -> published. Every step leaves exactly one Published row (the
    database also enforces it with a partial unique index)."""
    for n in (1, 2, 3):
        await import_(admin, variant(n))
        await move(admin, n, "in_review")
        assert (await move(admin, n, "published")).status_code == 200

    async def published() -> list[int]:
        async with sessionmaker() as db:
            rows = await db.scalars(
                select(ProfileRow.version).where(ProfileRow.status == ProfileStatus.PUBLISHED)
            )
            return list(rows)

    assert await published() == [3]
    for version in (1, 2, 1, 3):
        r = await move(admin, version, "published")
        assert r.status_code == 200, r.text
        assert await published() == [version]
    # The published version cannot go back to draft, but it can be archived (generic mode).
    assert (await move(admin, 3, "draft")).status_code == 409
    assert (await move(admin, 3, "archived")).status_code == 200
    assert await published() == []
    assert (await move(admin, 9, "archived")).status_code == 404


# --- AT-5 -----------------------------------------------------------------------------------


async def _add_requests(admin: httpx.AsyncClient, sessionmaker: Maker) -> None:
    ana = (await sign_in(admin, "ana@example.com"))["user"]
    bo = (await sign_in(admin, "bo@example.com"))["user"]
    await sign_in(admin, ADMIN)
    start = datetime(2026, 10, 1, 9, tzinfo=UTC)
    rows = [
        (ana, "Acme Inc.", "acme", "jobs.acme.com", 0),
        (ana, "Acme", "acme", None, 1),
        (bo, "ACME", "acme", "boards.greenhouse.io", 3),
        (bo, "Initech", "initech", None, 2),
    ]
    async with sessionmaker() as db:
        for user, name, key, host, day in rows:
            db.add(
                CompanyRequest(
                    org_id=uuid.UUID(user["org_id"]),
                    user_id=uuid.UUID(user["id"]),
                    company_name=name,
                    normalized_name=key,
                    matched_company_id=None,
                    source_host=host,
                    created_at=start + timedelta(days=day),
                )
            )
        await db.commit()


async def test_at5_requests_grouped_with_users_dates_hosts_and_default_triage(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    await _add_requests(admin, sessionmaker)
    groups = (await admin.get("/admin/company-requests")).json()
    assert [g["normalized_name"] for g in groups] == ["acme", "initech"]
    acme = groups[0]
    assert acme["users"] == 2 and acme["requests"] == 3
    assert acme["first_requested"].startswith("2026-10-01")
    assert acme["last_requested"].startswith("2026-10-04")
    assert acme["source_hosts"] == ["boards.greenhouse.io", "jobs.acme.com"]
    assert set(acme["names"]) == {"Acme Inc.", "Acme", "ACME"}
    assert acme["triage"]["state"] == "new" and acme["triage"]["updated_by"] is None


async def test_at5_triage_states_link_company_and_audit(
    admin: httpx.AsyncClient, sessionmaker: Maker
) -> None:
    await _add_requests(admin, sessionmaker)
    url = "/admin/company-requests/acme/triage"
    r = await admin.put(
        url, json={"state": "planned", "note": "Q4", "reason": "popular"}, headers=H
    )
    assert r.status_code == 200, r.text
    assert r.json()["triage"]["state"] == "planned" and r.json()["triage"]["note"] == "Q4"

    # added needs a company, and only added may have one
    bad = await admin.put(url, json={"state": "added", "reason": "done"}, headers=H)
    assert bad.status_code == 422
    companies = (await admin.get("/admin/companies")).json()
    google = next(c for c in companies if c["slug"] == "google")
    r = await admin.put(
        url, json={"state": "added", "company_id": google["id"], "reason": "done"}, headers=H
    )
    assert r.status_code == 200
    assert r.json()["triage"]["company_slug"] == "google"

    planned = (await admin.get("/admin/company-requests?state=added")).json()
    assert [g["normalized_name"] for g in planned] == ["acme"]
    assert (
        await admin.put(
            "/admin/company-requests/nobody/triage",
            json={"state": "declined", "reason": "none"},
            headers=H,
        )
    ).status_code == 404

    async with sessionmaker() as db:
        triage = await db.get(CompanyRequestTriage, "acme")
        requests = list(await db.scalars(select(CompanyRequest.company_name)))
    assert triage is not None and triage.updated_by == ADMIN
    assert len(requests) == 4  # request rows are not edited
    rows = await audits(sessionmaker, "company_request.triage")
    assert [r.details_json["after"]["state"] for r in rows] == ["planned", "added"]
    assert rows[1].details_json["before"]["state"] == "planned"
