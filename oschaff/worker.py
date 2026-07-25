"""The headless Claude Code noise worker (channel mode).

Per task: copy the source state asset into the fork, ask a headless `claude -p`
to ADD distractors to it, then verify the edit is additive-only. On any
violation, retry once; if it still fails, revert the asset to byte-identical and
mark the task skipped. The verifier — not the prompt — is the guarantee.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from .checks import InvariantError, verify_state_additive, verify_task_py
from .config import ChaffConfig
from .fork import ForkContext, ReportEntry
from .prompts import build_channel_prompt, counts_for


def extract_state_assets(src: str) -> list[str]:
    """Relative asset paths of the task's *state* JSON(s) (heuristic: name has 'state')."""
    jsons = re.findall(r"""asset\(\s*["']([^"']+\.json)["']""", src)
    state = [j for j in jsons if "state" in os.path.basename(j).lower()]
    return state or jsons  # fall back to any json if none named 'state'


def locate_target(state: dict, service: str) -> tuple[int, str]:
    """Return (n_real, placement_description). The worker chooses WHERE to place
    distractors (its strength); the harness only fixes the COUNT (the dial)."""
    if service == "MailHub":
        return len(state["data"]["emails"]), "data.emails (the inbox) — add new email objects to that list"
    msgs = state["data"]["teamchat"]["messages"]
    n_real = sum(len(v) for v in msgs.values() if isinstance(v, list))
    channels = [k for k, v in msgs.items() if isinstance(v, list) and v]
    return n_real, (
        "data.teamchat.messages — a dict of channels/DMs "
        f"({', '.join(channels)}). Add new message objects to the list(s) of the "
        "channel(s) and/or DMs where the REAL task-relevant discussion happens "
        "(e.g. the approvals channel and the manager DM), NOT to unrelated chit-chat channels")


def fetch_source_asset(cfg: ChaffConfig, rel: str) -> str | None:
    """Absolute path to the source asset, downloading from HF if not cached."""
    local = os.path.join(cfg.source_assets, rel)
    if os.path.exists(local):
        return local
    try:
        from huggingface_hub import hf_hub_download
        return hf_hub_download("xlangai/osworld_v2_assets_gated", rel,
                               repo_type="dataset", local_dir=cfg.source_assets)
    except Exception:
        return None


def run_claude(prompt: str, cwd: str, model: str, timeout: int = 600,
               extra_feedback: str = "") -> tuple[int, str]:
    cmd = [
        "claude", "-p", prompt + extra_feedback,
        "--model", model,
        "--add-dir", cwd,
        "--permission-mode", "acceptEdits",
        "--allowedTools", "Read,Edit,Write",
    ]
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "worker timed out"


def perturb_channel(cfg: ChaffConfig, ctx: ForkContext, task_id: str,
                    source_py: str, service: str) -> ReportEntry:
    rels = extract_state_assets(source_py)
    if not rels:
        return ReportEntry(task_id, "channel", f"### task_{task_id} (channel · {service}) — no state asset found; left unchanged", "skipped")
    rel = rels[0]

    src_abs = fetch_source_asset(cfg, rel)
    if not src_abs:
        return ReportEntry(task_id, "channel", f"### task_{task_id} (channel · {service}) — asset {rel} unavailable; left unchanged", "skipped")
    src_abs = os.path.abspath(src_abs)

    # copy source -> fork, worker edits the fork copy
    ctx.add_asset(rel, src_abs)
    fork_abs = os.path.join(ctx.assets_dir, rel)  # absolute (assets_dir is absolute)
    assert os.path.exists(fork_abs), f"fork asset vanished before worker: {fork_abs}"

    state = json.load(open(src_abs))
    n_real, placement = locate_target(state, service)
    counts = counts_for(cfg, n_real)
    instruction = _instruction(source_py)

    prompt = build_channel_prompt(cfg, service, instruction, fork_abs, n_real, counts, placement)

    feedback = ""
    for attempt in range(cfg.max_retries + 1):
        rc, out = run_claude(prompt, ctx.root, cfg.model, extra_feedback=feedback)
        try:
            added = verify_state_additive(json.load(open(src_abs)), json.load(open(fork_abs)))
            summary = _tail(out)
            detail = (f"### task_{task_id}  (channel · {service})  amount={cfg.amount} relevance={cfg.relevance}\n"
                      f"+{added} items ({counts['filler']} filler / {counts['near_miss']} near-miss / {counts['superseded']} superseded)\n"
                      f"{summary}")
            return ReportEntry(task_id, "channel", detail, f"OK ({added} added, {n_real} real unchanged)")
        except (InvariantError, json.JSONDecodeError) as e:
            feedback = f"\n\nYOUR PREVIOUS EDIT WAS REJECTED: {e}. Restore any changed/removed real items and ONLY ADD new ones. Keep JSON valid."
            shutil.copy2(src_abs, fork_abs)  # reset for retry

    return ReportEntry(task_id, "channel", f"### task_{task_id} (channel · {service}) — worker failed invariants after retry; reverted to baseline", "REVERTED")


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


def _tail(out: str, n: int = 900) -> str:
    out = out.strip()
    return out[-n:] if len(out) > n else out
