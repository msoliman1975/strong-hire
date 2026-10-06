"""Write apps/web/openapi.json from the FastAPI app, plus every shared contract in strong_core.

The web app generates its typed client from this file (`pnpm gen:api`). Contracts are added to
components.schemas even when no route uses them yet, so mocks of planned endpoints are typed
with the same shapes the backend will return.

    uv run python apps/web/scripts/export_openapi.py          # write
    uv run python apps/web/scripts/export_openapi.py --check  # fail if the file is stale
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

# The schema always includes the local-only dev login route, whatever the developer's .env says.
os.environ["APP_ENV"] = "local"

from strong_api.main import create_app
from strong_core.schemas import (
    EXPORTED_SCHEMAS,
    SessionStatus,
    SubscriptionStatus,
)

OUT = Path(__file__).resolve().parents[1] / "openapi.json"


async def _no_check() -> None:
    return None


class _ExtraEnums(BaseModel):
    """Enums that no exported contract references yet, but the web app displays."""

    session_status: SessionStatus
    subscription_status: SubscriptionStatus


def build_openapi() -> dict[str, Any]:
    spec = create_app({"database": _no_check}).openapi()
    _, defs = models_json_schema(
        [(m, "serialization") for m in [*EXPORTED_SCHEMAS.values(), _ExtraEnums]],
        ref_template="#/components/schemas/{model}",
    )
    components = spec.setdefault("components", {}).setdefault("schemas", {})
    for name, schema in defs.get("$defs", {}).items():
        if name != _ExtraEnums.__name__:
            components.setdefault(name, schema)
    spec["components"]["schemas"] = dict(sorted(components.items()))
    return spec


def render() -> str:
    return json.dumps(build_openapi(), indent=2, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = render()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT} is stale. Run: uv run python apps/web/scripts/export_openapi.py")
            return 1
        print("openapi.json is fresh")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
