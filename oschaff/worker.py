"""The headless Claude Code noise worker.

Per task: run `claude -p` to add distractors (channel mode) or attach + fill a
new channel (bolt-on mode). No gating/retry — the edit lands in the fork and you
review it by diff. An optional soft `check` prints an additive-only warning but
never blocks or reverts.
"""

from __future__ import annotations

import json
import os
import re
import subprocess

from .config import ChaffConfig
from .fork import ForkContext
from .prompts import (build_bolton_prompt, build_channel_prompt,
                      counts_boltnon, counts_channel)

_EMPTY_MAILHUB = {
    "meta": {"type": "mailhub", "version": 1},
    "data": {"user": {"userId": "user-chaff", "email": "user@example.com"},
             "emails": [], "labels": [], "drafts": []},
    "note": "OSChaff-injected channel",
}


def extract_state_assets(src: str) -> list[str]:
    jsons = re.findall(r"""asset\(\s*["']([^"']+\.json)["']""", src)
    return [j for j in jsons if "state" in os.path.basename(j).lower()] or jsons


def locate_target(state: dict, service: str) -> tuple[int, str]:
    if service == "MailHub":
        return len(state["data"]["emails"]), "data.emails (the inbox) — add new email objects to that list"
    msgs = state["data"]["teamchat"]["messages"]
    n = sum(len(v) for v in msgs.values() if isinstance(v, list))
    chans = [k for k, v in msgs.items() if isinstance(v, list) and v]
    return n, (f"data.teamchat.messages ({', '.join(chans)}). Add message objects to the list(s) "
               "of the channel(s)/DMs where the REAL task discussion happens, not unrelated chit-chat")


def fetch_source_asset(cfg: ChaffConfig, rel: str) -> str | None:
    local = os.path.join(cfg.source_assets, rel)
    if os.path.exists(local):
        return os.path.abspath(local)
    try:
        from huggingface_hub import hf_hub_download
        return hf_hub_download("xlangai/osworld_v2_assets_gated", rel,
                               repo_type="dataset", local_dir=cfg.source_assets)
    except Exception:
        return None


def run_claude(prompt: str, cwd: str, model: str, timeout: int = 600) -> tuple[int, str]:
    cmd = ["claude", "-p", prompt, "--model", model, "--add-dir", cwd,
           "--permission-mode", "acceptEdits", "--allowedTools", "Read,Edit,Write"]
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "(worker timed out — it likely finished editing before wrap-up)"


def _instruction(src: str) -> str:
    import ast
    for node in ast.parse(src).body:
        if isinstance(node, ast.ClassDef):
            for n in node.body:
                if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "instruction" for t in n.targets):
                    try:
                        return ast.literal_eval(n.value)
                    except Exception:
                        return ""
    return ""


def _tail(out: str, n: int = 1200) -> str:
    out = out.strip()
    return out[-n:] if len(out) > n else out


def _soft_check(src_obj, fork_obj) -> str:
    from .checks import InvariantError, verify_state_additive
    try:
        verify_state_additive(src_obj, fork_obj)
        return "check: additive-only OK"
    except InvariantError as e:
        return f"check: WARNING — {e}"


# --------------------------------------------------------------------------- #
def perturb_channel(cfg: ChaffConfig, ctx: ForkContext, task_id: str,
                    source_py: str, service: str, check: bool = False) -> str:
    rels = extract_state_assets(source_py)
    if not rels:
        summary = "no state asset found; left unchanged"
        ctx.record_task(task_id, "channel", summary); return summary
    rel = rels[0]
    src_abs = fetch_source_asset(cfg, rel)
    if not src_abs:
        summary = f"asset {rel} unavailable; left unchanged"
        ctx.record_task(task_id, "channel", summary); return summary

    fork_abs = os.path.join(ctx.assets_dir, rel)
    state = json.load(open(src_abs))
    n_real, placement = locate_target(state, service)
    counts = counts_channel(cfg, n_real)
    prompt = build_channel_prompt(cfg, service, _instruction(source_py), fork_abs, n_real, counts, placement)

    added, out = 0, ""
    for attempt in range(cfg.retries + 1):
        ctx.add_asset(rel, src_abs)   # reset to source each attempt
        _, out = run_claude(prompt, ctx.root, cfg.model)
        try:
            n_after, _ = locate_target(json.load(open(fork_abs)), service)
            added = n_after - n_real
        except Exception:
            added = 0
        if added > 0:
            break

    status = f"OK ({added} added)" if added > 0 else f"FAILED — no-op after {cfg.retries + 1} attempts"
    line = f"+{added}/{sum(counts.values())} items ({counts['filler']}f/{counts['near_miss']}n/{counts['superseded']}s) into {n_real} real [{status}]\n{_tail(out)}"
    if check and added > 0:
        line += "\n" + _soft_check(json.load(open(src_abs)), json.load(open(fork_abs)))
    ctx.record_task(task_id, "channel", line)
    return line


def perturb_bolton(cfg: ChaffConfig, ctx: ForkContext, task_id: str, source_py: str) -> str:
    service = "MailHub"
    rel = f"task_{task_id}/chaff_mail.json"
    state_abs = os.path.join(ctx.assets_dir, rel)
    task_abs = os.path.join(ctx.tasks_dir, f"task_{task_id}.py")

    counts = counts_boltnon(cfg)
    prompt = build_bolton_prompt(cfg, service, _instruction(source_py), state_abs, task_abs, counts)
    prompt = prompt.replace("{RELATIVE_STATE_ASSET}", rel)

    emails, py_changed, out = 0, False, ""
    for attempt in range(cfg.retries + 1):
        ctx.write_asset(rel, json.dumps(_EMPTY_MAILHUB, indent=2))  # reset state
        ctx.add_task_file(task_id, source_py)                       # reset task .py
        _, out = run_claude(prompt, ctx.root, cfg.model)
        try:
            emails = len(json.load(open(state_abs))["data"]["emails"])
        except Exception:
            emails = 0
        py_changed = open(task_abs, encoding="utf-8").read() != source_py
        if emails > 0 and py_changed:
            break

    ok = emails > 0 and py_changed
    status = "OK" if ok else f"FAILED after {cfg.retries + 1} attempts (emails={emails}, provisioned={py_changed})"
    line = f"attached {service} + {emails}/{sum(counts.values())} emails, setup provisioned={py_changed} [{status}]\n{_tail(out)}"
    ctx.record_task(task_id, "bolt_on", line)
    return line
