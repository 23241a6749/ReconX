from __future__ import annotations

import copy
import hashlib
import json
import random
from collections import Counter
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from reconx.domain.models import SCHEMA_VERSION


class Scenario(StrEnum):
    DUPLICATE_EVENT = "duplicate_event"
    CONFLICTING_DUPLICATE = "conflicting_duplicate"
    OUT_OF_ORDER = "out_of_order"
    MISSING_UTR = "missing_utr"
    MALFORMED_UTR = "malformed_utr"
    DELAYED_SETTLEMENT = "delayed_settlement"
    BANK_HOLIDAY_SHIFT = "bank_holiday_shift"
    ONE_TO_MANY_SETTLEMENT = "one_to_many_settlement"
    SPLIT_LEDGER = "split_ledger"
    PARTIAL_REFUND = "partial_refund"
    MULTIPLE_PARTIAL_REFUNDS = "multiple_partial_refunds"
    POST_SETTLEMENT_REFUND = "post_settlement_refund"
    FEE_MISMATCH = "fee_mismatch"
    TAX_MISMATCH = "tax_mismatch"
    AMOUNT_COLLISION = "amount_collision"
    CAPTURED_PAYMENT_MISSING_LEDGER = "captured_payment_missing_ledger"
    ORPHAN_LEDGER = "orphan_ledger"
    DUPLICATE_BANK_CREDIT = "duplicate_bank_credit"
    REVERSAL_ADJUSTMENT = "reversal_adjustment"
    UNSUPPORTED_CURRENCY = "unsupported_currency"
    CORRUPT_ROW = "corrupt_row"
    EQUAL_SCORE_AMBIGUITY = "equal_score_ambiguity"


