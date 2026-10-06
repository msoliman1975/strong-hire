"""Field-by-field diff between two company profiles (AD-1).

The diff ignores `meta` (version, status, reviewer), because those change on every import.
Lists compare by position, so an inserted item shows as changes to the items after it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

IGNORED_KEYS = frozenset({"meta"})
MAX_VALUE_CHARS = 100


class ChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


@dataclass(frozen=True)
class FieldChange:
    path: str
    kind: ChangeKind
    old: Any = None
    new: Any = None

    @property
    def top_field(self) -> str:
        return self.path.split(".", 1)[0].split("[", 1)[0]


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Map each leaf to its dotted path. Empty lists and dicts are leaves."""
    out: dict[str, Any] = {}
    if isinstance(value, dict) and value:
        for key, item in value.items():
            if not prefix and key in IGNORED_KEYS:
                continue
            out.update(flatten(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            out.update(flatten(item, f"{prefix}[{index}]"))
    else:
        out[prefix] = value
    return out


def diff_profiles(old: dict[str, Any] | None, new: dict[str, Any]) -> list[FieldChange]:
    """Changes from `old` to `new`, both as JSON dicts (profile_json). None means no old one."""
    before = flatten(old or {})
    after = flatten(new)
    before.pop("", None)
    changes: list[FieldChange] = []
    for path, value in after.items():
        if path not in before:
            changes.append(FieldChange(path, ChangeKind.ADDED, new=value))
        elif before[path] != value:
            changes.append(FieldChange(path, ChangeKind.CHANGED, old=before[path], new=value))
    changes.extend(
        FieldChange(path, ChangeKind.REMOVED, old=value)
        for path, value in before.items()
        if path not in after
    )
    return changes


def _show(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) > MAX_VALUE_CHARS:
        text = text[: MAX_VALUE_CHARS - 3] + "..."
    return text


def format_change(change: FieldChange) -> str:
    if change.kind is ChangeKind.ADDED:
        return f"+ {change.path}: {_show(change.new)}"
    if change.kind is ChangeKind.REMOVED:
        return f"- {change.path}: {_show(change.old)}"
    return f"~ {change.path}: {_show(change.old)} -> {_show(change.new)}"


def format_diff(changes: list[FieldChange], top_fields: list[str]) -> list[str]:
    """One summary line per top-level field, then the changed paths under it."""
    lines: list[str] = []
    for field in top_fields:
        mine = [c for c in changes if c.top_field == field]
        if not mine:
            lines.append(f"{field}: unchanged")
            continue
        lines.append(f"{field}: {len(mine)} change{'s' if len(mine) != 1 else ''}")
        lines.extend(f"  {format_change(c)}" for c in mine)
    return lines
