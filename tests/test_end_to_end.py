from __future__ import annotations

import json
import unittest
from pathlib import Path

from reconx.application.close_pack import build_close_pack
from reconx.application.imports import ImportValidationError, import_reconciliation_inputs
from reconx.application.reconcile import reconcile_batch

ROOT = Path(__file__).resolve().parents[1]


class ImportToCloseTests(unittest.TestCase):
    def payload(self) -> dict:
        recon = json.loads(
            (ROOT / "fixtures" / "razorpay" / "settlement-recon-close-demo.json").read_text()
        )
        return {
            "batch_id": "import_contract_test",
            "synthetic": True,
            "razorpay_recon": recon,
            "bank_csv": (
                "id,utr,amount_paise,currency,value_date,narration\n"
                "bank_1,1568176960vxp0rj,97100,INR,2019-09-11,RAZORPAY SETTLEMENT\n"
            ),
            "ledger_csv": (
                "id,reference,amount_paise,currency,booked_at\n"
                "ledger_1,setl_DGlQ1Rj8os78Ec,97100,INR,2019-09-11T12:00:00+00:00\n"
            ),
        }

    def test_official_recon_and_csv_evidence_reach_auditable_close_pack(self) -> None:
        batch, issues = import_reconciliation_inputs(self.payload())
        result = reconcile_batch(batch)
        pack = build_close_pack(result)

        self.assertEqual(len(issues), 1)
        self.assertIn("UNSUPPORTED_RECON_ITEM_TYPE", issues[0]["codes"])
        self.assertEqual(result.groups[0].state.value, "auto_approved")
        self.assertEqual(pack["summary"]["auto_closed_groups"], 1)
        self.assertEqual(len(pack["evidence_sha256"]), 64)
        self.assertFalse(pack["controls"]["accounting_post_performed"])

    def test_import_rejects_missing_csv_columns(self) -> None:
        payload = self.payload()
        payload["bank_csv"] = "id,utr\nbank_1,utr\n"

        with self.assertRaises(ImportValidationError):
            import_reconciliation_inputs(payload)


if __name__ == "__main__":
    unittest.main()
