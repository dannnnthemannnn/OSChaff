"""Run OSChaff over the sample MailHub state and show the difficulty curve.

    python examples/demo.py

Prints, for a sweep of the two dials, how many distractors get injected, the
type mix, and confirms the ground-truth invariants hold every time.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oschaff import PerturbConfig, perturb  # noqa: E402
from oschaff.verify import strip_perturbations  # noqa: E402
from oschaff.schemas import get_schema  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def load_state():
    with open(os.path.join(HERE, "mailhub_state.json")) as fh:
        return json.load(fh)


def main():
    base = load_state()
    print(f"Baseline MailHub inbox: {len(base['emails'])} real emails\n")

    print(f"{'signal':>7} {'nasty':>6} {'total':>6} {'distract':>9} "
          f"{'filler':>7} {'near':>5} {'super':>6} {'inv':>4}")
    print("-" * 60)

    # VOLUME sweep at fixed high nastiness, then CLOSENESS sweep at fixed volume.
    sweeps = [
        ("volume ", [(sf, 0.8) for sf in (1.0, 0.75, 0.5, 0.3)]),
        ("nasty  ", [(0.5, n) for n in (0.0, 0.5, 1.0)]),
    ]
    for label, points in sweeps:
        for sf, nasty in points:
            cfg = PerturbConfig(
                targets=["MailHub.emails"],
                signal_fraction=sf,
                nastiness=nasty,
                generator="templated",
            )
            states, reports = perturb({"MailHub.emails": base}, cfg)
            r = reports[0]
            print(f"{sf:>7.2f} {nasty:>6.2f} "
                  f"{r.real_count + r.distractor_count:>6} {r.distractor_count:>9} "
                  f"{r.by_type['filler']:>7} {r.by_type['near_miss']:>5} "
                  f"{r.by_type['superseded']:>6} "
                  f"{'ok' if r.invariants_ok else 'FAIL':>4}")
        print()

    # Show a concrete superseded distractor + that reset restores baseline.
    cfg = PerturbConfig(targets=["MailHub.emails"], signal_fraction=0.3, nastiness=1.0)
    states, _ = perturb({"MailHub.emails": base}, cfg)
    perturbed = states["MailHub.emails"]
    sup = next(e for e in perturbed["emails"]
               if e.get("_oschaff", {}).get("noise_type") == "superseded")
    print("Example 'superseded' distractor (note earlier timestamp, changed body):")
    print(json.dumps({k: sup[k] for k in ("subject", "body", "timestamp", "_oschaff")},
                     indent=2))

    restored = strip_perturbations(perturbed, get_schema("MailHub.emails"))
    assert len(restored["emails"]) == len(base["emails"]), "reset failed"
    print(f"\nReset removes all injected items -> back to {len(restored['emails'])} real emails.")


if __name__ == "__main__":
    main()
