"""OSChaff: a signal-to-noise perturbation harness for OSWorld 2.0.

Add controlled distractor material to an OSWorld 2.0 task's initial web-service
state, without altering ground truth, producing a paired difficulty curve on
tasks whose graders are already validated.

Two dials:
    signal_fraction  volume (how much distractor material)
    nastiness        closeness (filler -> near_miss -> superseded)

Quickstart:
    from oschaff import PerturbConfig, perturb
    cfg = PerturbConfig(targets=["MailHub.emails"], signal_fraction=0.4, nastiness=0.8)
    perturbed_states, reports = perturb({"MailHub.emails": mailhub_state}, cfg)
"""

from .perturb import (
    PerturbConfig,
    PerturbationReport,
    nastiness_to_mix,
    perturb,
    perturb_collection,
)
from .schemas import REGISTRY, Schema, get_schema
from .verify import InvariantError, check_invariants, strip_perturbations

__all__ = [
    "PerturbConfig",
    "PerturbationReport",
    "perturb",
    "perturb_collection",
    "nastiness_to_mix",
    "Schema",
    "get_schema",
    "REGISTRY",
    "check_invariants",
    "InvariantError",
    "strip_perturbations",
]

__version__ = "0.1.0"
