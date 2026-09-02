from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class WebhookOutcome(StrEnum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    STALE_IGNORED = "stale_ignored"
    UNSUPPORTED = "unsupported"


@dataclass(slots=True, frozen=True)
class NormalizedRazorpayEvent:
    event_type: str
    event_created_at: int
    entity_type: str | None
    entity_id: str | None
    entity_status: str | None
    amount_paise: int | None
    currency: str | None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class WebhookReceipt:
    event_id: str
    event_type: str
    outcome: WebhookOutcome
    entity_type: str | None
    entity_id: str | None
    event_created_at: int
    payload_sha256: str
    duplicate: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "outcome": self.outcome.value,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "event_created_at": self.event_created_at,
            "payload_sha256": self.payload_sha256,
            "duplicate": self.duplicate,
        }


@dataclass(slots=True, frozen=True)
class EntitySnapshot:
    entity_type: str
    entity_id: str
    event_type: str
    event_id: str
    event_created_at: int
    entity_status: str | None
    amount_paise: int | None
    currency: str | None
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "event_type": self.event_type,
            "event_id": self.event_id,
            "event_created_at": self.event_created_at,
            "entity_status": self.entity_status,
            "amount_paise": self.amount_paise,
            "currency": self.currency,
            "data": self.data,
        }
