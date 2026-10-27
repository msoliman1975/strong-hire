"""v2 part 1 core changes (C1): tone (TN-1), auto-profiles (AP-1) and v2_enabled (FL-1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from strong_core import runtime_settings as rs
from strong_core.db.models import USER_OWNED_TABLES, Base
from strong_core.schemas import (
    AutoProfileStatus,
    AutoProfileSummary,
    Difficulty,
    InterviewType,
    Level,
    Mode,
    SessionConfig,
    Tone,
)

FIXTURES = Path(__file__).parents[1] / "src" / "strong_core" / "gateway" / "fixtures"


def _config(**extra: object) -> SessionConfig:
    return SessionConfig.model_validate(
        {
            "interview_type": InterviewType.BEHAVIORAL,
            "difficulty": Difficulty.REALISTIC,
            "mode": Mode.REALISTIC,
            "duration_min": 30,
            "level": Level.SENIOR,
            **extra,
        }
    )


def test_tn1_session_config_tone_defaults_to_as_company() -> None:
    """TN-1: a config without a tone (every v1 client) reads as as_company."""
    assert _config().tone == Tone.AS_COMPANY
    assert _config(tone="direct").tone == Tone.DIRECT
    with pytest.raises(ValidationError):
        _config(tone="sarcastic")


def test_tn1_session_tone_column_defaults_old_rows_to_as_company() -> None:
    """TN-1: the sessions.tone column is non-null with a server default, so old rows read as
    as_company after the migration."""
    column = Base.metadata.tables["sessions"].columns["tone"]
    assert not column.nullable
    assert column.server_default is not None
    assert str(column.server_default.arg) == "as_company"


def test_ap1_auto_profile_table_is_platform_with_provenance() -> None:
    """AP-1, PL-6: auto-profiles are shared per company (no org_id) and record provenance."""
    table = Base.metadata.tables["company_auto_profiles"]
    assert "company_auto_profiles" not in USER_OWNED_TABLES
    assert "org_id" not in table.columns
    for name in ("model_profile", "model_id", "prompt_version", "reviewed_by", "reviewed_at"):
        assert name in table.columns
    assert str(table.columns["status"].server_default.arg) == AutoProfileStatus.PENDING


def test_ap1_auto_profile_summary_fixture_validates() -> None:
    """AP-1: the extractor's fake reply for AutoProfileSummary validates."""
    raw = json.loads((FIXTURES / "extractor" / "AutoProfileSummary.json").read_text("utf-8"))
    summary = AutoProfileSummary.model_validate(raw)
    assert summary.sources


def test_ap1_auto_profile_summary_rejects_unknown_fields_and_needs_sources() -> None:
    """AP-1: the contract rejects unknown fields and a summary without sources."""
    good = {"summary": "A company.", "sources": ["https://example.com/about"]}
    AutoProfileSummary.model_validate(good)
    with pytest.raises(ValidationError):
        AutoProfileSummary.model_validate({**good, "rating": 5})
    with pytest.raises(ValidationError):
        AutoProfileSummary.model_validate({**good, "sources": []})


def test_fl1_v2_enabled_defaults_off() -> None:
    """FL-1: v2_enabled is a runtime setting and is off by default."""
    assert rs.SettingKey.V2_ENABLED == "v2_enabled"
    assert rs.DEFAULTS.v2_enabled is False
    assert rs.validate("v2_enabled", True) is True
