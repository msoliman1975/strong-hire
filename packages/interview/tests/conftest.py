"""Fixtures: a clock the test moves, and the fake model gateway."""

from __future__ import annotations

import pytest

from strong_core.config import ModelProfile, Settings
from strong_core.gateway import ModelGateway, build_gateway
from strong_interview.testing import FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def gateway() -> ModelGateway:
    return build_gateway(Settings(model_profile=ModelProfile.FAKE))
