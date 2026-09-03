from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from reconx.domain.models import (
    DecisionState,
    FinanceBatch,
    LineKind,
    PaymentStatus,
    RefundStatus,
    Settlement,
)

POLICY_VERSION = "reconciliation-policy/2.1"
AUTO_APPROVE_THRESHOLD = 0.98
CANDIDATE_AMOUNT_WEIGHT = 0.50
CANDIDATE_REFERENCE_WEIGHT = 0.30
CANDIDATE_STRONG_DATE_WEIGHT = 0.20
CANDIDATE_EXTENDED_DATE_WEIGHT = 0.10
STRONG_DATE_WINDOW_DAYS = 2
MAX_CANDIDATE_WINDOW_DAYS = 7
MIN_CANDIDATE_MARGIN = 0.15


def policy_contract() -> dict[str, Any]:
    """Return the machine-checkable policy frozen before held-out evaluation."""

    return {
        "policy_version": POLICY_VERSION,
        "money": {
            "unit": "paise",
            "fee_includes_tax": True,
            "expected_bank_credit": (
                "captured_payments-refunds-inclusive_fees+adjustments"
            ),
            "required_difference_paise": 0,
        },
        "candidate_matching": {
            "amount_must_match": True,
            "amount_weight": CANDIDATE_AMOUNT_WEIGHT,
            "reference_weight": CANDIDATE_REFERENCE_WEIGHT,
            "strong_date_weight": CANDIDATE_STRONG_DATE_WEIGHT,
            "extended_date_weight": CANDIDATE_EXTENDED_DATE_WEIGHT,
            "strong_date_window_days": STRONG_DATE_WINDOW_DAYS,
            "maximum_date_window_days": MAX_CANDIDATE_WINDOW_DAYS,
            "auto_approve_threshold": AUTO_APPROVE_THRESHOLD,
            "minimum_runner_up_margin": MIN_CANDIDATE_MARGIN,
        },
        "approval": {
            "requires_unique_bank_entry": True,
            "requires_exact_ledger_reference": True,
            "requires_money_conservation": True,
            "requires_positive_expected_bank_credit": True,
            "ambiguous_candidates_auto_approve": False,
        },
    }


def policy_contract_hash() -> str:
    return _stable_hash(policy_contract())


@dataclass(slots=True)
class ExceptionCase:
    code: str
    severity: str
    source_record_ids: list[str]
    message: str
    status: str = "open"


@dataclass(slots=True)
class AuditEvent:
    id: str
    actor: str
    action: str
    reason_codes: list[str]
    input_hash: str
    decision_hash: str
    policy_version: str
    occurred_at: str


@dataclass(slots=True)
class ReconciliationGroup:
    settlement_id: str
    state: DecisionState
    confidence: float
    reason_codes: list[str]
    evidence_ids: list[str]
    gross_payments_paise: int
    refunds_paise: int
    inclusive_fees_paise: int
    tax_component_paise: int
    adjustments_paise: int
    expected_bank_credit_paise: int
    actual_bank_credit_paise: int | None
    difference_paise: int | None
    bank_entry_id: str | None
    ledger_entry_id: str | None
    bank_match_method: str | None


