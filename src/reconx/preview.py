"""Dependency-free local preview transport.

This is a development convenience for restricted environments. The submission API is
FastAPI (`reconx.api`); both transports invoke the same application use case.
"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from reconx import __version__
from reconx.adapters.razorpay import WebhookPayloadError, WebhookSignatureError
from reconx.application.bootstrap import (
    analyst_runtime,
    build_demo_review_service,
    build_heldout_dashboard,
    build_integration_dashboard,
    build_razorpay_webhook_service,
)
from reconx.application.close_pack import build_close_pack
from reconx.application.imports import ImportValidationError, import_reconciliation_inputs
from reconx.application.ingest import ingest_raw_batch
from reconx.application.reconcile import reconcile_batch
from reconx.application.review import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewValidationError,
)
from reconx.application.webhooks import WebhookSizeError, WebhookTimestampError
from reconx.domain.review import ReviewAction
from reconx.evaluation.runner import run_evaluation
from reconx.infrastructure.webhook_store import WebhookConflictError
from reconx.synthetic.development import build_development_dataset
from reconx.synthetic.generator import build_demo_batch
from reconx.synthetic.heldout import build_heldout_dataset

ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "apps" / "web"
CONTENT_TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}
REVIEW_SERVICE = build_demo_review_service()


class PreviewHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, sort_keys=True, default=str).encode()
        self._send(status, body, "application/json")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._json({"status": "ok", "version": __version__})
            return
        if path == "/api/demo":
            self._json(reconcile_batch(build_demo_batch()).to_dict())
            return
        if path == "/api/evaluation":
            raw, manifest, ground_truth = build_development_dataset()
            result = run_evaluation(raw, ground_truth, manifest)
            self._json(
                {
                    "batch_id": result["batch_id"],
                    "phase_gate_passed": result["phase_gate_passed"],
                    "manifest": result["manifest"],
                    "ingestion": {
                        key: value
                        for key, value in result["ingestion"].items()
                        if key != "issues"
                    },
                    "candidate_engine": result["candidate_engine"],
                    "exact_id_baseline": result["exact_id_baseline"],
                    "gate_checks": result["gate_checks"],
                }
            )
            return
        if path == "/api/heldout":
            self._json(build_heldout_dashboard())
            return
        if path == "/api/reconcile/heldout":
            raw, _, _ = build_heldout_dataset()
            self._json(reconcile_batch(ingest_raw_batch(raw).batch).to_dict())
            return
        if path == "/api/close-pack/heldout":
            raw, _, _ = build_heldout_dataset()
            self._json(build_close_pack(reconcile_batch(ingest_raw_batch(raw).batch)))
            return
        if path == "/api/integration":
            self._json(build_integration_dashboard())
            return
        if path == "/api/reviews":
            cases = REVIEW_SERVICE.list_cases()
            self._json(
                {
                    "cases": [case.to_dict() for case in cases],
                    "events": {
                        case.id: [
                            event.to_dict() for event in REVIEW_SERVICE.get_events(case.id)
                        ]
                        for case in cases
                    },
                    "runtime": analyst_runtime(),
                }
            )
            return
        if path == "/":
            target = WEB_ROOT / "index.html"
        elif path.startswith("/assets/"):
            target = WEB_ROOT / path.removeprefix("/assets/")
        else:
            self._json({"detail": "not found"}, 404)
            return

        if not target.is_file() or target.parent != WEB_ROOT:
            self._json({"detail": "not found"}, 404)
            return
        self._send(200, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/import/reconcile":
            try:
                payload = self._read_json_body()
                batch, import_issues = import_reconciliation_inputs(payload)
                result = reconcile_batch(batch)
                self._json(
                    {
                        "result": result.to_dict(),
                        "import_issues": import_issues,
                        "close_pack": build_close_pack(result),
                    }
                )
            except (ImportValidationError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self._json({"detail": str(exc)}, 422)
            return
        if path == "/api/webhooks/razorpay":
            service = build_razorpay_webhook_service()
            if service is None:
                self._json({"detail": "Razorpay webhook receiver is disabled"}, 503)
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length <= 0 or content_length > 262_144:
                    raise WebhookSizeError("invalid webhook request size")
                raw_body = self.rfile.read(content_length)
                receipt = service.process(
                    raw_body=raw_body,
                    signature=self.headers.get("X-Razorpay-Signature", ""),
                    event_id=self.headers.get("X-Razorpay-Event-Id", ""),
                )
                self._json({"status": "accepted", "receipt": receipt.to_dict()})
            except WebhookSignatureError as exc:
                self._json({"detail": str(exc)}, 401)
            except WebhookConflictError as exc:
                self._json({"detail": str(exc)}, 409)
            except (WebhookPayloadError, WebhookSizeError, WebhookTimestampError) as exc:
                self._json({"detail": str(exc)}, 422)
            return
        analysis_match = re.fullmatch(r"/api/reviews/([A-Za-z0-9_-]+)/analyse", path)
        if analysis_match:
            try:
                payload = self._read_json_body()
                case_id = analysis_match.group(1)
                case = REVIEW_SERVICE.reanalyse(
                    case_id,
                    actor=payload.get("actor", "demo-reviewer"),
                    expected_version=int(payload["expected_version"]),
                )
                self._json(
                    {
                        "case": case.to_dict(),
                        "events": [
                            event.to_dict() for event in REVIEW_SERVICE.get_events(case_id)
                        ],
                        "runtime": analyst_runtime(),
                    }
                )
            except ReviewNotFoundError:
                self._json({"detail": "review case not found"}, 404)
            except ReviewConflictError as exc:
                self._json({"detail": str(exc)}, 409)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError, ReviewValidationError) as exc:
                self._json({"detail": str(exc)}, 422)
            return
        match = re.fullmatch(r"/api/reviews/([A-Za-z0-9_-]+)/decision", path)
        if not match:
            self._json({"detail": "not found"}, 404)
            return
        try:
            payload = self._read_json_body()
            case_id = match.group(1)
            case = REVIEW_SERVICE.decide(
                case_id,
                action=ReviewAction(payload["action"]),
                actor=payload["actor"],
                reason=payload["reason"],
                expected_version=int(payload["expected_version"]),
            )
            self._json(
                {
                    "case": case.to_dict(),
                    "events": [
                        event.to_dict() for event in REVIEW_SERVICE.get_events(case_id)
                    ],
                }
            )
        except ReviewNotFoundError:
            self._json({"detail": "review case not found"}, 404)
        except ReviewConflictError as exc:
            self._json({"detail": str(exc)}, 409)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, ReviewValidationError) as exc:
            self._json({"detail": str(exc)}, 422)

    def _read_json_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > 4_500_000:
            raise ReviewValidationError("invalid request size")
        payload = json.loads(self.rfile.read(content_length))
        if not isinstance(payload, dict):
            raise ReviewValidationError("request body must be a JSON object")
        return payload

    def log_message(self, format: str, *args: object) -> None:
        print(f"preview: {format % args}")


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8000), PreviewHandler)
    print("ReconX preview running at http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
