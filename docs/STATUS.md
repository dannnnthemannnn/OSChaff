# OSChaff — project status & handoff

Working notes so a fresh session (or a new contributor) can pick up without
re-deriving everything. Update this as decisions change.

## What OSChaff is

A signal-to-noise **perturbation harness** for OSWorld 2.0. It injects controlled
distractor material into a task's **initial web-service state** without altering
ground truth, producing a paired difficulty curve on tasks whose graders are
already validated. We do **not** author tasks or write graders.

Goal behind the project: a computer-use difficulty **dial** — something that can
push a frontier model (e.g. Opus 5, reported 70.6% on OSWorld 2.0) down, on an
axis the benchmark authors already showed agents fail on.

## Decisions locked so far

- **Two orthogonal dials** (not the writeup's giant YAML):
  - `signal_fraction` (0,1] — VOLUME: fraction of items that are real/load-bearing.
  - `nastiness` [0,1] — CLOSENESS: distractor type mix filler → near_miss → superseded.
  - User explicitly wants BOTH dials; fine to also re-derive "longer = harder" as
    a controlled curve.
- **Invariants live in code, not config** ("add material, never alter ground truth").
- **Deterministic Python library first**; an "agentic skill" is a later wrapper.
- **Distractor generation**: templated (offline, deterministic) now; LLM generator
  pluggable (understands the seed item; writes natural near_miss/superseded).

## The three noise types

- `filler` — topically unrelated. Resolved by TOPIC. The floor condition.
- `near_miss` — plausible but wrong; shares an entity with a real item but differs
  on a load-bearing field. Resolved by SCOPE/IDENTITY ("whose order is this?").
  Defeats topic-filtering; this is the meaty middle.
- `superseded` — an earlier-timestamped version of a real claim with a different
  value; the newer real item stays authoritative. Resolved by RECENCY. Static form
  of the Task 035 trap, so needs zero understanding of the dynamic-update hook.

## Architecture hook (confirmed from paper Appendix C.2)

The mock sites are **local Docker containers** launched during the run, NOT a remote
service (`web.hku.icu` is just XLANG's own deployment; routing is `appname.localhost`).
Per-run flow:
1. Task setup **launches** the site containers and **writes initial JSON state** to
   each via `/api/state`, scoped by a `user_id` browser cookie (one container serves
   many state instances → one deployment, N cookies, run in parallel).
2. Agent interacts via the browser at `appname.localhost`.
3. Evaluator reads final state back and scores against task checkpoints.

**OSChaff's hook = step 1.** Intercept the initial-state JSON, perturb it, hand it to
normal setup. Everything downstream is a standard OSWorld run. The invariant is what
keeps the untouched graders valid.

## What's done (this branch)

- `oschaff/` engine: `schemas.py`, `generate.py`, `perturb.py`, `verify.py`.
- MailHub schema baked in from paper Figure 13 (the one fully-published schema).
- `examples/demo.py` (dial sweep) + `tests/test_invariants.py` (11 passing).
- `oschaff.yaml` — the tiny config.

Run: `python examples/demo.py` and `python -m pytest tests/`. No deps, no network.

## Open questions / next steps (in order)

1. **Get gated HF access working** (see Access below), then inspect real task classes:
   - Confirm HOW each task delivers initial web state (JSON asset file vs `/api/state`
     push vs inline in the Python class). Decides the exact injector hook.
   - Confirm WHERE the site containers are distributed (likely the gated assets, maybe
     an `xlang-ai/osworld_image` image). This is the one real unknown for running tasks.
2. **Capture remaining state schemas** (TeamChat.messages, VaultBank.transactions,
   CloudCRM.records) from each service's `/state-manage` page; add to `schemas.py`.
3. **Sharpen generators** so near_miss/superseded mutate the actual load-bearing VALUE
   ("$8,000 cap" → "$6,000 cap", "vendor Northwind" → "vendor Eastgate"), not a tag.
   Fully offline/testable against the MailHub sample. (Unblocked now.)
4. **Wire into the OSWorld-V2 runner** as a state-setup shim.
5. **phenomenon_score**: tag which checkpoints require resolving the conflict; report
   alongside binary/partial. It's the metric designed to separate.
6. **Paired noise curve** on ~10 short, conflict-tagged tasks; report steps alongside
   score so degradation can be separated from horizon.
7. **Correction-budget telemetry**: does self-repair spending rise under noise?

## Access / environment (IMPORTANT for a new session)

To download the gated datasets you need BOTH, and both only apply to a NEW session:
- **Network policy** must allow: `huggingface.co`, `*.hf.co`, `*.xethub.hf.co`.
  (This environment's default policy REJECTS huggingface.co — confirmed via proxy.)
- **`HF_TOKEN`** env var set to a HF read token (added via "edit environment").

Gated datasets (accept the "Agree and access" gate on each while logged in):
- Tasks:  https://huggingface.co/datasets/xlangai/osworld_v2_tasks  (Python task_*.py)
- Assets: https://huggingface.co/datasets/xlangai/osworld_v2_assets_gated

Download (from the OSWorld-V2 checkout, once access + token + network are in place):
    uv run scripts/tools/download_osworld_v2_tasks.py  --benchmark-release osworld-v2-2026.06.24
    uv run scripts/tools/download_osworld_v2_assets.py --benchmark-release osworld-v2-2026.06.24 --target-dir cache/osworld_v2_assets

## Pitch framing (for the hiring-manager goal)

- The paper DEFINES "Conflict Disambiguation" (36% of tasks) as "resolving stale,
  noisy, contradictory, or distracting information by identifying which source is
  authoritative" — verbatim what `nastiness` injects. We turn up a phenomenon they
  already measured agents failing at; we don't invent one.
- Decide the metric before claiming "<50%": Opus 5's 70.6% is almost certainly
  partial. Binary (~20% for Opus 4.8) and our `phenomenon_score` sit lower. Honest
  claim = "the noise level at which Opus 5 crosses below 50%, grader untouched."
- Future direction: a benchmark with a difficulty parameter doesn't saturate.
