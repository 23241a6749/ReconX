from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = "1.0"


class PaymentStatus(StrEnum):
    CAPTURED = "captured"
    FAILED = "failed"


class RefundStatus(StrEnum):
    PROCESSED = "processed"
    PENDING = "pending"


class LineKind(StrEnum):
    PAYMENT = "payment"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class DecisionState(StrEnum):
    AUTO_APPROVED = "auto_approved"
    REVIEW_REQUIRED = "review_required"
    UNRESOLVED = "unresolved"


def _require_non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _require_currency(value: str) -> None:
    if len(value) != 3 or not value.isalpha() or not value.isupper():
        raise ValueError("currency must be a three-letter uppercase code")


def _require_datetime(name: str, value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")


def _require_date(name: str, value: str) -> None:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO-8601 date") from exc


@dataclass(slots=True)
class Order:
    id: str
    merchant_reference: str
    amount_paise: int
    currency: str
    created_at: str

    def __post_init__(self) -> None:
        _require_non_negative("order amount", self.amount_paise)
        _require_currency(self.currency)
        _require_datetime("order created_at", self.created_at)


@dataclass(slots=True)
class Payment:
    id: str
    order_id: str
    amount_paise: int
    fee_paise: int
    tax_paise: int
    currency: str
    status: PaymentStatus
    created_at: str

    def __post_init__(self) -> None:
        _require_non_negative("payment amount", self.amount_paise)
        _require_non_negative("payment fee", self.fee_paise)
        _require_non_negative("payment tax", self.tax_paise)
        if self.tax_paise > self.fee_paise:
            raise ValueError("payment tax must be a component of fee")
        _require_currency(self.currency)
        _require_datetime("payment created_at", self.created_at)


@dataclass(slots=True)
class Refund:
    id: str
    payment_id: str
    amount_paise: int
    currency: str
    status: RefundStatus
    created_at: str

    def __post_init__(self) -> None:
        _require_non_negative("refund amount", self.amount_paise)
        _require_currency(self.currency)
        _require_datetime("refund created_at", self.created_at)


@dataclass(slots=True)
class Settlement:
    id: str
    utr: str
    currency: str
    settled_at: str

    def __post_init__(self) -> None:
        _require_currency(self.currency)
        _require_datetime("settlement settled_at", self.settled_at)


@dataclass(slots=True)
class SettlementLine:
    id: str
    settlement_id: str
    kind: LineKind
    entity_id: str
    amount_paise: int
    fee_paise: int
    tax_paise: int

    def __post_init__(self) -> None:
        if self.kind is not LineKind.ADJUSTMENT:
            _require_non_negative("settlement line amount", self.amount_paise)
        _require_non_negative("settlement line fee", self.fee_paise)
        _require_non_negative("settlement line tax", self.tax_paise)
        if self.tax_paise > self.fee_paise:
            raise ValueError("settlement tax must be a component of fee")


@dataclass(slots=True)
class BankEntry:
    id: str
    utr: str
    amount_paise: int
    currency: str
    value_date: str
    narration: str

    def __post_init__(self) -> None:
        _require_currency(self.currency)
        _require_date("bank value_date", self.value_date)


@dataclass(slots=True)
class LedgerEntry:
    id: str
    reference: str
    amount_paise: int
    currency: str
    booked_at: str

    def __post_init__(self) -> None:
        _require_currency(self.currency)
        _require_datetime("ledger booked_at", self.booked_at)


@dataclass(slots=True)
class FinanceBatch:
    batch_id: str
    schema_version: str
    synthetic: bool
    orders: list[Order]
    payments: list[Payment]
    refunds: list[Refund]
    settlements: list[Settlement]
    settlement_lines: list[SettlementLine]
    bank_entries: list[BankEntry]
    ledger_entries: list[LedgerEntry]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FinanceBatch:
        if raw.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema version: {raw.get('schema_version')}")
        return cls(
            batch_id=raw["batch_id"],
            schema_version=raw["schema_version"],
            synthetic=bool(raw["synthetic"]),
            orders=[Order(**item) for item in raw.get("orders", [])],
            payments=[
                Payment(**{**item, "status": PaymentStatus(item["status"])})
                for item in raw.get("payments", [])
            ],
            refunds=[
                Refund(**{**item, "status": RefundStatus(item["status"])})
                for item in raw.get("refunds", [])
            ],
            settlements=[Settlement(**item) for item in raw.get("settlements", [])],
            settlement_lines=[
                SettlementLine(**{**item, "kind": LineKind(item["kind"])})
                for item in raw.get("settlement_lines", [])
            ],
            bank_entries=[BankEntry(**item) for item in raw.get("bank_entries", [])],
            ledger_entries=[LedgerEntry(**item) for item in raw.get("ledger_entries", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def source_record_count(self) -> int:
        return sum(
            len(records)
            for records in (
                self.orders,
                self.payments,
                self.refunds,
                self.settlements,
                self.settlement_lines,
                self.bank_entries,
                self.ledger_entries,
            )
        )
