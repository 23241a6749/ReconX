from __future__ import annotations

import argparse
import json
from pathlib import Path

from reconx.application.reconcile import reconcile_batch
from reconx.domain.models import FinanceBatch
from reconx.evaluation.heldout import run_heldout_evaluation
from reconx.evaluation.integration import run_integration_evaluation
from reconx.evaluation.runner import run_evaluation
from reconx.evaluation.safety import run_safety_evaluation
from reconx.synthetic.development import build_development_dataset
from reconx.synthetic.generator import build_demo_batch
from reconx.synthetic.heldout import build_heldout_dataset


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def _generate(output: Path) -> None:
    batch = build_demo_batch()
    _write_json(output, batch.to_dict())
    print(f"Generated {batch.source_record_count} synthetic records at {output}")


def _reconcile(input_path: Path, output: Path | None) -> None:
    batch = FinanceBatch.from_dict(json.loads(input_path.read_text()))
    result = reconcile_batch(batch).to_dict()
    if output:
        _write_json(output, result)
        print(f"Reconciliation result written to {output}")
    print(json.dumps(result["metrics"], indent=2, sort_keys=True))


def _generate_development(output_dir: Path, groups: int, seed: int) -> None:
    raw, manifest, ground_truth = build_development_dataset(group_count=groups, seed=seed)
    _write_json(output_dir / "raw-batch.json", raw)
    _write_json(output_dir / "manifest.json", manifest)
    _write_json(output_dir / "ground-truth.json", ground_truth)
    print(
        f"Generated {manifest['raw_record_count']} raw records across "
        f"{manifest['scenario_count']} scenarios at {output_dir}"
    )


def _evaluate_development(input_dir: Path, output: Path) -> None:
    raw = json.loads((input_dir / "raw-batch.json").read_text())
    manifest = json.loads((input_dir / "manifest.json").read_text())
    ground_truth = json.loads((input_dir / "ground-truth.json").read_text())
    result = run_evaluation(raw, ground_truth, manifest)
    _write_json(output, result)
    summary = {
        "phase_gate_passed": result["phase_gate_passed"],
        "raw_records": result["manifest"]["raw_record_count"],
        "candidate_coverage": result["candidate_engine"]["auto_reconciliation_coverage"],
        "baseline_coverage": result["exact_id_baseline"]["auto_reconciliation_coverage"],
        "safe_auto_precision": result["candidate_engine"]["safe_auto_precision"],
        "quarantined": result["ingestion"]["quarantined_record_count"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


def _evaluate_safety(output: Path) -> None:
    result = run_safety_evaluation()
    _write_json(output, result)
    print(
        json.dumps(
            {
                "phase_gate_passed": result["phase_gate_passed"],
                "passed": result["passed"],
                "total": result["total"],
                "model_authority": result["model_authority"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def _generate_heldout(output_dir: Path, groups: int, seed: int) -> None:
    raw, manifest, ground_truth = build_heldout_dataset(group_count=groups, seed=seed)
    _write_json(output_dir / "raw-batch.json", raw)
    _write_json(output_dir / "manifest.json", manifest)
    _write_json(output_dir / "ground-truth.json", ground_truth)
    print(
        f"Generated {manifest['raw_record_count']} held-out raw records across "
        f"{manifest['group_count']} groups at {output_dir}"
    )


def _evaluate_heldout(input_dir: Path, output: Path) -> None:
    raw = json.loads((input_dir / "raw-batch.json").read_text())
    manifest = json.loads((input_dir / "manifest.json").read_text())
    ground_truth = json.loads((input_dir / "ground-truth.json").read_text())
    result = run_heldout_evaluation(raw, ground_truth, manifest)
    _write_json(output, result)
    summary = {
        "phase_gate_passed": result["phase_gate_passed"],
        "raw_records": result["business_summary"]["raw_records"],
        "settlement_groups": result["business_summary"]["settlement_groups"],
        "safe_auto_precision": result["business_summary"]["safe_auto_precision"],
        "eligible_coverage": result["business_summary"]["eligible_group_coverage"],
        "baseline_coverage": result["exact_id_baseline"]["auto_reconciliation_coverage"],
        "exceptions": result["business_summary"]["exceptions_not_auto_resolved"],
        "unexpected_exceptions": result["business_summary"]["unexpected_exceptions"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


def _evaluate_integration(output: Path) -> None:
    result = run_integration_evaluation()
    _write_json(output, result)
    print(
        json.dumps(
            {
                "phase_gate_passed": result["phase_gate_passed"],
                "passed": result["passed"],
                "total": result["total"],
                "unique_events": result["webhook_summary"]["unique_events"],
                "recon_fixture_items": result["recon_fixture_summary"]["fixture_items"],
                "live_razorpay_call_made": result["live_razorpay_call_made"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reconx")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="generate the deterministic demo batch")
    generate.add_argument("--output", type=Path, required=True)

    reconcile = subparsers.add_parser("reconcile", help="reconcile a canonical JSON batch")
    reconcile.add_argument("input", type=Path)
    reconcile.add_argument("--output", type=Path)

    development = subparsers.add_parser(
        "generate-development", help="generate the deterministic Phase 2 dataset"
    )
    development.add_argument("--output-dir", type=Path, required=True)
    development.add_argument("--groups", type=int, default=66)
    development.add_argument("--seed", type=int, default=20_260_830)

    evaluate = subparsers.add_parser(
        "evaluate-development", help="evaluate Phase 2 data against frozen ground truth"
    )
    evaluate.add_argument("input_dir", type=Path)
    evaluate.add_argument("--output", type=Path, required=True)

    safety = subparsers.add_parser(
        "evaluate-safety", help="run deterministic Phase 3 AI and review guardrail checks"
    )
    safety.add_argument("--output", type=Path, required=True)

    heldout = subparsers.add_parser(
        "generate-heldout", help="generate the separate Phase 4 held-out split"
    )
    heldout.add_argument("--output-dir", type=Path, required=True)
    heldout.add_argument("--groups", type=int, default=110)
    heldout.add_argument("--seed", type=int, default=20_260_901)

    heldout_evaluation = subparsers.add_parser(
        "evaluate-heldout", help="evaluate the frozen policy on the Phase 4 held-out split"
    )
    heldout_evaluation.add_argument("input_dir", type=Path)
    heldout_evaluation.add_argument("--output", type=Path, required=True)

    integration = subparsers.add_parser(
        "evaluate-integration", help="run Phase 5 Razorpay contract and delivery checks"
    )
    integration.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "generate":
        _generate(args.output)
    elif args.command == "reconcile":
        _reconcile(args.input, args.output)
    elif args.command == "generate-development":
        _generate_development(args.output_dir, args.groups, args.seed)
    elif args.command == "evaluate-development":
        _evaluate_development(args.input_dir, args.output)
    elif args.command == "evaluate-safety":
        _evaluate_safety(args.output)
    elif args.command == "generate-heldout":
        _generate_heldout(args.output_dir, args.groups, args.seed)
    elif args.command == "evaluate-heldout":
        _evaluate_heldout(args.input_dir, args.output)
    else:
        _evaluate_integration(args.output)


if __name__ == "__main__":
    main()
