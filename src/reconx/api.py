from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from reconx import __version__
from reconx.adapters.razorpay import (
    RazorpayApiError,
    RazorpaySettlementReconClient,
    WebhookPayloadError,
    WebhookSignatureError,
)
from reconx.application.bootstrap import (
    analyst_runtime,
    build_demo_review_service,
    build_heldout_dashboard,
    build_integration_dashboard,
    build_razorpay_webhook_service,
)
from reconx.application.close_pack import build_close_pack
from reconx.application.imports import (
    ImportValidationError,
    canonical_from_recon_items,
    import_reconciliation_inputs,
)
from reconx.application.ingest import ingest_raw_batch
from reconx.application.reconcile import reconcile_batch
from reconx.application.review import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewValidationError,
)
from reconx.application.webhooks import (
    MAX_WEBHOOK_BODY_BYTES,
    WebhookSizeError,
    WebhookTimestampError,
)
from reconx.domain.models import FinanceBatch
from reconx.domain.review import ReviewAction
from reconx.evaluation.runner import run_evaluation
from reconx.infrastructure.webhook_store import WebhookConflictError
from reconx.synthetic.development import build_development_dataset
from reconx.synthetic.generator import build_demo_batch
from reconx.synthetic.heldout import build_heldout_dataset

ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "apps" / "web"

app = FastAPI(
    title="ReconX API",
    version=__version__,
    description="Evidence-first settlement reconciliation",
)
app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="assets")
review_service = build_demo_review_service()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    response.headers.setdefault(
        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
    )
    if request.url.path == "/" or request.url.path.startswith("/assets/"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/demo")
def demo() -> dict:
    return reconcile_batch(build_demo_batch()).to_dict()


@app.get("/api/evaluation")
def evaluation() -> dict:
    raw, manifest, ground_truth = build_development_dataset()
    result = run_evaluation(raw, ground_truth, manifest)
    return {
        "batch_id": result["batch_id"],
        "phase_gate_passed": result["phase_gate_passed"],
        "manifest": result["manifest"],
        "ingestion": {
            key: value for key, value in result["ingestion"].items() if key != "issues"
        },
        "candidate_engine": result["candidate_engine"],
        "exact_id_baseline": result["exact_id_baseline"],
        "gate_checks": result["gate_checks"],
    }


@app.get("/api/heldout")
def heldout_evaluation() -> dict:
    return build_heldout_dashboard()


@app.get("/api/reconcile/heldout")
def reconcile_heldout() -> dict:
    raw, _, _ = build_heldout_dataset()
    return reconcile_batch(ingest_raw_batch(raw).batch).to_dict()


@app.get("/api/close-pack/heldout")
def heldout_close_pack() -> JSONResponse:
    raw, _, _ = build_heldout_dataset()
    pack = build_close_pack(reconcile_batch(ingest_raw_batch(raw).batch))
    return JSONResponse(
        pack,
        headers={"Content-Disposition": 'attachment; filename="reconx-heldout-close-pack.json"'},
    )


@app.post("/api/import/reconcile")
def import_and_reconcile(payload: dict) -> dict:
    try:
        batch, import_issues = import_reconciliation_inputs(payload)
        result = reconcile_batch(batch)
        return {
            "result": result.to_dict(),
            "import_issues": import_issues,
            "close_pack": build_close_pack(result),
        }
    except (ImportValidationError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/import/razorpay/{settlement_date}")
def import_from_razorpay(settlement_date: date) -> dict:
    if os.environ.get("ENABLE_RAZORPAY_IMPORT", "false").lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=503, detail="live Razorpay import is disabled")
    try:
        client = RazorpaySettlementReconClient(
            os.environ.get("RAZORPAY_KEY_ID", ""), os.environ.get("RAZORPAY_KEY_SECRET", "")
        )
        items = client.fetch(settlement_date)
        batch, import_issues = canonical_from_recon_items(
            items, batch_id=f"razorpay_{settlement_date.isoformat()}"
        )
        result = reconcile_batch(batch)
        return {
            "result": result.to_dict(),
            "import_issues": import_issues,
            "close_pack": build_close_pack(result),
            "note": "Bank and ledger evidence must be supplied before any group can auto-close.",
        }
    except (RazorpayApiError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/integration")
def integration_evidence() -> dict:
    return build_integration_dashboard()


@app.post("/api/webhooks/razorpay")
async def razorpay_webhook(request: Request) -> dict:
    service = build_razorpay_webhook_service()
    if service is None:
        raise HTTPException(status_code=503, detail="Razorpay webhook receiver is disabled")
    signature = request.headers.get("x-razorpay-signature", "")
    event_id = request.headers.get("x-razorpay-event-id", "")
    try:
        raw_buffer = bytearray()
        async for chunk in request.stream():
            raw_buffer.extend(chunk)
            if len(raw_buffer) > MAX_WEBHOOK_BODY_BYTES:
                raise WebhookSizeError("webhook request body exceeds 256 KiB")
        raw_body = bytes(raw_buffer)
        receipt = service.process(
            raw_body=raw_body,
            signature=signature,
            event_id=event_id,
        )
        return {"status": "accepted", "receipt": receipt.to_dict()}
    except WebhookSignatureError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except WebhookConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (WebhookPayloadError, WebhookSizeError, WebhookTimestampError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/reviews")
def reviews() -> dict:
    cases = review_service.list_cases()
    return {
        "cases": [case.to_dict() for case in cases],
        "events": {
            case.id: [event.to_dict() for event in review_service.get_events(case.id)]
            for case in cases
        },
        "runtime": analyst_runtime(),
    }


@app.post("/api/reviews/{case_id}/analyse")
def analyse_review(case_id: str, payload: dict) -> dict:
    try:
        case = review_service.reanalyse(
            case_id,
            actor=payload.get("actor", "demo-reviewer"),
            expected_version=int(payload["expected_version"]),
        )
        return {
            "case": case.to_dict(),
            "events": [event.to_dict() for event in review_service.get_events(case_id)],
            "runtime": analyst_runtime(),
        }
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail="review case not found") from exc
    except ReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, TypeError, ValueError, ReviewValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/reviews/{case_id}/decision")
def decide_review(case_id: str, payload: dict) -> dict:
    try:
        action = ReviewAction(payload["action"])
        case = review_service.decide(
            case_id,
            action=action,
            actor=payload["actor"],
            reason=payload["reason"],
            expected_version=int(payload["expected_version"]),
        )
        return {
            "case": case.to_dict(),
            "events": [event.to_dict() for event in review_service.get_events(case_id)],
        }
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail="review case not found") from exc
    except ReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, TypeError, ValueError, ReviewValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/reconcile")
def reconcile(payload: dict) -> dict:
    try:
        batch = FinanceBatch.from_dict(payload)
        return reconcile_batch(batch).to_dict()
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")
