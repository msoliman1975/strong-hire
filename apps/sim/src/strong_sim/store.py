"""Run folders and uploads (P13).

    runs/<run-id>/
        report.html, report.json, scenarios.yaml, run.log
        <session-id>/transcript.json, transcript.txt, audio.ogg (voice), judge.json,
                     debrief.json, meta.json

After each session, its folder (and the run's files so far) go to the upload target with rsync
over SSH, so a run that stops early keeps every finished session. The upload user on the main
server can write only to /srv/stronghire/sim (rrsync).
"""

from __future__ import annotations

import json
import logging
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from strong_sim.settings import SimSettings
from strong_sim.transcript import Line, as_text

log = logging.getLogger("strong_sim")


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def save_session(folder: Path, lines: list[Line], files: dict[str, Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / "transcript.json", [line.model_dump() for line in lines])
    (folder / "transcript.txt").write_text(as_text(lines), encoding="utf-8")
    for name, data in files.items():
        write_json(folder / name, data)


class Uploader:
    def __init__(self, settings: SimSettings) -> None:
        self.target = settings.upload_target
        self.key = settings.upload_key

    @property
    def enabled(self) -> bool:
        return bool(self.target)

    def push(self, run_dir: Path) -> bool:
        """Copy the run folder to the target. Returns False (and logs) on failure."""
        if not self.enabled:
            return True
        if not shutil.which("rsync"):
            log.error("rsync is not installed; cannot upload %s", run_dir.name)
            return False
        ssh = "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes"
        if self.key:
            ssh += f" -i {shlex.quote(str(self.key))}"
        base = self.target if self.target.endswith(":") else self.target.rstrip("/") + "/"
        cmd = ["rsync", "-a", "-e", ssh, f"{run_dir}/", f"{base}{run_dir.name}/"]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if done.returncode != 0:
            log.error("upload of %s failed: %s", run_dir.name, done.stderr.strip()[:500])
            return False
        return True
