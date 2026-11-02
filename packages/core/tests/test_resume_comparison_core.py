"""Resume comparison core (RC-6, RC-7, RC-8): the resume_comparisons table, the purpose of a
gap analysis row and the entry contract."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from strong_core.db.models import USER_OWNED_TABLES, Base
from strong_core.schemas import EXPORTED_SCHEMAS, GapPurpose, ResumeComparisonEntry

MIGRATION = next(
    (Path(__file__).parents[1] / "migrations" / "versions").glob("*_0028_resume_comparisons.py")
)


def test_rc8_resume_comparisons_table_is_user_owned_and_saved_on_the_role() -> None:
    """RC-8: a comparison is saved on the role, with what it compared, what the user picked and
    which hints were dismissed or applied. It is user-owned, so export and delete cover it."""
    assert "resume_comparisons" in USER_OWNED_TABLES
    table = Base.metadata.tables["resume_comparisons"]
    for column in (
        "org_id",
        "user_id",
        "job_target_id",
        "entries_json",
        "new_runs",
        "chosen_resume_id",
        "dismissed_json",
        "applied_json",
        "created_at",
    ):
        assert column in table.columns, column
    for column in ("org_id", "user_id", "job_target_id", "entries_json", "new_runs"):
        assert not table.columns[column].nullable, column
    org_fk = next(iter(table.columns["org_id"].foreign_keys))
    assert org_fk.ondelete == "CASCADE"
    chosen_fk = next(iter(table.columns["chosen_resume_id"].foreign_keys))
    assert chosen_fk.ondelete == "SET NULL"


def test_rc7_gap_rows_have_a_purpose_and_existing_rows_are_role_rows() -> None:
    """RC-7: a comparison row is told apart from the role's own analysis. Rows from before the
    migration are role rows (server default)."""
    table = Base.metadata.tables["gap_analyses"]
    purpose = table.columns["purpose"]
    assert not purpose.nullable
    assert purpose.server_default is not None
    assert str(purpose.server_default.arg) == GapPurpose.ROLE.value
    assert {p.value for p in GapPurpose} == {"role", "comparison"}


def test_rc6_a_copied_role_row_points_at_its_source() -> None:
    """RC-6: Use this one copies the comparison row into a role row; the copy keeps its source,
    and deleting the source leaves the copy."""
    table = Base.metadata.tables["gap_analyses"]
    source = table.columns["source_gap_id"]
    assert source.nullable
    fk = next(iter(source.foreign_keys))
    assert fk.column.table.name == "gap_analyses"
    assert fk.ondelete == "SET NULL"


def test_rc2_comparison_entry_contract() -> None:
    """RC-2: each entry names the resume and the analysis it is ranked by, and whether it was
    reused. Unknown fields are refused."""
    entry = ResumeComparisonEntry(resume_id=uuid.uuid4(), gap_analysis_id=uuid.uuid4(), reused=True)
    assert ResumeComparisonEntry.model_validate(entry.model_dump(mode="json")) == entry
    with pytest.raises(ValidationError):
        ResumeComparisonEntry.model_validate({**entry.model_dump(mode="json"), "match_score": 80})
    assert EXPORTED_SCHEMAS["resume_comparison_entry"] is ResumeComparisonEntry


def test_rc8_migration_has_a_downgrade() -> None:
    text = MIGRATION.read_text("utf-8")
    assert "down_revision: str | None = '0027'" in text
    assert "op.drop_table('resume_comparisons')" in text
    assert "op.drop_column('gap_analyses', 'purpose')" in text
    assert "op.drop_column('gap_analyses', 'source_gap_id')" in text
