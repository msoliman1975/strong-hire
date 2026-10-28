"""PL-1 for the eval harness: no model SDK imports and no model names in evals code."""

from __future__ import annotations

import re

import yaml

from strong_core.config import find_repo_root

REPO = find_repo_root()
MODEL_NAME = re.compile(
    r"\b(gpt-[0-9]|claude-|llama[-_.0-9]|qwen[0-9]|mistral|gemma|phi-?[0-9]|whisper-|"
    r"ollama_chat/|groq/|together_ai/|deepinfra/|fireworks_ai/)",
    re.IGNORECASE,
)
MODEL_SDK = re.compile(r"^\s*(from|import)\s+(pydantic_ai|openai|litellm|anthropic|ollama)\b", re.M)


def _aliases() -> set[str]:
    out: set[str] = set()
    for path in (REPO / "config").glob("models.*.yaml"):
        out |= set(yaml.safe_load(path.read_text(encoding="utf-8")).get("models") or {})
    return out


def test_evals_code_has_no_model_names_or_sdks() -> None:
    evals = REPO / "evals"
    files = [
        *(evals / "src").rglob("*.py"),
        *(evals / "config").glob("*.yaml"),
        *(evals / "suites").glob("*.yaml"),
        *(REPO / "prompts" / "evals").glob("*.txt"),
        REPO / "scripts" / "eval.ps1",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        for alias in _aliases():  # gateway aliases such as claude-fast are not model names
            text = re.sub(rf"\b{re.escape(alias)}\b", "", text)
        assert not MODEL_NAME.search(text), path
        if path.suffix == ".py":
            assert not MODEL_SDK.search(text), path
