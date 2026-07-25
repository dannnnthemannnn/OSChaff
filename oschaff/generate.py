"""Distractor generation.

Three noise types, in ascending order of how hard they are for an agent to
dismiss (paper §Conflict Disambiguation is defined as exactly this problem:
"resolving stale, noisy, contradictory, or distracting information by
identifying which source is authoritative"):

    filler      topically unrelated. Cheap to filter. The floor condition.
    near_miss   plausible but wrong: shares an entity with a real item but
                differs on a load-bearing field. Forces real discrimination.
    superseded  an earlier-timestamped version of a real item's claim with a
                different value. The real (newer) item stays present; the agent
                must notice the distractor is stale.

A generator turns (schema, real seed items, type, n) into distractor items.
Two backends:

    TemplatedGenerator  deterministic, offline, no dependencies. Structural
                        cloning of real items. Always available; used in tests.
    LLMGenerator        calls an LLM to write natural distractors that
                        understand the seed item. Used when an API key exists;
                        falls back to templated on any failure.
"""

from __future__ import annotations

import copy
import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .schemas import Schema

NOISE_TYPES = ("filler", "near_miss", "superseded")


def _seeded_rng(seed: int, *parts: Any) -> random.Random:
    """Deterministic RNG derived from the run seed plus some discriminators."""
    h = hashlib.sha256(("|".join(map(str, (seed, *parts)))).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def _shift_timestamp(ts: str, hours: float) -> str:
    """Return ``ts`` shifted by ``hours`` (negative = earlier). Best-effort."""
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        dt = datetime(2026, 5, 1, tzinfo=timezone.utc)
    return (dt + timedelta(hours=hours)).isoformat()


class Generator:
    """Base interface."""

    def generate(
        self, schema: Schema, seeds: list[dict], noise_type: str, n: int, seed: int
    ) -> list[dict]:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Templated (deterministic, offline)
# --------------------------------------------------------------------------- #

_FILLER_SUBJECTS = [
    "Weekly newsletter: industry roundup",
    "Your subscription receipt",
    "Team lunch on Friday",
    "Reminder: office wifi maintenance",
    "New comment on a doc you follow",
    "Survey: how are we doing?",
]
_FILLER_SENDERS = [
    "news@dailydigest.example.com",
    "no-reply@notifications.example.com",
    "hr@company.example.com",
    "facilities@company.example.com",
]


@dataclass
class TemplatedGenerator(Generator):
    """Deterministic distractors via structural cloning. No external deps."""

    def generate(
        self, schema: Schema, seeds: list[dict], noise_type: str, n: int, seed: int
    ) -> list[dict]:
        if noise_type not in NOISE_TYPES:
            raise ValueError(f"unknown noise_type {noise_type!r}")
        if n <= 0:
            return []
        method = getattr(self, f"_{noise_type}")
        return [method(schema, seeds, i, seed) for i in range(n)]

    # -- filler: unrelated content, no relationship to any real item --------- #
    def _filler(self, schema: Schema, seeds: list[dict], i: int, seed: int) -> dict:
        rng = _seeded_rng(seed, "filler", i)
        item = schema.template()
        if "subject" in item:
            item["subject"] = rng.choice(_FILLER_SUBJECTS)
        if "from" in item:
            item["from"] = rng.choice(_FILLER_SENDERS)
        if "body" in item:
            item["body"] = "Automated notification. No action required."
        if schema.order_field in item:
            item[schema.order_field] = _shift_timestamp(
                _base_ts(seeds, schema), rng.uniform(-96, 96)
            )
        return _stamp(item, schema, seed, "filler", i)

    # -- near_miss: clone a real item, keep an entity, change signal fields --- #
    def _near_miss(self, schema: Schema, seeds: list[dict], i: int, seed: int) -> dict:
        rng = _seeded_rng(seed, "near_miss", i)
        base = copy.deepcopy(rng.choice(seeds)) if seeds else schema.template()
        base.pop(schema.id_field, None)
        # Perturb every signal field so it can never be mistaken for the real one
        # by a grader, but keep it topically adjacent.
        for f in schema.signal_fields:
            base[f] = _mutate_value(base.get(f, ""), rng, kind="near")
        # Shift the locating entity a little (different sender/date window).
        if "from" in base and rng.random() < 0.7:
            base["from"] = _alt_sender(base["from"], rng)
        if schema.order_field in base:
            base[schema.order_field] = _shift_timestamp(
                base[schema.order_field], rng.uniform(-48, 48)
            )
        return _stamp(base, schema, seed, "near_miss", i)

    # -- superseded: earlier version of a real claim, different value -------- #
    def _superseded(self, schema: Schema, seeds: list[dict], i: int, seed: int) -> dict:
        rng = _seeded_rng(seed, "superseded", i)
        base = copy.deepcopy(rng.choice(seeds)) if seeds else schema.template()
        base.pop(schema.id_field, None)
        # Same subject/topic, *different* body value, *earlier* timestamp: the
        # real (newer) item stays present and authoritative.
        for f in schema.signal_fields:
            if f == schema.order_field:
                continue
            base[f] = _mutate_value(base.get(f, ""), rng, kind="stale")
        if schema.order_field in base:
            base[schema.order_field] = _shift_timestamp(
                base[schema.order_field], rng.uniform(-72, -6)
            )
        return _stamp(base, schema, seed, "superseded", i)


def _base_ts(seeds: list[dict], schema: Schema) -> str:
    for s in seeds:
        if schema.order_field in s:
            return s[schema.order_field]
    return datetime(2026, 5, 1, tzinfo=timezone.utc).isoformat()


def _mutate_value(val: Any, rng: random.Random, kind: str) -> Any:
    """Change a value enough that it cannot collide with the original."""
    tag = "(updated)" if kind == "near" else "(earlier draft)"
    if isinstance(val, str):
        return f"{val} {tag} #{rng.randint(1000, 9999)}".strip()
    if isinstance(val, (int, float)):
        # >=5% delta so it never accidentally equals a checkpoint target.
        factor = rng.choice([0.85, 0.9, 1.1, 1.15])
        return round(val * factor, 2)
    if isinstance(val, list):
        return val
    return f"{val} {tag}"


def _alt_sender(sender: str, rng: random.Random) -> str:
    if "@" in sender:
        local, domain = sender.split("@", 1)
        return f"{local}.{rng.choice(['ops','team','intl','2'])}@{domain}"
    return sender


def _stamp(item: dict, schema: Schema, seed: int, noise_type: str, i: int) -> dict:
    """Give the distractor a stable synthetic id and mark its provenance.

    The ``_oschaff`` marker lets verify.py and cleanup distinguish injected
    material from real items with zero ambiguity.
    """
    ident = "osc_" + hashlib.sha256(f"{seed}:{noise_type}:{i}".encode()).hexdigest()[:12]
    item[schema.id_field] = ident
    item["_oschaff"] = {"seed": seed, "noise_type": noise_type, "index": i}
    return item


# --------------------------------------------------------------------------- #
# LLM backend (pluggable; degrades to templated)
# --------------------------------------------------------------------------- #


@dataclass
class LLMGenerator(Generator):
    """Generate natural-language distractors with an LLM.

    Kept intentionally thin: it builds a prompt from the seed items and the
    noise type, asks for JSON items matching the schema, then hands the result
    through the *same* invariant checks as everything else. If the SDK or an API
    key is missing, or the call fails, it falls back to the templated generator
    so the library always runs.
    """

    model: str = "claude-opus-4-8"
    max_tokens: int = 4000
    _fallback: TemplatedGenerator = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._fallback = TemplatedGenerator()

    def _client(self):  # pragma: no cover - depends on env
        try:
            import anthropic  # noqa: WPS433
        except ImportError:
            return None
        try:
            return anthropic.Anthropic()
        except Exception:
            return None

    def generate(
        self, schema: Schema, seeds: list[dict], noise_type: str, n: int, seed: int
    ) -> list[dict]:
        client = self._client()
        if client is None or n <= 0:
            return self._fallback.generate(schema, seeds, noise_type, n, seed)
        try:  # pragma: no cover - network path
            items = self._call(client, schema, seeds, noise_type, n, seed)
        except Exception:
            return self._fallback.generate(schema, seeds, noise_type, n, seed)
        # Normalize + stamp so downstream treats LLM output identically.
        out = []
        for i, raw in enumerate(items[:n]):
            item = schema.template()
            item.update({k: v for k, v in raw.items() if k in item})
            out.append(_stamp(item, schema, seed, noise_type, i))
        if len(out) < n:  # top up deterministically if the model under-produced
            out += self._fallback.generate(
                schema, seeds, noise_type, n - len(out), seed
            )
        return out

    def _call(self, client, schema, seeds, noise_type, n, seed):  # pragma: no cover
        import json

        guidance = {
            "filler": "topically unrelated to the real items; cheap to ignore",
            "near_miss": (
                "plausible but WRONG: share one entity (sender/topic/date) with a "
                "real item but differ on the load-bearing fields "
                f"{schema.signal_fields}; never match a real item on all of them"
            ),
            "superseded": (
                "an EARLIER-timestamped version of a real item's claim with a "
                "DIFFERENT value; the newer real item stays authoritative"
            ),
        }[noise_type]
        prompt = (
            f"You generate distractor items for a computer-use benchmark.\n"
            f"Service: {schema.service}, collection: {schema.collection}.\n"
            f"Real items (do NOT copy their {schema.signal_fields} values):\n"
            f"{json.dumps(seeds, indent=2)[:6000]}\n\n"
            f"Produce {n} distractor items of type '{noise_type}': {guidance}.\n"
            f"Each item must have exactly these fields: "
            f"{list(schema.template().keys())}.\n"
            f"Return ONLY a JSON array."
        )
        msg = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text
        start, end = text.find("["), text.rfind("]")
        return json.loads(text[start : end + 1])


def make_generator(kind: str) -> Generator:
    if kind == "templated":
        return TemplatedGenerator()
    if kind == "llm":
        return LLMGenerator()
    raise ValueError(f"unknown generator {kind!r} (use 'templated' or 'llm')")
