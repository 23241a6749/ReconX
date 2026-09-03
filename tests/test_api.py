from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # Keeps the dependency-free domain test command usable.
    TestClient = None  # type: ignore[assignment,misc]


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "razorpay"
WEBHOOK_SECRET = "api-contract-test-secret"


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed")
class FastApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="reconx-api-tests-")
        runtime = Path(cls.temporary.name)
        cls.environment = patch.dict(
            os.environ,
            {
                "ENABLE_LLM": "false",
                "ENABLE_RAZORPAY_IMPORT": "false",
                "RAZORPAY_WEBHOOK_SECRET": WEBHOOK_SECRET,
                "RAZORPAY_WEBHOOK_PREVIOUS_SECRET": "",
                "RECONX_REVIEW_DB": str(runtime / "reviews.sqlite3"),
                "RECONX_WEBHOOK_DB": str(runtime / "webhooks.sqlite3"),
            },
            clear=False,
        )
        cls.environment.start()

        from reconx.application.bootstrap import (
            build_demo_review_service,
            build_exception_analyst,
            build_integration_dashboard,
            build_razorpay_webhook_service,
        )

        for cached_builder in (
            build_demo_review_service,
            build_exception_analyst,
            build_integration_dashboard,
            build_razorpay_webhook_service,
        ):
            cached_builder.cache_clear()

        import reconx.api as api_module

        api_module.review_service = build_demo_review_service()
        cls.api_module = api_module
        cls.client = TestClient(api_module.app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        cls.environment.stop()
        cls.temporary.cleanup()

    def test_public_ui_health_and_evidence_endpoints(self) -> None:
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        root = self.client.get("/")
        self.assertEqual(root.status_code, 200)
        self.assertIn("Every rupee, traced", root.text)
        self.assertEqual(root.headers["x-content-type-options"], "nosniff")
        self.assertEqual(root.headers["x-frame-options"], "DENY")
        self.assertIn("default-src 'self'", root.headers["content-security-policy"])
        self.assertEqual(self.client.get("/assets/app.js").status_code, 200)

        demo = self.client.get("/api/demo").json()
        self.assertEqual(demo["groups"][0]["state"], "auto_approved")
        self.assertTrue(self.client.get("/api/evaluation").json()["phase_gate_passed"])

        heldout = self.client.get("/api/heldout").json()
        self.assertTrue(heldout["phase_gate_passed"])
        self.assertEqual(heldout["business_summary"]["raw_records"], 1_400)
        self.assertEqual(len(heldout["exceptions"]), 45)

        reconciled = self.client.get("/api/reconcile/heldout").json()
        # Five deliberately malformed settlement groups are quarantined before
        # deterministic reconciliation; the held-out report still accounts for all 110.
        self.assertEqual(reconciled["metrics"]["group_count"], 105)
        self.assertEqual(reconciled["metrics"]["auto_approved"], 65)

        close_pack = self.client.get("/api/close-pack/heldout")
        self.assertEqual(close_pack.status_code, 200)
        self.assertIn("attachment", close_pack.headers["content-disposition"])
        self.assertEqual(len(close_pack.json()["evidence_sha256"]), 64)

        integration = self.client.get("/api/integration").json()
        self.assertEqual((integration["passed"], integration["total"]), (19, 19))
        self.assertTrue(integration["runtime"]["webhook_configured"])

        reviews = self.client.get("/api/reviews").json()
        self.assertEqual(len(reviews["cases"]), 40)
        self.assertEqual(reviews["runtime"]["mode"], "deterministic_fallback")

    def test_import_to_close_and_validation_errors(self) -> None:
        payload = {
            "batch_id": "api_import_contract",
            "synthetic": True,
            "razorpay_recon": json.loads(
                (FIXTURES / "settlement-recon-close-demo.json").read_text()
            ),
            "bank_csv": (
                "id,utr,amount_paise,currency,value_date,narration\n"
                "bank_1,1568176960vxp0rj,97100,INR,2019-09-11,RAZORPAY SETTLEMENT\n"
            ),
            "ledger_csv": (
                "id,reference,amount_paise,currency,booked_at\n"
                "ledger_1,setl_DGlQ1Rj8os78Ec,97100,INR,2019-09-11T12:00:00+00:00\n"
            ),
        }

        imported = self.client.post("/api/import/reconcile", json=payload)
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.json()["result"]["metrics"]["auto_approved"], 1)
        self.assertEqual(len(imported.json()["import_issues"]), 1)

        payload["bank_csv"] = "id,utr\nbank_1,utr\n"
        invalid = self.client.post("/api/import/reconcile", json=payload)
        self.assertEqual(invalid.status_code, 422)
        self.assertIn("missing columns", invalid.json()["detail"])

        self.assertEqual(
            self.client.post("/api/reconcile", json={"schema_version": "wrong"}).status_code,
            422,
        )
        self.assertEqual(
            self.client.post("/api/import/razorpay/2026-09-01").status_code,
            503,
        )

    def test_review_analysis_and_versioned_decision(self) -> None:
        case = self.client.get("/api/reviews").json()["cases"][0]
        analysed = self.client.post(
            f"/api/reviews/{case['id']}/analyse",
            json={"actor": "api-test", "expected_version": case["version"]},
        )
        self.assertEqual(analysed.status_code, 200)
        updated = analysed.json()["case"]
        self.assertEqual(updated["version"], case["version"] + 1)
        self.assertEqual(updated["deterministic_state"], case["deterministic_state"])

        stale = self.client.post(
            f"/api/reviews/{case['id']}/decision",
            json={
                "action": "approve",
                "actor": "api-test",
                "reason": "Regression test evidence was reviewed.",
                "expected_version": case["version"],
            },
        )
        self.assertEqual(stale.status_code, 409)

        decided = self.client.post(
            f"/api/reviews/{case['id']}/decision",
            json={
                "action": "reject",
                "actor": "api-test",
                "reason": "Regression test evidence remains incomplete.",
                "expected_version": updated["version"],
            },
        )
        self.assertEqual(decided.status_code, 200)
        self.assertEqual(decided.json()["case"]["status"], "rejected")

    def test_signed_webhook_endpoint_applies_once(self) -> None:
        body = (FIXTURES / "payment.captured.json").read_bytes()
        signature = hmac.new(
            WEBHOOK_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Razorpay-Signature": signature,
            "X-Razorpay-Event-Id": "evt_fastapi_contract",
        }

        first = self.client.post("/api/webhooks/razorpay", content=body, headers=headers)
        second = self.client.post("/api/webhooks/razorpay", content=body, headers=headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["receipt"]["outcome"], "applied")
        self.assertEqual(second.json()["receipt"]["outcome"], "duplicate")

        invalid_headers = {
            **headers,
            "X-Razorpay-Signature": "0" * 64,
            "X-Razorpay-Event-Id": "evt_fastapi_invalid",
        }
        self.assertEqual(
            self.client.post(
                "/api/webhooks/razorpay", content=body, headers=invalid_headers
            ).status_code,
            401,
        )


if __name__ == "__main__":
    unittest.main()
