"""Request and response bodies of the interview plan page (PP-1, PP-2, PP-4)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from strong_api.gap.schemas import GapAnalysisOut
from strong_api.inputs.schemas import JobTargetOut, ResumeOut
from strong_api.reports.schemas import ReportItem
from strong_api.scoring.schemas import CustomRecommendation
from strong_core.schemas import (
    Competency,
    Difficulty,
    InterviewType,
    Level,
    Mode,
    PlannedSession,
    Tone,
)

CompanyMode = Literal["curated", "generic"]


class CompetencyWeight(BaseModel):
    competency: Competency
    weight: float = Field(description="The profile's scoring weight. 1.0 when it sets none.")
    share: float = Field(ge=0, le=1, description="The weight's share within its interview type.")


class TypeWeights(BaseModel):
    """One interview type and the competencies it scores, with the company's weights."""

    interview_type: InterviewType
    in_loop: bool = Field(
        description="The company's loop for this role family has a round of this type. Always "
        "false in generic mode."
    )
    competencies: list[CompetencyWeight] = Field(description="Highest weight first.")


class PlanSetupDefaults(BaseModel):
    """PP-4: what the setup on the plan page starts with. Every v1 option stays editable."""

    interview_type: InterviewType = Field(description="PR-2's next session, else GA-3's first.")
    difficulty: Difficulty
    mode: Mode
    duration_min: Literal[30, 45] = Field(
        description="The default full length. Free accounts get the mini interview instead."
    )
    level: Level | None = Field(description="The job's level, else the user's target level.")
    tone: Tone = Field(description="TN-3: as_company with a curated profile, else neutral.")


class PlanView(BaseModel):
    """PP-1: everything the plan page for one job and CV pair shows, in one read."""

    job: JobTargetOut
    resume: ResumeOut
    company_mode: CompanyMode
    company_name: str | None = Field(description="From the profile, else the posting.")
    values_framework: str | None = Field(
        description="The company's values framework name, for example 'Leadership Principles'."
    )
    interview_date: date | None = Field(description="PP-2: the real interview date, if set.")
    days_left: int | None = Field(
        description="PP-2: days from today (UTC) to interview_date. 0 is today, negative is past."
    )
    tested: list[TypeWeights] = Field(
        description="What they'll test: the loop's types first, then the other standard types."
    )
    gap: GapAnalysisOut | None = Field(
        description="The latest gap analysis of this pair (GA-1 to GA-3, probe areas and the "
        "session plan). None when the pair has none yet."
    )
    reports: list[ReportItem] = Field(description="PR-3: this pair's reports, newest first.")
    next_session: PlannedSession | None = Field(description="PR-2.")
    next_custom_session: CustomRecommendation | None = Field(description="CU-10.")
    setup: PlanSetupDefaults


class InterviewDateIn(BaseModel):
    """PP-2: the candidate's real interview date. null clears it."""

    model_config = ConfigDict(extra="forbid")

    interview_date: date | None


class InterviewDateOut(BaseModel):
    interview_date: date | None
    days_left: int | None
