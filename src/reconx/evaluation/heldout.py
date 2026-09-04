from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter
from typing import Any

from reconx.application.ingest import ingest_raw_batch
from reconx.application.reconcile import policy_contract_hash, reconcile_batch
from reconx.evaluation.runner import run_evaluation


class EvaluationIntegrityError(ValueError):
    pass


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def verify_inputs(
    raw_batch: dict[str, Any], ground_truth: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, bool]:
    sources = (
        "orders",
        "payments",
        "refunds",
        "settlements",
        "settlement_lines",
        "bank_entries",
        "ledger_entries",
    )
    sources_are_lists = all(isinstance(raw_batch.get(source), list) for source in sources)
    actual_source_counts = (
        {source: len(raw_batch[source]) for source in sources} if sources_are_lists else {}
    )
    actual_record_count = sum(actual_source_counts.values()) if sources_are_lists else -1
    truth_groups = ground_truth.get("groups", [])
    truth_is_valid_list = isinstance(truth_groups, list) and all(
        isinstance(item, dict) for item in truth_groups
    )
    truth_ids = [item.get("settlement_id") for item in truth_groups] if truth_is_valid_list else []
    truth_ids_are_valid = all(isinstance(item, str) and item for item in truth_ids)
    scenarios = [item.get("scenario") for item in truth_groups] if truth_is_valid_list else []
    scenarios_are_valid = all(isinstance(item, str) and item for item in scenarios)
    scenario_counts = (
        dict(sorted(Counter(scenarios).items()))
        if truth_is_valid_list and scenarios_are_valid
        else {}
    )
    checks = {
        "raw_batch_hash_matches_manifest": _hash(raw_batch)
        == manifest.get("raw_batch_sha256"),
        "ground_truth_hash_matches_manifest": _hash(ground_truth)
        == manifest.get("ground_truth_sha256"),
        "policy_hash_matches_frozen_contract": policy_contract_hash()
        == manifest.get("policy_contract_sha256"),
        "batch_ids_agree": raw_batch.get("batch_id")
        == ground_truth.get("batch_id")
        == manifest.get("batch_id"),
        "split_is_held_out": manifest.get("split") == "held_out"
        and ground_truth.get("split") == "held_out",
        "source_collections_are_lists": sources_are_lists,
        "manifest_record_count_matches_raw": manifest.get("raw_record_count")
        == actual_record_count,
        "manifest_source_counts_match_raw": manifest.get("source_record_counts")
        == actual_source_counts,
        "manifest_group_count_matches_truth": truth_is_valid_list
        and manifest.get("group_count") == len(truth_groups),
        "truth_settlement_ids_are_unique": truth_ids_are_valid
        and len(truth_ids) == len(set(truth_ids)),
        "truth_scenarios_are_valid": scenarios_are_valid,
        "manifest_scenario_counts_match_truth": manifest.get("scenario_counts")
        == scenario_counts,
        "schema_versions_agree": raw_batch.get("schema_version")
        == ground_truth.get("schema_version")
        == manifest.get("schema_version"),
    }
    if not all(checks.values()):
        failed = ", ".join(name for name, passed in checks.items() if not passed)
        raise EvaluationIntegrityError(f"held-out input integrity failed: {failed}")
    return checks


def _without_timing(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metrics.items()
        if key not in {"elapsed_ms", "throughput_records_per_second"}
    }


