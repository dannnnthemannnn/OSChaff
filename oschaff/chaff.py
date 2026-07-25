"""OSChaff single-task noise injector.

    python -m oschaff.chaff <task_id> --group <task-group-id> \
        [--out-root forks] [--volume N] [--deceptiveness M] [--model M] [--config chaff.yaml] [--check]

Edits ONE task into <out-root>/<group>/ (tasks/ + assets/). Loop it over task ids
with the same --group to build a subset/full fork. Review by `git diff`.
Claude Code auth is ambient — this just shells out to `claude`.
"""

from __future__ import annotations

import argparse
import os
import re

from .config import CHANNEL_APPS, ChaffConfig
from .fork import finalize, open_fork
from .worker import perturb_bolton, perturb_channel

_APP_SERVICE = {"mailhub": "MailHub", "teamchat": "TeamChat"}


def _channel_service(src: str) -> str | None:
    """Return the service to flood if the task already uses one, else None."""
    if "prepare_stateful_website_urls" not in src:
        return None
    apps = set(re.findall(r"""app\s*=\s*["']([a-z_]+)["']""", src)) & CHANNEL_APPS
    if "teamchat" in apps:
        return "TeamChat"
    if "mailhub" in apps:
        return "MailHub"
    return None


def run_one(cfg: ChaffConfig, task_id: str, group: str, check: bool = False) -> None:
    task_id = task_id.zfill(3)
    src_path = os.path.join(cfg.source_tasks, f"task_{task_id}.py")
    if not os.path.exists(src_path):
        raise SystemExit(f"task not found: {src_path}")
    source_py = open(src_path, encoding="utf-8").read()

    ctx = open_fork(cfg, group)
    ctx.add_task_file(task_id, source_py)   # baseline; bolt-on edits it in place

    service = _channel_service(source_py)
    if service:
        print(f"task_{task_id}: channel · {service}  (vol={cfg.volume} dec={cfg.deceptiveness})")
        summary = perturb_channel(cfg, ctx, task_id, source_py, service, check=check)
    else:
        print(f"task_{task_id}: bolt-on · MailHub  (vol={cfg.volume} dec={cfg.deceptiveness})")
        summary = perturb_bolton(cfg, ctx, task_id, source_py)

    fork_id = finalize(ctx)
    print(f"\n--- {group} (fork_id {fork_id}) ---\n{summary}\n\n-> {ctx.root}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="oschaff.chaff")
    ap.add_argument("task_id", help="e.g. 035 or 35")
    ap.add_argument("--group", required=True, help="task-group-id; names/routes the fork dir")
    ap.add_argument("--out-root", help="output root (default from config: forks)")
    ap.add_argument("--volume", type=int, help="0-10")
    ap.add_argument("--deceptiveness", type=int, help="0-10")
    ap.add_argument("--model")
    ap.add_argument("--config", help="chaff.yaml (optional)")
    ap.add_argument("--check", action="store_true", help="print an additive-only sanity warning")
    args = ap.parse_args()

    cfg = ChaffConfig.from_yaml(args.config) if args.config else ChaffConfig()
    for k in ("out_root", "volume", "deceptiveness", "model"):
        v = getattr(args, k)
        if v is not None:
            setattr(cfg, k, v)
    cfg.__post_init__()  # revalidate after overrides
    run_one(cfg, args.task_id, args.group, check=args.check)


if __name__ == "__main__":
    main()
