"""Account self-service (P9): training-data consent (AC-2), data export and delete (AC-1).

`install_account(app)` adds the /account routes. Export and file deletion run as Arq jobs in
the worker (strong_worker.account), because the encrypted resume files live there.
"""

from __future__ import annotations

from fastapi import FastAPI

from strong_api.account.exports import ExportStore, MemoryExportStore, RedisExportStore
from strong_api.account.router import DELETE_ACCOUNT_FILES, EXPORT_ACCOUNT, build_router
from strong_api.account.settings import AccountSettings, get_account_settings
from strong_api.auth.settings import AuthSettings, get_auth_settings
from strong_core.config import get_settings


def install_account(
    app: FastAPI,
    settings: AccountSettings | None = None,
    *,
    auth_settings: AuthSettings | None = None,
    export_store: ExportStore | None = None,
) -> None:
    app.state.account_settings = settings or get_account_settings()
    app.state.export_store = export_store or RedisExportStore(get_settings().redis_url)
    app.include_router(build_router(auth_settings or get_auth_settings()))


__all__ = [
    "DELETE_ACCOUNT_FILES",
    "EXPORT_ACCOUNT",
    "AccountSettings",
    "MemoryExportStore",
    "install_account",
]
