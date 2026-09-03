from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ExceptionCategory(StrEnum):
    SETTLEMENT_MISMATCH = "settlement_mismatch"
    MISSING_BANK_CREDIT = "missing_bank_credit"
    MISSING_LEDGER_ENTRY = "missing_ledger_entry"
    DUPLICATE_OR_CONFLICT = "duplicate_or_conflict"
    FEE_OR_TAX_MISMATCH = "fee_or_tax_mismatch"
    REFERENCE_AMBIGUITY = "reference_ambiguity"
    TIMING_DIFFERENCE = "timing_difference"
    UNSUPPORTED_RECORD = "unsupported_record"
    UNKNOWN = "unknown"


class SuggestedAction(StrEnum):
    INVESTIGATE_BANK = "investigate_bank"
    VERIFY_LEDGER = "verify_ledger"
    CORRECT_SOURCE_RECORD = "correct_source_record"
    WAIT_AND_RECHECK = "wait_and_recheck"
    MANUAL_RECONCILE = "manual_reconcile"
    NO_ACTION = "no_action"


@dataclass(slots=True)
class AnalysisRequest:
    case_id: str
    reason_codes: list[str]
    evidence_ids: list[str]
    deterministic_facts: dict[str, int | float | str | bool | None]
    evidence_excerpts: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ExceptionAnalysis:
    category: ExceptionCategory
    confidence: float
    cited_evidence_ids: list[str]
    explanation: str
    suggested_action: SuggestedAction
    source: str
    provider: str
    attempts: int
    fallback_reason: str | None = None
    security_flags: list[str] = field(default_factory=list)
    output_hash: str = ""
    missing_evidence_types: list[str] = field(default_factory=list)
    risk_level: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "confidence": self.confidence,
            "cited_evidence_ids": self.cited_evidence_ids,
            "explanation": self.explanation,
            "suggested_action": self.suggested_action.value,
            "source": self.source,
            "provider": self.provider,
            "attempts": self.attempts,
            "fallback_reason": self.fallback_reason,
            "security_flags": self.security_flags,
            "output_hash": self.output_hash,
            "missing_evidence_types": self.missing_evidence_types,
            "risk_level": self.risk_level,
        }
