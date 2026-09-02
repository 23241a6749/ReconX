from __future__ import annotations

import json
import unittest

from reconx.application.ingest import ingest_raw_batch
from reconx.evaluation.runner import run_evaluation
from reconx.synthetic.development import Scenario, build_development_dataset


class PhaseTwoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw, cls.manifest, cls.truth = build_development_dataset()
        cls.ingestion = ingest_raw_batch(cls.raw)
        cls.evaluation = run_evaluation(cls.raw, cls.truth, cls.manifest)

    def test_generator_is_reproducible(self) -> None:
        raw_two, manifest_two, truth_two = build_development_dataset()

        self.assertEqual(self.raw, raw_two)
        self.assertEqual(self.truth, truth_two)
        self.assertEqual(self.manifest, manifest_two)
        self.assertEqual(len(self.manifest["raw_batch_sha256"]), 64)
        self.assertEqual(len(self.manifest["ground_truth_sha256"]), 64)

    def test_all_scenarios_and_record_floor_are_present(self) -> None:
        self.assertEqual(self.manifest["scenario_count"], 22)
        self.assertEqual(set(self.manifest["scenario_counts"]), {item.value for item in Scenario})
        self.assertGreaterEqual(self.manifest["raw_record_count"], 500)

    def test_ingestion_deduplicates_and_quarantines(self) -> None:
        issue_codes = {issue.code for issue in self.ingestion.issues}

        self.assertIn("DUPLICATE_RECORD_DEDUPED", issue_codes)
        self.assertIn("CONFLICTING_DUPLICATE_QUARANTINED", issue_codes)
        self.assertIn("SCHEMA_VALIDATION_FAILED", issue_codes)
        self.assertIn("UNSUPPORTED_CURRENCY", issue_codes)
        self.assertGreater(self.ingestion.quarantined_record_count, 0)
        self.assertGreater(self.ingestion.duplicate_record_count, 0)

    def test_phase_gate_passes_without_unsafe_auto_approval(self) -> None:
        candidate = self.evaluation["candidate_engine"]

        self.assertTrue(self.evaluation["phase_gate_passed"])
        self.assertTrue(all(self.evaluation["gate_checks"].values()))
        self.assertEqual(candidate["false_match_rate"], 0.0)
        self.assertEqual(candidate["unsafe_auto_approval_count"], 0)
        self.assertEqual(candidate["safe_auto_precision"], 1.0)

    def test_candidate_policy_beats_exact_id_baseline(self) -> None:
        candidate = self.evaluation["candidate_engine"]
        baseline = self.evaluation["exact_id_baseline"]

        self.assertGreater(
            candidate["auto_reconciliation_coverage"],
            baseline["auto_reconciliation_coverage"],
        )

    def test_missing_utr_is_recovered_but_equal_ambiguity_is_not(self) -> None:
        by_scenario: dict[str, list[dict]] = {}
        for item in self.evaluation["scenario_results"]:
            by_scenario.setdefault(item["scenario"], []).append(item)

        self.assertTrue(
            all(
                item["actual_state"] == "auto_approved"
                for item in by_scenario[Scenario.MISSING_UTR.value]
            )
        )
        self.assertTrue(
            all(
                item["actual_state"] != "auto_approved"
                for item in by_scenario[Scenario.EQUAL_SCORE_AMBIGUITY.value]
            )
        )

    def test_conflicts_and_unsupported_currency_cannot_auto_approve(self) -> None:
        by_scenario = {
            item["scenario"]: item for item in self.evaluation["scenario_results"]
        }

        self.assertNotEqual(
            by_scenario[Scenario.CONFLICTING_DUPLICATE.value]["actual_state"],
            "auto_approved",
        )
        self.assertEqual(
            by_scenario[Scenario.UNSUPPORTED_CURRENCY.value]["actual_state"],
            "quarantined",
        )

    def test_auto_approved_groups_never_reuse_a_bank_entry(self) -> None:
        bank_ids = [
            item["actual_bank_entry_id"]
            for item in self.evaluation["scenario_results"]
            if item["actual_state"] == "auto_approved"
        ]
        self.assertEqual(len(bank_ids), len(set(bank_ids)))

    def test_evaluation_output_is_json_serialisable(self) -> None:
        json.dumps(self.evaluation, sort_keys=True, default=str)


if __name__ == "__main__":
    unittest.main()

