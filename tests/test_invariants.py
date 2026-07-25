"""The invariants are the product. Test them hard."""

import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oschaff import PerturbConfig, perturb, perturb_collection
from oschaff.generate import TemplatedGenerator
from oschaff.perturb import nastiness_to_mix
from oschaff.schemas import get_schema
from oschaff.verify import InvariantError, check_invariants, strip_perturbations

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "examples", "mailhub_state.json")


@pytest.fixture
def base():
    with open(STATE) as fh:
        return json.load(fh)


def _run(base, **kw):
    cfg = PerturbConfig(targets=["MailHub.emails"], generator="templated", **kw)
    states, reports = perturb({"MailHub.emails": base}, cfg)
    return states["MailHub.emails"], reports[0]


def test_real_items_never_change(base):
    original = copy.deepcopy(base["emails"])
    perturbed, _ = _run(base, signal_fraction=0.3, nastiness=1.0)
    real = [e for e in perturbed["emails"] if "_oschaff" not in e]
    # every original id present and body/subject/timestamp intact
    by_id = {e["id"]: e for e in real}
    for o in original:
        assert o["id"] in by_id
        for f in ("subject", "body", "timestamp", "from"):
            assert by_id[o["id"]][f] == o[f]


def test_input_state_not_mutated(base):
    before = copy.deepcopy(base)
    _run(base, signal_fraction=0.25, nastiness=0.9)
    assert base == before  # perturb() must be pure


def test_volume_dial(base):
    r = len(base["emails"])
    for sf in (1.0, 0.5, 0.25):
        _, report = _run(base, signal_fraction=sf, nastiness=0.5)
        expected_total = round(r / sf)
        assert report.real_count == r
        assert report.real_count + report.distractor_count == expected_total


def test_closeness_dial_mix():
    assert nastiness_to_mix(0.0)["filler"] == 1.0
    assert nastiness_to_mix(1.0)["superseded"] == pytest.approx(0.5)
    mid = nastiness_to_mix(0.5)
    assert mid["near_miss"] == pytest.approx(0.7)
    assert sum(nastiness_to_mix(0.7).values()) == pytest.approx(1.0)


def test_no_signal_field_collision(base):
    schema = get_schema("MailHub.emails")
    perturbed, _ = _run(base, signal_fraction=0.2, nastiness=1.0)
    real_sigs = {(e["subject"], e["body"]) for e in base["emails"]}
    for e in perturbed["emails"]:
        if "_oschaff" in e:
            assert (e["subject"], e["body"]) not in real_sigs


def test_superseded_is_earlier(base):
    perturbed, _ = _run(base, signal_fraction=0.3, nastiness=1.0)
    sup = [e for e in perturbed["emails"]
           if e.get("_oschaff", {}).get("noise_type") == "superseded"]
    assert sup, "expected some superseded distractors at nastiness=1.0"
    earliest_real = min(e["timestamp"] for e in base["emails"])
    for e in sup:
        assert e["timestamp"] < earliest_real or e["timestamp"] <= max(
            r["timestamp"] for r in base["emails"]
        )


def test_determinism(base):
    a, _ = _run(copy.deepcopy(base), signal_fraction=0.3, nastiness=0.8)
    b, _ = _run(copy.deepcopy(base), signal_fraction=0.3, nastiness=0.8)
    assert a == b


def test_reset_restores_baseline(base):
    schema = get_schema("MailHub.emails")
    perturbed, _ = _run(base, signal_fraction=0.2, nastiness=1.0)
    restored = strip_perturbations(perturbed, schema)
    assert restored["emails"] == base["emails"]


def test_verify_catches_tampering(base):
    """If a real item is altered, check_invariants must raise."""
    schema = get_schema("MailHub.emails")
    original = base["emails"]
    tampered = copy.deepcopy(original)
    tampered[0]["body"] = "SILENTLY CHANGED"  # simulate a bad injector
    with pytest.raises(InvariantError):
        check_invariants(original, tampered, schema)


def test_verify_catches_value_collision(base):
    schema = get_schema("MailHub.emails")
    original = base["emails"]
    colliding = copy.deepcopy(original) + [{
        **original[0], "id": "osc_bad", "_oschaff": {"noise_type": "near_miss"},
    }]
    with pytest.raises(InvariantError):
        check_invariants(original, colliding, schema)


def test_empty_collection_errors():
    with pytest.raises(ValueError):
        perturb_collection(
            {"emails": []}, get_schema("MailHub.emails"),
            PerturbConfig(), TemplatedGenerator(),
        )
