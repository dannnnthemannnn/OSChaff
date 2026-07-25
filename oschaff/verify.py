"""Mechanical invariant enforcement.

The core promise of OSChaff is: **add material, never alter ground truth.** If it
holds, every one of the ~27 validated checkpoints per task still means exactly
what upstream validated it to mean, and we inherit their grader for free.

We enforce it at the *state* level, which is stronger and simpler than trying to
parse each grader:

  1. ground_truth_immutable  every original (real) item is still present and
                             byte-for-byte unchanged. Only additions are allowed.
  2. no_value_collision      no distractor matches a real item on *all* of the
                             schema's signal_fields at once (which would turn a
                             wrong answer into a scored-correct one).
  3. provenance_marked       every added item carries the ``_oschaff`` marker, so
                             injected material can always be told from real data.

A run that violates any of these raises — it is a bug in the injector, not a
harder task.
"""

from __future__ import annotations

import json
from typing import Any

from .schemas import Schema


class InvariantError(AssertionError):
    """Raised when a perturbation would compromise ground truth."""


def _canonical(item: dict) -> str:
    """Stable serialization of a real item, ignoring the injector marker."""
    return json.dumps(
        {k: v for k, v in item.items() if k != "_oschaff"},
        sort_keys=True,
        default=str,
    )


def _signal_tuple(item: dict, schema: Schema) -> tuple:
    return tuple(_hashable(item.get(f)) for f in schema.signal_fields)


def _hashable(v: Any):
    if isinstance(v, list):
        return tuple(_hashable(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((k, _hashable(x)) for k, x in v.items()))
    return v


def check_invariants(
    original_items: list[dict], new_items: list[dict], schema: Schema
) -> None:
    """Assert the three invariants or raise ``InvariantError``."""
    new_by_canon: dict[str, dict] = {}
    added: list[dict] = []
    for it in new_items:
        if "_oschaff" in it:
            added.append(it)
        else:
            new_by_canon[_canonical(it)] = it

    # (1) every original item survives unchanged.
    missing = []
    for orig in original_items:
        if _canonical(orig) not in new_by_canon:
            missing.append(orig.get(schema.id_field, orig.get("subject", "?")))
    if missing:
        raise InvariantError(
            f"{schema.key}: {len(missing)} real item(s) altered or removed: {missing[:5]}"
        )
    if len(new_by_canon) != len(original_items):
        raise InvariantError(
            f"{schema.key}: real-item count changed "
            f"({len(original_items)} -> {len(new_by_canon)})"
        )

    # (2) no distractor collides with a real item on all signal fields.
    real_sigs = {_signal_tuple(o, schema) for o in original_items}
    for d in added:
        if _signal_tuple(d, schema) in real_sigs:
            raise InvariantError(
                f"{schema.key}: distractor {d.get(schema.id_field)!r} collides with a "
                f"real item on signal fields {schema.signal_fields}"
            )

    # (3) every added item is marked.
    unmarked = [i for i, it in enumerate(new_items)
                if _canonical(it) not in new_by_canon and "_oschaff" not in it]
    if unmarked:
        raise InvariantError(f"{schema.key}: {len(unmarked)} added item(s) lack provenance marker")


def strip_perturbations(state: dict, schema: Schema) -> dict:
    """Return ``state`` with all injected items removed (reset to baseline)."""
    import copy

    state = copy.deepcopy(state)
    state[schema.collection] = [
        it for it in state.get(schema.collection, []) if "_oschaff" not in it
    ]
    return state
