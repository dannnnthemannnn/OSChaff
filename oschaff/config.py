"""ChaffConfig — the whole surface for the per-task noise injector.

Two 0-10 dials (volume, deceptiveness) plus the model and where source tasks/
assets live. Kept deliberately small.
"""

from __future__ import annotations

from dataclasses import dataclass

# The two injectable services whose state we know how to flood.
CHANNEL_APPS = {"mailhub", "teamchat"}


@dataclass
class ChaffConfig:
    model: str = "claude-opus-4-8"      # model the headless worker uses
    volume: int = 5                     # 0-10: how much distractor material
    deceptiveness: int = 7              # 0-10: filler -> near-miss -> disarmable traps
    source_tasks: str = "cache/osworld_tasks"
    source_assets: str = "cache/osworld_assets"
    out_root: str = "forks"
    retries: int = 2                    # re-run the worker if it errors / no-ops

    def __post_init__(self) -> None:
        for name in ("volume", "deceptiveness"):
            v = getattr(self, name)
            if not (isinstance(v, int) and 0 <= v <= 10):
                raise ValueError(f"{name} must be an int in [0, 10]")

    @classmethod
    def from_yaml(cls, path: str) -> "ChaffConfig":
        import yaml

        data = yaml.safe_load(open(path)) or {}
        allowed = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in allowed})
