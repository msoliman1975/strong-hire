"""SV-14: the coach prompts that speak to the candidate carry Strova's voice (ux-spec section 4.6).

Candid, in the candidate's corner, and praise only when it is earned. In a coaching session she
never praises at all: the session prompts keep their no-praise rule, which the coach eval judges.
"""

import pytest

from strong_core.gateway import Role
from strong_core.prompts import load_prompt

SESSION = ["turn", "craft_turn"]
PROSE = ["review", "ask", "suggest_tailor"]


@pytest.mark.parametrize("name", SESSION + PROSE)
def test_sv14_strova_speaks_in_her_voice(name: str) -> None:
    """SV-14: every prompt Strova speaks to the candidate through names her and her voice."""
    text = load_prompt(Role.COACH, name).render(style="", skills="")
    assert text.startswith("You are Strova, ")
    assert "Your voice, as Strova:" in text
    assert "- Candid:" in text
    assert "- In the candidate's corner:" in text


@pytest.mark.parametrize("name", PROSE)
def test_sv14_praise_only_when_earned(name: str) -> None:
    """SV-14: outside a session, praise names what earned it; empty praise and "!" are out."""
    text = load_prompt(Role.COACH, name).render()
    assert "- Earned praise only:" in text
    assert "no exclamation marks" in text


@pytest.mark.parametrize("name", SESSION)
def test_sv14_no_praise_in_a_session(name: str) -> None:
    """SV-14: in a coaching session the voice adds no praise; the no-praise rule stays."""
    text = load_prompt(Role.COACH, name).render(style="", skills="")
    assert "Earned praise" not in text
    assert "Never grade, praise or judge the story" in text
