"""RP-11: the AI candidate plays the seller in a role-play, and the role-play suite loads."""

from __future__ import annotations

import pytest

from strong_core.gateway import ModelGateway
from strong_core.gateway.fake import FakeBackend
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import InterviewType, RolePlayScenario
from strong_sim.candidate import Candidate
from strong_sim.cost import CostMeter
from strong_sim.scenarios import Scenario, load_suite


def gateway() -> ModelGateway:
    return ModelGateway(fake_models_config(), fake=FakeBackend())


def test_rp11_role_play_candidate_is_the_seller() -> None:
    """RP-11: a role-play scenario uses candidate/persona_role_play; others keep persona."""
    rp = Scenario(id="rp", interview_type=InterviewType.ROLE_PLAY, role_play="discovery_call")
    seller = Candidate(rp, gateway(), CostMeter({}))
    assert seller.prompt_refs[0] == "candidate/persona_role_play"
    assert "You are the seller" in seller.system.content
    beh = Candidate(Scenario(id="beh"), gateway(), CostMeter({}))
    assert beh.prompt_refs[0] == "candidate/persona"


def test_rp11_role_play_scenario_needs_its_call() -> None:
    """RP-11: a role-play scenario, and only one, names the call."""
    with pytest.raises(ValueError, match="needs role_play"):
        Scenario(id="rp", interview_type=InterviewType.ROLE_PLAY).check()
    with pytest.raises(ValueError, match="needs role_play"):
        Scenario(id="beh", role_play="cold_call").check()


def test_rp11_role_play_suite_covers_every_call() -> None:
    """RP-11: one sim scenario per call type."""
    suite = load_suite("text-role-play")
    assert {s.role_play for s in suite.scenarios} == set(RolePlayScenario)
    for s in suite.scenarios:
        s.check()
        assert s.session_config().role_play == s.role_play
