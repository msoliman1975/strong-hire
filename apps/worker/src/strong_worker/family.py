"""Per-family guidance for the planner and the scorer (RF-5, RF-6; role-families spec D-7).

The prose lives in `prompts/planner/family_<value>.v<N>.txt`, never in code. The family itself
comes from the job posting or the brief, never from a model.
"""

from __future__ import annotations

from strong_core.gateway import Role
from strong_core.prompts import load_prompt
from strong_core.role_families import family_prompt_name
from strong_core.schemas import RoleFamily


def family_guidance(family: RoleFamily) -> str:
    return load_prompt(Role.PLANNER, family_prompt_name(family)).render().strip()
