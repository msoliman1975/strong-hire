"""LT-30: both production tracing flags are off by default, everywhere they can be set.

The gates in docs/llm-tracing/phase2-gates.md decide when a person turns them on. Nothing in the
code, the compose files or the example env files may turn them on first.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from strong_core.config import Settings, find_repo_root

REPO = find_repo_root()
FLAGS = ("LLM_TRACING_PROD", "LLM_TRACING_PROD_CONTENT")


class _ComposeLoader(yaml.SafeLoader):
    pass


def _tagged(loader: yaml.SafeLoader, node: yaml.Node) -> object:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)  # type: ignore[arg-type]


_ComposeLoader.add_constructor("!reset", _tagged)
_ComposeLoader.add_constructor("!override", _tagged)


def _compose(path: Path) -> dict[str, object]:
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader)
    assert isinstance(data, dict)
    return data


def test_lt30_flags_are_off_in_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """LT-30: with nothing set, the settings say off and sample everything once on."""
    for flag in (*FLAGS, "LLM_TRACING_SAMPLE"):
        monkeypatch.delenv(flag, raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.llm_tracing_prod is False
    assert settings.llm_tracing_prod_content is False
    assert settings.llm_tracing_sample == 1.0


def test_lt30_compose_passes_the_flags_with_off_defaults() -> None:
    """LT-30: every Python service gets the flags from .env, off when .env says nothing; no
    compose file sets them on."""
    env = _compose(REPO / "infra/compose.yaml")["x-python-env"]
    assert isinstance(env, dict)
    for flag in FLAGS:
        assert env[flag] == f"${{{flag}:-off}}"
    for path in (REPO / "infra").rglob("compose*.yaml"):
        text = path.read_text(encoding="utf-8")
        for flag in FLAGS:
            for found in re.findall(rf"{flag}\s*[:=]\s*(\S+)", text):
                assert found in (f'"${{{flag}:-off}}"', f"${{{flag}:-off}}"), (path, found)


@pytest.mark.parametrize("path", [".env.example", "infra/server/env.server.example"])
def test_lt30_example_env_files_leave_the_flags_off(path: str) -> None:
    """LT-30: copying an example env file never turns production tracing on."""
    lines = (REPO / path).read_text(encoding="utf-8").splitlines()
    for flag in FLAGS:
        values = [ln.split("=", 1)[1].strip() for ln in lines if ln.startswith(f"{flag}=")]
        assert values == ["off"], (path, flag, values)


def test_lt30_the_gates_document_names_both_flags() -> None:
    """LT-30: the checklist a person follows before turning each flag on exists."""
    gates = (REPO / "docs/llm-tracing/phase2-gates.md").read_text(encoding="utf-8")
    for flag in FLAGS:
        assert flag in gates


def test_lt30_the_test_map_lists_every_id_and_real_files() -> None:
    """PT06: docs/llm-tracing/phase2-test-map.md names a test for each of LT-16 to LT-31, and
    every file it names exists."""
    text = (REPO / "docs/llm-tracing/phase2-test-map.md").read_text(encoding="utf-8")
    rows = {
        m.group(1): m.group(2) for m in re.finditer(r"^\| (LT-\d+) \|[^|]*\| (.+) \|$", text, re.M)
    }
    assert sorted(rows, key=lambda i: int(i[3:])) == [f"LT-{n}" for n in range(16, 32)]
    for ident, tests in rows.items():
        files = re.findall(r"`((?:apps|packages)/[^`]+\.(?:py|tsx))`", tests)
        assert files, ident
        for name in files:
            assert (REPO / name).is_file(), (ident, name)
