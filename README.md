# OSChaff — a difficulty dial for OSWorld 2.0

**OSChaff turns up the difficulty of [OSWorld 2.0](https://osworld-v2.xlang.ai/) computer-use
tasks by injecting realistic *information noise* — distractor emails and chat messages the agent
must sift through — without changing what a task requires or its correct answer.** You point it at
a task, pull two dials (how much noise, how deceptive), and it emits a *fork* you run with the
stock OSWorld-V2 runner. Same graders, same tasks, more hay around the needle.

## Why

OSWorld 2.0's own failure analysis found that frontier agents don't fail on GUI control or coding —
they fail on **holding a task model together in a messy environment**: they miss information, can't
tell stale facts from current ones, and act on the wrong source. Those are *information-discrimination*
failures. OSChaff makes that axis a **knob**: keep the task and its validated grader exactly as they
are, and flood the environment with plausible-but-wrong material. A benchmark with a difficulty
parameter doesn't saturate — you turn the dial.

**Core invariant: add material, never alter ground truth.** Real items stay byte-for-byte; graders
are never touched. So every validated checkpoint still means what it meant.

---

## How it works

### Two dials (0–10)

| Dial | What it controls |
|---|---|
| **`--volume`** | how much distractor material (floods even a sparse inbox at high volume) |
| **`--deceptiveness`** | how hard the distractors are to dismiss: `0` = obvious filler → `5` = plausible near-misses → `10` = the disarmable-trap patterns below |

### Distractor types

Distractors are **non-authoritative content that looks decision-relevant but isn't** — a careless
agent is tricked, but a careful one that trusts the real task still gets it right (that fairness
property is deliberate: if following a distractor would be the *reasonable* choice, it's too strong):

- **filler** — topically unrelated; cheap to ignore.
- **near-miss** — shares an entity (sender/topic/date) with a real item but differs on the load-bearing detail (a *different* team, amount, vendor, date).
- **future-dated** — a policy that "takes effect later." *"We now mirror exports L-R — effective in 2 weeks; keep the current process until then."*
- **conditional / wrong-scope** — applies to a *different* team/context. *"For Marketing deliverables use 1024×768."* (task is an Eng deliverable)
- **superseded** — an earlier value a later real item overrode (*"cap is $800"* before the real *"$1,000"*).
- **rejected** — a proposal shot down in-thread. *"Drop the cap to $500?"* → *"No, keep $1,000."*
- **merely-floated** — an idea raised but never confirmed. *"Maybe switch vendors?"* → *(no reply)*.

### Two modes (auto-detected)

- **Channel** — the task *already* uses MailHub (email) or TeamChat (Slack): OSChaff **floods the existing state** so distractors compete with the real load-bearing items. Strongest signal.
- **Bolt-on** — the task has no such channel: OSChaff **attaches a MailHub inbox** (writes a new state, adds the launch/provision lines to the task's `setup()`, and appends a hint to the instruction — *"you may have relevant messages in MailHub"*), then floods that. Lets any task carry the noise axis.

A headless **Claude Code** worker (`claude -p`) authors the actual content — it reads the task and
writes distractors targeting its real decision points. The harness fixes the *counts* (from the
dials); the model decides *what* to write and *where*.

---

## Install & prerequisites

```bash
pip install huggingface_hub pyyaml          # the tool's only deps beyond the stdlib
```
- **Claude Code CLI** installed and logged in — the worker shells out to `claude` (auth is ambient).
- **OSWorld 2.0 gated access** (the task classes and assets are gated to prevent benchmark leakage):
  request access to [`xlangai/osworld_v2_tasks`](https://huggingface.co/datasets/xlangai/osworld_v2_tasks)
  and [`xlangai/osworld_v2_assets_gated`](https://huggingface.co/datasets/xlangai/osworld_v2_assets_gated),
  then `hf auth login`.
- Put the task classes under **`cache/osworld_tasks/`** (`task_001.py … task_108.py`). Assets are
  fetched from HF on demand (or pre-download them under `cache/osworld_assets/`).

---

## Usage

### Perturb one task

```bash
python -m oschaff.chaff 035 --group harder-v1 --volume 6 --deceptiveness 8
```
- `<task_id>` — e.g. `035` (or `35`).
- `--group` — names the fork; output is routed to `forks/<group>/`. Reuse the same group to
  **accumulate** tasks into one fork.
- Mode is auto-detected; review the change with `git diff forks/harder-v1`.

### Generate a full benchmark fork

Loop the command over whatever subset (or all 108) you want, into one group:

```bash
for id in $(seq -w 1 108); do
  python -m oschaff.chaff $id --group harder-v1 --volume 6 --deceptiveness 7
done
```
Each run auto-picks channel vs. bolt-on. Some tasks **skip cleanly** (e.g. channel tasks that build
their state dynamically); the report notes them.

### What a fork contains

```
forks/harder-v1/
  tasks/task_*.py     edited task classes (only channel/bolt-on tasks differ)
  assets/             perturbed + injected state JSONs (same relative paths as upstream)
  fork.json           config + fork id
  MANIFEST.lock       sha256 of every file (integrity)
  REPORT.md           human-readable audit: per task, the injected messages (eyeball this)
```

---

## Running the fork (baseline vs. fork)

OSChaff only *produces* the fork; **the stock OSWorld-V2 runner executes it.** Two integration
points, no changes to their code: drop the fork's `task_*.py` into `evaluation_examples/task_class/`,
and set `OSWORLD_FILE_BASE_URL` to the fork's `assets/`.

`scripts/run_chaff_eval.sh` does that for you and prints the per-task **baseline vs. fork** score delta:

```bash
export ANTHROPIC_API_KEY=sk-...
scripts/run_chaff_eval.sh \
  --osworld /path/to/OSWorld-V2 \
  --fork    /path/to/OSChaff/forks/harder-v1 \
  --tasks   "007 016 002" \
  --steps   150            # defaults: --model claude-sonnet-4-6
```
```
task     baseline   fork     delta
007      0.90       0.40     -0.50    ← chaff made it harder
```

**Environment setup (their side):** an [OSWorld-V2](https://github.com/xlang-ai/OSWorld-V2) checkout
with a VM provider. Simplest is the **Docker provider on one x86 Linux EC2 box** (ssh in, `pip install -e .`,
download tasks/assets). The mock web services are live at the default `WEBSITE_HOST_SUFFIX=web.hku.icu`,
so there's **no web infra to stand up**. The runner defaults to `claude-sonnet-4-6`. See their
`docs/PROVIDER_SETUP.md`.

---

## OSChaff vs. OSWorld-V2

| | Source | Role |
|---|---|---|
| `oschaff/`, `scripts/run_chaff_eval.sh` | **this repo** | *compiler* — produces a harder fork + glue to run it |
| `desktop_env/`, `mm_agents/`, `run_multienv_claude.py`, tasks, assets, graders | **OSWorld-V2 + gated HF** | *runtime* — spins the VM, runs the agent, scores |

OSChaff is a **compiler** that emits a harder benchmark; OSWorld-V2 is the **runtime** that executes it.

---

## Limitations (read these)

- **Perceptual tasks are hard to bite.** For tasks whose difficulty is drawing/video/CAD editing,
  distractor emails mostly just waste steps — unless a *disarmable-trap directive* targets a real
  parameter (an orientation, dimension, format), which can flip the deliverable. The tool never
  *skips* them (it'll bolt-on to anything); whether it bit is decided by the score delta, not by us.
- **Some channel tasks skip.** A few build their MailHub/TeamChat state in Python rather than a JSON
  asset; those are reported as skipped.
- **Fairness isn't machine-checked.** The "must be disarmable" rule is enforced by the worker prompt
  and by *you* eyeballing `REPORT.md` — that's what the report is for.
- **Don't publicly redistribute forks.** A fork embeds the tasks' graders/answers. Publishing it
  leaks the benchmark (and re-hosting the gated assets is a licensing gray area). Share the *tool +
  config*; let others reproduce forks against their own gated access.

---

## Layout

```
oschaff/
  chaff.py      CLI entrypoint (single task -> fork)
  config.py     ChaffConfig (the 0-10 dials)
  prompts.py    worker prompts + distractor pattern library
  worker.py     the headless `claude -p` channel/bolt-on workers
  fork.py       the group-keyed, accumulating fork directory
  checks.py     optional additive-only sanity check (`--check`)
scripts/run_chaff_eval.sh   baseline-vs-fork eval wrapper
chaff.yaml                  example config
```
