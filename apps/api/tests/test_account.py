"""Account self-service (P9). Requirement IDs: AC-1 (export and full delete), AC-2 (training-data
consent toggle, off by default, changeable any time, recorded in AuditLog)."""

from __future__ import annotations

import io
import json
import os
import uuid
import zipfile
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from strong_api.account import DELETE_ACCOUNT_FILES, EXPORT_ACCOUNT
from strong_api.account.deletion import delete_org_rows, user_owned_tables_children_first
from strong_api.account.exports import MemoryExportStore, export_key
from strong_core.db.engine import async_database_url
from strong_core.db.models import USER_OWNED_TABLES, AuditLog, Base, Org, Resume, User
from strong_worker.account import jobs as account_jobs
from strong_worker.account.jobs import CTX_KEY, AccountContext
from strong_worker.inputs.storage import LocalEncryptedFileStore
from strong_worker.inputs.testing import set_extractor_output

from .accounts_support import CUSTOMER_ID, FakeStripe, fill_every_user_table, sign_up
from .conftest import InlineQueue

Maker = async_sessionmaker[AsyncSession]
RESUME_BYTES = b"Ana Lee. Backend engineer, 7 years of Python and payments systems."


@pytest.fixture
def stripe() -> FakeStripe:
    return FakeStripe()


@pytest.fixture
def account_app(app: FastAPI, stripe: FakeStripe) -> FastAPI:
    app.state.stripe = stripe
    return app


@pytest.fixture
async def user(account_app: FastAPI, client: httpx.AsyncClient) -> dict[str, Any]:
    return await sign_up(client)


def file_store(ctx: dict[str, Any]) -> LocalEncryptedFileStore:
    store = ctx[CTX_KEY].store
    assert isinstance(store, LocalEncryptedFileStore)
    return store


async def audit(maker: Maker, action: str) -> list[AuditLog]:
    async with maker() as db:
        return list(await db.scalars(select(AuditLog).where(AuditLog.action == action)))


def test_queue_names_match_worker_functions() -> None:
    for name in (EXPORT_ACCOUNT, DELETE_ACCOUNT_FILES):
        assert getattr(account_jobs, name) in account_jobs.FUNCTIONS


def test_export_keys_match_between_api_and_worker() -> None:
    org, export = uuid.uuid4(), uuid.uuid4()
    assert export_key(org, export) == account_jobs.export_key(org, export)


# ---------------------------------------------------------------- AC-2 consent


