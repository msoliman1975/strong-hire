"""The API Docker image has no worker package (infra/docker/python.Dockerfile copies only the
app's own folder), so API code must never import strong_worker. Tests may."""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).parents[1] / "src"


def test_api_code_does_not_import_the_worker() -> None:
    pattern = re.compile(r"^\s*(from|import)\s+strong_worker\b", re.MULTILINE)
    offenders = [
        str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if pattern.search(p.read_text("utf-8"))
    ]
    assert offenders == []
