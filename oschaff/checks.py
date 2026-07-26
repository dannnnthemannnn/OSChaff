"""Fork-level invariant checks — the guardrail on the autonomous worker.

Every per-task edit is diffed source-vs-fork and must pass these, or it's
reverted. The promise is "add material, never alter ground truth":

  - State asset edits are **additive only**: every original item survives
    byte-identical; the only changes are appended list elements (or wholly new
    container keys, e.g. an added ``time_data`` for mid-run delivery).
  - The **grader is untouched**: the ``evaluate`` method is structurally
    identical; any ``*_gt*`` asset is byte-identical.
  - Prompt edits are **additive**: the original ``instruction`` text is preserved
    verbatim (appended-to, never rewritten).
  - The fork task still **parses** and exposes ``TASK_CLASS``.

These are schema-free (they don't need a per-service model), so they hold for
MailHub, TeamChat, and anything we add later.
"""

from __future__ import annotations

import ast
import json


class InvariantError(AssertionError):
    """Raised when a perturbation would compromise ground truth."""


# --------------------------------------------------------------------------- #
# State asset: additive-only
# --------------------------------------------------------------------------- #
def verify_state_additive(source_obj, fork_obj, path: str = "$") -> int:
    """Assert ``fork_obj`` only ADDS to ``source_obj``. Returns items added.

    dicts: every source key preserved (recursed); new keys allowed.
    lists: every source element still present unchanged (order-independent);
           extra elements allowed and counted.
    scalars: must be equal.
    """
    added = 0
    if isinstance(source_obj, dict):
        if not isinstance(fork_obj, dict):
            raise InvariantError(f"{path}: dict changed to {type(fork_obj).__name__}")
        for k, v in source_obj.items():
            if k not in fork_obj:
                raise InvariantError(f"{path}.{k}: key removed")
            added += verify_state_additive(v, fork_obj[k], f"{path}.{k}")
    elif isinstance(source_obj, list):
        if not isinstance(fork_obj, list):
            raise InvariantError(f"{path}: list changed to {type(fork_obj).__name__}")
        remaining = list(fork_obj)
        for item in source_obj:
            match = next((i for i, f in enumerate(remaining) if f == item), None)
            if match is None:
                raise InvariantError(f"{path}: original item altered/removed: {str(item)[:100]}")
            remaining.pop(match)
        added += len(remaining)  # the injected distractors
    else:
        if source_obj != fork_obj:
            raise InvariantError(f"{path}: value changed {source_obj!r} -> {fork_obj!r}")
    return added


def verify_state_file(source_path: str, fork_path: str) -> int:
    return verify_state_additive(json.load(open(source_path)), json.load(open(fork_path)))


# --------------------------------------------------------------------------- #
# Task .py: grader untouched, prompt additive, still loadable
# --------------------------------------------------------------------------- #
def _task_classdef(src: str) -> ast.ClassDef:
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.lower().startswith("task"):
            return node
    raise InvariantError("no Task class found")


def _method(cls: ast.ClassDef, name: str):
    return next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name), None)


def _instruction_text(cls: ast.ClassDef) -> str | None:
    for n in cls.body:
        if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "instruction" for t in n.targets
        ):
            try:
                return ast.literal_eval(n.value)
            except Exception:
                return None
    return None


def verify_task_py(source_src: str, fork_src: str) -> None:
    """Assert the grader is untouched, the prompt only grew, and it still parses."""
    try:
        fork_cls = _task_classdef(fork_src)
    except SyntaxError as e:
        raise InvariantError(f"fork task does not parse: {e}")
    src_cls = _task_classdef(source_src)

    # grader: evaluate() structurally identical
    se, fe = _method(src_cls, "evaluate"), _method(fork_cls, "evaluate")
    if (se is None) != (fe is None):
        raise InvariantError("evaluate() presence changed")
    if se is not None and ast.dump(se) != ast.dump(fe):
        raise InvariantError("evaluate() (the grader) was modified")

    # prompt: original instruction preserved verbatim (appended-to is OK)
    si, fi = _instruction_text(src_cls), _instruction_text(fork_cls)
    if si is not None:
        if fi is None:
            raise InvariantError("instruction became unreadable")
        if " ".join(si.split()) not in " ".join(fi.split()):
            raise InvariantError("original instruction text was altered, not just appended to")

    if "TASK_CLASS" not in fork_src:
        raise InvariantError("fork task is missing TASK_CLASS export")


def verify_bytes_identical(source_path: str, fork_path: str, label: str = "asset") -> None:
    with open(source_path, "rb") as a, open(fork_path, "rb") as b:
        if a.read() != b.read():
            raise InvariantError(f"{label} changed but must be byte-identical: {fork_path}")
