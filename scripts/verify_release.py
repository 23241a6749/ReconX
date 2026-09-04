#!/usr/bin/env python3
"""Dependency-free, fail-closed release verification for ReconX."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
REQUIRED_FILES = {
    ".env.example",
    ".github/workflows/ci.yml",
    "Dockerfile",
    "LICENSE",
    "README.md",
    "PLAN.md",
    "policies/reconciliation-policy-v2.2.json",
    "data/heldout/ground-truth.json",
    "data/heldout/manifest.json",
    "data/heldout/raw-batch.json",
    "docs/architecture.md",
    "docs/dataset-provenance.md",
    "docs/demo-script.md",
    "docs/evaluation.md",
    "docs/integration.md",
    "docs/render-deployment.md",
    "docs/security.md",
    "docs/submission.md",
    "docs/user-setup.md",
    "reports/phase2-evaluation.json",
    "reports/phase3-safety-report.json",
    "reports/phase4-heldout-evaluation.json",
    "reports/phase5-integration-report.json",
    "render.yaml",
}
SECRET_ENV_KEYS = {
    "RAZORPAY_KEY_ID",
    "RAZORPAY_KEY_SECRET",
    "RAZORPAY_WEBHOOK_SECRET",
    "RAZORPAY_WEBHOOK_PREVIOUS_SECRET",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
}
TEXT_SUFFIXES = {
    "",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
}
ENV_ASSIGNMENT = re.compile(
    r"^\s*(RAZORPAY_KEY_ID|RAZORPAY_KEY_SECRET|RAZORPAY_WEBHOOK_SECRET|"
    r"RAZORPAY_WEBHOOK_PREVIOUS_SECRET|GROQ_API_KEY|OPENAI_API_KEY)\s*=\s*(.*?)\s*$"
)


def load_report(name: str) -> dict:
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def env_example_is_safe() -> bool:
    assignments = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        assignments[key.strip()] = value.strip()
    return all(assignments.get(key) == "" for key in SECRET_ENV_KEYS)


def repository_candidate_files() -> list[Path]:
    """Return tracked and untracked-but-not-ignored files when Git is available."""

    try:
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return [path for path in ROOT.rglob("*") if path.is_file()]
    return [ROOT / item.decode("utf-8") for item in completed.stdout.split(b"\0") if item]


def unignored_secret_config_files() -> list[str]:
    return sorted(
        str(path.relative_to(ROOT))
        for path in repository_candidate_files()
        if path.name.lower().startswith(".env") and path.name != ".env.example"
    )


def _contains_non_placeholder_assignment(content: str) -> bool:
    for line in content.splitlines():
        matched = ENV_ASSIGNMENT.fullmatch(line)
        if not matched:
            continue
        value = matched.group(2).strip().strip('"\'')
        if not value:
            continue
        lowered = value.lower()
        if value.startswith(("<", "${")):
            continue
        if "your_" in lowered or "example" in lowered or "placeholder" in lowered:
            continue
        return True
    return False


def suspicious_secret_files() -> list[str]:
    # Split tokens keep the scanner from matching its own pattern definitions.
    patterns = (
        re.compile("rzp" + r"_live_[A-Za-z0-9]{14,}"),
        re.compile("gh" + r"p_[A-Za-z0-9]{20,}"),
        re.compile("github" + r"_pat_[A-Za-z0-9_]{20,}"),
        re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    )
    hits = []
    excluded_parts = {".git", ".venv", "__pycache__", "data", "artifacts"}
    for path in repository_candidate_files():
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path == Path(__file__).resolve() or excluded_parts.intersection(path.parts):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(pattern.search(content) for pattern in patterns) or _contains_non_placeholder_assignment(
            content
        ):
            hits.append(str(path.relative_to(ROOT)))
    return sorted(hits)


def main() -> int:
    phase2 = load_report("phase2-evaluation.json")
    phase3 = load_report("phase3-safety-report.json")
    phase4 = load_report("phase4-heldout-evaluation.json")
    phase5 = load_report("phase5-integration-report.json")
    phase4_manifest = phase4.get("manifest", {})
    phase4_provenance = phase4_manifest.get("provenance", {})
    missing = sorted(path for path in REQUIRED_FILES if not (ROOT / path).is_file())
    secret_hits = suspicious_secret_files()
    unsafe_secret_configs = unignored_secret_config_files()

    checks = {
        "required_submission_files_present": not missing,
        "secret_environment_values_blank": env_example_is_safe(),
        "common_live_secret_patterns_absent": not secret_hits,
        "unignored_secret_config_files_absent": not unsafe_secret_configs,
        "phase2_gate_passed": phase2.get("phase_gate_passed") is True,
        "phase3_gate_passed": phase3.get("phase_gate_passed") is True,
        "phase3_ai_is_advisory_only": phase3.get("model_authority") == "advisory_only",
        "phase4_gate_passed": phase4.get("phase_gate_passed") is True,
        "phase4_record_floor_met": phase4.get("business_summary", {}).get("raw_records", 0) >= 50,
        "phase4_safe_auto_precision_is_one": phase4.get("business_summary", {}).get("safe_auto_precision") == 1.0,
        "phase4_exceptions_are_complete": phase4.get("business_summary", {}).get("exceptions_not_auto_resolved") == len(phase4.get("exceptions", [])),
        "phase4_source_counts_total_1400": sum(
            phase4_manifest.get("source_record_counts", {}).values()
        )
        == 1400,
        "phase4_real_data_claim_is_false": phase4_provenance.get(
            "contains_real_merchant_data"
        )
        is False
        and phase4_provenance.get("contains_customer_personal_data") is False,
        "phase4_ingestion_is_fully_accounted": phase4.get("ingestion", {}).get(
            "raw_record_count"
        )
        == 1400
        and phase4.get("ingestion", {}).get("accepted_record_count") == 1335
        and phase4.get("ingestion", {}).get("duplicate_record_count") == 10
        and phase4.get("ingestion", {}).get("quarantined_record_count") == 60
        and phase4.get("ingestion", {}).get("issue_count")
        == len(phase4.get("ingestion", {}).get("issues", []))
        == 95,
        "phase5_gate_passed": phase5.get("phase_gate_passed") is True,
        "phase5_all_controls_passed": phase5.get("passed") == phase5.get("total") == 19,
        "phase5_contains_no_live_call_claim": phase5.get("live_razorpay_call_made") is False,
        "synthetic_evidence_disclosed": all(report.get("synthetic") is True for report in (phase2, phase3, phase4, phase5)),
    }
    for name, passed in checks.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    if missing:
        print("Missing files: " + ", ".join(missing))
    if secret_hits:
        print("Potential secret patterns found in: " + ", ".join(secret_hits))
    if unsafe_secret_configs:
        print("Unignored secret configuration files: " + ", ".join(unsafe_secret_configs))
    passed = sum(checks.values())
    print(f"Release gate: {passed}/{len(checks)} checks passed")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
