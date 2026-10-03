from __future__ import annotations

from pathlib import Path

from strong_core import export_schemas


def test_check_passes_after_export(tmp_path: Path) -> None:
    assert export_schemas.main(["--out", str(tmp_path)]) == 0
    assert (tmp_path / "company_profile.schema.json").exists()
    assert export_schemas.main(["--out", str(tmp_path), "--check"]) == 0


def test_check_fails_when_stale(tmp_path: Path) -> None:
    export_schemas.main(["--out", str(tmp_path)])
    (tmp_path / "turn.schema.json").write_text("{}", encoding="utf-8")
    assert export_schemas.main(["--out", str(tmp_path), "--check"]) == 1


def test_check_fails_on_leftover_file(tmp_path: Path) -> None:
    export_schemas.main(["--out", str(tmp_path)])
    (tmp_path / "old.schema.json").write_text("{}", encoding="utf-8")
    assert export_schemas.main(["--out", str(tmp_path), "--check"]) == 1


def test_repo_schemas_are_fresh() -> None:
    """Same check as CI: schemas/ matches the Pydantic models."""
    assert export_schemas.main(["--check"]) == 0
