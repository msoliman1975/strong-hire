"""Which run folders to delete (SM-14). Replaces the host cron script infra/sim/sim-retention.sh.

Rules, in order:
1. Never the newest folder, a folder marked Keep (SM-13), or the folder of a run in progress.
2. Every other folder older than keep_days.
3. Then the oldest others until the whole folder is under keep_gb. Kept folders count toward
   the size but are never deleted, so the total can stay above the limit.

Folder names start with a UTC time (runner.new_run_id), so the name gives the age. A folder
with another name uses its modification time.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

NAME_TIME = "%Y%m%d-%H%M%S"


@dataclass(frozen=True)
class RunFolder:
    name: str
    created: datetime
    size: int  # bytes


def folder_time(path: Path) -> datetime:
    try:
        return datetime.strptime(path.name[:15], NAME_TIME).replace(tzinfo=UTC)
    except ValueError:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def folder_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def scan(base: Path) -> list[RunFolder]:
    if not base.is_dir():
        return []
    return [
        RunFolder(p.name, folder_time(p), folder_size(p))
        for p in base.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    ]


def plan(
    folders: list[RunFolder],
    protected: set[str],
    now: datetime,
    keep_days: int,
    keep_gb: float,
) -> list[tuple[str, str]]:
    """The folders to delete, oldest first, each with the reason."""
    ordered = sorted(folders, key=lambda f: (f.created, f.name))
    if not ordered:
        return []
    protected = protected | {ordered[-1].name}
    out: list[tuple[str, str]] = []
    total = sum(f.size for f in ordered)
    limit = int(keep_gb * 1024**3)
    cutoff = now - timedelta(days=keep_days)
    for f in ordered:
        if f.name in protected:
            continue
        if f.created < cutoff:
            out.append((f.name, f"older than {keep_days} days"))
            total -= f.size
    gone = {name for name, _ in out}
    for f in ordered:
        if total <= limit:
            break
        if f.name in protected or f.name in gone:
            continue
        out.append((f.name, f"the runs folder was over {keep_gb:g} GB"))
        total -= f.size
    return out


def delete_folder(base: Path, name: str) -> None:
    """Delete one run folder. The name must be a plain folder name inside `base`."""
    target = (base / name).resolve()
    if target.parent != base.resolve() or not name or name.startswith("."):
        raise ValueError(f"not a run folder: {name!r}")
    shutil.rmtree(target, ignore_errors=True)
