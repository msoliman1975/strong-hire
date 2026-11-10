"""MLflow behind admin sign-in (LT-28, LT-29, docs/llm-tracing/spec.md "Phase 2").

    GET /admin/mlflow-auth    Caddy's forward_auth check for every request to the MLflow UI and
                              API: 200 to let it through, 401 to refuse it

Caddy asks this endpoint before it proxies a request to MLflow:

- `admin.{$DOMAIN}/mlflow/*`: the admin's own session cookie (`sh_admin`, host-only on the admin
  host, AA-3) must be live (AA-4). A candidate session never passes.
- `mlflow.{$DOMAIN}`: the sim server logs its runs with `Authorization: Bearer $MLFLOW_SIM_TOKEN`
  (MLflow sends MLFLOW_TRACKING_TOKEN that way). Without MLFLOW_SIM_TOKEN no token passes.

LT-29: when an admin's request reads traces (get a trace, read its spans, search traces), this
writes `admin.trace_viewed` with the admin and the trace id or the search. The MLflow UI repeats
the same reads while a page is open, so one row per admin and target in VIEW_DEDUPE.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from strong_api.admin.deps import OptionalAdmin, admin_auth, admin_settings
from strong_api.admin.identity import AdminPrincipal
from strong_api.auth.deps import DbSession
from strong_core.db.models import AuditLog

router = APIRouter(prefix="/admin", tags=["admin"])

TRACE_VIEWED = "admin.trace_viewed"
VIEW_DEDUPE = timedelta(minutes=10)
TARGET_MAX = 200  # AuditLog.entity is String(200)

_PREFIX = re.compile(r"^(?:/mlflow)?/(?:ajax-)?api/(?P<version>[23]\.0)/mlflow/(?P<rest>.*)$")
_ID = r"[A-Za-z0-9_:.-]+"
_RESERVED = {"get", "batchGet", "batchGetInfos", "search", "metrics", "delete-traces"}


@dataclass(frozen=True)
class TraceRead:
    kind: Literal["get", "search"]
    target: str


def trace_read(method: str, uri: str) -> TraceRead | None:
    """The trace read an MLflow request makes, or None when it reads no trace.

    `uri` is the forwarded path and query (X-Forwarded-Uri), with or without the /mlflow prefix.
    A search sent as POST carries its filter in the body, which forward_auth does not pass on;
    the row then says which search endpoint was called.
    """
    parts = urlsplit(uri)
    match = _PREFIX.match(parts.path)
    if match is None:
        return None
    rest = match.group("rest").rstrip("/")
    query = parse_qs(parts.query)
    method = method.upper()

    def first(*names: str) -> str | None:
        for name in names:
            if query.get(name):
                return ",".join(query[name])
        return None

    if method == "GET":
        if rest == "get-trace-artifact" or rest == "traces/get" or rest == "traces/batchGet":
            found = first("trace_id", "request_id", "trace_ids")
            return TraceRead("get", found or rest)
        if rest == "traces":  # the v2 search
            return TraceRead("search", parts.query or "traces")
        single = re.fullmatch(rf"traces/(?P<id>{_ID})(?:/info)?", rest)
        if single and single.group("id") not in _RESERVED:
            return TraceRead("get", single.group("id"))
        return None
    if method == "POST":
        if rest == "traces/search":
            return TraceRead("search", parts.query or "traces/search")
        if rest == "traces/batchGetInfos":
            return TraceRead("get", "traces/batchGetInfos")
    return None


def sim_token_ok(request: Request) -> bool:
    expected = admin_settings(request).mlflow_sim_token
    if expected is None or not expected.get_secret_value():
        return False
    scheme, _, given = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not given:
        return False
    return hmac.compare_digest(given.strip().encode(), expected.get_secret_value().encode())


async def _record_view(
    db: DbSession, admin: AdminPrincipal, read: TraceRead, now: datetime
) -> None:
    entity = f"trace:{read.target}"[:TARGET_MAX]
    recent = await db.scalar(
        select(AuditLog.id)
        .where(
            AuditLog.action == TRACE_VIEWED,
            AuditLog.actor == admin.email,
            AuditLog.entity == entity,
            AuditLog.at >= now - VIEW_DEDUPE,
        )
        .limit(1)
    )
    if recent is not None:
        return
    db.add(
        AuditLog(
            org_id=None,
            actor=admin.email,
            action=TRACE_VIEWED,
            entity=entity,
            details_json={"kind": read.kind, "target": read.target, "admin_id": str(admin.id)},
            at=now,
        )
    )
    await db.commit()


@router.get("/mlflow-auth", include_in_schema=False)
async def mlflow_auth(request: Request, db: DbSession, admin: OptionalAdmin) -> Response:
    """LT-28: 200 for a live admin session or the sim token, else 401 (never 404: Caddy shows
    the refusal as is, and the MLflow hosts are not hidden)."""
    if admin is not None:
        read = trace_read(
            request.headers.get("x-forwarded-method", "GET"),
            request.headers.get("x-forwarded-uri", ""),
        )
        if read is not None:
            await _record_view(db, admin, read, admin_auth(request).clock())
        return Response(status_code=status.HTTP_200_OK)
    if sim_token_ok(request):
        return Response(status_code=status.HTTP_200_OK)
    return Response(status_code=status.HTTP_401_UNAUTHORIZED)