async def test_ac2_consent_toggle_is_saved_and_audited(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    assert user["training_consent"] is False  # off by default
    resp = await client.put("/account/consent", json={"training_consent": True})
    assert resp.status_code == 200
    assert resp.json() == {"training_consent": True}
    assert (await client.get("/auth/me")).json()["user"]["training_consent"] is True

    # The same value again changes nothing and adds no audit entry.
    await client.put("/account/consent", json={"training_consent": True})
    await client.put("/account/consent", json={"training_consent": False})
    assert (await client.get("/auth/me")).json()["user"]["training_consent"] is False

    entries = await audit(sessionmaker, "account.consent_changed")
    assert [(e.details_json or {}).get("training_consent_to") for e in entries] == [True, False]
    assert all(e.actor == f"user:{user['id']}" for e in entries)
    assert all(str(e.org_id) == user["org_id"] for e in entries)


async def test_ac2_consent_needs_sign_in(
    account_app: FastAPI, anon_client: httpx.AsyncClient
) -> None:
    resp = await anon_client.put("/account/consent", json={"training_consent": True})
    assert resp.status_code == 401


# ---------------------------------------------------------------- AC-1 export


async def _upload_resume(client: httpx.AsyncClient, fake_fixtures: Any) -> str:
    set_extractor_output(
        fake_fixtures,
        "Resume",
        json.loads((fake_fixtures / "extractor" / "Resume.json").read_text(encoding="utf-8")),
    )
    resp = await client.post("/resumes", files={"file": ("cv.txt", RESUME_BYTES, "text/plain")})
    assert resp.status_code == 202, resp.text
    resume_id: str = resp.json()["resume"]["id"]
    return resume_id


async def test_ac1_export_has_all_user_data_and_the_original_resume(
    client: httpx.AsyncClient,
    user: dict[str, Any],
    sessionmaker: Maker,
    fake_fixtures: Any,
    ctx: dict[str, Any],
) -> None:
    resume_id = await _upload_resume(client, fake_fixtures)
    org_id, user_id = uuid.UUID(user["org_id"]), uuid.UUID(user["id"])
    async with sessionmaker() as db:
        filled = await fill_every_user_table(db, org_id, user_id, file_ref=None)
        # Another user's data must not appear in this export.
        other_org = Org(name="other")
        db.add(other_org)
        await db.flush()
        other = User(org_id=other_org.id, email="bo@example.com", auth_provider="dev")
        db.add(other)
        await db.flush()
        await fill_every_user_table(db, other_org.id, other.id, file_ref=None)

    started = await client.post("/account/export")
    assert started.status_code == 202, started.text
    export = started.json()
    assert export["status"] == "ready"  # the inline queue runs the job at once
    assert export["download_url"] == (
        f"http://localhost:5180/api/account/export/{export['id']}/download"
    )

    resp = await client.get(f"/account/export/{export['id']}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "attachment" in resp.headers["content-disposition"]
    bundle = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(bundle.namelist())
    assert {"README.txt", "data.json"} <= names
    data = json.loads(bundle.read("data.json"))
    assert data["format"] == "strong-hire-export"
    assert data["user_id"] == user["id"]

    tables = data["tables"]
    assert set(USER_OWNED_TABLES) | {"orgs", "audit_logs"} == set(tables)
    for name in filled:
        assert tables[name], f"{name} is empty in the export"
        for row in tables[name]:
            assert row["org_id"] == user["org_id"], name
    assert tables["users"][0]["email"] == "ana@example.com"
    assert tables["orgs"][0]["id"] == user["org_id"]
    assert {r["action"] for r in tables["audit_logs"]} >= {
        "user.signup",
        "account.export_requested",
    }
    assert "bo@example.com" not in bundle.read("data.json").decode()

    # The original resume file, decrypted.
    files = [f for f in data["files"] if f["resume_id"] == resume_id]
    assert len(files) == 1 and files[0]["path"]
    assert bundle.read(files[0]["path"]) == RESUME_BYTES


async def test_ac1_export_downloads_once(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    export = (await client.post("/account/export")).json()
    url = f"/account/export/{export['id']}/download"
    assert (await client.get(url)).status_code == 200
    second = await client.get(url)
    assert second.status_code == 410
    assert second.json()["detail"]["code"] == "export_gone"
    status = (await client.get(f"/account/export/{export['id']}")).json()
    assert status["status"] == "downloaded"
    assert status["download_url"] is None
    assert len(await audit(sessionmaker, "account.export_requested")) == 1
    assert len(await audit(sessionmaker, "account.export_downloaded")) == 1


async def test_ac1_export_status_while_preparing_and_after_expiry(
    client: httpx.AsyncClient,
    user: dict[str, Any],
    queue: InlineQueue,
    export_store: MemoryExportStore,
) -> None:
    queue.run_jobs = False
    export = (await client.post("/account/export")).json()
    assert export["status"] == "preparing"
    assert export["download_url"] is None

    queue.run_jobs = True
    ready = (await client.post("/account/export")).json()
    export_store.data.clear()  # the time limit passed
    assert (await client.get(f"/account/export/{ready['id']}")).json()["status"] == "expired"


async def test_ac1_export_belongs_to_its_user(
    account_app: FastAPI, client: httpx.AsyncClient, user: dict[str, Any]
) -> None:
    export = (await client.post("/account/export")).json()
    await client.post("/auth/logout")
    await sign_up(client, "bo@example.com")
    assert (await client.get(f"/account/export/{export['id']}")).status_code == 404
    assert (await client.get(f"/account/export/{export['id']}/download")).status_code == 404
    assert (await client.get("/account/export/not-a-uuid")).status_code == 404


async def test_ac1_export_too_large_fails_cleanly(
    account_app: FastAPI, client: httpx.AsyncClient, user: dict[str, Any]
) -> None:
    account_app.state.account_settings = account_app.state.account_settings.model_copy(
        update={"account_export_max_mb": 0}
    )
    export = (await client.post("/account/export")).json()
    assert export["status"] == "failed"
    assert "larger than" in export["error"]


# ---------------------------------------------------------------- AC-1 delete


async def count_org_rows(db: AsyncSession, org_id: uuid.UUID) -> dict[str, int]:
    counts = {}
    for table in user_owned_tables_children_first():
        counts[table.name] = int(
            await db.scalar(select(func.count()).select_from(table).where(table.c.org_id == org_id))
            or 0
        )
    counts["orgs"] = int(
        await db.scalar(select(func.count()).select_from(Org).where(Org.id == org_id)) or 0
    )
    return counts


async def test_ac1_delete_leaves_no_rows_and_no_files(
    client: httpx.AsyncClient,
    user: dict[str, Any],
    sessionmaker: Maker,
    fake_fixtures: Any,
    ctx: dict[str, Any],
    stripe: FakeStripe,
    export_store: MemoryExportStore,
    queue: InlineQueue,
) -> None:
    await _upload_resume(client, fake_fixtures)
    await client.put("/account/consent", json={"training_consent": True})
    export = (await client.post("/account/export")).json()
    org_id, user_id = uuid.UUID(user["org_id"]), uuid.UUID(user["id"])
    async with sessionmaker() as db:
        filled = await fill_every_user_table(db, org_id, user_id, file_ref=None)
        sub = await db.scalar(
            select(Resume.file_ref).where(Resume.org_id == org_id, Resume.file_ref.is_not(None))
        )
        assert sub is not None
        file_ref = sub
        # Give the subscription a Stripe customer, so delete must cancel billing.
        from strong_core.db.models import Subscription

        row = await db.scalar(select(Subscription).where(Subscription.org_id == org_id))
        assert row is not None
        row.stripe_customer_id = CUSTOMER_ID
        # Someone else's data must stay.
        other_org = Org(name="other")
        db.add(other_org)
        await db.flush()
        other = User(org_id=other_org.id, email="bo@example.com", auth_provider="dev")
        db.add(other)
        await db.flush()
        await db.commit()
        await fill_every_user_table(db, other_org.id, other.id, file_ref=None)
        before = await count_org_rows(db, org_id)
    assert all(before[name] > 0 for name in filled), before
    store = file_store(ctx)
    assert await store.get(file_ref) == RESUME_BYTES
    assert export_key(org_id, export["id"]) in export_store.data

    resp = await client.delete("/account")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "deleted"
    assert body["files_pending"] == 1
    assert body["files_deleted_within_hours"] == 24
    assert body["backups_expire_within_days"] == 30

    async with sessionmaker() as db:
        after = await count_org_rows(db, org_id)
        assert set(after.values()) == {0}, after
        assert (
            await db.scalar(
                select(func.count()).select_from(User).where(User.email == "ana@example.com")
            )
            == 0
        )
        other_rows = await count_org_rows(db, other_org.id)
        assert all(other_rows[name] > 0 for name in filled)
        logs = list(await db.scalars(select(AuditLog).where(AuditLog.org_id == org_id)))

    # The resume file is gone, and so is the waiting export.
    assert [j[0] for j in queue.enqueued].count(DELETE_ACCOUNT_FILES) == 1
    with pytest.raises(FileNotFoundError):
        await store.get(file_ref)
    assert not any(k.startswith(export_key(org_id, "")) for k in export_store.data)
    # Billing stopped.
    assert stripe.deleted_customers == [CUSTOMER_ID]

    # The audit log keeps the deletion, without the email.
    actions = [log.action for log in logs]
    assert "account.deleted" in actions
    assert "account.files_deleted" in actions
    assert all("ana@example.com" not in log.actor for log in logs)
    deleted = next(log for log in logs if log.action == "account.deleted")
    assert deleted.details_json is not None
    assert deleted.details_json["rows"]["users"] == 1
    assert deleted.details_json["backups_expire_within_days"] == 30

    # Signed out: the session no longer works.
    assert (await client.get("/auth/me")).json()["status"] == "signed_out"
    assert (await client.get("/billing/usage")).status_code == 401


async def test_ac1_delete_needs_stripe_when_the_user_has_a_customer(
    account_app: FastAPI, client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    from strong_core.db.models import Subscription
    from strong_core.schemas import SubscriptionStatus

    async with sessionmaker() as db:
        db.add(
            Subscription(
                org_id=uuid.UUID(user["org_id"]),
                user_id=uuid.UUID(user["id"]),
                status=SubscriptionStatus.ACTIVE,
                stripe_customer_id=CUSTOMER_ID,
            )
        )
        await db.commit()
    account_app.state.stripe = None
    resp = await client.delete("/account")
    assert resp.status_code == 503
    async with sessionmaker() as db:
        assert await db.get(User, uuid.UUID(user["id"])) is not None


async def test_ac1_file_delete_job_retries_on_storage_errors(
    sessionmaker: Maker, ctx: dict[str, Any]
) -> None:
    from arq import Retry

    class BrokenStore:
        async def delete(self, ref: str) -> None:
            raise OSError("disk is busy")

    broken = {CTX_KEY: AccountContext(sessionmaker, BrokenStore(), MemoryExportStore())}  # type: ignore[arg-type]
    with pytest.raises(Retry):
        await account_jobs.delete_account_files(
            {**broken, "job_try": 1}, str(uuid.uuid4()), ["local:x/y"]
        )
    with pytest.raises(OSError):
        await account_jobs.delete_account_files(
            {**broken, "job_try": account_jobs.DELETE_MAX_TRIES}, str(uuid.uuid4()), ["local:x/y"]
        )


async def test_inputs_belong_to_the_signed_in_user(
    client: httpx.AsyncClient, user: dict[str, Any], sessionmaker: Maker
) -> None:
    resp = await client.post("/job-targets", json={"text": "Senior engineer at Stripe. " * 10})
    assert resp.status_code == 202, resp.text
    async with sessionmaker() as db:
        from strong_core.db.models import JobTarget

        target = await db.get(JobTarget, uuid.UUID(resp.json()["job_target"]["id"]))
    assert target is not None
    assert str(target.org_id) == user["org_id"]
    assert str(target.user_id) == user["id"]


# ---------------------------------------------------------------- Postgres (optional)

POSTGRES_URL = os.environ.get("STRONG_TEST_POSTGRES_URL")


@pytest.mark.skipif(POSTGRES_URL is None, reason="needs STRONG_TEST_POSTGRES_URL (migrated)")
async def test_ac1_delete_on_postgres_leaves_no_rows() -> None:
    """Runs on the migrated Postgres schema, so foreign keys and the delete order are real."""
    assert POSTGRES_URL is not None
    engine = create_async_engine(async_database_url(POSTGRES_URL))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as db:
            org = Org(name="pg-delete-test")
            db.add(org)
            await db.flush()
            user = User(
                org_id=org.id, email=f"pg-{uuid.uuid4().hex}@example.com", auth_provider="dev"
            )
            db.add(user)
            await db.commit()
            await fill_every_user_table(db, org.id, user.id, file_ref="local:resumes/x/y.pdf")
            result = await delete_org_rows(db, org.id)
            await db.commit()
            assert result.file_refs == ["local:resumes/x/y.pdf"]
            assert result.rows["users"] == 1
            for table in Base.metadata.sorted_tables:
                if table.name in USER_OWNED_TABLES:
                    count = await db.scalar(
                        text(f"SELECT count(*) FROM {table.name} WHERE org_id = :o"),
                        {"o": org.id},
                    )
                    assert count == 0, table.name
            assert await db.get(Org, org.id) is None
            await db.execute(text("DELETE FROM audit_logs WHERE org_id = :o"), {"o": org.id})
            await db.commit()
    finally:
        await engine.dispose()
