from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from reconx.adapters.openai import OpenAIResponsesProvider
from reconx.adapters.razorpay import WebhookSecret
from reconx.application.analyst import DisabledProvider, ExceptionAnalyst
from reconx.application.ingest import ingest_raw_batch
from reconx.application.reconcile import reconcile_batch
from reconx.application.review import ReviewService
from reconx.application.webhooks import RazorpayWebhookService
from reconx.evaluation.heldout import dashboard_payload, run_heldout_evaluation
from reconx.infrastructure.review_store import SQLiteReviewRepository
from reconx.infrastructure.webhook_store import SQLiteWebhookStore
from reconx.synthetic.heldout import build_heldout_dataset

DEMO_TIME = datetime(2026, 8, 31, 10, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[3]


def _enabled(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def build_exception_analyst() -> ExceptionAnalyst:
    if not _enabled("ENABLE_LLM"):
        return ExceptionAnalyst(DisabledProvider())
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return ExceptionAnalyst(DisabledProvider())
    return ExceptionAnalyst(
        OpenAIResponsesProvider(
            key,
            model=os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"),
            endpoint=os.environ.get(
                "OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses"
            ),
        )
    )


def analyst_runtime() -> dict[str, str | bool]:
    analyst = build_exception_analyst()
    enabled = analyst.provider.name != "disabled"
    return {
        "enabled": enabled,
        "provider": analyst.provider.name,
        "mode": "advisory_only" if enabled else "deterministic_fallback",
    }


@lru_cache(maxsize=1)
def build_demo_review_service() -> ReviewService:
    """Build the held-out exception queue without spending model tokens at startup."""

    raw, _, _ = build_heldout_dataset()
    batch = ingest_raw_batch(raw).batch
    result = reconcile_batch(batch)
    database = Path(
        os.environ.get("RECONX_REVIEW_DB", str(ROOT / "data" / "runtime" / "reviews.sqlite3"))
    )
    service = ReviewService(
        build_exception_analyst(),
        repository=SQLiteReviewRepository(database),
        clock=lambda: DEMO_TIME,
    )
    runtime_analyst = service.analyst
    service.analyst = ExceptionAnalyst(DisabledProvider())
    bank_excerpts = {item.id: item.narration for item in batch.bank_entries}
    for group in result.groups:
        if group.state.value != "auto_approved":
            service.create_case(
                group,
                evidence_excerpts={
                    evidence_id: bank_excerpts[evidence_id]
                    for evidence_id in group.evidence_ids
                    if evidence_id in bank_excerpts
                },
                occurred_at=DEMO_TIME.isoformat().replace("+00:00", "Z"),
            )
    service.analyst = runtime_analyst
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
