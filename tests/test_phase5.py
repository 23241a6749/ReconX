from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, date, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from reconx.adapters.razorpay import (
    RAZORPAY_RECON_URL,
    RazorpayAdapterError,
    RazorpayApiError,
    RazorpaySettlementReconClient,
    WebhookPayloadError,
    WebhookSecret,
    WebhookSignatureError,
    parse_settlement_recon_response,
    parse_webhook_payload,
    verify_webhook_signature,
)
from reconx.application.bootstrap import build_razorpay_webhook_service
from reconx.application.webhooks import (
    MAX_WEBHOOK_BODY_BYTES,
    RazorpayWebhookService,
    WebhookSizeError,
    WebhookTimestampError,
)
from reconx.domain.webhook import WebhookOutcome
from reconx.evaluation.integration import run_integration_evaluation
from reconx.infrastructure.webhook_store import SQLiteWebhookStore, WebhookConflictError
from reconx.preview import PreviewHandler

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "razorpay"
SECRET = b"phase5-unit-test-secret"
FIXED_TIME = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def sign(body: bytes, secret: bytes = SECRET) -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def changed_payment(*, created_at: int, amount: int) -> bytes:
    payload = json.loads(fixture("payment.captured.json"))
    payload["created_at"] = created_at
    payload["payload"]["payment"]["entity"]["amount"] = amount
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


class RazorpayWebhookAdapterTests(unittest.TestCase):
    def test_signature_covers_exact_raw_bytes_and_supports_rotation(self) -> None:
        body = fixture("payment.captured.json")
        secrets = (
            WebhookSecret("current", SECRET),
            WebhookSecret("previous", b"previous-secret"),
        )

        self.assertEqual(verify_webhook_signature(body, sign(body), secrets), "current")
        previous_signature = sign(body, b"previous-secret")
        self.assertEqual(
            verify_webhook_signature(body, previous_signature, secrets), "previous"
        )
        with self.assertRaises(WebhookSignatureError):
            verify_webhook_signature(body + b"\n", sign(body), secrets)

    def test_parser_minimises_data_and_rejects_duplicate_keys(self) -> None:
        payload = json.loads(fixture("payment.captured.json"))
        entity = payload["payload"]["payment"]["entity"]
        entity.update({"email": "not-stored@example.com", "contact": "+910000000000"})
        raw = json.dumps(payload).encode()

        parsed = parse_webhook_payload(raw)

        self.assertEqual(parsed.data, {"order_id": "order_phase5_001"})
        self.assertNotIn("email", json.dumps(parsed.data))
        with self.assertRaises(WebhookPayloadError):
            parse_webhook_payload(
                b'{"event":"payment.captured","event":"refund.processed",'
                b'"created_at":1788260400}'
            )


class DurableDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="reconx-phase5-tests-")
        self.path = Path(self.temporary.name) / "webhooks.sqlite3"
        self.store = SQLiteWebhookStore(self.path)
        self.service = RazorpayWebhookService(
            (WebhookSecret("current", SECRET),),
            self.store,
            clock=lambda: FIXED_TIME,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_atomic_idempotency_under_concurrent_retries(self) -> None:
        body = fixture("payment.captured.json")

        def deliver(_: int):
            return self.service.process(
                raw_body=body,
                signature=sign(body),
                event_id="evt_concurrent_retry",
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(deliver, range(12)))

        self.assertEqual(
            sum(receipt.outcome is WebhookOutcome.APPLIED for receipt in receipts), 1
        )
        self.assertEqual(
            sum(receipt.outcome is WebhookOutcome.DUPLICATE for receipt in receipts), 11
        )
        summary = self.store.summary()
        self.assertEqual(summary["unique_events"], 1)
        self.assertEqual(summary["deliveries"], 12)
        self.assertEqual(summary["audit_events"], 12)
        self.assertTrue(self.store.verify_audit_chain())

    def test_same_event_id_with_changed_body_is_rejected(self) -> None:
        original = fixture("payment.captured.json")
        changed = changed_payment(created_at=1_788_256_800, amount=50_001)
        self.service.process(
            raw_body=original,
            signature=sign(original),
            event_id="evt_conflict",
        )

        with self.assertRaises(WebhookConflictError):
            self.service.process(
                raw_body=changed,
                signature=sign(changed),
                event_id="evt_conflict",
            )
        self.assertEqual(self.store.summary()["unique_events"], 1)

    def test_out_of_order_and_equal_timestamp_projection_is_deterministic(self) -> None:
        newer = changed_payment(created_at=1_788_262_000, amount=51_000)
        older = changed_payment(created_at=1_788_255_000, amount=49_000)
        self.service.process(raw_body=newer, signature=sign(newer), event_id="evt_newer")
        stale = self.service.process(
            raw_body=older, signature=sign(older), event_id="evt_older"
        )

        self.assertEqual(stale.outcome, WebhookOutcome.STALE_IGNORED)
        snapshot = self.store.get_snapshot("payment", "pay_phase5_001")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.amount_paise, 51_000)

        first_path = Path(self.temporary.name) / "tie-first.sqlite3"
        second_path = Path(self.temporary.name) / "tie-second.sqlite3"
        event_a = changed_payment(created_at=1_788_260_000, amount=52_000)
        event_b = changed_payment(created_at=1_788_260_000, amount=53_000)
        for path, order in (
            (first_path, (("evt_a", event_a), ("evt_b", event_b))),
            (second_path, (("evt_b", event_b), ("evt_a", event_a))),
        ):
            service = RazorpayWebhookService(
                (WebhookSecret("current", SECRET),),
                SQLiteWebhookStore(path),
                clock=lambda: FIXED_TIME,
            )
            for event_id, body in order:
                service.process(raw_body=body, signature=sign(body), event_id=event_id)
        first = SQLiteWebhookStore(first_path).get_snapshot("payment", "pay_phase5_001")
        second = SQLiteWebhookStore(second_path).get_snapshot("payment", "pay_phase5_001")
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.event_id, "evt_b")

    def test_size_future_time_and_signature_before_parse_are_enforced(self) -> None:
        with self.assertRaises(WebhookSizeError):
            self.service.process(
                raw_body=b"x" * (MAX_WEBHOOK_BODY_BYTES + 1),
                signature="0" * 64,
                event_id="evt_large",
            )
        with self.assertRaises(WebhookSignatureError):
            self.service.process(
                raw_body=b'{"event":',
                signature="0" * 64,
                event_id="evt_bad_json",
            )
        future = changed_payment(created_at=1_788_264_301, amount=50_000)
        with self.assertRaises(WebhookTimestampError):
            self.service.process(
                raw_body=future,
                signature=sign(future),
                event_id="evt_future",
            )

    def test_state_survives_repository_restart(self) -> None:
        body = fixture("settlement.processed.json")
        self.service.process(raw_body=body, signature=sign(body), event_id="evt_persist")

        reopened = SQLiteWebhookStore(self.path)

        self.assertEqual(reopened.summary()["unique_events"], 1)
        self.assertIsNotNone(reopened.get_snapshot("settlement", "setl_phase5_001"))
        self.assertTrue(reopened.verify_audit_chain())


