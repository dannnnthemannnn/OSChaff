"""Verifier tests — run against the real gated states cached locally.

These use cache/ (gitignored, gated) so they only run where the assets exist;
they skip cleanly otherwise, so CI without gated access still passes.
"""

import copy
import json
import os

import pytest

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oschaff.checks import (
    InvariantError, verify_state_additive, verify_task_py,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEAMCHAT = os.path.join(ROOT, "cache/osworld_assets/task_035/dynamic_state_035.json")
MAILHUB = os.path.join(ROOT, "cache/osworld_assets/task_007_hitl/state.json")
TASK035 = os.path.join(ROOT, "cache/osworld_tasks/task_035.py")

need_assets = pytest.mark.skipif(
    not os.path.exists(TEAMCHAT), reason="gated cache/ states not present")


# ---- state additive checks (synthetic, always run) ---------------------- #
def test_append_is_additive():
    src = {"data": {"emails": [{"id": "1", "subject": "a"}, {"id": "2", "subject": "b"}]}}
    fork = copy.deepcopy(src)
    fork["data"]["emails"].append({"id": "x", "subject": "distractor"})
    assert verify_state_additive(src, fork) == 1


def test_new_container_key_allowed():
    src = {"data": {"messages": {"c": [{"id": "1"}]}}}
    fork = copy.deepcopy(src)
    fork["data"]["time_data"] = [{"id": "d", "arrive_after_s": 60}]  # dynamic delivery
    assert verify_state_additive(src, fork) >= 0


def test_modifying_real_item_raises():
    src = {"data": {"emails": [{"id": "1", "subject": "real"}]}}
    fork = copy.deepcopy(src)
    fork["data"]["emails"][0]["subject"] = "TAMPERED"
    with pytest.raises(InvariantError):
        verify_state_additive(src, fork)


def test_removing_item_raises():
    src = {"data": {"emails": [{"id": "1"}, {"id": "2"}]}}
    fork = {"data": {"emails": [{"id": "1"}]}}
    with pytest.raises(InvariantError):
        verify_state_additive(src, fork)


def test_scalar_change_raises():
    with pytest.raises(InvariantError):
        verify_state_additive({"note": "x"}, {"note": "y"})


# ---- against real states ------------------------------------------------ #
@need_assets
def test_real_teamchat_append():
    state = json.load(open(TEAMCHAT))
    fork = copy.deepcopy(state)
    ch = fork["data"]["teamchat"]["messages"]["finance-approvals"]
    ch.append({"messageId": "osc_x", "senderId": "user_x", "content": "distractor",
               "timestamp": "2025-12-20T08:00:00.000000Z", "threadId": None,
               "reactions": [], "isEdited": False})
    assert verify_state_additive(state, fork) == 1


@need_assets
def test_real_teamchat_tamper_raises():
    state = json.load(open(TEAMCHAT))
    fork = copy.deepcopy(state)
    fork["data"]["teamchat"]["messages"]["finance-approvals"][0]["content"] = "CHANGED"
    with pytest.raises(InvariantError):
        verify_state_additive(state, fork)


# ---- task .py checks ---------------------------------------------------- #
@need_assets
def test_task_py_identical_ok():
    src = open(TASK035).read()
    verify_task_py(src, src)  # no change → passes


@need_assets
def test_task_py_instruction_append_ok():
    src = open(TASK035).read()
    fork = src.replace(
        'source = "brainstorm"',
        'source = "brainstorm"\n    _extra = "You may have relevant MailHub messages."')
    verify_task_py(src, fork)  # instruction untouched, evaluate untouched


@need_assets
def test_task_py_grader_edit_raises():
    src = open(TASK035).read()
    fork = src.replace("return float(round(score, 4))", "return 1.0")
    with pytest.raises(InvariantError):
        verify_task_py(src, fork)
