"""Guards for the gateway rule (PL-1): no model names or model SDKs outside their allowed places."""

from __future__ import annotations

import re
from pathlib import Path

from strong_core.config import find_repo_root

REPO = find_repo_root()
CODE_DIRS = [
    "packages/core/src",
    "apps/api/src",
    "apps/worker/src",
    "apps/voice/src",
    "apps/web/src",
]
GATEWAY = REPO / "packages/core/src/strong_core/gateway"

MODEL_NAME = re.compile(
    r"\b(gpt-[0-9]|claude-|llama[-_.0-9]|qwen[0-9]|mistral|gemma|phi-?[0-9]|whisper-|"
    r"ollama_chat/|groq/|together_ai/|deepinfra/|fireworks_ai/)",
    re.IGNORECASE,
)
MODEL_SDK = re.compile(r"^\s*(from|import)\s+(pydantic_ai|openai|litellm|anthropic|ollama)\b", re.M)


def _code_files() -> list[Path]:
    files: list[Path] = []
    for d in CODE_DIRS:
        files += [p for p in (REPO / d).rglob("*") if p.suffix in {".py", ".ts", ".tsx"}]
    return files


def test_no_model_names_in_code() -> None:
    offenders = [
        f"{p.relative_to(REPO)}: {m.group(0)}"
        for p in _code_files()
        if (m := MODEL_NAME.search(p.read_text(encoding="utf-8")))
    ]
    assert not offenders, "Model names belong in config/ only:\n" + "\n".join(offenders)


def test_only_gateway_imports_model_sdks() -> None:
    offenders = [
        str(p.relative_to(REPO))
        for p in _code_files()
        if p.suffix == ".py"
        and GATEWAY not in p.parents
        and MODEL_SDK.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, "Only strong_core.gateway may import model SDKs:\n" + "\n".join(offenders)