@dataclass(slots=True)
class BatchResult:
    batch_id: str
    synthetic: bool
    source_record_count: int
    groups: list[ReconciliationGroup]
    exceptions: list[ExceptionCase]
    audit_events: list[AuditEvent]
    elapsed_ms: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metrics"] = {
            "group_count": len(self.groups),
            "auto_approved": sum(
                group.state is DecisionState.AUTO_APPROVED for group in self.groups
            ),
            "review_required": sum(
                group.state is DecisionState.REVIEW_REQUIRED for group in self.groups
            ),
            "unresolved": sum(group.state is DecisionState.UNRESOLVED for group in self.groups)
            + len(self.exceptions),
            "throughput_records_per_second": round(
                self.source_record_count / max(self.elapsed_ms / 1000, 0.000001), 2
            ),
        }
        return payload


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _normalise_reference(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _date_distance_days(settled_at: str, value_date: str) -> int:
    settled = datetime.fromisoformat(settled_at).date()
    bank_date = date.fromisoformat(value_date)
    return abs((bank_date - settled).days)


def _candidate_score(settlement: Settlement, narration: str, amount_matches: bool, days: int) -> float:
    score = CANDIDATE_AMOUNT_WEIGHT if amount_matches else 0.0
    normalised_narration = _normalise_reference(narration)
    if _normalise_reference(settlement.id) in normalised_narration:
        score += CANDIDATE_REFERENCE_WEIGHT
    if days <= STRONG_DATE_WINDOW_DAYS:
        score += CANDIDATE_STRONG_DATE_WEIGHT
    elif days <= MAX_CANDIDATE_WINDOW_DAYS:
        score += CANDIDATE_EXTENDED_DATE_WEIGHT
    return round(score, 4)


def _choose_bank_entry(
    batch: FinanceBatch,
    settlement: Settlement,
    expected: int,
    reserved_bank_ids: set[str],
    allow_candidates: bool,
) -> tuple[Any | None, float, str | None, list[str], bool]:
    reasons: list[str] = []
    exact_banks = [
        entry
        for entry in batch.bank_entries
        if settlement.utr and entry.utr == settlement.utr
    ]
    if len(exact_banks) > 1:
        return None, 0.0, None, ["DUPLICATE_BANK_UTR"], True
    if len(exact_banks) == 1:
        bank = exact_banks[0]
        if bank.id in reserved_bank_ids:
            return None, 0.0, None, ["BANK_ENTRY_ALREADY_MATCHED"], True
        return bank, 1.0, "exact_utr", ["EXACT_UTR"], False

    reasons.append("BANK_UTR_NOT_FOUND")
    if not allow_candidates:
        return None, 0.0, None, reasons, False

    scored: list[tuple[float, str, Any]] = []
    for entry in batch.bank_entries:
        if entry.id in reserved_bank_ids or entry.currency != settlement.currency:
            continue
        days = _date_distance_days(settlement.settled_at, entry.value_date)
        if days > MAX_CANDIDATE_WINDOW_DAYS or entry.amount_paise != expected:
            continue
        score = _candidate_score(settlement, entry.narration, True, days)
        scored.append((score, entry.id, entry))

    scored.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    if not scored:
        reasons.append("NO_SAFE_BANK_CANDIDATE")
        return None, 0.0, None, reasons, False

    top_score, _, top_bank = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if top_score < AUTO_APPROVE_THRESHOLD or top_score - runner_up < MIN_CANDIDATE_MARGIN:
        reasons.append("AMBIGUOUS_BANK_CANDIDATES")
        return None, top_score, None, reasons, False

    reasons.extend(
        ["CANDIDATE_AMOUNT_EXACT", "CANDIDATE_DATE_WINDOW", "CANDIDATE_REFERENCE_EXACT"]
    )
    return top_bank, top_score, "evidence_candidate", reasons, False


def _settlement_group(
    batch: FinanceBatch,
    settlement: Settlement,
    reserved_bank_ids: set[str],
    allow_candidates: bool,
) -> ReconciliationGroup:
    lines = [line for line in batch.settlement_lines if line.settlement_id == settlement.id]
    payment_by_id = {payment.id: payment for payment in batch.payments}
    refund_by_id = {refund.id: refund for refund in batch.refunds}

    reason_codes: list[str] = []
    evidence_ids = [settlement.id]
    gross = refunds = fees = taxes = adjustments = 0
    forced_unresolved = False

    for line in lines:
        evidence_ids.append(line.id)
        if line.tax_paise > line.fee_paise:
            reason_codes.append("TAX_EXCEEDS_INCLUSIVE_FEE")
            forced_unresolved = True

        if line.kind is LineKind.PAYMENT:
            payment = payment_by_id.get(line.entity_id)
            if payment is None or payment.status is not PaymentStatus.CAPTURED:
                reason_codes.append("PAYMENT_SOURCE_MISSING_OR_NOT_CAPTURED")
                forced_unresolved = True
                continue
            evidence_ids.append(payment.id)
            if payment.currency != settlement.currency:
                reason_codes.append("PAYMENT_CURRENCY_MISMATCH")
                forced_unresolved = True
            if (
                payment.amount_paise != line.amount_paise
                or payment.fee_paise != line.fee_paise
                or payment.tax_paise != line.tax_paise
            ):
                reason_codes.append("PAYMENT_RECON_FIELDS_MISMATCH")
                forced_unresolved = True
            gross += line.amount_paise
            fees += line.fee_paise
            taxes += line.tax_paise
        elif line.kind is LineKind.REFUND:
            refund = refund_by_id.get(line.entity_id)
            if refund is None or refund.status is not RefundStatus.PROCESSED:
                reason_codes.append("REFUND_SOURCE_MISSING_OR_NOT_PROCESSED")
                forced_unresolved = True
                continue
            evidence_ids.append(refund.id)
            if refund.currency != settlement.currency:
                reason_codes.append("REFUND_CURRENCY_MISMATCH")
                forced_unresolved = True
            if refund.amount_paise != line.amount_paise:
                reason_codes.append("REFUND_RECON_FIELDS_MISMATCH")
                forced_unresolved = True
            if datetime.fromisoformat(refund.created_at) > datetime.fromisoformat(
                settlement.settled_at
            ):
                reason_codes.append("POST_SETTLEMENT_REFUND")
                forced_unresolved = True
            refunds += line.amount_paise
        else:
            adjustments += line.amount_paise

    expected = gross - refunds - fees + adjustments
    if expected <= 0:
        reason_codes.append("NON_POSITIVE_EXPECTED_BANK_CREDIT")
        forced_unresolved = True
    bank, bank_confidence, bank_match_method, bank_reasons, bank_forced = _choose_bank_entry(
        batch, settlement, expected, reserved_bank_ids, allow_candidates
    )
    reason_codes.extend(bank_reasons)
    forced_unresolved = forced_unresolved or bank_forced
    if bank is not None:
        evidence_ids.append(bank.id)

    ledger_candidates = [
        entry
        for entry in batch.ledger_entries
        if entry.reference == settlement.id and entry.currency == settlement.currency
    ]
    ledger = ledger_candidates[0] if len(ledger_candidates) == 1 else None
    if ledger:
        evidence_ids.append(ledger.id)
        reason_codes.append("EXACT_LEDGER_REFERENCE")
        if ledger.amount_paise != expected:
            reason_codes.append("LEDGER_AMOUNT_MISMATCH")

    actual = bank.amount_paise if bank else None
    difference = actual - expected if actual is not None else None
    currencies = {settlement.currency}
    if bank:
        currencies.add(bank.currency)
    if ledger:
        currencies.add(ledger.currency)
    if len(currencies) > 1:
        reason_codes.append("CURRENCY_MISMATCH")
        forced_unresolved = True

    if forced_unresolved:
        state = DecisionState.UNRESOLVED
        confidence = 0.0
    elif bank and difference == 0 and ledger and ledger.amount_paise == expected:
        state = DecisionState.AUTO_APPROVED
        confidence = bank_confidence
        reason_codes.extend(["MONEY_CONSERVED", "UNIQUE_EVIDENCE_GRAPH"])
    elif bank and difference == 0:
        state = DecisionState.REVIEW_REQUIRED
        confidence = 0.85
        reason_codes.append("MONEY_CONSERVED")
        if ledger is None:
            reason_codes.append("LEDGER_CONFIRMATION_MISSING")
    elif bank:
        state = DecisionState.REVIEW_REQUIRED
        confidence = 0.65
        reason_codes.append("BANK_AMOUNT_IMBALANCE")
    else:
        state = DecisionState.UNRESOLVED
        confidence = 0.25

    return ReconciliationGroup(
        settlement_id=settlement.id,
        state=state,
        confidence=confidence,
        reason_codes=reason_codes,
        evidence_ids=sorted(set(evidence_ids)),
        gross_payments_paise=gross,
        refunds_paise=refunds,
        inclusive_fees_paise=fees,
        tax_component_paise=taxes,
        adjustments_paise=adjustments,
        expected_bank_credit_paise=expected,
        actual_bank_credit_paise=actual,
        difference_paise=difference,
        bank_entry_id=bank.id if bank else None,
        ledger_entry_id=ledger.id if ledger else None,
        bank_match_method=bank_match_method,
    )


def reconcile_batch(batch: FinanceBatch, *, allow_candidates: bool = True) -> BatchResult:
    started = time.perf_counter()
    groups: list[ReconciliationGroup] = []
    reserved_bank_ids: set[str] = set()
    for settlement in sorted(batch.settlements, key=lambda item: (item.settled_at, item.id)):
        group = _settlement_group(batch, settlement, reserved_bank_ids, allow_candidates)
        groups.append(group)
        if group.bank_entry_id:
            reserved_bank_ids.add(group.bank_entry_id)
    used_ledger_ids = {group.ledger_entry_id for group in groups if group.ledger_entry_id}
    exceptions = [
        ExceptionCase(
            code="UNMATCHED_LEDGER_ENTRY",
            severity="medium",
            source_record_ids=[entry.id],
            message="Ledger entry has no evidence-backed settlement match.",
        )
        for entry in batch.ledger_entries
        if entry.id not in used_ledger_ids
    ]

    input_hash = _stable_hash(batch.to_dict())
    decision_payload = [asdict(group) for group in groups]
    audit_events = [
        AuditEvent(
            id=f"audit_{_stable_hash([input_hash, group.settlement_id])[:16]}",
            actor="reconx-policy-engine",
            action=group.state.value,
            reason_codes=group.reason_codes,
            input_hash=input_hash,
            decision_hash=_stable_hash(decision_payload),
            policy_version=POLICY_VERSION,
            occurred_at=next(
                settlement.settled_at
                for settlement in batch.settlements
                if settlement.id == group.settlement_id
            ),
        )
        for group in groups
    ]
    elapsed_ms = (time.perf_counter() - started) * 1000
    return BatchResult(
        batch_id=batch.batch_id,
        synthetic=batch.synthetic,
        source_record_count=batch.source_record_count,
        groups=groups,
        exceptions=exceptions,
        audit_events=audit_events,
        elapsed_ms=elapsed_ms,
    )
