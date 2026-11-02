"""Role-play interview type, its competencies and the sales role family (RP-1, RP-2)

Adds role_play to the interview type checks (sessions, target interviews, saved questions), the
four role-play competencies to the progress snapshot check, and sales to the waitlist role family
check. Downgrade deletes the rows that use the new values first, as 0021 did for recruiter_screen,
and maps sales waitlist entries to other.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-02
"""
from collections.abc import Sequence

from alembic import op

revision: str = '0027'
down_revision: str | None = '0026'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = "'behavioral', 'hiring_manager', 'technical_qa', 'case', 'custom', 'recruiter_screen'"
_COMPETENCIES = (
    "'ownership', 'impact', 'collaboration', 'conflict_handling', 'learning_from_failure', "
    "'communication', 'role_fit', 'depth_of_experience', 'judgment', 'motivation', 'team_fit', "
    "'scope_at_level', 'technical_depth', 'accuracy', 'reasoning', 'trade_offs', "
    "'clarity_of_explanation', 'problem_framing', 'structure', 'user_and_business_sense', "
    "'estimation_logic', 'prioritization', 'recommendation', 'logistics_and_expectations'"
)
_NEW_COMPETENCIES = "'discovery', 'objection_handling', 'value_articulation', 'closing'"
_FAMILIES = (
    "'swe', 'data_ml', 'pm', 'design', 'tpm', 'other', 'infra_security', 'data_analytics', "
    "'eng_management', 'finance', 'consulting_strategy', 'project_program'"
)
# (constraint, table, column, old values, new values)
_CHECKS = (
    ('ck_sessions_interview_type', 'sessions', 'type', _TYPES, "'role_play'"),
    ('ck_target_interviews_interview_type', 'target_interviews', 'interview_type', _TYPES, "'role_play'"),
    ('ck_saved_questions_saved_question_category', 'saved_questions', 'category', _TYPES, "'role_play'"),
    ('ck_progress_snapshots_competency', 'progress_snapshots', 'competency', _COMPETENCIES, _NEW_COMPETENCIES),
    ('ck_waitlist_entries_role_family', 'waitlist_entries', 'role_family', _FAMILIES, "'sales'"),
)


def upgrade() -> None:
    for ck, table, column, old, new in _CHECKS:
        op.drop_constraint(op.f(ck), table, type_='check')
        op.create_check_constraint(op.f(ck), table, f"{column} IN ({old}, {new})")


def downgrade() -> None:
    op.execute("UPDATE waitlist_entries SET role_family = 'other' WHERE role_family = 'sales'")
    op.execute(f"DELETE FROM progress_snapshots WHERE competency IN ({_NEW_COMPETENCIES})")
    op.execute("DELETE FROM saved_questions WHERE category = 'role_play'")
    op.execute("DELETE FROM target_interviews WHERE interview_type = 'role_play'")
    op.execute("DELETE FROM sessions WHERE type = 'role_play'")
    for ck, table, column, old, _ in _CHECKS:
        op.drop_constraint(op.f(ck), table, type_='check')
        op.create_check_constraint(op.f(ck), table, f"{column} IN ({old})")
