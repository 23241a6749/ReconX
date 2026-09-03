from __future__ import annotations

import json
import unittest
from dataclasses import replace

from reconx.application.reconcile import reconcile_batch
from reconx.domain.models import DecisionState, Payment
from reconx.synthetic.generator import build_demo_batch


class ReconciliationTests(unittest.TestCase):
    def test_balanced_group_is_auto_approved(self) -> None:
        result = reconcile_batch(build_demo_batch())
        group = result.groups[0]

        self.assertEqual(group.state, DecisionState.AUTO_APPROVED)
        self.assertEqual(group.expected_bank_credit_paise, 682_300)
        self.assertEqual(group.actual_bank_credit_paise, 682_300)
        self.assertEqual(group.difference_paise, 0)
        self.assertEqual(group.confidence, 1.0)
        self.assertIn("MONEY_CONSERVED", group.reason_codes)

    def test_tax_is_reported_but_not_double_subtracted(self) -> None:
        group = reconcile_batch(build_demo_batch()).groups[0]

        self.assertEqual(group.gross_payments_paise, 750_000)
        self.assertEqual(group.refunds_paise, 50_000)
        self.assertEqual(group.inclusive_fees_paise, 17_700)
        self.assertEqual(group.tax_component_paise, 2_700)
        self.assertEqual(
            group.expected_bank_credit_paise,
            group.gross_payments_paise - group.refunds_paise - group.inclusive_fees_paise,
        )

    def test_bank_imbalance_never_auto_approves(self) -> None:
        batch = build_demo_batch()
        batch.bank_entries[0] = replace(batch.bank_entries[0], amount_paise=682_301)

        group = reconcile_batch(batch).groups[0]

        self.assertEqual(group.state, DecisionState.REVIEW_REQUIRED)
        self.assertEqual(group.difference_paise, 1)
        self.assertIn("BANK_AMOUNT_IMBALANCE", group.reason_codes)

    def test_ledger_imbalance_never_auto_approves(self) -> None:
        batch = build_demo_batch()
        batch.ledger_entries[0] = replace(batch.ledger_entries[0], amount_paise=682_301)

        group = reconcile_batch(batch).groups[0]

        self.assertEqual(group.state, DecisionState.REVIEW_REQUIRED)
        self.assertIn("LEDGER_AMOUNT_MISMATCH", group.reason_codes)
        self.assertNotIn("LEDGER_CONFIRMATION_MISSING", group.reason_codes)

    def test_currency_mismatch_is_unresolved(self) -> None:
        batch = build_demo_batch()
        batch.bank_entries[0] = replace(batch.bank_entries[0], currency="USD")

        group = reconcile_batch(batch).groups[0]

        self.assertEqual(group.state, DecisionState.UNRESOLVED)
        self.assertIn("CURRENCY_MISMATCH", group.reason_codes)

    def test_replay_is_decision_deterministic(self) -> None:
        batch = build_demo_batch()
        first = reconcile_batch(batch).to_dict()
        second = reconcile_batch(batch).to_dict()

        first.pop("elapsed_ms")
        second.pop("elapsed_ms")
        first["metrics"].pop("throughput_records_per_second")
        second["metrics"].pop("throughput_records_per_second")
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_unmatched_ledger_is_exposed(self) -> None:
        result = reconcile_batch(build_demo_batch())

        self.assertEqual(len(result.exceptions), 1)
        self.assertEqual(result.exceptions[0].code, "UNMATCHED_LEDGER_ENTRY")
        self.assertEqual(result.exceptions[0].source_record_ids, ["ledger_orphan_01"])

    def test_non_positive_expected_credit_never_auto_approves(self) -> None:
        batch = build_demo_batch()
        batch.refunds[0] = replace(batch.refunds[0], amount_paise=800_000)
        batch.settlement_lines[-1] = replace(batch.settlement_lines[-1], amount_paise=800_000)
        batch.bank_entries[0] = replace(batch.bank_entries[0], amount_paise=-67_700)
        batch.ledger_entries[0] = replace(batch.ledger_entries[0], amount_paise=-67_700)

        group = reconcile_batch(batch).groups[0]

        self.assertEqual(group.state, DecisionState.UNRESOLVED)
        self.assertIn("NON_POSITIVE_EXPECTED_BANK_CREDIT", group.reason_codes)

    def test_refund_must_belong_to_a_payment_in_the_same_settlement(self) -> None:
        batch = build_demo_batch()
        batch.refunds[0] = replace(batch.refunds[0], payment_id="pay_not_in_settlement")

        group = reconcile_batch(batch).groups[0]

        self.assertEqual(group.state, DecisionState.UNRESOLVED)
        self.assertIn("REFUND_PAYMENT_OUTSIDE_SETTLEMENT", group.reason_codes)
        self.assertIn("REFUND_PAYMENT_MISSING_OR_NOT_CAPTURED", group.reason_codes)

    def test_aggregate_refunds_cannot_exceed_the_captured_payment(self) -> None:
        batch = build_demo_batch()
        batch.refunds[0] = replace(batch.refunds[0], amount_paise=450_000)
        batch.settlement_lines[-1] = replace(
            batch.settlement_lines[-1], amount_paise=450_000
        )
        batch.bank_entries[0] = replace(batch.bank_entries[0], amount_paise=282_300)
        batch.ledger_entries[0] = replace(batch.ledger_entries[0], amount_paise=282_300)

        group = reconcile_batch(batch).groups[0]

        self.assertEqual(group.state, DecisionState.UNRESOLVED)
        self.assertIn("REFUND_TOTAL_EXCEEDS_CAPTURED_PAYMENT", group.reason_codes)

    def test_reused_settlement_entity_cannot_form_a_unique_evidence_graph(self) -> None:
        batch = build_demo_batch()
        duplicate = replace(batch.settlement_lines[0], id="line_pay_01_duplicate")
        batch.settlement_lines.append(duplicate)
        batch.bank_entries[0] = replace(batch.bank_entries[0], amount_paise=779_940)
        batch.ledger_entries[0] = replace(batch.ledger_entries[0], amount_paise=779_940)

        group = reconcile_batch(batch).groups[0]

        self.assertEqual(group.state, DecisionState.UNRESOLVED)
        self.assertIn("DUPLICATE_SETTLEMENT_ENTITY_REFERENCE", group.reason_codes)
        self.assertNotIn("UNIQUE_EVIDENCE_GRAPH", group.reason_codes)

    def test_tax_cannot_exceed_fee(self) -> None:
        with self.assertRaisesRegex(ValueError, "tax must be a component of fee"):
            Payment(
                id="pay_bad",
                order_id="order_bad",
                amount_paise=100,
                fee_paise=10,
                tax_paise=11,
                currency="INR",
                status="captured",  # type: ignore[arg-type]
                created_at="2026-08-30T00:00:00Z",
            )

    def test_canonical_batch_round_trip(self) -> None:
        batch = build_demo_batch()
        restored = type(batch).from_dict(batch.to_dict())

        self.assertEqual(restored.to_dict(), batch.to_dict())
        self.assertEqual(restored.source_record_count, 15)


if __name__ == "__main__":
    unittest.main()
