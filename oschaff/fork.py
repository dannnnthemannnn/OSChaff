"""Fork materialization: the frozen, hashed OSWorld-Chaff-<uuid> bundle.

The fork is an OVERLAY on a stock OSWorld-V2 checkout: it ships the (possibly
edited) task_*.py for every task plus only the assets that changed or were
injected. To run it, point the stock runner's task dir at ``tasks/`` and layer
``assets/`` over the original asset base.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field

from .config import ChaffConfig


@dataclass
class ReportEntry:
    task_id: str
    mode: str
    detail: str = ""          # human-readable block for REPORT.md
    invariants: str = "n/a"


@dataclass
class ForkContext:
    root: str
    tasks_dir: str
    assets_dir: str
    fork_uuid: str
    cfg: ChaffConfig
    entries: list[ReportEntry] = field(default_factory=list)

    def add_task_file(self, task_id: str, text: str) -> None:
        with open(os.path.join(self.tasks_dir, f"task_{task_id}.py"), "w", encoding="utf-8") as f:
            f.write(text)

    def add_asset(self, rel_path: str, src_abs: str) -> None:
        dst = os.path.join(self.assets_dir, rel_path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src_abs, dst)

    def write_asset(self, rel_path: str, text: str) -> None:
        dst = os.path.join(self.assets_dir, rel_path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(text)


def new_fork(cfg: ChaffConfig) -> ForkContext:
    fork_uuid = str(uuid.uuid4())[:8]
    root = os.path.join(cfg.output_root, f"OSWorld-Chaff-{fork_uuid}")
    tasks_dir = os.path.join(root, "tasks")
    assets_dir = os.path.join(root, "assets")
    os.makedirs(tasks_dir, exist_ok=True)
    os.makedirs(assets_dir, exist_ok=True)
    return ForkContext(root, tasks_dir, assets_dir, fork_uuid, cfg)


def _hash_tree(root: str) -> dict[str, str]:
    """sha256 of every file under root, keyed by relative posix path."""
    out: dict[str, str] = {}
    for dirpath, _, files in os.walk(root):
        for fn in files:
            ap = os.path.join(dirpath, fn)
            rel = os.path.relpath(ap, root).replace(os.sep, "/")
            if rel in ("MANIFEST.lock", "fork.json", "REPORT.md"):
                continue
            h = hashlib.sha256()
            with open(ap, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            out[rel] = h.hexdigest()
    return dict(sorted(out.items()))


def finalize(ctx: ForkContext, classifications: list) -> str:
    """Write MANIFEST.lock, fork.json, REPORT.md. Return the content fork_id."""
    manifest = _hash_tree(ctx.root)
    manifest_text = "\n".join(f"{h}  {rel}" for rel, h in manifest.items()) + "\n"
    with open(os.path.join(ctx.root, "MANIFEST.lock"), "w", encoding="utf-8") as f:
        f.write(manifest_text)
    fork_id = hashlib.sha256(manifest_text.encode()).hexdigest()[:12]

    mode_counts: dict[str, int] = {}
    for c in classifications:
        mode_counts[c.mode] = mode_counts.get(c.mode, 0) + 1

    meta = {
        "name": f"OSWorld-Chaff-{ctx.fork_uuid}",
        "fork_id": fork_id,
        "source_release": "osworld-v2-2026.06.24",
        "config": ctx.cfg.canonical(),
        "mode_counts": mode_counts,
        "file_count": len(manifest),
    }
    with open(os.path.join(ctx.root, "fork.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    _write_report(ctx, mode_counts, classifications)
    return fork_id


def _write_report(ctx: ForkContext, mode_counts: dict, classifications: list) -> None:
    cfg = ctx.cfg
    lines = [
        f"# OSWorld-Chaff-{ctx.fork_uuid} — injection report",
        "",
        f"- model: `{cfg.model}`  · amount: `{cfg.amount}`  · relevance: `{cfg.relevance}`",
        f"- services: {cfg.services}  · bolt_on: {cfg.bolt_on}  · dynamic_delivery: {cfg.dynamic_delivery}  · seed: {cfg.seed}",
        f"- tasks: " + "  ".join(f"{m}={n}" for m, n in sorted(mode_counts.items())),
        "",
        "## Per-task",
        "",
    ]
    by_id = {e.task_id: e for e in ctx.entries}
    for c in sorted(classifications, key=lambda c: c.task_id):
        e = by_id.get(c.task_id)
        if e and e.detail:
            lines.append(e.detail.rstrip())
            lines.append(f"  invariants: {e.invariants}")
        else:
            lines.append(f"### task_{c.task_id}  ({c.mode})  — {c.reason}")
        lines.append("")
    with open(os.path.join(ctx.root, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
