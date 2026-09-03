from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any

from reconx.adapters.razorpay import SettlementReconItem, parse_settlement_recon_response
from reconx.domain.models import SCHEMA_VERSION, FinanceBatch

MAX_CSV_BYTES = 2_000_000
MAX_CSV_ROWS = 10_000


class ImportValidationError(ValueError):
    pass


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def _read_csv(text: str, required: set[str], source: str) -> list[dict[str, str]]:
    if len(text.encode("utf-8")) > MAX_CSV_BYTES:
        raise ImportValidationError(f"{source} CSV exceeds 2 MB")
    try:
        reader = csv.DictReader(io.StringIO(text))
        fields = set(reader.fieldnames or [])
        if not required.issubset(fields):
            missing = ", ".join(sorted(required - fields))
            raise ImportValidationError(f"{source} CSV is missing columns: {missing}")
        rows = list(reader)
    except csv.Error as exc:
        raise ImportValidationError(f"{source} CSV is invalid") from exc
    if len(rows) > MAX_CSV_ROWS:
        raise ImportValidationError(f"{source} CSV exceeds {MAX_CSV_ROWS} rows")
    return rows


def _canonical_from_items(
    items: list[SettlementReconItem], *, batch_id: str, synthetic: bool
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw: dict[str, Any] = {
        "batch_id": batch_id,
        "schema_version": SCHEMA_VERSION,
        "synthetic": synthetic,
        "orders": [],
        "payments": [],
        "refunds": [],
        "settlements": [],
        "settlement_lines": [],
        "bank_entries": [],
        "ledger_entries": [],
    }
    issues: list[dict[str, Any]] = []
    seen_orders: set[str] = set()
    seen_settlements: set[str] = set()
    for item in items:
        if not item.supported_for_reconciliation:
            issues.append(
                {
                    "entity_id": item.entity_id,
                    "item_type": item.item_type,
                    "codes": list(item.validation_codes),
                    "status": "quarantined",
                }
            )
            continue
        if item.settlement_id not in seen_settlements:
            raw["settlements"].append(
                {
                    "id": item.settlement_id,
                    "utr": item.settlement_utr or "",
                    "currency": item.currency,
                    "settled_at": _iso(item.settled_at),
                }
            )
            seen_settlements.add(item.settlement_id)
        if item.item_type == "payment":
            order_id = item.order_id or f"order_import_{item.entity_id}"
            if order_id not in seen_orders:
                raw["orders"].append(
                    {
                        "id": order_id,
                        "merchant_reference": f"import:{order_id}",
                        "amount_paise": item.amount_paise,
                        "currency": item.currency,
                        "created_at": _iso(item.created_at),
                    }
                )
                seen_orders.add(order_id)
            raw["payments"].append(
                {
                    "id": item.entity_id,
                    "order_id": order_id,
                    "amount_paise": item.amount_paise,
                    "fee_paise": item.fee_paise,
                    "tax_paise": item.tax_paise,
                    "currency": item.currency,
                    "status": "captured",
                    "created_at": _iso(item.created_at),
                }
            )
            line_kind = "payment"
        elif item.item_type == "refund":
            raw["refunds"].append(
                {
                    "id": item.entity_id,
                    "payment_id": item.payment_id or f"unknown_{item.entity_id}",
                    "amount_paise": item.amount_paise,
                    "currency": item.currency,
                    "status": "processed",
                    "created_at": _iso(item.created_at),
                }
            )
            line_kind = "refund"
        else:
            line_kind = "adjustment"
        raw["settlement_lines"].append(
            {
                "id": f"recon_{item.entity_id}",
                "settlement_id": item.settlement_id,
                "kind": line_kind,
                "entity_id": item.entity_id,
                "amount_paise": (
                    item.credit_paise - item.debit_paise
                    if line_kind == "adjustment"
                    else item.amount_paise
                ),
                "fee_paise": item.fee_paise,
                "tax_paise": item.tax_paise,
            }
        )
    return raw, issues


def import_reconciliation_inputs(payload: dict[str, Any]) -> tuple[FinanceBatch, list[dict[str, Any]]]:
    recon = payload.get("razorpay_recon")
    if not isinstance(recon, dict):
        raise ImportValidationError("razorpay_recon must be an official-shape JSON object")
    items = parse_settlement_recon_response(recon)
    raw, issues = _canonical_from_items(
        items,
        batch_id=str(payload.get("batch_id") or "imported_batch"),
        synthetic=bool(payload.get("synthetic", False)),
    )

    bank_csv = payload.get("bank_csv", "")
    ledger_csv = payload.get("ledger_csv", "")
    if not isinstance(bank_csv, str) or not isinstance(ledger_csv, str):
        raise ImportValidationError("bank_csv and ledger_csv must be text")
    for row in _read_csv(
        bank_csv, {"id", "utr", "amount_paise", "currency", "value_date", "narration"}, "bank"
    ):
        raw["bank_entries"].append(
            {
                **{key: row[key] for key in ("id", "utr", "currency", "value_date", "narration")},
                "amount_paise": int(row["amount_paise"]),
            }
        )
    for row in _read_csv(
        ledger_csv, {"id", "reference", "amount_paise", "currency", "booked_at"}, "ledger"
    ):
        raw["ledger_entries"].append(
            {
                **{key: row[key] for key in ("id", "reference", "currency", "booked_at")},
                "amount_paise": int(row["amount_paise"]),
            }
        )
    return FinanceBatch.from_dict(raw), issues


def canonical_from_recon_items(
    items: list[SettlementReconItem], *, batch_id: str, synthetic: bool = False
) -> tuple[FinanceBatch, list[dict[str, Any]]]:
    raw, issues = _canonical_from_items(items, batch_id=batch_id, synthetic=synthetic)
    return FinanceBatch.from_dict(raw), issues
