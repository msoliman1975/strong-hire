"""Delete real users' traces from MLflow (LT-24, LT-25, LT-27, D-14, D-18).

    delete_org_traces(org_id, "all")       account deleted (LT-25)
    delete_org_traces(org_id, "content")   consent withdrawn (LT-24): turn.content traces only
    prune_prod(content_days=30, metadata_days=90)   daily retention (LT-27)

Every production trace carries `org_id` and `content` tags (LT-18, LT-23), so one search per org
finds them. These functions talk to MLflow and may raise: the worker job that calls them retries
(LT-26). A client can be passed in for tests; otherwise the MLflow tracing client is built from
MLFLOW_TRACKING_URI.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Literal, Protocol

Scope = Literal["all", "content"]
BATCH = 100
CONTENT_TAG = "turns"


class TraceStore(Protocol):
    def experiment_id(self, name: str) -> str | None: ...

    def trace_ids(self, experiment_id: str, filter_string: str) -> list[str]: ...

    def delete(self, experiment_id: str, trace_ids: list[str]) -> int: ...

    def delete_before(self, experiment_id: str, before_ms: int) -> int: ...


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def org_filter(org_id: uuid.UUID, scope: Scope) -> str:
    """The search for one org's traces; `content` narrows it to turn.content traces."""
    f = f"tags.org_id = '{_quote(str(org_id))}'"
    if scope == "content":
        f += f" AND tags.content = '{CONTENT_TAG}'"
    return f


def delete_org_traces(org_id: uuid.UUID, scope: Scope, store: TraceStore | None = None) -> int:
    """Delete an org's production traces. Returns how many were deleted."""
    store = store or MlflowTraceStore.from_settings()
    experiment = _prod_experiment(store)
    if experiment is None:
        return 0
    deleted = 0
    while True:
        ids = store.trace_ids(experiment, org_filter(org_id, scope))
        if not ids:
            return deleted
        this_round = 0
        for start in range(0, len(ids), BATCH):
            this_round += store.delete(experiment, ids[start : start + BATCH])
        if this_round == 0:  # found but not deletable: fail loudly, the job retries (LT-26)
            raise RuntimeError(f"MLflow kept {len(ids)} traces of org {org_id} after a delete")
        deleted += this_round


def prune_prod(
    content_days: int = 30,
    metadata_days: int = 90,
    store: TraceStore | None = None,
    now_s: float | None = None,
) -> dict[str, int]:
    """Delete turn.content traces older than content_days and all other production traces older
    than metadata_days (LT-27). Returns the counts."""
    if not 1 <= content_days <= metadata_days:
        raise ValueError("need 1 <= content_days <= metadata_days")
    store = store or MlflowTraceStore.from_settings()
    experiment = _prod_experiment(store)
    if experiment is None:
        return {"content": 0, "metadata": 0}
    now = time.time() if now_s is None else now_s
    content_cutoff = int((now - content_days * 86400) * 1000)
    old_content = store.trace_ids(
        experiment,
        f"tags.content = '{CONTENT_TAG}' AND attributes.timestamp_ms < {content_cutoff}",
    )
    content = 0
    for start in range(0, len(old_content), BATCH):
        content += store.delete(experiment, old_content[start : start + BATCH])
    metadata = store.delete_before(experiment, int((now - metadata_days * 86400) * 1000))
    return {"content": content, "metadata": metadata}


def _prod_experiment(store: TraceStore) -> str | None:
    from strong_core.config import get_settings

    return store.experiment_id(get_settings().mlflow_prod_experiment)


class MlflowTraceStore:
    """TraceStore on the MLflow tracing client."""

    def __init__(self, tracking_uri: str) -> None:
        os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
        import mlflow
        from mlflow.tracing.client import TracingClient

        mlflow.set_tracking_uri(tracking_uri)
        self.client: Any = TracingClient(tracking_uri)

    @classmethod
    def from_settings(cls) -> MlflowTraceStore:
        from strong_core.config import get_settings

        uri = get_settings().mlflow_tracking_uri
        if not uri:
            raise RuntimeError("no MLFLOW_TRACKING_URI: cannot delete production traces")
        return cls(uri)

    def experiment_id(self, name: str) -> str | None:
        found = self.client.store.get_experiment_by_name(name)
        return None if found is None else str(found.experiment_id)

    def trace_ids(self, experiment_id: str, filter_string: str) -> list[str]:
        page = self.client.search_traces(
            locations=[experiment_id],
            filter_string=filter_string,
            max_results=BATCH,
            include_spans=False,
        )
        return [str(t.info.trace_id) for t in page]

    def delete(self, experiment_id: str, trace_ids: list[str]) -> int:
        return int(self.client.delete_traces(experiment_id, trace_ids=trace_ids))

    def delete_before(self, experiment_id: str, before_ms: int) -> int:
        return int(self.client.delete_traces(experiment_id, max_timestamp_millis=before_ms))


__all__ = [
    "BATCH",
    "MlflowTraceStore",
    "Scope",
    "TraceStore",
    "delete_org_traces",
    "org_filter",
    "prune_prod",
]
