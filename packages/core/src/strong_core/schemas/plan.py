"""The personal plan (PS-1 to PS-5): one plan per user, computed from the user's data."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field, model_validator

from strong_core.schemas.base import Contract
from strong_core.schemas.enums import PlanItemKind, PlanItemStatus, PlanStyle


class PlanItem(Contract):
    """PS-1: one rehearsal, story or resume item. Done is computed, never ticked by hand."""

    key: str = Field(
        min_length=1, description="Stable id of the item, for example interview:<uuid>."
    )
    kind: PlanItemKind
    title: str = Field(min_length=1, description="Stripe · Behavioral: readiness 75 or more")
    sub: str | None = Field(default=None, description="The sub-line, for example: now 58.")
    status: PlanItemStatus
    due: date | None = Field(default=None, description="PS-4: the day it is planned for (weekly).")
    action_label: str | None = Field(default=None, description="The action button's label.")
    action_target: str | None = Field(
        default=None, description="The app path the action opens, for example /interviews/<id>."
    )
    target_id: UUID | None = Field(
        default=None, description="The interview, story or resume the item is about."
    )


class Plan(Contract):
    """PS-1: the user's personal plan in the chosen style."""

    style: PlanStyle
    week_start: date | None = Field(
        default=None, description="PS-4: the Monday of the week shown. Weekly style only."
    )
    items: list[PlanItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> Plan:
        keys = [i.key for i in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("item keys must not repeat")
        if self.style == PlanStyle.WEEKLY:
            days = [i.due for i in self.items if i.due is not None]
            if len(days) != len(set(days)):
                raise ValueError("PS-4: the weekly plan has at most one item per day")
        return self
