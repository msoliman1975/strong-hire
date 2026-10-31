"""RF-5: in generic mode the live interviewer uses the style of the job's role family."""

from __future__ import annotations

import pytest

from strong_core.gateway import ModelGateway
from strong_core.schemas import Phase, RoleFamily
from strong_interview.controller import Move, MoveKind
from strong_interview.interviewer import Interviewer
from strong_interview.testing import make_brief


@pytest.mark.parametrize(
    ("family", "words"),
    [
        (RoleFamily.FINANCE, "a general interview style for finance roles."),
        (RoleFamily.SWE, "a general interview style for software engineering roles."),
        (RoleFamily.OTHER, "a general interview style for this role."),
    ],
)
def test_rf5_generic_interviewer_style_follows_the_family(
    gateway: ModelGateway, family: RoleFamily, words: str
) -> None:
    """RF-5 / RF-7: no 'tech interview style' for a non-tech job; the family is the brief's."""
    brief = make_brief().model_copy(update={"role_family": family})
    assert brief.company_name is None
    system, _ = Interviewer(gateway, brief).turn_messages(Move(MoveKind.GREET, Phase.INTRO), [])
    assert words in system.content
    assert "tech interview style" not in system.content
