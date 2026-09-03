from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from reconx.application.reconcile import policy_contract, policy_contract_hash
from reconx.evaluation.heldout import (
    EvaluationIntegrityError,
    dashboard_payload,
    run_heldout_evaluation,
    verify_inputs,
)
from reconx.synthetic.development import build_development_dataset
from reconx.synthetic.heldout import build_heldout_dataset

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "orders",
    "payments",
    "refunds",
    "settlements",
    "settlement_lines",
    "bank_entries",
    "ledger_entries",
)


class PhaseFourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw, cls.manifest, cls.truth = build_heldout_dataset()
        cls.evaluation = run_heldout_evaluation(
            cls.raw,
            cls.truth,
            cls.manifest,
            reproducibility_runs=3,
            benchmark_trials=2,
        )

    def test_runtime_policy_matches_frozen_artifact(self) -> None:
        frozen = json.loads(
            (ROOT / "policies" / "reconciliation-policy-v2.2.json").read_text()
        )

        self.assertEqual(frozen, policy_contract())
        self.assertEqual(self.manifest["policy_contract_sha256"], policy_contract_hash())

    def test_heldout_generator_is_reproducible_and_distinct(self) -> None:
        raw_two, manifest_two, truth_two = build_heldout_dataset()
        development, _, _ = build_development_dataset()
        heldout_ids = {
            record["id"]
            for source in SOURCES
            for record in self.raw[source]
            if isinstance(record, dict) and "id" in record
        }
        development_ids = {
            record["id"]
            for source in SOURCES
            for record in development[source]
            if isinstance(record, dict) and "id" in record
        }

        self.assertEqual(self.raw, raw_two)
        self.assertEqual(self.manifest, manifest_two)
        self.assertEqual(self.truth, truth_two)
        self.assertTrue(heldout_ids.isdisjoint(development_ids))
        self.assertEqual(self.manifest["namespace"], "hold")
        self.assertEqual(self.manifest["raw_record_count"], 1400)
        self.assertEqual(self.manifest["group_count"], 110)
        self.assertEqual(set(self.manifest["scenario_counts"].values()), {5})

    def test_input_hashes_reject_ground_truth_or_record_tampering(self) -> None:
        self.assertTrue(all(verify_inputs(self.raw, self.truth, self.manifest).values()))
        changed = copy.deepcopy(self.raw)
        changed["bank_entries"][0]["amount_paise"] += 1

        with self.assertRaises(EvaluationIntegrityError):
            verify_inputs(changed, self.truth, self.manifest)

        changed_manifest = copy.deepcopy(self.manifest)
        changed_manifest["raw_record_count"] += 1
        with self.assertRaises(EvaluationIntegrityError):
            verify_inputs(self.raw, self.truth, changed_manifest)

        malformed_truth = copy.deepcopy(self.truth)
        malformed_truth["groups"][0].pop("scenario")
        with self.assertRaises(EvaluationIntegrityError):
            verify_inputs(self.raw, malformed_truth, self.manifest)

    def test_heldout_gate_passes_with_honest_metrics(self) -> None:
        summary = self.evaluation["business_summary"]

        self.assertTrue(self.evaluation["phase_gate_passed"])
        self.assertTrue(all(self.evaluation["gate_checks"].values()))
        self.assertEqual(summary["correct_automatic_matches"], 65)
        self.assertEqual(summary["safe_auto_precision"], 1.0)
        self.assertEqual(summary["eligible_group_coverage"], 1.0)
        self.assertEqual(summary["false_matches"], 0)
        self.assertEqual(summary["exceptions_not_auto_resolved"], 45)
        self.assertEqual(summary["unexpected_exceptions"], 0)

    def test_candidate_beats_baseline_without_hiding_exceptions(self) -> None:
        candidate = self.evaluation["candidate_engine"]
        baseline = self.evaluation["exact_id_baseline"]

        self.assertGreater(
            candidate["auto_reconciliation_coverage"],
            baseline["auto_reconciliation_coverage"],
        )
        self.assertEqual(len(self.evaluation["exceptions"]), 45)
        self.assertTrue(
            all(not item["expected_auto_approval"] for item in self.evaluation["exceptions"])
        )
        self.assertEqual(self.evaluation["exception_summary"]["unexpected"], 0)

    def test_decision_evidence_hash_excludes_hardware_timing(self) -> None:
        repeated = run_heldout_evaluation(
            self.raw,
            self.truth,
            self.manifest,
            reproducibility_runs=2,
            benchmark_trials=1,
        )

        self.assertEqual(
            self.evaluation["deterministic_evidence_sha256"],
            repeated["deterministic_evidence_sha256"],
        )
        self.assertTrue(repeated["decision_reproducibility"]["all_equal"])

    def test_dashboard_projection_keeps_core_proof_and_exception_list(self) -> None:
        payload = dashboard_payload(self.evaluation)

        self.assertTrue(payload["phase_gate_passed"])
        self.assertEqual(payload["business_summary"]["raw_records"], 1400)
        self.assertEqual(len(payload["exceptions"]), 45)
        self.assertEqual(len(payload["policy_contract_sha256"]), 64)
        self.assertEqual(len(payload["deterministic_evidence_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
