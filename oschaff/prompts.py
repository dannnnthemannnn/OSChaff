"""Prompts for the headless noise worker.

The harness fixes *how much* and *what mix* (from the 0-10 dials); the worker
writes plausible, task-aware content and (for bolt-on) provisions the channel.
The pattern library below is what makes distractors potent-yet-fair.
"""

from __future__ import annotations

from .config import ChaffConfig

_ITEM_WORD = {"MailHub": "email", "TeamChat": "message"}


def nastiness_to_mix(deceptiveness: float) -> dict[str, float]:
    """Map deceptiveness (0-1) to a filler/near_miss/superseded split.

    0.0 -> all filler; 0.5 -> mostly near-miss; 1.0 -> superseded-heavy.
    """
    anchors = {
        0.0: {"filler": 1.0, "near_miss": 0.0, "superseded": 0.0},
        0.5: {"filler": 0.3, "near_miss": 0.7, "superseded": 0.0},
        1.0: {"filler": 0.2, "near_miss": 0.3, "superseded": 0.5},
    }
    lo, hi = (0.0, 0.5) if deceptiveness <= 0.5 else (0.5, 1.0)
    t = 0.0 if hi == lo else (deceptiveness - lo) / (hi - lo)
    return {k: anchors[lo][k] + t * (anchors[hi][k] - anchors[lo][k])
            for k in ("filler", "near_miss", "superseded")}

# The gold-standard trap patterns: non-authoritative content that looks
# decision-relevant but isn't, so a careless agent is tricked but a careful one
# that trusts the real task/spec still gets it right.
PATTERNS = """DISTRACTOR PATTERNS — each looks decision-relevant but a careful reader can rule it out:
- FUTURE-DATED: a policy/decision that "takes effect" later. e.g. "New rule: mirror all exports L-R — effective in 2 weeks; until then keep the current process." (correct read: no change now)
- CONDITIONAL / WRONG-SCOPE: applies to a DIFFERENT team/item/context. e.g. "For Marketing deliverables use 1024x768." (the task is an Engineering deliverable -> N/A)
- SUPERSEDED: an EARLIER-timestamped value that a later real item overrides. e.g. an old "cap is $800" before the real "$1,000".
- REJECTED: a proposal that is shot down in the same thread. e.g. "Can we drop the cap to $500?" -> "No, keep it at $1,000."
- MERELY-FLOATED: an idea raised but never confirmed. e.g. "Maybe switch vendors to Eastgate?" -> (no reply / "let me think about it")
- NEAR-MISS: shares an entity (sender/topic/date) with the real target but differs on the load-bearing detail (different team, amount, vendor, item).
Where relevant, reference the task's ACTUAL requirement so the trap is tempting.
"""

_RULE = ("HARD RULE: a careful worker who trusts the real task and the authoritative items must "
         "still get the task RIGHT. If following your distractor would be the *reasonable* choice, "
         "it is too strong — soften it (make it clearly future/conditional/rejected/unconfirmed).")


def _split(total: int, mix: dict[str, float]) -> dict[str, int]:
    raw = {k: total * mix[k] for k in mix}
    out = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[: total - sum(out.values())]:
        out[k] += 1
    return out


def volume_floor(volume: int) -> int:
    """Minimum distractors, scaled by the dial (so high volume floods even a
    sparse inbox). 0 at volume 0, else at least 3."""
    return 0 if volume <= 0 else max(3, round(volume * 1.5))


def counts_channel(cfg: ChaffConfig, n_real: int) -> dict[str, int]:
    # ratio to existing content, but never below the volume-scaled floor
    total = max(volume_floor(cfg.volume), round(n_real * cfg.volume / 2))
    return _split(total, nastiness_to_mix(cfg.deceptiveness / 10))


def counts_boltnon(cfg: ChaffConfig) -> dict[str, int]:
    total = volume_floor(cfg.volume)            # no real items to scale off; use the dial
    return _split(total, nastiness_to_mix(cfg.deceptiveness / 10))