class SettlementReconAdapterTests(unittest.TestCase):
    def test_official_shape_fixture_and_client_contract(self) -> None:
        raw = fixture("settlement-recon.json")
        observed: dict[str, object] = {}

        def transport(request, timeout_seconds: float, max_bytes: int) -> bytes:
            observed["url"] = request.full_url
            observed["auth"] = request.get_header("Authorization", "")
            observed["timeout"] = timeout_seconds
            observed["limit"] = max_bytes
            return raw

        client = RazorpaySettlementReconClient(
            "rzp_test_unit", "unit-secret", transport=transport, timeout_seconds=99
        )
        items = client.fetch(date(2022, 6, 11))

        self.assertEqual(len(items), 4)
        self.assertEqual(sum(item.supported_for_reconciliation for item in items), 3)
        transfer = next(item for item in items if item.item_type == "transfer")
        self.assertIn("UNSUPPORTED_RECON_ITEM_TYPE", transfer.validation_codes)
        self.assertTrue(str(observed["url"]).startswith(RAZORPAY_RECON_URL))
        self.assertTrue(str(observed["auth"]).startswith("Basic "))
        self.assertEqual(observed["timeout"], 5.0)

    def test_recon_contract_quarantines_money_mismatch_and_rejects_bad_count(self) -> None:
        payload = json.loads(fixture("settlement-recon.json"))
        mismatch = deepcopy(payload)
        mismatch["items"][0]["credit"] += 1
        parsed = parse_settlement_recon_response(mismatch)
        self.assertFalse(parsed[0].supported_for_reconciliation)
        self.assertIn("PAYMENT_NET_CREDIT_MISMATCH", parsed[0].validation_codes)

        payload["count"] = 99
        with self.assertRaises(RazorpayAdapterError):
            parse_settlement_recon_response(payload)

    def test_api_errors_are_sanitised(self) -> None:
        def failing_transport(request, timeout_seconds: float, max_bytes: int) -> bytes:
            raise RuntimeError("unit-secret should never appear")

        client = RazorpaySettlementReconClient(
            "rzp_test_unit", "unit-secret", transport=failing_transport
        )
        with self.assertRaises(RazorpayApiError) as caught:
            client.fetch(date(2022, 6, 11))
        self.assertNotIn("unit-secret", str(caught.exception))


class WebhookHttpTests(unittest.TestCase):
    def test_dependency_free_http_receiver_accepts_and_deduplicates_signed_event(self) -> None:
        body = fixture("payment.captured.json")
        with tempfile.TemporaryDirectory(prefix="reconx-phase5-http-") as temporary:
            environment = {
                "RAZORPAY_WEBHOOK_SECRET": SECRET.decode(),
                "RAZORPAY_WEBHOOK_PREVIOUS_SECRET": "",
                "RECONX_WEBHOOK_DB": str(Path(temporary) / "http.sqlite3"),
            }
            with patch.dict(os.environ, environment, clear=False):
                build_razorpay_webhook_service.cache_clear()
                server = ThreadingHTTPServer(("127.0.0.1", 0), PreviewHandler)
                thread = Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    url = f"http://127.0.0.1:{server.server_port}/api/webhooks/razorpay"
                    outcomes = []
                    for _ in range(2):
                        request = Request(
                            url,
                            data=body,
                            headers={
                                "Content-Type": "application/json",
                                "X-Razorpay-Signature": sign(body),
                                "X-Razorpay-Event-Id": "evt_http_phase5",
                            },
                            method="POST",
                        )
                        with urlopen(request, timeout=10) as response:
                            outcomes.append(json.loads(response.read())["receipt"]["outcome"])
                    self.assertEqual(outcomes, ["applied", "duplicate"])

                    invalid = Request(
                        url,
                        data=body,
                        headers={
                            "X-Razorpay-Signature": "0" * 64,
                            "X-Razorpay-Event-Id": "evt_http_invalid",
                        },
                        method="POST",
                    )
                    with self.assertRaises(HTTPError) as caught:
                        urlopen(invalid, timeout=10)
                    self.assertEqual(caught.exception.code, 401)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)
                    build_razorpay_webhook_service.cache_clear()


class IntegrationEvidenceTests(unittest.TestCase):
    def test_phase5_integration_gate_is_reproducible(self) -> None:
        first = run_integration_evaluation()
        second = run_integration_evaluation()

        self.assertTrue(first["phase_gate_passed"])
        self.assertEqual(first["passed"], first["total"])
        self.assertEqual(first["total"], 19)
        self.assertEqual(
            first["deterministic_evidence_sha256"],
            second["deterministic_evidence_sha256"],
        )
        self.assertFalse(first["live_razorpay_call_made"])


if __name__ == "__main__":
    unittest.main()
