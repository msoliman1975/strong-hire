from __future__ import annotations

import pytest

from strong_core.config import get_settings


@pytest.fixture(autouse=True)
def _fake_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never call a real model."""
    monkeypatch.setenv("MODEL_PROFILE", "fake")
    get_settings.cache_clear()
