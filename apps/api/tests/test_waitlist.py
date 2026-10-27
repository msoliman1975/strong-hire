"""L04 step 1: the public waitlist with double opt-in, and its admin list and CSV export."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.auth.magic_links import MagicLinks, MemoryUsedTokenStore
from strong_api.public import WAITLIST_LINK_SALT, JoinLimiter, Waitlist
from strong_core.db.models import AdminUser, WaitlistEntry

from .conftest import make_admin


class RecordingSender:
    def __init__(self) -> None:
        self.mail: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, text: str) -> None:
        self.mail.append((to, subject, text))


@pytest.fixture
def sender(app: FastAPI) -> RecordingSender:
    recording = RecordingSender()
    app.state.waitlist = Waitlist(
        links=MagicLinks("t" * 40, 3600, MemoryUsedTokenStore(), salt=WAITLIST_LINK_SALT),
        email_sender=recording,
        limiter=JoinLimiter(limit=3),
        web_base_url="https://example.test",
    )
    return recording


JOIN = {"email": "Ada@Example.com", "interview_within": "two_weeks", "role_family": "swe"}


def _token(sender: RecordingSender) -> str:
    link = sender.mail[-1][2].split("\n\n")[1]
    assert link.startswith("https://example.test/waitlist/confirm?token=")
    return parse_qs(urlparse(link).query)["token"][0]


async def _entry(maker: async_sessionmaker[AsyncSession], email: str) -> WaitlistEntry | None:
    async with maker() as db:
        return await db.scalar(select(WaitlistEntry).where(WaitlistEntry.email == email))


async def test_l04_join_then_confirm(
    anon_client: httpx.AsyncClient,
    sender: RecordingSender,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """L04: joining stores a lowercased entry and emails a link; the link confirms it."""
    r = await anon_client.post("/public/waitlist", json={**JOIN, "source": "reddit"})
    assert r.status_code == 202
    assert r.json() == {"status": "check_email"}
    entry = await _entry(sessionmaker, "ada@example.com")
    assert entry is not None
    assert entry.confirmed_at is None
    assert entry.marketing_consent is False
    assert entry.source == "reddit"
    assert sender.mail[-1][0] == "ada@example.com"

    r = await anon_client.post("/public/waitlist/confirm", json={"token": _token(sender)})
    assert r.status_code == 200
    entry = await _entry(sessionmaker, "ada@example.com")
    assert entry is not None and entry.confirmed_at is not None


async def test_l04_join_again_updates_and_never_reveals_membership(
    anon_client: httpx.AsyncClient,
    sender: RecordingSender,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """L04: a second join answers the same, updates the entry, and a confirmed entry gets no
    new email."""
    await anon_client.post("/public/waitlist", json=JOIN)
    await anon_client.post("/public/waitlist/confirm", json={"token": _token(sender)})
    sent = len(sender.mail)

    again = {**JOIN, "interview_within": "month", "marketing_consent": True}
    r = await anon_client.post("/public/waitlist", json=again)
    assert r.status_code == 202
    assert r.json() == {"status": "check_email"}
    assert len(sender.mail) == sent
    entry = await _entry(sessionmaker, "ada@example.com")
    assert entry is not None
    assert entry.interview_within.value == "month"
    assert entry.marketing_consent is True


async def test_l04_honeypot_is_dropped(
    anon_client: httpx.AsyncClient,
    sender: RecordingSender,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """L04: a filled hidden field looks accepted but stores and sends nothing."""
    r = await anon_client.post("/public/waitlist", json={**JOIN, "website": "spam.example"})
    assert r.status_code == 202
    assert sender.mail == []
    assert await _entry(sessionmaker, "ada@example.com") is None


async def test_l04_joins_are_rate_limited(
    anon_client: httpx.AsyncClient, sender: RecordingSender
) -> None:
    """L04: joins are limited per client address."""
    for i in range(3):
        r = await anon_client.post("/public/waitlist", json={**JOIN, "email": f"u{i}@example.com"})
        assert r.status_code == 202
    r = await anon_client.post("/public/waitlist", json={**JOIN, "email": "u9@example.com"})
    assert r.status_code == 429


async def test_l04_rejects_bad_input_and_bad_links(
    anon_client: httpx.AsyncClient, sender: RecordingSender
) -> None:
    """L04: invalid emails, unknown fields and forged links are refused."""
    bad = await anon_client.post("/public/waitlist", json={**JOIN, "email": "not-an-email"})
    assert bad.status_code == 422
    extra = await anon_client.post("/public/waitlist", json={**JOIN, "name": "Ada"})
    assert extra.status_code == 422
    forged = await anon_client.post("/public/waitlist/confirm", json={"token": "abc"})
    assert forged.status_code == 400


async def test_l04_admin_lists_and_exports_the_waitlist(
    anon_client: httpx.AsyncClient, admin_client: httpx.AsyncClient, sender: RecordingSender
) -> None:
    """L04: admins see counts and entries, and download a CSV."""
    await anon_client.post("/public/waitlist", json={**JOIN, "marketing_consent": True})
    await anon_client.post("/public/waitlist/confirm", json={"token": _token(sender)})
    await anon_client.post(
        "/public/waitlist", json={"email": "bo@example.com", "interview_within": "not_yet"}
    )

    r = await admin_client.get("/admin/waitlist")
    assert r.status_code == 200
    body = r.json()
    assert (body["total"], body["confirmed"], body["marketing_consent"]) == (2, 1, 1)
    assert {e["email"] for e in body["entries"]} == {"ada@example.com", "bo@example.com"}

    csv = await admin_client.get("/admin/waitlist.csv")
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    lines = csv.text.strip().splitlines()
    assert lines[0] == (
        "email,interview_within,role_family,marketing_consent,source,confirmed_at,invited_at,"
        "created_at"
    )
    assert len(lines) == 3


async def test_l04_waitlist_admin_routes_need_an_admin(
    anon_client: httpx.AsyncClient, sender: RecordingSender
) -> None:
    """L04: the list and the CSV are admin-only (non-admins get 404, as for every admin route)."""
    assert (await anon_client.get("/admin/waitlist")).status_code == 404
    assert (await anon_client.get("/admin/waitlist.csv")).status_code == 404


async def test_l04_each_active_admin_is_emailed_about_a_new_entry(
    app: FastAPI,
    anon_client: httpx.AsyncClient,
    sender: RecordingSender,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """L04: a new join emails every active admin, one email each and without the confirmation
    link. A second join of the same email sends no new notice."""
    await make_admin(app, "boss@example.com")
    await make_admin(app, "ops@example.com")
    await make_admin(app, "gone@example.com")
    async with sessionmaker() as db:
        gone = await db.scalar(select(AdminUser).where(AdminUser.email == "gone@example.com"))
        assert gone is not None
        gone.disabled_at = datetime.now(UTC)
        await db.commit()

    await anon_client.post("/public/waitlist", json={**JOIN, "source": "reddit"})
    notices = [m for m in sender.mail if m[1].startswith("Waitlist: ")]
    assert sorted(m[0] for m in notices) == ["boss@example.com", "ops@example.com"]
    _, subject, text = notices[0]
    assert subject == "Waitlist: ada@example.com joined"
    assert "Interview: two_weeks" in text and "Source: reddit" in text
    assert "token=" not in text  # only the person who joined can confirm
    assert sender.mail[-1][0] == "ada@example.com"  # their confirmation still goes out

    before = len(sender.mail)
    await anon_client.post("/public/waitlist", json={**JOIN, "interview_within": "month"})
    assert not [m for m in sender.mail[before:] if m[1].startswith("Waitlist: ")]
