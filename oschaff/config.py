"""ChaffConfig: the whole user-facing surface for compiling a fork.

Two dials (amount, relevance) plus what to target and which model authors the
noise. Everything that protects ground truth lives in code, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


# Service name -> the `app=` string used in prepare_stateful_website_urls.
SERVICE_APPS = {
    "MailHub": "mailhub",
    "TeamChat": "teamchat",
    "VaultBank": "vaultbank",
    "CloudCRM": "cloudcrm",
    "CareerLink": "careerlink",
    "FormCraft": "formcraft",
}


@dataclass
class ChaffConfig:
    model: str = "claude-opus-4-8"        # LLM for the headless worker
    amount: float = 0.5                   # fraction of items that stay REAL (volume dial)
    relevance: float = 0.7                # 0=filler, 0.5=near-miss, 1=superseded (closeness dial)
    services: list[str] = field(default_factory=lambda: ["MailHub", "TeamChat"])
    bolt_on: bool = True                  # provision channels into tasks that lack one
    dynamic_delivery: bool = True         # inject mid-run messages via time_data where supported
    seed: int = 20260724
    source_tasks: str = "cache/osworld_tasks"
    source_assets: str = "cache/osworld_assets"
    output_root: str = "forks"            # OSWorld-Chaff-<uuid> is created under here
    max_parallel: int = 4
    max_retries: int = 1

    def __post_init__(self) -> None:
        if not 0.0 < self.amount <= 1.0:
            raise ValueError("amount must be in (0, 1]")
        if not 0.0 <= self.relevance <= 1.0:
            raise ValueError("relevance must be in [0, 1]")
        unknown = [s for s in self.services if s not in SERVICE_APPS]
        if unknown:
            raise ValueError(f"unknown services {unknown}; known: {sorted(SERVICE_APPS)}")

    @property
    def apps(self) -> set[str]:
        """The `app=` strings for the configured services."""
        return {SERVICE_APPS[s] for s in self.services}

    def canonical(self) -> dict:
        """Config as a stable dict (used in fork.json / the fork id)."""
        d = asdict(self)
        d["services"] = sorted(d["services"])
        return d

    @classmethod
    def from_yaml(cls, path: str) -> "ChaffConfig":
        import yaml

        data = yaml.safe_load(open(path)) or {}
        allowed = set(cls.__dataclass_fields__)
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        return cls(**data)