def _decision_fingerprint(evaluation: dict[str, Any]) -> str:
    return _hash(
        {
            "candidate_engine": _without_timing(evaluation["candidate_engine"]),
            "exact_id_baseline": _without_timing(evaluation["exact_id_baseline"]),
            "scenario_results": evaluation["scenario_results"],
            "ingestion": evaluation["ingestion"],
            "gate_checks": evaluation["gate_checks"],
        }
    )


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _benchmark(raw_batch: dict[str, Any], *, trials: int, warmups: int = 2) -> dict[str, Any]:
    if trials < 1:
        raise ValueError("benchmark trials must be positive")

    def run_once() -> float:
        started = time.perf_counter()
        report = ingest_raw_batch(raw_batch)
        reconcile_batch(report.batch, allow_candidates=True)
        return time.perf_counter() - started

    for _ in range(warmups):
        run_once()
    elapsed = [run_once() for _ in range(trials)]
    records = sum(
        len(raw_batch.get(source, []))
        for source in (
            "orders",
            "payments",
            "refunds",
            "settlements",
            "settlement_lines",
            "bank_entries",
            "ledger_entries",
        )
    )
    rates = [records / max(seconds, 0.000001) for seconds in elapsed]
    return {
        "scope": "validation_normalisation_and_candidate_reconciliation",
        "warmup_runs": warmups,
        "measured_runs": trials,
        "records_per_run": records,
        "median_records_per_second": round(_percentile(rates, 0.50), 2),
        "p95_records_per_second": round(_percentile(rates, 0.95), 2),
        "slowest_records_per_second": round(min(rates), 2),
        "fastest_records_per_second": round(max(rates), 2),
        "environment_note": "Local single-process result; hardware-dependent, not a service SLO.",
    }


def run_heldout_evaluation(
    raw_batch: dict[str, Any],
    ground_truth: dict[str, Any],
    manifest: dict[str, Any],
    *,
    reproducibility_runs: int = 3,
    benchmark_trials: int = 7,
) -> dict[str, Any]:
    if reproducibility_runs < 2:
        raise ValueError("at least two reproducibility runs are required")
    integrity = verify_inputs(raw_batch, ground_truth, manifest)
    evaluations = [
        run_evaluation(raw_batch, ground_truth, manifest)
        for _ in range(reproducibility_runs)
    ]
    evaluation = evaluations[0]
    decision_hashes = [_decision_fingerprint(item) for item in evaluations]
    reproducible = len(set(decision_hashes)) == 1

    exceptions = [
        {
            "settlement_id": item["settlement_id"],
            "scenario": item["scenario"],
            "state": item["actual_state"],
            "reason_codes": item["actual_reason_codes"],
            "expected_auto_approval": item["should_auto_approve"],
            "expected_bank_entry_id": item["bank_entry_id"],
            "actual_bank_entry_id": item["actual_bank_entry_id"],
        }
        for item in evaluation["scenario_results"]
        if item["actual_state"] != "auto_approved"
    ]
    unexpected_exceptions = [item for item in exceptions if item["expected_auto_approval"]]
    expected_non_auto = sum(
        not item["should_auto_approve"] for item in ground_truth["groups"]
    )
    candidate = evaluation["candidate_engine"]
    baseline = evaluation["exact_id_baseline"]
    correct_auto = sum(
        item["actual_state"] == "auto_approved"
        and item["actual_bank_entry_id"] == item["bank_entry_id"]
        for item in evaluation["scenario_results"]
    )
    all_group_match_rate = round(correct_auto / manifest["group_count"], 6)

    state_counts = Counter(item["state"] for item in exceptions)
    scenario_counts = Counter(item["scenario"] for item in exceptions)
    gate_checks = {
        **integrity,
        "official_record_floor_exceeded": manifest["raw_record_count"] >= 50,
        "all_declared_scenarios_present": manifest["scenario_count"] == 22
        and all(count > 0 for count in manifest["scenario_counts"].values()),
        "decisions_reproduce_across_runs": reproducible,
        "safe_auto_precision_at_least_99_percent": candidate["safe_auto_precision"]
        >= 0.99,
        "zero_false_matches": candidate["false_match_rate"] == 0.0,
        "zero_unsafe_auto_approvals": candidate["unsafe_auto_approval_count"] == 0,
        "eligible_coverage_at_least_90_percent": candidate[
            "auto_reconciliation_coverage"
        ]
        >= 0.90,
        "candidate_beats_exact_id_baseline": candidate[
            "auto_reconciliation_coverage"
        ]
        > baseline["auto_reconciliation_coverage"],
        "no_unexpected_heldout_exceptions": len(unexpected_exceptions) == 0,
        "exception_list_is_complete": len(exceptions) == expected_non_auto,
    }
    deterministic_evidence = {
        "manifest": manifest,
        "candidate_engine": _without_timing(candidate),
        "exact_id_baseline": _without_timing(baseline),
        "scenario_results": evaluation["scenario_results"],
        "exceptions": exceptions,
        "gate_checks": gate_checks,
        "decision_fingerprint": decision_hashes[0],
    }
    return {
        "evaluation": "phase4_heldout",
        "synthetic": True,
        "evaluation_scope": (
            "Public synthetic held-out split with frozen policy; not externally sequestered "
            "and not production data."
        ),
        "manifest": manifest,
        "input_integrity": integrity,
        "ingestion": evaluation["ingestion"],
        "policy_contract_sha256": policy_contract_hash(),
        "decision_reproducibility": {
            "runs": reproducibility_runs,
            "all_equal": reproducible,
            "decision_sha256": decision_hashes[0],
        },
        "business_summary": {
            "raw_records": manifest["raw_record_count"],
            "settlement_groups": manifest["group_count"],
            "correct_automatic_matches": correct_auto,
            "all_group_auto_match_rate": all_group_match_rate,
            "eligible_group_coverage": candidate["auto_reconciliation_coverage"],
            "safe_auto_precision": candidate["safe_auto_precision"],
            "false_matches": int(candidate["false_match_rate"] * candidate["auto_approved"]),
            "exceptions_not_auto_resolved": len(exceptions),
            "unexpected_exceptions": len(unexpected_exceptions),
        },
        "candidate_engine": candidate,
        "exact_id_baseline": baseline,
        "coverage_delta_vs_baseline": round(
            candidate["auto_reconciliation_coverage"]
            - baseline["auto_reconciliation_coverage"],
            6,
        ),
        "throughput": _benchmark(raw_batch, trials=benchmark_trials),
        "exception_summary": {
            "total": len(exceptions),
            "by_state": dict(sorted(state_counts.items())),
            "by_scenario": dict(sorted(scenario_counts.items())),
            "unexpected": len(unexpected_exceptions),
        },
        "exceptions": exceptions,
        "gate_checks": gate_checks,
        "phase_gate_passed": all(gate_checks.values()),
        "deterministic_evidence_sha256": _hash(deterministic_evidence),
    }


