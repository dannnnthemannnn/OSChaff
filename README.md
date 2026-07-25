# OSChaff

A signal-to-noise **perturbation harness** for [OSWorld 2.0](https://osworld-v2.xlang.ai/).
It takes an existing OSWorld 2.0 task and injects controlled distractor material
into its initial web-service state **without altering ground truth**, producing a
paired difficulty curve on tasks whose graders are already validated.

We are not authoring tasks and not writing graders — those are the expensive,
already-validated parts (36 authors, two annotators re-solving every task). We
add one orthogonal difficulty **dial** to that work and report what happens.

## Why this is worth building

OSWorld 2.0's own failure analysis says agents don't fail on GUI control or
coding. They fail on **hidden-state phenomena**: they drop constraints, can't
tell stale information from current, and spend <7% of their budget catching their
own mistakes. The paper *defines* the phenomenon called **Conflict Disambiguation**
(36% of tasks) as, verbatim, "resolving stale, noisy, contradictory, or
distracting information by identifying which source is authoritative." That is a
word-for-word description of what this harness injects. OSChaff doesn't invent a
new difficulty axis — it turns a **dial** on a phenomenon the authors already
measured agents failing at.

A benchmark with a difficulty parameter doesn't saturate. OSWorld 1.0 went 12% →
83.5% in two years and had to be replaced. You turn the dial instead.

## Two dials, one invariant

The whole config is two numbers plus what to fuzz (`oschaff.yaml`):

| Dial | Field | What it does |
|---|---|---|
| **Volume** | `signal_fraction` (0,1] | fraction of items that are real. `1.0` = untouched, `0.5` = one distractor per real item, `0.25` = three per real. Lower = more to read (the horizon axis). |
| **Closeness** | `nastiness` [0,1] | distractor *type* mix. `0.0` = harmless filler → `0.5` = near-miss (plausible but wrong) → `1.0` = superseded (stale, conflicting earlier versions). |

They're orthogonal on purpose: hold the distractor **count** fixed and move only
`nastiness` to isolate *discrimination* difficulty from *horizon*. Everything
that protects ground truth is **enforced in code, not config** — it's the
integrity of the method, not a user preference.

**The invariant:** *add material, never alter ground truth.* `verify.py` enforces
it mechanically on every run:
1. every real item is still present and byte-for-byte unchanged (only additions);
2. no distractor matches a real item on all its load-bearing fields (no accidental scored-correct);
3. every injected item is provenance-marked, so it can always be stripped back to baseline.

A violation raises — it's a bug, not a harder task.

## Three noise types

- **`filler`** — topically unrelated. Cheap to filter. The floor condition.
- **`near_miss`** — plausible but wrong: shares an entity with a real item but
  differs on a load-bearing field. Forces real discrimination, not topic filtering.
- **`superseded`** — an *earlier-timestamped* version of a real claim with a
  different value; the newer real item stays authoritative. This is the
  interesting one, and it's the **static** form of the Task 035 trap (a mid-run
  TeamChat correction), so it needs zero understanding of the dynamic-update hook.

## Try it (no deployment, no API key)

```bash
python examples/demo.py     # sweeps both dials over the sample MailHub inbox
python -m pytest tests/     # the invariants are the product; they're tested hard
```

The offline `templated` generator is deterministic and dependency-free. The
`llm` generator (set `generator: llm`) writes natural distractors that understand
the seed item — it needs the `anthropic` SDK + a key, and **falls back to
templated** on any failure, so the library always runs.

## Status & what's real vs. gated

This repo currently implements the **perturbation engine + invariant enforcement**,
provable today against MailHub — the one state schema fully published in the paper
(Figure 13). That's deliberate: it's the part that carries the scientific claim
and needs no deployment.

What "run a perturbed task end-to-end" additionally requires (and does **not** yet
exist here):

- **Gated access** to the tasks (`xlangai/osworld_v2_tasks`, Python task classes)
  and assets (`xlangai/osworld_v2_assets_gated`). Request on Hugging Face.
- **The self-hosted website stack** (`basesite`) — *not* in the public OSWorld-V2
  repo; hosted separately. This is where `/api/state` and `/state-manage` live.
- A desktop-VM provider + model spend (~$72/task at 500 steps).

First thing to confirm once gated access lands: whether each service's initial
state arrives as a JSON asset file, a `/api/state` push at setup, or inline in the
task class. All three are perturbable; we just need to see which.

## Roadmap

- [x] Perturbation engine, two dials, mechanical invariants, MailHub schema, tests
- [ ] Capture remaining schemas (TeamChat, VaultBank, CloudCRM) from `/state-manage`
- [ ] Wire into the OSWorld-V2 runner as a state-setup shim (perturb, then hand off)
- [ ] `phenomenon_score`: tag which checkpoints require resolving the conflict,
      and report it alongside binary/partial (it's the metric designed to separate)
- [ ] Paired noise curve on ~10 short, conflict-tagged tasks; report steps
      alongside score so degradation can be separated from horizon
- [ ] Correction-budget telemetry: does self-repair spending rise under noise?

## Layout

```
oschaff/
  schemas.py   per-service state schemas (MailHub known; rest from /state-manage)
  generate.py  distractor generators: templated (offline) + llm (pluggable)
  perturb.py   the two dials + config
  verify.py    mechanical invariant enforcement
examples/      sample MailHub state + a runnable dial-sweep demo
tests/         invariant tests
```
