from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from reconx.adapters.razorpay import WebhookSecret
from reconx.application.analyst import DisabledProvider, ExceptionAnalyst
from reconx.application.reconcile import reconcile_batch
from reconx.application.review import ReviewService
from reconx.application.webhooks import RazorpayWebhookService
from reconx.evaluation.heldout import dashboard_payload, run_heldout_evaluation
from reconx.infrastructure.webhook_store import SQLiteWebhookStore
from reconx.synthetic.generator import build_demo_batch
from reconx.synthetic.heldout import build_heldout_dataset

DEMO_TIME = datetime(2026, 8, 31, 10, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[3]


def build_demo_review_service() -> ReviewService:
    """Create one safe, deterministic review-first workflow for the UI."""

    batch = build_demo_batch()
    batch.bank_entries[0] = replace(batch.bank_entries[0], amount_paise=682_301)
    result = reconcile_batch(batch)
    group = result.groups[0]
    service = ReviewService(
        ExceptionAnalyst(DisabledProvider()),
        clock=lambda: DEMO_TIME,
    )
    service.create_case(
        group,
        evidence_excerpts={
            batch.bank_entries[0].id: batch.bank_entries[0].narration,
            batch.ledger_entries[0].id: "Internal settlement ledger entry",
        },
        occurred_at=DEMO_TIME.isoformat().replace("+00:00", "Z"),
    )
    return service


@lru_cache(maxsize=1)
def build_heldout_dashboard() -> dict:
    report_path = ROOT / "reports" / "phase4-heldout-evaluation.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text())
    else:
        raw, manifest, ground_truth = build_heldout_dataset()
        report = run_heldout_evaluation(raw, ground_truth, manifest)
    return dashboard_payload(report)


@lru_cache(maxsize=1)
def build_razorpay_webhook_service() -> RazorpayWebhookService | None:
    current = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not current:
        return None
    secrets = [WebhookSecret("current", current.encode("utf-8"))]
    previous = os.environ.get("RAZORPAY_WEBHOOK_PREVIOUS_SECRET", "")
    if previous and previous != current:
        secrets.append(WebhookSecret("previous", previous.encode("utf-8")))
    database = Path(
        os.environ.get("RECONX_WEBHOOK_DB", str(ROOT / "data" / "runtime" / "webhooks.sqlite3"))
    )
    return RazorpayWebhookService(tuple(secrets), SQLiteWebhookStore(database))


@lru_cache(maxsize=1)
def build_integration_dashboard() -> dict:
    report_path = ROOT / "reports" / "phase5-integration-report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text())
    else:
        report = {
            "evaluation": "phase5_integration",
            "phase_gate_passed": False,
            "checks": {},
            "webhook_summary": {},
        }
    service = build_razorpay_webhook_service()
    return {
        "evaluation": report["evaluation"],
        "phase_gate_passed": report["phase_gate_passed"],
        "live_razorpay_call_made": report.get("live_razorpay_call_made", False),
        "passed": report.get("passed", 0),
        "total": report.get("total", 0),
        "checks": report.get("checks", {}),
        "webhook_summary": report.get("webhook_summary", {}),
        "recon_fixture_summary": report.get("recon_fixture_summary", {}),
        "security_controls": report.get("security_controls", []),
        "runtime": {
            "webhook_configured": service is not None,
            "mode": "configured" if service is not None else "disabled_without_secret",
        },
    }
