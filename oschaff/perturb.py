"""The perturbation layer: two orthogonal dials, one invariant.

Config is deliberately tiny (paper's giant per-field YAML is not the point).
The whole surface is:

    targets           which collections to fuzz ("Service.collection")
    signal_fraction   VOLUME dial (0,1]. Fraction of items that are real /
                      load-bearing. 0.5 => one distractor per real item;
                      0.25 => three per real item. Lower = more to read
                      (this is the horizon axis, and re-deriving "longer is
                      harder" on a controlled curve is fine — it is still a
                      thing agents fail at).
    nastiness         CLOSENESS dial [0,1]. Maps to the distractor type mix:
                      0.0 -> all filler; 0.5 -> mostly near_miss;
                      1.0 -> heavy on superseded. This axis is (near-)volume-
                      preserving, so holding the distractor count fixed and
                      moving only nastiness isolates discrimination difficulty
                      from horizon.

Everything else — the invariants — lives in code, not config, because they are
the integrity of the method, not a user preference.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .generate import NOISE_TYPES, Generator, make_generator
from .schemas import Schema, get_schema
from .verify import InvariantError, check_invariants


@dataclass
class PerturbConfig:
    targets: list[str] = field(default_factory=lambda: ["MailHub.emails"])
    signal_fraction: float = 0.5      # volume dial
    nastiness: float = 0.7            # closeness dial
    generator: str = "templated"
    seed: int = 20260724

    def __post_init__(self) -> None:
        if not 0.0 < self.signal_fraction <= 1.0:
            raise ValueError("signal_fraction must be in (0, 1]")
        if not 0.0 <= self.nastiness <= 1.0:
            raise ValueError("nastiness must be in [0, 1]")

    @classmethod
    def from_yaml(cls, path: str) -> "PerturbConfig":
        import yaml  # lazy: only needed if you use YAML

        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in allowed})


def nastiness_to_mix(nastiness: float) -> dict[str, float]:
    """Map the single closeness dial to a distractor type mix.

    Piecewise-linear over three anchor points so the dial reads intuitively:
        0.0 -> pure filler
        0.5 -> mostly near_miss, some filler
        1.0 -> superseded-heavy, the rest near_miss/filler
    """
    anchors = {
        0.0: {"filler": 1.0, "near_miss": 0.0, "superseded": 0.0},
        0.5: {"filler": 0.3, "near_miss": 0.7, "superseded": 0.0},
        1.0: {"filler": 0.2, "near_miss": 0.3, "superseded": 0.5},
    }
    lo, hi = (0.0, 0.5) if nastiness <= 0.5 else (0.5, 1.0)
    t = 0.0 if hi == lo else (nastiness - lo) / (hi - lo)
    return {
        k: anchors[lo][k] + t * (anchors[hi][k] - anchors[lo][k]) for k in NOISE_TYPES
    }


def _counts(n_distractors: int, mix: dict[str, float]) -> dict[str, int]:
    """Split a distractor budget across noise types (largest-remainder)."""
    raw = {k: n_distractors * mix[k] for k in NOISE_TYPES}
    floor = {k: int(v) for k, v in raw.items()}
    rem = n_distractors - sum(floor.values())
    for k in sorted(NOISE_TYPES, key=lambda k: raw[k] - floor[k], reverse=True)[:rem]:
        floor[k] += 1
    return floor


@dataclass
class PerturbationReport:
    target: str
    real_count: int
    distractor_count: int
    by_type: dict[str, int]
    signal_fraction_achieved: float
    invariants_ok: bool


def perturb_collection(
    state: dict, schema: Schema, cfg: PerturbConfig, generator: Generator
) -> tuple[dict, PerturbationReport]:
    """Return (new_state, report). ``state`` is not mutated."""
    state = copy.deepcopy(state)
    real_items = list(state.get(schema.collection, []))
    real_count = len(real_items)
    if real_count == 0:
        raise ValueError(
            f"{schema.key}: collection '{schema.collection}' is empty; nothing to anchor noise to."
        )

    # VOLUME dial: n_real / (n_real + n_distract) = signal_fraction
    target_total = round(real_count / cfg.signal_fraction)
    n_distract = max(0, target_total - real_count)

    # CLOSENESS dial: distribute the distractor budget across noise types.
    mix = nastiness_to_mix(cfg.nastiness)
    by_type = _counts(n_distract, mix)

    distractors: list[dict] = []
    for noise_type, n in by_type.items():
        distractors += generator.generate(
            schema, real_items, noise_type, n, cfg.seed
        )

    new_items = real_items + distractors
    # Deterministic interleave so distractors are not all clustered at the end.
    new_items.sort(key=lambda it: str(it.get(schema.order_field, "")))
    state[schema.collection] = new_items

    ok = True
    try:
        check_invariants(real_items, new_items, schema)
    except InvariantError:
        raise  # fail loud: an invariant violation is a bug, not a result

    total = len(new_items)
    report = PerturbationReport(
        target=schema.key,
        real_count=real_count,
        distractor_count=len(distractors),
        by_type=by_type,
        signal_fraction_achieved=real_count / total if total else 1.0,
        invariants_ok=ok,
    )
    return state, report


def perturb(
    states: dict[str, dict], cfg: PerturbConfig
) -> tuple[dict[str, dict], list[PerturbationReport]]:
    """Perturb every configured target.

    ``states`` maps ``"Service.collection"`` -> that service's state envelope.
    Returns the perturbed envelopes and one report per target.
    """
    generator = make_generator(cfg.generator)
    out: dict[str, dict] = dict(states)
    reports: list[PerturbationReport] = []
    for target in cfg.targets:
        schema = get_schema(target)
        if target not in states:
            raise KeyError(f"no state provided for target {target!r}")
        new_state, report = perturb_collection(
            states[target], schema, cfg, generator
        )
        out[target] = new_state
        reports.append(report)
    return out, reports
