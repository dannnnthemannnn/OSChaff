"""Fork compiler entrypoint.

    python -m oschaff.compile --config chaff.yaml

M1 scope: classify every task and materialize a baseline fork (all tasks copied,
manifest + fork.json + REPORT.md written). The per-task noise worker (M3+) plugs
in at the marked hook.
"""

from __future__ import annotations

import argparse
import glob
import os

from .classify import Classification, load_and_classify
from .config import ChaffConfig
from .fork import ForkContext, ReportEntry, finalize, new_fork
from .worker import perturb_channel


def compile_fork(cfg: ChaffConfig, dry: bool = False, limit: int | None = None) -> str:
    task_paths = sorted(glob.glob(os.path.join(cfg.source_tasks, "task_*.py")))
    if not task_paths:
        raise SystemExit(f"no task_*.py under {cfg.source_tasks!r}")

    ctx = new_fork(cfg)
    classifications: list[Classification] = []
    perturbed = 0

    for path in task_paths:
        c = load_and_classify(path, cfg)
        classifications.append(c)
        src = open(path, encoding="utf-8").read()
        ctx.add_task_file(c.task_id, src)  # every task ships (edited in place for bolt_on)

        if c.mode == "skip":
            continue
        if dry or (limit is not None and perturbed >= limit):
            ctx.entries.append(ReportEntry(c.task_id, c.mode, f"### task_{c.task_id}  ({c.mode})  — {c.reason}  [not perturbed]"))
            continue

        if c.mode == "channel":
            print(f"  perturbing task_{c.task_id} (channel · {c.services[0]}) ...", flush=True)
            ctx.entries.append(perturb_channel(cfg, ctx, c.task_id, src, c.services[0]))
            perturbed += 1
        elif c.mode == "bolt_on":
            # M5: perturb_bolt_on(); copied unchanged for now.
            ctx.entries.append(ReportEntry(c.task_id, c.mode, f"### task_{c.task_id}  (bolt_on)  — {c.reason}  [bolt-on worker pending]"))

    fork_id = finalize(ctx, classifications)
    _summary(cfg, ctx, classifications, fork_id)
    return ctx.root


def _summary(cfg, ctx, classifications, fork_id) -> None:
    from collections import Counter
    modes = Counter(c.mode for c in classifications)
    print(f"\nOSWorld-Chaff-{ctx.fork_uuid}  (fork_id {fork_id})")
    print(f"  {ctx.root}")
    print(f"  tasks: {dict(modes)}")
    ch = [c.task_id for c in classifications if c.mode == "channel"]
    bo = [c.task_id for c in classifications if c.mode == "bolt_on"]
    print(f"  channel  ({len(ch)}): {' '.join(ch)}")
    print(f"  bolt_on  ({len(bo)}): {' '.join(bo)}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="oschaff.compile")
    ap.add_argument("--config", help="path to chaff.yaml (defaults if omitted)")
    ap.add_argument("--dry", action="store_true", help="classify + materialize only; no worker")
    ap.add_argument("--limit", type=int, help="perturb at most N channel tasks (for testing)")
    args = ap.parse_args()
    cfg = ChaffConfig.from_yaml(args.config) if args.config else ChaffConfig()
    compile_fork(cfg, dry=args.dry, limit=args.limit)


if __name__ == "__main__":
    main()
