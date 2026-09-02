from __future__ import annotations

from dataclasses import asdict
from typing import Any

from reconx.application.ingest import ingest_raw_batch
from reconx.application.reconcile import reconcile_batch
from reconx.domain.models import DecisionState


def _score(groups: list[Any], truth_groups: list[dict[str, Any]]) -> dict[str, Any]:
    predictions = {group.settlement_id: group for group in groups}
    auto_groups = [group for group in groups if group.state is DecisionState.AUTO_APPROVED]
    truth_by_id = {item["settlement_id"]: item for item in truth_groups}

    relationship_correct = sum(
        truth_by_id.get(group.settlement_id, {}).get("bank_entry_id") == group.bank_entry_id
        for group in auto_groups
    )
    safe_auto = sum(
        truth_by_id.get(group.settlement_id, {}).get("bank_entry_id") == group.bank_entry_id
        and truth_by_id.get(group.settlement_id, {}).get("should_auto_approve") is True
        for group in auto_groups
    )
    eligible = [item for item in truth_groups if item["should_auto_approve"]]
    correct_eligible_auto = sum(
        (
            item["settlement_id"] in predictions
            and predictions[item["settlement_id"]].state is DecisionState.AUTO_APPROVED
            and predictions[item["settlement_id"]].bank_entry_id == item["bank_entry_id"]
        )
        for item in eligible
    )
    unsafe = [item for item in truth_groups if not item["should_auto_approve"]]
    detected_unsafe = sum(
        item["settlement_id"] not in predictions
        or predictions[item["settlement_id"]].state is not DecisionState.AUTO_APPROVED
        for item in unsafe
    )
    false_matches = len(auto_groups) - relationship_correct
    unsafe_auto = len(auto_groups) - safe_auto

    return {
        "auto_approved": len(auto_groups),
        "eligible_for_auto": len(eligible),
        "auto_match_precision": round(
            relationship_correct / len(auto_groups) if auto_groups else 1.0, 6
        ),
        "safe_auto_precision": round(safe_auto / len(auto_groups) if auto_groups else 1.0, 6),
        "auto_reconciliation_coverage": round(
            correct_eligible_auto / len(eligible) if eligible else 1.0, 6
        ),
        "false_match_rate": round(false_matches / len(auto_groups) if auto_groups else 0.0, 6),
        "unsafe_auto_approval_count": unsafe_auto,
        "unsafe_scenario_detection_recall": round(
            detected_unsafe / len(unsafe) if unsafe else 1.0, 6
        ),
        "review_required": sum(
            group.state is DecisionState.REVIEW_REQUIRED for group in groups
        ),
        "unresolved_groups": sum(group.state is DecisionState.UNRESOLVED for group in groups),
        "missing_groups_after_quarantine": sum(
            item["settlement_id"] not in predictions for item in truth_groups
        ),
    }


def run_evaluation(
    raw_batch: dict[str, Any], ground_truth: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    report = ingest_raw_batch(raw_batch)
    candidate_result = reconcile_batch(report.batch, allow_candidates=True)
    baseline_result = reconcile_batch(report.batch, allow_candidates=False)
    candidate_metrics = _score(candidate_result.groups, ground_truth["groups"])
    baseline_metrics = _score(baseline_result.groups, ground_truth["groups"])

    gate_checks = {
        "at_least_500_raw_records": manifest["raw_record_count"] >= 500,
        "all_22_scenarios_present": manifest["scenario_count"] == 22
        and all(count > 0 for count in manifest["scenario_counts"].values()),
        "zero_false_matches": candidate_metrics["false_match_rate"] == 0.0,
        "zero_unsafe_auto_approvals": candidate_metrics["unsafe_auto_approval_count"] == 0,
        "candidate_coverage_beats_exact_baseline": candidate_metrics[
            "auto_reconciliation_coverage"
        ]
        > baseline_metrics["auto_reconciliation_coverage"],
        "unsafe_detection_recall_is_100_percent": candidate_metrics[
            "unsafe_scenario_detection_recall"
        ]
        == 1.0,
        "quarantine_path_exercised": report.quarantined_record_count > 0,
    }
    return {
        "batch_id": report.batch.batch_id,
        "synthetic": report.batch.synthetic,
        "manifest": manifest,
        "ingestion": report.summary(),
        "candidate_engine": {
            **candidate_metrics,
            "elapsed_ms": candidate_result.elapsed_ms,
            "throughput_records_per_second": candidate_result.to_dict()["metrics"][
                "throughput_records_per_second"
            ],
        },
        "exact_id_baseline": {
            **baseline_metrics,
            "elapsed_ms": baseline_result.elapsed_ms,
            "throughput_records_per_second": baseline_result.to_dict()["metrics"][
                "throughput_records_per_second"
            ],
        },
        "gate_checks": gate_checks,
        "phase_gate_passed": all(gate_checks.values()),
        "scenario_results": [
            {
                **truth,
                "actual_state": next(
                    (
                        group.state.value
                        for group in candidate_result.groups
                        if group.settlement_id == truth["settlement_id"]
                    ),
                    "quarantined",
                ),
                "actual_bank_entry_id": next(
                    (
                        group.bank_entry_id
                        for group in candidate_result.groups
                        if group.settlement_id == truth["settlement_id"]
                    ),
                    None,
                ),
                "actual_confidence": next(
                    (
                        group.confidence
                        for group in candidate_result.groups
                        if group.settlement_id == truth["settlement_id"]
                    ),
                    None,
                ),
                "actual_match_method": next(
                    (
                        group.bank_match_method
                        for group in candidate_result.groups
                        if group.settlement_id == truth["settlement_id"]
                    ),
                    None,
                ),
                "actual_reason_codes": next(
                    (
                        group.reason_codes
                        for group in candidate_result.groups
                        if group.settlement_id == truth["settlement_id"]
                    ),
                    ["GROUP_QUARANTINED"],
                ),
            }
            for truth in ground_truth["groups"]
        ],
        "audit_sample": [asdict(event) for event in candidate_result.audit_events[:3]],
    }
