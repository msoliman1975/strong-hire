"""Start the MLflow tracking server (LT-12): create its database if missing, then run it.

The backend store is a separate `mlflow` database in the stack's Postgres, so traces never mix
with app tables. Artifacts go to /mlflow/artifacts (a volume). Settings come from the environment:

    POSTGRES_HOST, POSTGRES_USER, POSTGRES_PASSWORD   the stack's Postgres
    MLFLOW_DB                  database name (default mlflow)
    MLFLOW_ALLOWED_HOSTS       Host headers the server answers (DNS-rebinding guard)
    MLFLOW_WORKERS             server worker processes (default 2)
"""

from __future__ import annotations

import os
import sys
import time

import psycopg
from psycopg import sql


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        sys.exit(f"start.py: set {name}")
    return value


def ensure_database(host: str, user: str, password: str, name: str) -> None:
    """Create database `name` once Postgres answers. Waits up to 60 s."""
    deadline = time.monotonic() + 60
    while True:
        try:
            conn = psycopg.connect(
                host=host, user=user, password=password, dbname="postgres", autocommit=True
            )
            break
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)
    with conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        if cur.fetchone() is None:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            print(f"start.py: created database {name}", flush=True)


def server_args(host: str, user: str, password: str, name: str) -> list[str]:
    store = f"postgresql+psycopg://{user}:{password}@{host}:5432/{name}"
    return [
        "mlflow",
        "server",
        "--backend-store-uri",
        store,
        "--artifacts-destination",
        "/mlflow/artifacts",
        "--host",
        "0.0.0.0",
        "--port",
        "5000",
        "--workers",
        os.environ.get("MLFLOW_WORKERS", "2"),
        "--allowed-hosts",
        env("MLFLOW_ALLOWED_HOSTS"),
    ]


def main() -> None:
    host = env("POSTGRES_HOST", "postgres")
    user = env("POSTGRES_USER")
    password = env("POSTGRES_PASSWORD")
    name = env("MLFLOW_DB", "mlflow")
    ensure_database(host, user, password, name)
    args = server_args(host, user, password, name)
    os.execvp(args[0], args)


if __name__ == "__main__":
    main()
