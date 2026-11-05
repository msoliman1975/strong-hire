"""Delete old traces from an MLflow experiment (LT-11, D-6: dev traces live 30 days).

    uv run python -m strong_core.tracing prune [--experiment dev] [--days 30]

Reads MLFLOW_TRACKING_URI (and MLFLOW_TRACKING_USERNAME / MLFLOW_TRACKING_PASSWORD) from the
environment. Exits 0 with a message when no tracking URI is set or the experiment does not exist.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Protocol

DEFAULT_DAYS = 30


class TraceDeleter(Protocol):
    def delete_traces(self, experiment_id: str, max_timestamp_millis: int | None = None) -> int: ...


def cutoff_ms(days: int, now_s: float | None = None) -> int:
    """Traces that started before this time (epoch milliseconds) are deleted."""
    now = time.time() if now_s is None else now_s
    return int((now - days * 86400) * 1000)


def prune(client: TraceDeleter, experiment_id: str, days: int, now_s: float | None = None) -> int:
    """Delete the experiment's traces older than `days`. Returns how many were deleted."""
    if days < 1:
        raise ValueError("days must be at least 1")
    return int(client.delete_traces(experiment_id, max_timestamp_millis=cutoff_ms(days, now_s)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m strong_core.tracing", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prune", help="Delete traces older than --days.")
    p.add_argument("--experiment", default="dev")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    p.add_argument("--tracking-uri", default=None)
    args = parser.parse_args(argv)

    from strong_core.config import get_settings

    uri = args.tracking_uri or get_settings().mlflow_tracking_uri
    if not uri:
        print("No MLFLOW_TRACKING_URI set; nothing to prune.")
        return 0

    import mlflow
    from mlflow.tracing.client import TracingClient

    mlflow.set_tracking_uri(uri)
    client = TracingClient(uri)
    experiment = client.store.get_experiment_by_name(args.experiment)
    if experiment is None:
        print(f"No experiment named {args.experiment}; nothing to prune.")
        return 0
    deleted = prune(client, experiment.experiment_id, args.days)
    print(f"Deleted {deleted} traces older than {args.days} days from {args.experiment}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
