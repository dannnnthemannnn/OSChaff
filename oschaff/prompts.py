"""Build the per-task instruction for the headless noise worker.

The harness decides *how much* and *what mix* (deterministic, from the dials);
the worker decides *what to write* (plausible, task-aware content). The invariant
rules are stated in-prompt AND enforced afterward by checks.py — the prompt is
guidance, the verifier is the guarantee.
"""

from __future__ import annotations

from .config import ChaffConfig
from .perturb import nastiness_to_mix

_ITEM_WORD = {"MailHub": "email", "TeamChat": "message"}


def counts_for(cfg: ChaffConfig, n_real: int) -> dict[str, int]:
    """Deterministic distractor budget from the two dials."""
    target_total = round(n_real / cfg.amount)
    n_distract = max(0, target_total - n_real)
    mix = nastiness_to_mix(cfg.relevance)
    raw = {k: n_distract * mix[k] for k in mix}
    out = {k: int(v) for k, v in raw.items()}
    rem = n_distract - sum(out.values())
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[:rem]:
        out[k] += 1
    return out


_RULES = """HARD RULES — a violation makes the task invalid and your work will be discarded:
1. NEVER modify or delete any existing item. ONLY ADD new items.
2. Edit ONLY the one state file named below. Never touch any file whose name contains "gt" or "ground_truth", and never change the task's requirements.
3. Your additions must NOT change the task's correct answer. The real items stay authoritative; a distractor must be something a careful worker would correctly reject by trusting the real task instruction and the real items.
4. Make each addition realistic: match the senders, formatting, and style of existing items, and give it a unique id in the SAME format as existing ids.
5. Keep the JSON valid."""

_TYPES = """- {n_filler} FILLER: topically unrelated; cheap to ignore (newsletters, reminders, chit-chat).
- {n_near} NEAR-MISS: look relevant and plausible but are WRONG — share an entity (sender / topic / date) with a real item but differ on the load-bearing detail (a DIFFERENT team, amount, vendor, item, or date). If the agent wrongly acted on one, its deliverable would be wrong.
- {n_super} SUPERSEDED: an EARLIER-timestamped version of a real item's instruction/decision, with a DIFFERENT value. The real (newer) item stays authoritative. Give each a timestamp EARLIER than the real item it shadows."""


def build_channel_prompt(cfg: ChaffConfig, service: str, instruction: str,
                         abs_state_path: str, n_real: int, counts: dict[str, int],
                         placement: str) -> str:
    item_word = _ITEM_WORD[service]
    location = placement
    dynamic = ""
    if cfg.dynamic_delivery and service == "TeamChat":
        dynamic = (
            "\nMID-RUN DELIVERY: additionally, add 1-2 of the near-miss/filler items as timed "
            "messages by appending entries to data.time_data, each shaped "
            "{\"arrive_after_s\": <60-600>, \"conversation_id\": <channel id>, "
            "\"conversation_type\": \"channel\", \"messageId\": <unique>, \"senderId\": <a real user>, "
            "\"content\": <text>} so they arrive while the agent is working.\n")
    return f"""You are hardening a computer-use benchmark task by adding DISTRACTOR content to an app's saved state, to make it harder for an AI agent to pick out the real information — WITHOUT changing what the task requires or its correct answer.

THE TASK the agent-under-test must accomplish (for context — do NOT change it):
\"\"\"{instruction}\"\"\"

THE FILE TO EDIT (a JSON state envelope for {service}):
{abs_state_path}
The {item_word}s live at: {location}. There are currently {n_real} real {item_word}s there.

ADD EXACTLY {sum(counts.values())} new {item_word}s:
{_TYPES.format(n_filler=counts['filler'], n_near=counts['near_miss'], n_super=counts['superseded'])}
{dynamic}
{_RULES}

When finished, print a summary: one line per added item — its type, sender, and a short gist — so a human can eyeball plausibility."""
