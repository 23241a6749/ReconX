from __future__ import annotations

from reconx.domain.models import (
    BankEntry,
    FinanceBatch,
    LedgerEntry,
    LineKind,
    Order,
    Payment,
    PaymentStatus,
    Refund,
    RefundStatus,
    SCHEMA_VERSION,
    Settlement,
    SettlementLine,
)


def build_demo_batch() -> FinanceBatch:
    """Return a fixed, understandable grouped-settlement fixture.

    Gross payments are ₹7,500.00, one partial refund is ₹500.00 and the inclusive
    gateway fee is ₹177.00 (of which ₹27.00 is tax). Expected bank credit is
    therefore ₹6,823.00. Tax is not deducted twice.
    """

    timestamp = "2026-08-30T10:00:00Z"
    orders = [
        Order("order_demo_01", "SHOP-1001", 100_000, "INR", timestamp),
        Order("order_demo_02", "SHOP-1002", 250_000, "INR", timestamp),
        Order("order_demo_03", "SHOP-1003", 400_000, "INR", timestamp),
    ]
    payments = [
        Payment(
            "pay_demo_01",
            "order_demo_01",
            100_000,
            2_360,
            360,
            "INR",
            PaymentStatus.CAPTURED,
            timestamp,
        ),
        Payment(
            "pay_demo_02",
            "order_demo_02",
            250_000,
            5_900,
            900,
            "INR",
            PaymentStatus.CAPTURED,
            timestamp,
        ),
        Payment(
            "pay_demo_03",
            "order_demo_03",
            400_000,
            9_440,
            1_440,
            "INR",
            PaymentStatus.CAPTURED,
            timestamp,
        ),
    ]
    refunds = [
        Refund(
            "rfnd_demo_01",
            "pay_demo_03",
            50_000,
            "INR",
            RefundStatus.PROCESSED,
            timestamp,
        )
    ]
    settlements = [Settlement("setl_demo_01", "UTR-DEMO-682300", "INR", timestamp)]
    settlement_lines = [
        SettlementLine(
            "line_pay_01", "setl_demo_01", LineKind.PAYMENT, "pay_demo_01", 100_000, 2_360, 360
        ),
        SettlementLine(
            "line_pay_02", "setl_demo_01", LineKind.PAYMENT, "pay_demo_02", 250_000, 5_900, 900
        ),
        SettlementLine(
            "line_pay_03", "setl_demo_01", LineKind.PAYMENT, "pay_demo_03", 400_000, 9_440, 1_440
        ),
        SettlementLine(
            "line_rfnd_01", "setl_demo_01", LineKind.REFUND, "rfnd_demo_01", 50_000, 0, 0
        ),
    ]
    bank_entries = [
        BankEntry(
            "bank_demo_01",
            "UTR-DEMO-682300",
            682_300,
            "INR",
            "2026-08-30",
            "RAZORPAY SETTLEMENT UTR-DEMO-682300",
        )
    ]
    ledger_entries = [
        LedgerEntry("ledger_demo_01", "setl_demo_01", 682_300, "INR", timestamp),
        LedgerEntry("ledger_orphan_01", "UNKNOWN-REF", 12_345, "INR", timestamp),
    ]
    return FinanceBatch(
        batch_id="batch_demo_v1",
        schema_version=SCHEMA_VERSION,
        synthetic=True,
        orders=orders,
        payments=payments,
        refunds=refunds,
        settlements=settlements,
        settlement_lines=settlement_lines,
        bank_entries=bank_entries,
        ledger_entries=ledger_entries,
    )

