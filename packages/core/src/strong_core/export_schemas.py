"""Write JSON Schemas for the shared contracts into schemas/.

uv run python -m strong_core.export_schemas          # write files
uv run python -m strong_core.export_schemas --check  # exit 1 if any file is stale (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from strong_core.config import find_repo_root
from strong_core.schemas import EXPORTED_SCHEMAS


def render_all() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, model in EXPORTED_SCHEMAS.items():
        schema = model.model_json_schema(mode="validation")
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://strong-hire.local/schemas/{name}.schema.json",
            **schema,
        }
        out[f"{name}.schema.json"] = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if files are stale.")
    parser.add_argument("--out", type=Path, default=find_repo_root() / "schemas")
    args = parser.parse_args(argv)

    out_dir: Path = args.out
    expected = render_all()
    existing = {p.name for p in out_dir.glob("*.schema.json")} if out_dir.exists() else set()

    if args.check:
        stale = [n for n, text in expected.items() if not _same(out_dir / n, text)]
        extra = sorted(existing - set(expected))
        if stale or extra:
            for n in stale:
                print(f"stale or missing: schemas/{n}", file=sys.stderr)
            for n in extra:
                print(f"no longer generated: schemas/{n}", file=sys.stderr)
            print("Run: uv run python -m strong_core.export_schemas", file=sys.stderr)
            return 1
        print(f"{len(expected)} schemas are up to date.")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    for n, text in expected.items():
        (out_dir / n).write_text(text, encoding="utf-8", newline="\n")
    for n in existing - set(expected):
        (out_dir / n).unlink()
    print(f"Wrote {len(expected)} schemas to {out_dir}.")
    return 0


def _same(path: Path, text: str) -> bool:
    return path.exists() and path.read_text(encoding="utf-8") == text


if __name__ == "__main__":
    raise SystemExit(main())
