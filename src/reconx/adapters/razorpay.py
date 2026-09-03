from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from reconx.domain.webhook import NormalizedRazorpayEvent

RAZORPAY_RECON_URL = "https://api.razorpay.com/v1/settlements/recon/combined"
RECON_PAGE_SIZE = 1_000
MAX_RECON_ITEMS = 10_000
SUPPORTED_WEBHOOK_EVENTS = {
    "payment.captured": ("payment", "captured"),
    "refund.processed": ("refund", "processed"),
    "settlement.processed": ("settlement", "processed"),
}
SIGNATURE_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
EVENT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")


class RazorpayAdapterError(ValueError):
    pass


class WebhookSignatureError(RazorpayAdapterError):
    pass


class WebhookPayloadError(RazorpayAdapterError):
    pass


class RazorpayApiError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class WebhookSecret:
    key_id: str
    value: bytes

    def __post_init__(self) -> None:
        if not self.key_id or not self.value:
            raise ValueError("webhook secret requires a key id and non-empty value")


def validate_event_id(event_id: str) -> str:
    if not isinstance(event_id, str) or not EVENT_ID_PATTERN.fullmatch(event_id):
        raise WebhookPayloadError("invalid X-Razorpay-Event-Id")
    return event_id


def verify_webhook_signature(
    raw_body: bytes,
    signature: str,
    secrets: tuple[WebhookSecret, ...],
) -> str:
    """Verify HMAC-SHA256 against exact request bytes using constant-time comparison."""

    if not secrets:
        raise WebhookSignatureError("webhook verification is not configured")
    if not isinstance(signature, str) or not SIGNATURE_PATTERN.fullmatch(signature.strip()):
        raise WebhookSignatureError("invalid webhook signature format")
    received = signature.strip().lower()
    matched_key_id: str | None = None
    for secret in secrets:
        expected = hmac.new(secret.value, raw_body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, received):
            matched_key_id = secret.key_id
    if matched_key_id is None:
        raise WebhookSignatureError("webhook signature mismatch")
    return matched_key_id


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WebhookPayloadError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _validate_json_shape(value: Any, *, depth: int = 0) -> None:
    if depth > 12:
        raise WebhookPayloadError("webhook JSON nesting exceeds limit")
    if isinstance(value, dict):
        if len(value) > 100:
            raise WebhookPayloadError("webhook JSON object exceeds field limit")
        for child in value.values():
            _validate_json_shape(child, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 500:
            raise WebhookPayloadError("webhook JSON array exceeds item limit")
        for child in value:
            _validate_json_shape(child, depth=depth + 1)


def _require_string(entity: dict[str, Any], field: str) -> str:
    value = entity.get(field)
    if not isinstance(value, str) or not value:
        raise WebhookPayloadError(f"entity {field} must be non-empty text")
    return value


def _optional_string(entity: dict[str, Any], field: str) -> str | None:
    value = entity.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise WebhookPayloadError(f"entity {field} must be text when present")
    return value


def _require_non_negative_integer(entity: dict[str, Any], field: str) -> int:
    value = entity.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WebhookPayloadError(f"entity {field} must be a non-negative integer")
    return value


def parse_webhook_payload(raw_body: bytes) -> NormalizedRazorpayEvent:
    try:
        payload = json.loads(raw_body.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except UnicodeDecodeError as exc:
        raise WebhookPayloadError("webhook body must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise WebhookPayloadError("webhook body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise WebhookPayloadError("webhook payload must be one JSON object")
    _validate_json_shape(payload)

    event_type = payload.get("event")
    created_at = payload.get("created_at")
    if not isinstance(event_type, str) or not event_type:
        raise WebhookPayloadError("webhook event must be non-empty text")
    if isinstance(created_at, bool) or not isinstance(created_at, int) or created_at < 0:
        raise WebhookPayloadError("webhook created_at must be a Unix timestamp")

    if event_type not in SUPPORTED_WEBHOOK_EVENTS:
        return NormalizedRazorpayEvent(
            event_type=event_type,
            event_created_at=created_at,
            entity_type=None,
            entity_id=None,
            entity_status=None,
            amount_paise=None,
            currency=None,
            data={},
        )

    entity_type, required_status = SUPPORTED_WEBHOOK_EVENTS[event_type]
    payload_container = payload.get("payload")
    if not isinstance(payload_container, dict):
        raise WebhookPayloadError("webhook payload field must be an object")
    entity_container = payload_container.get(entity_type)
    if not isinstance(entity_container, dict) or not isinstance(
        entity_container.get("entity"), dict
    ):
        raise WebhookPayloadError(f"webhook is missing payload.{entity_type}.entity")
    entity = entity_container["entity"]
    entity_id = _require_string(entity, "id")
    if _require_string(entity, "entity") != entity_type:
        raise WebhookPayloadError("entity type does not match webhook event")
    status = _require_string(entity, "status")
    if status != required_status:
        raise WebhookPayloadError("entity status does not match webhook event")
    amount = _require_non_negative_integer(entity, "amount")
    currency = _optional_string(entity, "currency")
    if currency is not None and (
        len(currency) != 3 or not currency.isalpha() or not currency.isupper()
    ):
        raise WebhookPayloadError("entity currency must be a three-letter uppercase code")

    minimal: dict[str, Any] = {}
    if entity_type == "payment":
        minimal["order_id"] = _optional_string(entity, "order_id")
    elif entity_type == "refund":
        minimal["payment_id"] = _require_string(entity, "payment_id")
    else:
        fees = _require_non_negative_integer(entity, "fees")
        tax = _require_non_negative_integer(entity, "tax")
        if tax > fees:
            raise WebhookPayloadError("settlement tax cannot exceed fees")
        minimal.update(
            {
                "fees_paise": fees,
                "tax_paise": tax,
                "utr": _optional_string(entity, "utr"),
            }
        )

    return NormalizedRazorpayEvent(
        event_type=event_type,
        event_created_at=created_at,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_status=status,
        amount_paise=amount,
        currency=currency,
        data=minimal,
    )


@dataclass(slots=True, frozen=True)
class SettlementReconItem:
    entity_id: str
    item_type: str
    debit_paise: int
    credit_paise: int
    amount_paise: int
    fee_paise: int
    tax_paise: int
    currency: str
    created_at: int
    settled_at: int
    settlement_id: str
    settlement_utr: str | None
    payment_id: str | None
    order_id: str | None
    supported_for_reconciliation: bool
    validation_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "item_type": self.item_type,
            "debit_paise": self.debit_paise,
            "credit_paise": self.credit_paise,
            "amount_paise": self.amount_paise,
            "fee_paise": self.fee_paise,
            "tax_paise": self.tax_paise,
            "currency": self.currency,
            "created_at": self.created_at,
            "settled_at": self.settled_at,
            "settlement_id": self.settlement_id,
            "settlement_utr": self.settlement_utr,
            "payment_id": self.payment_id,
            "order_id": self.order_id,
            "supported_for_reconciliation": self.supported_for_reconciliation,
            "validation_codes": list(self.validation_codes),
        }


def parse_settlement_recon_response(payload: dict[str, Any]) -> list[SettlementReconItem]:
    if payload.get("entity") != "collection" or not isinstance(payload.get("items"), list):
        raise RazorpayAdapterError("settlement recon response must be a collection")
    if payload.get("count") != len(payload["items"]):
        raise RazorpayAdapterError("settlement recon count does not match items")
    parsed: list[SettlementReconItem] = []
    for item in payload["items"]:
        if not isinstance(item, dict):
            raise RazorpayAdapterError("settlement recon item must be an object")
        required_strings = ("entity_id", "type", "currency", "settlement_id")
        if any(not isinstance(item.get(key), str) or not item[key] for key in required_strings):
            raise RazorpayAdapterError("settlement recon item has invalid identifiers")
        integers: dict[str, int] = {}
        for key in ("debit", "credit", "amount", "fee", "tax", "created_at", "settled_at"):
            value = item.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RazorpayAdapterError(f"settlement recon {key} must be non-negative integer")
            integers[key] = value
        if integers["tax"] > integers["fee"]:
            raise RazorpayAdapterError("settlement recon tax cannot exceed inclusive fee")
        if len(item["currency"]) != 3 or not item["currency"].isupper():
            raise RazorpayAdapterError("settlement recon currency is invalid")
        validation_codes: list[str] = []
        item_type = item["type"]
        payment_id = _optional_string(item, "payment_id")
        order_id = _optional_string(item, "order_id")
        if integers["debit"] > 0 and integers["credit"] > 0:
            validation_codes.append("BOTH_DEBIT_AND_CREDIT_PRESENT")
        if item_type == "payment" and (
            integers["debit"] != 0
            or integers["credit"] != integers["amount"] - integers["fee"]
        ):
            validation_codes.append("PAYMENT_NET_CREDIT_MISMATCH")
        elif item_type == "refund" and (
            integers["credit"] != 0 or integers["debit"] != integers["amount"]
        ):
            validation_codes.append("REFUND_DEBIT_MISMATCH")
        if item_type == "refund" and not payment_id:
            validation_codes.append("REFUND_PAYMENT_ID_MISSING")
        elif item_type == "adjustment" and abs(
            integers["credit"] - integers["debit"]
        ) != integers["amount"]:
            validation_codes.append("ADJUSTMENT_AMOUNT_MISMATCH")
        elif item_type not in {"payment", "refund", "adjustment"}:
            validation_codes.append("UNSUPPORTED_RECON_ITEM_TYPE")
        parsed.append(
            SettlementReconItem(
                entity_id=item["entity_id"],
                item_type=item_type,
                debit_paise=integers["debit"],
                credit_paise=integers["credit"],
                amount_paise=integers["amount"],
                fee_paise=integers["fee"],
                tax_paise=integers["tax"],
                currency=item["currency"],
                created_at=integers["created_at"],
                settled_at=integers["settled_at"],
                settlement_id=item["settlement_id"],
                settlement_utr=_optional_string(item, "settlement_utr"),
                payment_id=payment_id,
                order_id=order_id,
                supported_for_reconciliation=not validation_codes,
                validation_codes=tuple(validation_codes),
            )
        )
    return parsed


Transport = Callable[[Request, float, int], bytes]


def _urllib_transport(request: Request, timeout_seconds: float, max_bytes: int) -> bytes:
    with urlopen(request, timeout=timeout_seconds) as response:
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise RazorpayApiError("Razorpay response exceeded configured size limit")
    return body


class RazorpaySettlementReconClient:
    def __init__(
        self,
        key_id: str,
        key_secret: str,
        *,
        transport: Transport = _urllib_transport,
        timeout_seconds: float = 4.0,
        max_response_bytes: int = 1_048_576,
    ) -> None:
        if not key_id or not key_secret:
            raise ValueError("Razorpay API credentials are required")
        self._key_id = key_id
        self._key_secret = key_secret
        self._transport = transport
        self._timeout_seconds = min(max(timeout_seconds, 0.1), 5.0)
        self._max_response_bytes = max_response_bytes

    def fetch(self, settlement_date: date) -> list[SettlementReconItem]:
        token = base64.b64encode(
            f"{self._key_id}:{self._key_secret}".encode()
        ).decode("ascii")
        collected: list[SettlementReconItem] = []
        seen_entities: set[tuple[str, str]] = set()
        for skip in range(0, MAX_RECON_ITEMS, RECON_PAGE_SIZE):
            query = urlencode(
                {
                    "year": settlement_date.year,
                    "month": f"{settlement_date.month:02d}",
                    "day": f"{settlement_date.day:02d}",
                    "count": RECON_PAGE_SIZE,
                    "skip": skip,
                }
            )
            request = Request(
                f"{RAZORPAY_RECON_URL}?{query}",
                headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
                method="GET",
            )
            try:
                raw = self._transport(
                    request, self._timeout_seconds, self._max_response_bytes
                )
                payload = json.loads(
                    raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
                )
            except (UnicodeDecodeError, json.JSONDecodeError, WebhookPayloadError) as exc:
                raise RazorpayApiError("Razorpay returned an invalid JSON response") from exc
            except RazorpayApiError:
                raise
            except Exception as exc:
                raise RazorpayApiError(
                    f"Razorpay request failed: {type(exc).__name__}"
                ) from exc
            if not isinstance(payload, dict):
                raise RazorpayApiError("Razorpay response must be a JSON object")
            if "error" in payload:
                error = payload.get("error")
                code = error.get("code") if isinstance(error, dict) else "unknown"
                raise RazorpayApiError(f"Razorpay API returned error code {code}")
            page = parse_settlement_recon_response(payload)
            for item in page:
                identity = (item.item_type, item.entity_id)
                if identity in seen_entities:
                    raise RazorpayApiError(
                        "Razorpay recon pagination repeated a transaction entity"
                    )
                seen_entities.add(identity)
                collected.append(item)
            if len(page) < RECON_PAGE_SIZE:
                return collected
        raise RazorpayApiError(
            f"Razorpay recon result exceeds the {MAX_RECON_ITEMS}-item safety limit"
        )
