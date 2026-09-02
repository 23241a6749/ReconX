from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from reconx.domain.models import (
    SCHEMA_VERSION,
    BankEntry,
    FinanceBatch,
    LedgerEntry,
    LineKind,
    Order,
    Payment,
    PaymentStatus,
    Refund,
    RefundStatus,
    Settlement,
    SettlementLine,
)


@dataclass(slots=True)
class ValidationIssue:
    source: str
    index: int | None
    record_id: str | None
    code: str
    severity: str
    message: str


@dataclass(slots=True)
class IngestionReport:
    batch: FinanceBatch
    raw_record_count: int
    accepted_record_count: int
    duplicate_record_count: int
    quarantined_record_count: int
    issues: list[ValidationIssue]

    def summary(self) -> dict[str, Any]:
        return {
            "raw_record_count": self.raw_record_count,
            "accepted_record_count": self.accepted_record_count,
            "duplicate_record_count": self.duplicate_record_count,
            "quarantined_record_count": self.quarantined_record_count,
            "issue_count": len(self.issues),
            "issues": [asdict(issue) for issue in self.issues],
        }


def _payment(raw: dict[str, Any]) -> Payment:
    return Payment(**{**raw, "status": PaymentStatus(raw["status"])})


def _refund(raw: dict[str, Any]) -> Refund:
    return Refund(**{**raw, "status": RefundStatus(raw["status"])})


def _line(raw: dict[str, Any]) -> SettlementLine:
    return SettlementLine(**{**raw, "kind": LineKind(raw["kind"])})


PARSERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "orders": lambda raw: Order(**raw),
    "payments": _payment,
    "refunds": _refund,
    "settlements": lambda raw: Settlement(**raw),
    "settlement_lines": _line,
    "bank_entries": lambda raw: BankEntry(**raw),
    "ledger_entries": lambda raw: LedgerEntry(**raw),
}


def _fingerprint(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)


def ingest_raw_batch(
    raw: dict[str, Any], *, supported_currencies: frozenset[str] = frozenset({"INR"})
) -> IngestionReport:
    issues: list[ValidationIssue] = []
    parsed: dict[str, list[Any]] = {source: [] for source in PARSERS}
    raw_count = duplicate_count = quarantined_count = 0

    schema_version = raw.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema version: {schema_version}")

    for source, parser in PARSERS.items():
        records = raw.get(source, [])
        if not isinstance(records, list):
            issues.append(
                ValidationIssue(
                    source, None, None, "SOURCE_NOT_A_LIST", "error", "Source must be an array."
                )
            )
            quarantined_count += 1
            continue

        seen: dict[str, str] = {}
        conflicted_ids: set[str] = set()
        for index, record in enumerate(records):
            raw_count += 1
            if not isinstance(record, dict):
                quarantined_count += 1
                issues.append(
                    ValidationIssue(
                        source,
                        index,
                        None,
                        "RECORD_NOT_AN_OBJECT",
                        "error",
                        "Record must be a JSON object.",
                    )
                )
                continue

            record_id = record.get("id")
            if not isinstance(record_id, str) or not record_id:
                quarantined_count += 1
                issues.append(
                    ValidationIssue(
                        source,
                        index,
                        None,
                        "MISSING_RECORD_ID",
                        "error",
                        "Record requires a non-empty string id.",
                    )
                )
                continue

            fingerprint = _fingerprint(record)
            if record_id in seen:
                duplicate_count += 1
                if seen[record_id] == fingerprint and record_id not in conflicted_ids:
                    issues.append(
                        ValidationIssue(
                            source,
                            index,
                            record_id,
                            "DUPLICATE_RECORD_DEDUPED",
                            "warning",
                            "Exact duplicate was ignored idempotently.",
                        )
                    )
                else:
                    if record_id not in conflicted_ids:
                        parsed[source] = [
                            accepted
                            for accepted in parsed[source]
                            if getattr(accepted, "id", None) != record_id
                        ]
                        quarantined_count += 2
                        conflicted_ids.add(record_id)
                    else:
                        quarantined_count += 1
                    issues.append(
                        ValidationIssue(
                            source,
                            index,
                            record_id,
                            "CONFLICTING_DUPLICATE_QUARANTINED",
                            "error",
                            "Duplicate id has a different payload.",
                        )
                    )
                continue
            seen[record_id] = fingerprint

            currency = record.get("currency")
            if currency is not None and currency not in supported_currencies:
                quarantined_count += 1
                issues.append(
                    ValidationIssue(
                        source,
                        index,
                        record_id,
                        "UNSUPPORTED_CURRENCY",
                        "error",
                        f"Currency {currency!r} is outside this build's supported scope.",
                    )
                )
                continue

            try:
                parsed[source].append(parser(record))
            except (KeyError, TypeError, ValueError) as exc:
                quarantined_count += 1
                issues.append(
                    ValidationIssue(
                        source,
                        index,
                        record_id,
                        "SCHEMA_VALIDATION_FAILED",
                        "error",
                        str(exc),
                    )
                )

    batch = FinanceBatch(
        batch_id=str(raw.get("batch_id", "unknown_batch")),
        schema_version=SCHEMA_VERSION,
        synthetic=bool(raw.get("synthetic", False)),
        orders=parsed["orders"],
        payments=parsed["payments"],
        refunds=parsed["refunds"],
        settlements=parsed["settlements"],
        settlement_lines=parsed["settlement_lines"],
        bank_entries=parsed["bank_entries"],
        ledger_entries=parsed["ledger_entries"],
    )

    order_ids = {item.id for item in batch.orders}
    payment_ids = {item.id for item in batch.payments}
    refund_ids = {item.id for item in batch.refunds}
    settlement_ids = {item.id for item in batch.settlements}
    for payment in batch.payments:
        if payment.order_id not in order_ids:
            issues.append(
                ValidationIssue(
                    "payments",
                    None,
                    payment.id,
                    "ORDER_REFERENCE_NOT_FOUND",
                    "warning",
                    f"Order {payment.order_id} is missing.",
                )
            )
    for refund in batch.refunds:
        if refund.payment_id not in payment_ids:
            issues.append(
                ValidationIssue(
                    "refunds",
                    None,
                    refund.id,
                    "PAYMENT_REFERENCE_NOT_FOUND",
                    "warning",
                    f"Payment {refund.payment_id} is missing.",
                )
            )
    for line in batch.settlement_lines:
        if line.settlement_id not in settlement_ids:
            issues.append(
                ValidationIssue(
                    "settlement_lines",
                    None,
                    line.id,
                    "SETTLEMENT_REFERENCE_NOT_FOUND",
                    "warning",
                    f"Settlement {line.settlement_id} is missing.",
                )
            )
        expected_ids = payment_ids if line.kind is LineKind.PAYMENT else refund_ids
        if line.kind is not LineKind.ADJUSTMENT and line.entity_id not in expected_ids:
            issues.append(
                ValidationIssue(
                    "settlement_lines",
                    None,
                    line.id,
                    "ENTITY_REFERENCE_NOT_FOUND",
                    "warning",
                    f"Entity {line.entity_id} is missing.",
                )
            )

    return IngestionReport(
        batch=batch,
        raw_record_count=raw_count,
        accepted_record_count=batch.source_record_count,
        duplicate_record_count=duplicate_count,
        quarantined_record_count=quarantined_count,
        issues=issues,
    )