def dashboard_payload(report: dict[str, Any]) -> dict[str, Any]:
    """Return the compact, judge-facing projection used by both HTTP adapters."""

    manifest = report["manifest"]
    provenance = manifest["provenance"]
    ingestion = report["ingestion"]
    return {
        "evaluation": report["evaluation"],
        "synthetic": report["synthetic"],
        "evaluation_scope": report["evaluation_scope"],
        "phase_gate_passed": report["phase_gate_passed"],
        "business_summary": report["business_summary"],
        "candidate_engine": report["candidate_engine"],
        "exact_id_baseline": report["exact_id_baseline"],
        "coverage_delta_vs_baseline": report["coverage_delta_vs_baseline"],
        "throughput": report["throughput"],
        "exception_summary": report["exception_summary"],
        "exceptions": report["exceptions"],
        "decision_reproducibility": report["decision_reproducibility"],
        "data_provenance": {
            **provenance,
            "generator_version": manifest["generator_version"],
            "seed": manifest["seed"],
            "scenario_count": manifest["scenario_count"],
            "source_record_counts": manifest["source_record_counts"],
            "validation_summary": {
                key: value for key, value in ingestion.items() if key != "issues"
            },
            "raw_batch_sha256": manifest["raw_batch_sha256"],
            "ground_truth_sha256": manifest["ground_truth_sha256"],
            "input_integrity_verified": all(report["input_integrity"].values()),
        },
        "policy_contract_sha256": report["policy_contract_sha256"],
        "deterministic_evidence_sha256": report["deterministic_evidence_sha256"],
    }
