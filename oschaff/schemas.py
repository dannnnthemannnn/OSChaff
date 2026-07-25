"""Per-service state schemas.

OSWorld 2.0 self-hosts its task-facing web services (email, chat, banking, ...)
behind a shared ``basesite`` scaffold. Each service stores its data as a JSON
envelope of metadata plus a task-data collection, scoped by a ``user_id`` cookie
(see the paper, Appendix C.2 / Figure 13). OSChaff perturbs *that collection* and
nothing else.

Only MailHub's schema is published in the paper (Figure 13), so it is the one we
can build and test against with no deployment. The remaining schemas are pulled
from each service's ``/state-manage`` page once a live deployment is available;
add them here as they are captured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class Schema:
    """Describes one perturbable collection inside a service's state envelope.

    Attributes:
        service:        Renamed service, e.g. ``"MailHub"`` (Gmail stand-in).
        collection:     Top-level key holding the list of items, e.g. ``"emails"``.
        id_field:       Field uniquely identifying an item (used to prove that
                        real items are never altered or removed).
        signal_fields:  The fields a distractor must differ on to count as a
                        genuine *near-miss* rather than an accidental duplicate.
                        These are the "load-bearing" fields a grader is likely to
                        read; a distractor is never allowed to collide with a real
                        item on all of them at once.
        order_field:    Timestamp-like field used to make ``superseded`` noise
                        land *earlier* than the real item it shadows.
        template:       Callable returning a blank, schema-valid item.
    """

    service: str
    collection: str
    id_field: str
    signal_fields: tuple[str, ...]
    order_field: str
    template: Callable[[], dict[str, Any]]
    _registry: "dict[str, Schema]" = field(default=None, repr=False, compare=False)  # type: ignore[assignment]

    @property
    def key(self) -> str:
        return f"{self.service}.{self.collection}"


def _mailhub_template() -> dict[str, Any]:
    # Field set is taken verbatim from the published MailHub sample (Figure 13).
    return {
        "from": "",
        "to": [],
        "subject": "",
        "body": "",
        "timestamp": "",
        "read": False,
        "starred": False,
        "important": False,
        "labels": [],
        "category": "primary",
        "folder": "inbox",
        "attachments": [],  # each: {id, name, size, type, url}
    }


MAILHUB = Schema(
    service="MailHub",
    collection="emails",
    id_field="id",
    # subject+body carry the task-relevant claim; sender/timestamp locate it.
    signal_fields=("subject", "body"),
    order_field="timestamp",
    template=_mailhub_template,
)


# Registry keyed by "Service.collection". Populate the rest from /state-manage.
REGISTRY: dict[str, Schema] = {MAILHUB.key: MAILHUB}


def get_schema(key: str) -> Schema:
    """Look up a schema by ``"Service.collection"`` (e.g. ``"MailHub.emails"``)."""
    try:
        return REGISTRY[key]
    except KeyError:
        known = ", ".join(sorted(REGISTRY)) or "(none)"
        raise KeyError(
            f"No schema registered for {key!r}. Known: {known}. "
            f"Capture it from the service's /state-manage page and add it to schemas.py."
        )
