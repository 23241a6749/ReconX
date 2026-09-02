from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from reconx.domain.analysis import ExceptionAnalysis


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REOPEN = "reopen"


@dataclass(slots=True)
class ReviewCase:
    id: str
    settlement_id: str
    version: int
    status: ReviewStatus
    reason_codes: list[str]
    evidence_ids: list[str]
    deterministic_state: str
    expected_bank_credit_paise: int
    actual_bank_credit_paise: int | None
    difference_paise: int | None
    analysis: ExceptionAnalysis
    created_at: str
    updated_at: str
    decided_by: str | None = None
    decision_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "settlement_id": self.settlement_id,
            "version": self.version,
            "status": self.status.value,
            "reason_codes": self.reason_codes,
            "evidence_ids": self.evidence_ids,
            "deterministic_state": self.deterministic_state,
            "expected_bank_credit_paise": self.expected_bank_credit_paise,
            "actual_bank_credit_paise": self.actual_bank_credit_paise,
            "difference_paise": self.difference_paise,
            "analysis": self.analysis.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "decided_by": self.decided_by,
            "decision_reason": self.decision_reason,
        }


@dataclass(slots=True)
class ReviewEvent:
    id: str
    case_id: str
    version: int
    actor: str
    action: str
    reason: str
    previous_status: str | None
    new_status: str
    occurred_at: str
    previous_event_hash: str | None
    event_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "case_id": self.case_id,
            "version": self.version,
            "actor": self.actor,
            "action": self.action,
            "reason": self.reason,
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "occurred_at": self.occurred_at,
            "previous_event_hash": self.previous_event_hash,
            "event_hash": self.event_hash,
        }

