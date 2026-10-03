from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

YearMonth = Annotated[str, Field(pattern=r"^\d{4}(-(0[1-9]|1[0-2]))?$", examples=["2023-04"])]
"""A date as 'YYYY' or 'YYYY-MM'. Resumes rarely give exact days."""

RubricScore = Annotated[int, Field(ge=1, le=4)]
"""1 = no evidence, 2 = weak, 3 = meets the bar for this level, 4 = above the bar."""


class Contract(BaseModel):
    """Base for every shared contract: unknown fields are rejected, so drift fails loudly."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False, str_strip_whitespace=True)