SCENARIOS = list(Scenario)
SAFE_AUTO_SCENARIOS = {
    Scenario.DUPLICATE_EVENT,
    Scenario.OUT_OF_ORDER,
    Scenario.MISSING_UTR,
    Scenario.MALFORMED_UTR,
    Scenario.DELAYED_SETTLEMENT,
    Scenario.BANK_HOLIDAY_SHIFT,
    Scenario.ONE_TO_MANY_SETTLEMENT,
    Scenario.PARTIAL_REFUND,
    Scenario.MULTIPLE_PARTIAL_REFUNDS,
    Scenario.AMOUNT_COLLISION,
    Scenario.ORPHAN_LEDGER,
    Scenario.REVERSAL_ADJUSTMENT,
    Scenario.CORRUPT_ROW,
}


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _fee(amount_paise: int) -> tuple[int, int]:
    inclusive_fee = max(1, amount_paise * 236 // 10_000)
    tax_component = inclusive_fee * 18 // 118
    return inclusive_fee, tax_component


def _base_group(
    index: int,
    scenario: Scenario,
    *,
    namespace: str = "dev",
    time_origin: datetime = datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
    amount_offset_paise: int = 0,
) -> dict[str, Any]:
    suffix = f"{index:04d}"
    token = namespace.upper()
    settled_at = time_origin + timedelta(days=index % 25, minutes=index)
    created_at = settled_at - timedelta(days=2)
    settlement_id = f"setl_{namespace}_{suffix}"
    utr = f"UTR-{token}-{suffix}"
    amounts = [
        100_000 + amount_offset_paise + index * 101,
        250_000 + amount_offset_paise + index * 103,
        400_000 + amount_offset_paise + index * 107,
    ]

    orders: list[dict[str, Any]] = []
    payments: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for position, amount in enumerate(amounts, 1):
        order_id = f"order_{namespace}_{suffix}_{position}"
        payment_id = f"pay_{namespace}_{suffix}_{position}"
        fee, tax = _fee(amount)
        orders.append(
            {
                "id": order_id,
                "merchant_reference": f"SHOP-{suffix}-{position}",
                "amount_paise": amount,
                "currency": "INR",
                "created_at": _iso(created_at),
            }
        )
        payments.append(
            {
                "id": payment_id,
                "order_id": order_id,
                "amount_paise": amount,
                "fee_paise": fee,
                "tax_paise": tax,
                "currency": "INR",
                "status": "captured",
                "created_at": _iso(created_at),
            }
        )
        lines.append(
            {
                "id": f"line_{namespace}_{suffix}_pay_{position}",
                "settlement_id": settlement_id,
                "kind": "payment",
                "entity_id": payment_id,
                "amount_paise": amount,
                "fee_paise": fee,
                "tax_paise": tax,
            }
        )

    refunds: list[dict[str, Any]] = []
    if scenario in {
        Scenario.PARTIAL_REFUND,
        Scenario.MULTIPLE_PARTIAL_REFUNDS,
        Scenario.POST_SETTLEMENT_REFUND,
    }:
        refund_count = 2 if scenario is Scenario.MULTIPLE_PARTIAL_REFUNDS else 1
        for position in range(1, refund_count + 1):
            refund_id = f"rfnd_{namespace}_{suffix}_{position}"
            refund_amount = 20_000 + position * 5_000 + index
            refund_created = (
                settled_at + timedelta(days=1)
                if scenario is Scenario.POST_SETTLEMENT_REFUND
                else settled_at - timedelta(hours=3)
            )
            refunds.append(
                {
                    "id": refund_id,
                    "payment_id": payments[-1]["id"],
                    "amount_paise": refund_amount,
                    "currency": "INR",
                    "status": "processed",
                    "created_at": _iso(refund_created),
                }
            )
            lines.append(
                {
                    "id": f"line_{namespace}_{suffix}_rfnd_{position}",
                    "settlement_id": settlement_id,
                    "kind": "refund",
                    "entity_id": refund_id,
                    "amount_paise": refund_amount,
                    "fee_paise": 0,
                    "tax_paise": 0,
                }
            )

    if scenario is Scenario.REVERSAL_ADJUSTMENT:
        lines.append(
            {
                "id": f"line_{namespace}_{suffix}_adjustment",
                "settlement_id": settlement_id,
                "kind": "adjustment",
                "entity_id": f"adj_{namespace}_{suffix}",
                "amount_paise": -1_234,
                "fee_paise": 0,
                "tax_paise": 0,
            }
        )

    gross = sum(line["amount_paise"] for line in lines if line["kind"] == "payment")
    refund_total = sum(line["amount_paise"] for line in lines if line["kind"] == "refund")
    inclusive_fees = sum(line["fee_paise"] for line in lines if line["kind"] == "payment")
    adjustments = sum(line["amount_paise"] for line in lines if line["kind"] == "adjustment")
    expected = gross - refund_total - inclusive_fees + adjustments

    settlement = {
        "id": settlement_id,
        "utr": utr,
        "currency": "INR",
        "settled_at": _iso(settled_at),
    }
    bank_date = settled_at.date()
    if scenario is Scenario.DELAYED_SETTLEMENT:
        bank_date += timedelta(days=7)
    elif scenario is Scenario.BANK_HOLIDAY_SHIFT:
        bank_date += timedelta(days=3)
    bank = {
        "id": f"bank_{namespace}_{suffix}",
        "utr": utr,
        "amount_paise": expected,
        "currency": "INR",
        "value_date": bank_date.isoformat(),
        "narration": f"RAZORPAY {settlement_id} {utr}",
    }
    ledger = {
        "id": f"ledger_{namespace}_{suffix}",
        "reference": settlement_id,
        "amount_paise": expected,
        "currency": "INR",
        "booked_at": _iso(settled_at),
    }
    bank_entries = [bank]
    ledger_entries = [ledger]

    if scenario is Scenario.MISSING_UTR:
        settlement["utr"] = ""
    elif scenario is Scenario.MALFORMED_UTR:
        settlement["utr"] = f"BROKEN-{suffix}"
    elif scenario is Scenario.SPLIT_LEDGER:
        ledger_entries = [
            {**ledger, "id": f"ledger_{namespace}_{suffix}_a", "reference": f"{settlement_id}-A", "amount_paise": expected // 2},
            {**ledger, "id": f"ledger_{namespace}_{suffix}_b", "reference": f"{settlement_id}-B", "amount_paise": expected - expected // 2},
        ]
    elif scenario is Scenario.FEE_MISMATCH:
        payments[0]["fee_paise"] += 1
    elif scenario is Scenario.TAX_MISMATCH:
        payments[0]["tax_paise"] += 1
    elif scenario is Scenario.AMOUNT_COLLISION:
        settlement["utr"] = ""
        bank_entries.append(
            {
                **bank,
                "id": f"bank_{namespace}_{suffix}_collision",
                "utr": f"UTR-DECOY-{suffix}",
                "narration": "GENERIC RAZORPAY CREDIT",
            }
        )
    elif scenario is Scenario.CAPTURED_PAYMENT_MISSING_LEDGER:
        ledger_entries = []
    elif scenario is Scenario.ORPHAN_LEDGER:
        ledger_entries.append(
            {
                "id": f"ledger_{namespace}_{suffix}_orphan",
                "reference": f"UNKNOWN-{suffix}",
                "amount_paise": 12_345 + index,
                "currency": "INR",
                "booked_at": _iso(settled_at),
            }
        )
    elif scenario is Scenario.DUPLICATE_BANK_CREDIT:
        bank_entries.append({**bank, "id": f"bank_{namespace}_{suffix}_duplicate"})
    elif scenario is Scenario.UNSUPPORTED_CURRENCY:
        for record in [*orders, *payments, *refunds, settlement, *bank_entries, *ledger_entries]:
            record["currency"] = "USD"
    elif scenario is Scenario.EQUAL_SCORE_AMBIGUITY:
        settlement["utr"] = ""
        bank_entries[0]["narration"] = "GENERIC RAZORPAY CREDIT"
        bank_entries.append(
            {
                **bank,
                "id": f"bank_{namespace}_{suffix}_ambiguous",
                "utr": f"UTR-OTHER-{suffix}",
                "narration": "GENERIC RAZORPAY CREDIT",
            }
        )

    if scenario is Scenario.DUPLICATE_EVENT:
        payments.append(copy.deepcopy(payments[0]))
    elif scenario is Scenario.CONFLICTING_DUPLICATE:
        conflicting = copy.deepcopy(payments[0])
        conflicting["amount_paise"] += 1
        payments.append(conflicting)
    elif scenario is Scenario.CORRUPT_ROW:
        payments.append(
            {
                "id": f"pay_{namespace}_{suffix}_corrupt",
                "order_id": orders[0]["id"],
                "currency": "INR",
                "status": "captured"
            }
        )

    return {
        "orders": orders,
        "payments": payments,
        "refunds": refunds,
        "settlements": [settlement],
        "settlement_lines": lines,
        "bank_entries": bank_entries,
        "ledger_entries": ledger_entries,
        "truth": {
            "settlement_id": settlement_id,
            "bank_entry_id": bank["id"],
            "scenario": scenario.value,
            "should_auto_approve": scenario in SAFE_AUTO_SCENARIOS,
            "expected_bank_credit_paise": expected,
        },
    }


def build_development_dataset(
    *, group_count: int = 66, seed: int = 20_260_830
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if group_count < len(SCENARIOS):
        raise ValueError(f"group_count must be at least {len(SCENARIOS)}")

    raw: dict[str, Any] = {
        "batch_id": f"batch_development_{group_count}",
        "schema_version": SCHEMA_VERSION,
        "synthetic": True,
        "orders": [],
        "payments": [],
        "refunds": [],
        "settlements": [],
        "settlement_lines": [],
        "bank_entries": [],
        "ledger_entries": [],
    }
    truth_groups: list[dict[str, Any]] = []
    scenario_counts: Counter[str] = Counter()
    for index in range(group_count):
        scenario = SCENARIOS[index % len(SCENARIOS)]
        scenario_counts[scenario.value] += 1
        group = _base_group(index, scenario)
        for source in (
            "orders",
            "payments",
            "refunds",
            "settlements",
            "settlement_lines",
            "bank_entries",
            "ledger_entries",
        ):
            raw[source].extend(group[source])
        truth_groups.append(group["truth"])

    rng = random.Random(seed)
    for source in (
        "orders",
        "payments",
        "refunds",
        "settlements",
        "settlement_lines",
        "bank_entries",
        "ledger_entries",
    ):
        rng.shuffle(raw[source])

    raw_record_count = sum(
        len(raw[source])
        for source in (
            "orders",
            "payments",
            "refunds",
            "settlements",
            "settlement_lines",
            "bank_entries",
            "ledger_entries",
        )
    )
    manifest = {
        "batch_id": raw["batch_id"],
        "schema_version": SCHEMA_VERSION,
        "seed": seed,
        "group_count": group_count,
        "raw_record_count": raw_record_count,
        "scenario_count": len(SCENARIOS),
        "scenario_counts": dict(sorted(scenario_counts.items())),
    }
    ground_truth = {
        "batch_id": raw["batch_id"],
        "schema_version": SCHEMA_VERSION,
        "groups": truth_groups,
    }
    manifest["raw_batch_sha256"] = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest["ground_truth_sha256"] = hashlib.sha256(
        json.dumps(ground_truth, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return raw, manifest, ground_truth
