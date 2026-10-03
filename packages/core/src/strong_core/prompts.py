"""Prompt loader. Templates live in prompts/<role>/<name>.v<N>.txt and are never inline strings.

    prompt = load_prompt("extractor", "job_posting")          # latest version
    prompt = load_prompt("extractor", "job_posting", version=1)
    msg = prompt.message("system", posting_text=raw)           # Message with prompt_ref set

Templates use $name placeholders (string.Template), which is plain text with no vendor syntax.
The prompt ref, for example "extractor/job_posting.v2", travels with the Message so the gateway
can report which prompt versions produced an output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Literal

from strong_core.config import get_settings
from strong_core.gateway.types import Message, Role

_FILE = re.compile(r"^(?P<name>[a-z0-9_]+)\.v(?P<version>[1-9][0-9]*)\.txt$")


class PromptNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class PromptTemplate:
    role: str
    name: str
    version: int
    text: str

    @property
    def ref(self) -> str:
        return f"{self.role}/{self.name}.v{self.version}"

    def render(self, **values: object) -> str:
        """Fill $placeholders. A missing value raises KeyError, so typos fail loudly."""
        return Template(self.text).substitute({k: str(v) for k, v in values.items()})

    def message(
        self, role: Literal["system", "user", "assistant"] = "system", **values: object
    ) -> Message:
        return Message(role=role, content=self.render(**values), prompt_ref=self.ref)


def list_versions(role: str | Role, name: str, prompts_dir: Path | None = None) -> list[int]:
    folder = (prompts_dir or get_settings().resolved_prompts_dir) / str(role)
    versions = []
    for path in folder.glob(f"{name}.v*.txt"):
        match = _FILE.match(path.name)
        if match and match["name"] == name:
            versions.append(int(match["version"]))
    return sorted(versions)


def load_prompt(
    role: str | Role, name: str, version: int | None = None, *, prompts_dir: Path | None = None
) -> PromptTemplate:
    root = prompts_dir or get_settings().resolved_prompts_dir
    role_name = str(role)
    versions = list_versions(role_name, name, root)
    if not versions:
        raise PromptNotFoundError(f"No prompt {role_name}/{name}.v<N>.txt in {root}")
    chosen = versions[-1] if version is None else version
    if chosen not in versions:
        raise PromptNotFoundError(f"{role_name}/{name}.v{chosen} not found; have {versions}")
    path = root / role_name / f"{name}.v{chosen}.txt"
    return PromptTemplate(role_name, name, chosen, path.read_text(encoding="utf-8"))
