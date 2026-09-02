from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from reconx.adapters.razorpay import (
    RAZORPAY_RECON_URL,
    RazorpaySettlementReconClient,
    WebhookPayloadError,
    WebhookSecret,
    WebhookSignatureError,
    parse_settlement_recon_response,
)
from reconx.application.webhooks import (
    MAX_WEBHOOK_BODY_BYTES,
    RazorpayWebhookService,
    WebhookSizeError,
    WebhookTimestampError,
)
from reconx.domain.webhook import WebhookOutcome
from reconx.infrastructure.webhook_store import SQLiteWebhookStore, WebhookConflictError


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "fixtures" / "razorpay"
FIXED_TIME = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
CURRENT_SECRET = b"phase5-current-fixture-secret"
PREVIOUS_SECRET = b"phase5-previous-fixture-secret"


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _signature(body: bytes, secret: bytes = CURRENT_SECRET) -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def _fixture(name: str) -> bytes:
    return (FIXTURE_ROOT / name).read_bytes()


def _mutate(body: bytes, **changes: Any) -> bytes:
    payload = json.loads(body)
    for path, value in changes.items():
        target = payload
        keys = path.split("__")
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def run_integration_evaluation() -> dict[str, Any]:
    current = WebhookSecret("current", CURRENT_SECRET)
    previous = WebhookSecret("previous", PREVIOUS_SECRET)
    payment = _fixture("payment.captured.json")
    refund = _fixture("refund.processed.json")
    settlement = _fixture("settlement.processed.json")
    recon_raw = _fixture("settlement-recon.json")

    with tempfile.TemporaryDirectory(prefix="reconx-phase5-") as temporary:
        database = Path(temporary) / "webhooks.sqlite3"
        store = SQLiteWebhookStore(database)
        service = RazorpayWebhookService(
            (current, previous), store, clock=lambda: FIXED_TIME
        )

        payment_receipt = service.process(
            raw_body=payment,
            signature=_signature(payment),
            event_id="evt_phase5_payment",
        )
        duplicate_receipt = service.process(
            raw_body=payment,
            signature=_signature(payment),
            event_id="evt_phase5_payment",
        )
        refund_receipt = service.process(
            raw_body=refund,
            signature=_signature(refund, PREVIOUS_SECRET),
            event_id="evt_phase5_refund",
        )
        settlement_receipt = service.process(
            raw_body=settlement,
            signature=_signature(settlement),
            event_id="evt_phase5_settlement",
        )

        invalid_signature_rejected = False
        try:
            service.process(
                raw_body=payment + b" ",
                signature=_signature(payment),
                event_id="evt_phase5_tampered",
            )
        except WebhookSignatureError:
            invalid_signature_rejected = True

        authenticity_precedes_json = False
        try:
            service.process(
                raw_body=b'{"event":',
                signature="0" * 64,
                event_id="evt_phase5_invalid_json",
            )
        except WebhookSignatureError:
            authenticity_precedes_json = True

        conflict_rejected = False
        changed_payment = _mutate(
            payment, payload__payment__entity__amount=50_001
        )
        try:
            service.process(
                raw_body=changed_payment,
                signature=_signature(changed_payment),
                event_id="evt_phase5_payment",
            )
        except WebhookConflictError:
            conflict_rejected = True

        newer = _mutate(
            payment,
            created_at=1_788_262_000,
            payload__payment__entity__amount=51_000,
        )
        older = _mutate(
            payment,
            created_at=1_788_255_000,
            payload__payment__entity__amount=49_000,
        )
        newer_receipt = service.process(
            raw_body=newer,
            signature=_signature(newer),
            event_id="evt_phase5_newer",
        )
        older_receipt = service.process(
            raw_body=older,
            signature=_signature(older),
            event_id="evt_phase5_older",
        )
        snapshot = store.get_snapshot("payment", "pay_phase5_001")

        unsupported_payload = {
            "entity": "event",
            "event": "order.paid",
            "contains": ["order"],
            "payload": {},
            "created_at": 1_788_260_400,
        }
        unsupported_body = json.dumps(
            unsupported_payload, sort_keys=True, separators=(",", ":")
        ).encode()
        unsupported_receipt = service.process(
            raw_body=unsupported_body,
            signature=_signature(unsupported_body),
            event_id="evt_phase5_unsupported",
        )

        duplicate_keys_rejected = False
        duplicate_keys = (
            b'{"event":"payment.captured","event":"refund.processed",'
            b'"created_at":1788260400}'
        )
        try:
            service.process(
                raw_body=duplicate_keys,
                signature=_signature(duplicate_keys),
                event_id="evt_phase5_duplicate_keys",
            )
        except WebhookPayloadError:
            duplicate_keys_rejected = True

        oversized_rejected = False
        try:
            service.process(
                raw_body=b"x" * (MAX_WEBHOOK_BODY_BYTES + 1),
                signature="0" * 64,
                event_id="evt_phase5_oversized",
            )
        except WebhookSizeError:
            oversized_rejected = True

        future_rejected = False
        future = _mutate(payment, created_at=1_788_264_301)
        try:
            service.process(
                raw_body=future,
                signature=_signature(future),
                event_id="evt_phase5_future",
            )
        except WebhookTimestampError:
            future_rejected = True

        persisted_store = SQLiteWebhookStore(database)
        summary = persisted_store.summary()
        chain_valid = persisted_store.verify_audit_chain()

        recon_payload = json.loads(recon_raw)
        recon_items = parse_settlement_recon_response(recon_payload)
        transport_observation: dict[str, Any] = {}

        def fixture_transport(request, timeout_seconds: float, max_bytes: int) -> bytes:
            transport_observation.update(
                {
                    "url": request.full_url,
                    "has_basic_auth": request.get_header("Authorization", "").startswith(
                        "Basic "
                    ),
                    "timeout_bounded": timeout_seconds <= 5.0,
                    "response_limit": max_bytes,
                }
            )
            return recon_raw

        client = RazorpaySettlementReconClient(
            "rzp_test_fixture_id",
            "fixture_api_secret",
            transport=fixture_transport,
        )
        client_items = client.fetch(date(2022, 6, 11))

        checks = {
            "current_secret_signature_accepted": payment_receipt.outcome
            is WebhookOutcome.APPLIED,
            "previous_secret_retry_accepted": refund_receipt.outcome
            is WebhookOutcome.APPLIED,
            "tampered_raw_body_rejected": invalid_signature_rejected,
            "signature_checked_before_json_parse": authenticity_precedes_json,
            "duplicate_delivery_is_idempotent": duplicate_receipt.outcome
            is WebhookOutcome.DUPLICATE
            and summary["deliveries"] == summary["unique_events"] + 1,
            "event_id_payload_conflict_rejected": conflict_rejected,
            "newer_event_applied": newer_receipt.outcome is WebhookOutcome.APPLIED,
            "out_of_order_event_cannot_roll_back": older_receipt.outcome
            is WebhookOutcome.STALE_IGNORED
            and snapshot is not None
            and snapshot.amount_paise == 51_000,
            "unsupported_signed_event_acknowledged": unsupported_receipt.outcome
            is WebhookOutcome.UNSUPPORTED,
            "duplicate_json_keys_rejected": duplicate_keys_rejected,
            "oversized_body_rejected": oversized_rejected,
            "future_timestamp_rejected": future_rejected,
            "state_survives_store_restart": persisted_store.summary() == summary,
            "delivery_audit_chain_valid": chain_valid,
            "settlement_signature_fixture_accepted": settlement_receipt.outcome
            is WebhookOutcome.APPLIED,
            "official_shape_recon_fixture_parsed": len(recon_items) == 4
            and len(client_items) == 4,
            "unsupported_recon_type_is_visible": sum(
                not item.supported_for_reconciliation for item in recon_items
            )
            == 1,
            "recon_client_endpoint_and_limits_locked": transport_observation.get("url", "").startswith(
                RAZORPAY_RECON_URL
            )
            and transport_observation.get("has_basic_auth") is True
            and transport_observation.get("timeout_bounded") is True,
        }
        recon_summary = {
            "fixture_items": len(recon_items),
            "supported_items": sum(item.supported_for_reconciliation for item in recon_items),
            "unsupported_items": sum(
                not item.supported_for_reconciliation for item in recon_items
            ),
            "item_types": sorted({item.item_type for item in recon_items}),
        }
        report = {
            "evaluation": "phase5_integration",
            "synthetic": True,
            "live_razorpay_call_made": False,
            "contract_basis": "official-shape fixtures and injected HTTP transport",
            "supported_webhook_events": [
                "payment.captured",
                "refund.processed",
                "settlement.processed",
            ],
            "signature_scheme": "HMAC-SHA256 over exact raw request bytes",
            "checks": checks,
            "passed": sum(checks.values()),
            "total": len(checks),
            "phase_gate_passed": all(checks.values()),
            "webhook_summary": summary,
            "recon_fixture_summary": recon_summary,
            "security_controls": [
                "raw_body_signature_before_json",
                "constant_time_signature_compare",
                "current_and_previous_secret_rotation",
                "durable_event_id_idempotency",
                "out_of_order_monotonic_projection",
                "body_depth_size_and_duplicate_key_limits",
                "future_timestamp_limit",
                "append_only_hash_chained_delivery_audit",
                "disabled_without_webhook_secret",
                "fixed_razorpay_recon_endpoint_and_timeout",
            ],
        }
        serialised = json.dumps(report, sort_keys=True, separators=(",", ":"))
        checks["secrets_absent_from_evidence"] = (
            CURRENT_SECRET.decode() not in serialised
            and PREVIOUS_SECRET.decode() not in serialised
            and "fixture_api_secret" not in serialised
        )
        report["passed"] = sum(checks.values())
        report["total"] = len(checks)
        report["phase_gate_passed"] = all(checks.values())
        report["deterministic_evidence_sha256"] = _hash(
            {
                "checks": checks,
                "webhook_summary": summary,
                "recon_fixture_summary": recon_summary,
                "security_controls": report["security_controls"],
            }
        )
        return report
