"""R5 core: CV check issues the user accepted (resumes.accepted_issues)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from strong_core.db.models import Base
from strong_core.schemas import ACCEPTED_ISSUES_MAX, AcceptedIssue, AcceptedIssues

ISSUES: TypeAdapter[list[AcceptedIssue]] = TypeAdapter(AcceptedIssues)


def _issue(**extra: Any) -> dict[str, Any]:
    return {
        "key": "overlap:2019-06:2022-03:northwind:lumen-pay",
        "accepted_at": "2026-10-28T09:00:00Z",
    } | extra


def test_r5_accepted_issue_keeps_the_key_opaque() -> None:
    """R5: any non-empty key up to 200 characters is stored as given."""
    issue = AcceptedIssue.model_validate(_issue())
    assert issue.key == "overlap:2019-06:2022-03:northwind:lumen-pay"
    AcceptedIssue.model_validate(_issue(key="x" * 200))
    for bad in ("", "x" * 201):
        with pytest.raises(ValidationError):
            AcceptedIssue.model_validate(_issue(key=bad))


def test_r5_accepted_issue_rejects_unknown_fields() -> None:
    """R5: the contract rejects unknown fields."""
    with pytest.raises(ValidationError):
        AcceptedIssue.model_validate(_issue(note="fine"))


def test_r5_accepted_issues_has_at_most_100_entries() -> None:
    """R5: a CV keeps at most 100 accepted issues."""
    assert len(ISSUES.validate_python([_issue()] * ACCEPTED_ISSUES_MAX)) == 100
    with pytest.raises(ValidationError):
        ISSUES.validate_python([_issue()] * (ACCEPTED_ISSUES_MAX + 1))


def test_r5_resumes_accepted_issues_column_is_nullable() -> None:
    """R5: existing CVs have no accepted issues (NULL)."""
    column = Base.metadata.tables["resumes"].columns["accepted_issues"]
    assert column.nullable
