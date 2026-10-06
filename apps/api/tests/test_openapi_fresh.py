"""The web app's typed client is generated from apps/web/openapi.json; it must match the API."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "web" / "scripts" / "export_openapi.py"


def test_web_openapi_json_is_fresh() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
