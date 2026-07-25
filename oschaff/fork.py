"""Fork output — a per-group directory that accumulates across single-task runs.

`<out_root>/<group>/` holds edited `tasks/task_<id>.py` + injected `assets/`, plus
a rebuilt `fork.json`, `MANIFEST.lock` (sha256s), and human-readable `REPORT.md`.
Running more task IDs with the same group adds to the same dir; nothing is wiped.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass

from .config import ChaffConfig

_META = {"fork.json", "MANIFEST.lock", "REPORT.md", "chaff.json"}


@dataclass
class ForkContext:
    root: str
    tasks_dir: str
    assets_dir: str
    group: str
    cfg: ChaffConfig

    def add_task_file(self, task_id: str, text: str) -> None:
        with open(os.path.join(self.tasks_dir, f"task_{task_id}.py"), "w", encoding="utf-8") as f:
            f.write(text)

    def add_asset(self, rel_path: str, src_abs: str) -> None:
        dst = os.path.join(self.assets_dir, rel_path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src_abs, dst)

    def write_asset(self, rel_path: str, text: str) -> str:
        dst = os.path.join(self.assets_dir, rel_path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(text)
        return dst

    # -- accumulating record of what each task got ------------------------- #
    def _chaff_path(self) -> str:
        return os.path.join(self.root, "chaff.json")

    def record_task(self, task_id: str, mode: str, summary: str) -> None:
        data = self._load_record()
        data["tasks"][task_id] = {
            "mode": mode, "volume": self.cfg.volume,
            "deceptiveness": self.cfg.deceptiveness, "summary": summary,
        }
        with open(self._chaff_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _load_record(self) -> dict:
        if os.path.exists(self._chaff_path()):
            return json.load(open(self._chaff_path()))
        return {"group": self.group, "model": self.cfg.model, "tasks": {}}


def open_fork(cfg: ChaffConfig, group: str) -> ForkContext:
    """Open (create if needed) the group's fork dir. Never wipes existing content."""
    root = os.path.abspath(os.path.join(cfg.out_root, group))
    tasks_dir = os.path.join(root, "tasks")
    assets_dir = os.path.join(root, "assets")
    os.makedirs(tasks_dir, exist_ok=True)
    os.makedirs(assets_dir, exist_ok=True)
    return ForkContext(root, tasks_dir, assets_dir, group, cfg)


def finalize(ctx: ForkContext) -> str:
    """Rebuild MANIFEST.lock, fork.json, REPORT.md from current dir contents."""
    manifest = {}
    for dp, _, files in os.walk(ctx.root):
        for fn in files:
            rel = os.path.relpath(os.path.join(dp, fn), ctx.root).replace(os.sep, "/")
            if rel in _META:
                continue
            h = hashlib.sha256()
            with open(os.path.join(dp, fn), "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            manifest[rel] = h.hexdigest()
    manifest = dict(sorted(manifest.items()))
    text = "".join(f"{h}  {rel}\n" for rel, h in manifest.items())
    with open(os.path.join(ctx.root, "MANIFEST.lock"), "w") as f:
        f.write(text)
    fork_id = hashlib.sha256(text.encode()).hexdigest()[:12]

    rec = ctx._load_record()
    with open(os.path.join(ctx.root, "fork.json"), "w") as f:
        json.dump({"group": ctx.group, "fork_id": fork_id, "model": ctx.cfg.model,
                   "source_release": "osworld-v2-2026.06.24", "tasks": rec["tasks"],
                   "file_count": len(manifest)}, f, indent=2)
    _write_report(ctx, rec)
    return fork_id


def _write_report(ctx: ForkContext, rec: dict) -> None:
    lines = [f"# {ctx.group} — OSChaff injection report", "",
             f"model: `{ctx.cfg.model}` · tasks perturbed: {len(rec['tasks'])}", "", "## Per-task", ""]
    for tid in sorted(rec["tasks"]):
        t = rec["tasks"][tid]
        lines.append(f"### task_{tid}  ({t['mode']})  vol={t['volume']} dec={t['deceptiveness']}")
        lines.append(t["summary"].rstrip())
        lines.append("")
    with open(os.path.join(ctx.root, "REPORT.md"), "w") as f:
        f.write("\n".join(lines))
