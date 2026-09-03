from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from reconx.application.reconcile import BatchResult, policy_contract_hash
from reconx.domain.models import DecisionState


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def build_close_pack(result: BatchResult) -> dict[str, Any]:
    """Build a portable, audit-ready close artifact without mutating accounting systems."""

    automatic = [group for group in result.groups if group.state is DecisionState.AUTO_APPROVED]
    review = [group for group in result.groups if group.state is DecisionState.REVIEW_REQUIRED]
    unresolved = [group for group in result.groups if group.state is DecisionState.UNRESOLVED]
    evidence = {
        "batch_id": result.batch_id,
        "policy_contract_sha256": policy_contract_hash(),
        "groups": [asdict(group) for group in result.groups],
        "exceptions": [asdict(item) for item in result.exceptions],
        "audit_events": [asdict(item) for item in result.audit_events],
    }
    return {
        "artifact": "reconx_close_pack",
        "version": "1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "batch_id": result.batch_id,
        "synthetic": result.synthetic,
        "summary": {
            "source_records": result.source_record_count,
            "settlement_groups": len(result.groups),
            "auto_closed_groups": len(automatic),
            "review_required_groups": len(review),
            "unresolved_groups": len(unresolved),
            "open_record_exceptions": len(result.exceptions),
            "auto_closed_value_paise": sum(item.expected_bank_credit_paise for item in automatic),
            "human_review_exposure_paise": sum(
                abs(item.expected_bank_credit_paise) for item in review + unresolved
            ),
            "estimated_minutes_saved": len(automatic) * 4,
            "estimate_basis": "4 minutes of manual checking per safely auto-closed group",
        },
        "controls": {
            "model_authority": "advisory_only",
            "human_review_required_for_non_auto_groups": True,
            "accounting_post_performed": False,
            "policy_contract_sha256": policy_contract_hash(),
        },
        "evidence": evidence,
        "evidence_sha256": _hash(evidence),
    }