def _mix_line(counts: dict[str, int]) -> str:
    return (f"{counts['filler']} filler (topically unrelated, easy to ignore), "
            f"{counts['near_miss']} near-miss, {counts['superseded']} superseded/disarmable-trap")


def build_channel_prompt(cfg: ChaffConfig, service: str, instruction: str,
                         abs_state_path: str, n_real: int, counts: dict[str, int],
                         placement: str) -> str:
    word = _ITEM_WORD[service]
    total = sum(counts.values())
    dynamic = ""
    if service == "TeamChat":
        dynamic = ("\nMID-RUN: add 1-2 items as timed messages by appending to data.time_data "
                   "(each: {\"arrive_after_s\": 60-600, \"conversation_id\": <channel>, "
                   "\"conversation_type\": \"channel\", \"messageId\": <unique>, \"senderId\": <a real user>, "
                   "\"content\": <text>}), so they arrive while the agent works.\n")
    return f"""You are HARDENING a computer-use benchmark task by adding DISTRACTOR {word}s to an app's saved state — to make it harder for an AI agent to pick out the real information, WITHOUT changing what the task requires or its correct answer.

THE TASK the agent-under-test must do (context; do NOT change it):
\"\"\"{instruction}\"\"\"

FILE TO EDIT (a JSON state envelope for {service}): {abs_state_path}
The {word}s live at: {placement}. There are {n_real} REAL {word}s there now.

ADD EXACTLY {total} new {word}s: {_mix_line(counts)}.
{PATTERNS}{dynamic}
RULES:
1. NEVER modify or delete an existing item — ONLY ADD. Give each a unique id in the same format as existing ids, and match the senders/style/format of the real items.
2. Edit only this file. Never touch files with "gt" or "ground_truth" in the name. Keep the JSON valid.
3. {_RULE}

When done, print one line per added item: type, sender, and a short gist (for a human eyeball)."""


def build_bolton_prompt(cfg: ChaffConfig, service: str, instruction: str,
                        abs_state_path: str, abs_task_path: str, counts: dict[str, int]) -> str:
    word = _ITEM_WORD[service]
    total = sum(counts.values())
    return f"""You are HARDENING a computer-use benchmark task by ATTACHING a {service} channel to it and filling it with DISTRACTOR {word}s — plausible-but-wrong information that tempts an agent into a mistake, WITHOUT changing what the task requires or its correct answer.

THE TASK the agent-under-test must do (context; do NOT change its requirements):
\"\"\"{instruction}\"\"\"

Do THREE things:

A) POPULATE the new {service} state file: {abs_state_path}
   It's a valid-but-nearly-empty {service} envelope. Add {total} {word}s to data.emails:
   {_mix_line(counts)}.
   Since this channel is brand-new there are no real items here, so lean on the SELF-CONTAINED
   patterns (future-dated / conditional / wrong-scope / rejected / merely-floated) and make them
   reference the task's ACTUAL requirement, so they tempt an error while a careful reader rules
   them out. Use realistic senders and a plausible mix; keep JSON valid.
{PATTERNS}
B) PROVISION the channel in the task file: {abs_task_path}
   Inside setup(), ADD these lines (do not remove anything; if Chrome isn't already launched, add the two launch lines):
     setup_controller.launch(["google-chrome", "--remote-debugging-port=1337"])
     setup_controller.launch(["socat", "tcp-listen:9222,fork", "tcp:localhost:1337"])
     urls_to_open = prepare_stateful_website_urls(app="{service.lower()}", state=asset("{{RELATIVE_STATE_ASSET}}"))
     setup_controller._chrome_open_tabs_setup(urls_to_open)
   Ensure the needed imports exist (prepare_stateful_website_urls from desktop_env.controllers.website; asset from desktop_env.file_source).

C) APPEND to the `instruction` string (do NOT alter the existing text — only append):
   " You may also have relevant messages in {service} — check there if you need more information."

RULES:
- NEVER change the task's requirements or its evaluate()/grader. Only ADD.
- {_RULE}

When done, print one line per added {word}: type, sender, gist."""
