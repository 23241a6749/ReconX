from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from reconx.adapters.razorpay import (
    WebhookPayloadError,
    WebhookSecret,
    parse_webhook_payload,
    validate_event_id,
    verify_webhook_signature,
)
from reconx.domain.webhook import WebhookReceipt
from reconx.infrastructure.webhook_store import SQLiteWebhookStore

MAX_WEBHOOK_BODY_BYTES = 262_144
MAX_FUTURE_SKEW_SECONDS = 300


class WebhookSizeError(ValueError):
    pass


class WebhookTimestampError(ValueError):
    pass


class RazorpayWebhookService:
    def __init__(
        self,
        secrets: tuple[WebhookSecret, ...],
        store: SQLiteWebhookStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.secrets = secrets
        self.store = store
        self.clock = clock

    def process(self, *, raw_body: bytes, signature: str, event_id: str) -> WebhookReceipt:
        if not isinstance(raw_body, bytes) or not raw_body:
            raise WebhookPayloadError("webhook request body must be non-empty bytes")
        if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
            raise WebhookSizeError("webhook request body exceeds 256 KiB")
        valid_event_id = validate_event_id(event_id)

        # Authenticity is established before any JSON parsing or field access.
        signature_key_id = verify_webhook_signature(raw_body, signature, self.secrets)
        event = parse_webhook_payload(raw_body)
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("webhook clock must be timezone-aware")
        if event.event_created_at > int(now.timestamp()) + MAX_FUTURE_SKEW_SECONDS:
            raise WebhookTimestampError("webhook created_at is too far in the future")
        received_at = now.isoformat().replace("+00:00", "Z")
        payload_sha256 = hashlib.sha256(raw_body).hexdigest()
        return self.store.record(
            event_id=valid_event_id,
            event=event,
            payload_sha256=payload_sha256,
            signature_key_id=signature_key_id,
            received_at=received_at,
        )
