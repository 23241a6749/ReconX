from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from reconx.domain.webhook import (
    EntitySnapshot,
    NormalizedRazorpayEvent,
    WebhookOutcome,
    WebhookReceipt,
)


class WebhookConflictError(RuntimeError):
    pass


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class SQLiteWebhookStore:
    """Transactional delivery ledger and latest-entity projection.

    A fresh connection is used per operation so the store is safe across request
    threads. `BEGIN IMMEDIATE` serialises event-id claims and makes duplicate handling
    atomic across processes sharing the same SQLite database.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialise(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS webhook_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    entity_type TEXT,
                    entity_id TEXT,
                    event_created_at INTEGER NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    signature_key_id TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    delivery_count INTEGER NOT NULL DEFAULT 1,
                    normalised_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entity_snapshots (
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    event_created_at INTEGER NOT NULL,
                    entity_status TEXT,
                    amount_paise INTEGER,
                    currency TEXT,
                    data_json TEXT NOT NULL,
                    PRIMARY KEY (entity_type, entity_id)
                );
                CREATE TABLE IF NOT EXISTS webhook_audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    signature_key_id TEXT NOT NULL,
                    previous_hash TEXT,
                    event_hash TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _append_audit(
        connection: sqlite3.Connection,
        *,
        event_id: str,
        action: str,
        reason: str,
        payload_sha256: str,
        signature_key_id: str,
        occurred_at: str,
    ) -> None:
        previous = connection.execute(
            "SELECT event_hash FROM webhook_audit ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["event_hash"] if previous else None
        payload = {
            "event_id": event_id,
            "action": action,
            "reason": reason,
            "payload_sha256": payload_sha256,
            "signature_key_id": signature_key_id,
            "previous_hash": previous_hash,
            "occurred_at": occurred_at,
        }
        connection.execute(
            """
            INSERT INTO webhook_audit (
                event_id, action, reason, payload_sha256, signature_key_id,
                previous_hash, event_hash, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                action,
                reason,
                payload_sha256,
                signature_key_id,
                previous_hash,
                _hash(payload),
                occurred_at,
            ),
        )

    def record(
        self,
        *,
        event_id: str,
        event: NormalizedRazorpayEvent,
        payload_sha256: str,
        signature_key_id: str,
        received_at: str,
    ) -> WebhookReceipt:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM webhook_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if existing:
                if existing["payload_sha256"] != payload_sha256:
                    raise WebhookConflictError(
                        "event id was previously received with a different payload"
                    )
                connection.execute(
                    "UPDATE webhook_events SET delivery_count = delivery_count + 1 WHERE event_id = ?",
                    (event_id,),
                )
                self._append_audit(
                    connection,
                    event_id=event_id,
                    action=WebhookOutcome.DUPLICATE.value,
                    reason="same event id and payload hash already committed",
                    payload_sha256=payload_sha256,
                    signature_key_id=signature_key_id,
                    occurred_at=received_at,
                )
                connection.commit()
                return WebhookReceipt(
                    event_id=event_id,
                    event_type=existing["event_type"],
                    outcome=WebhookOutcome.DUPLICATE,
                    entity_type=existing["entity_type"],
                    entity_id=existing["entity_id"],
                    event_created_at=existing["event_created_at"],
                    payload_sha256=payload_sha256,
                    duplicate=True,
                )

            outcome = WebhookOutcome.UNSUPPORTED
            reason = "valid signed event is outside the configured allow-list"
            if event.entity_type is not None and event.entity_id is not None:
                snapshot = connection.execute(
                    """
                    SELECT event_created_at, event_id
                    FROM entity_snapshots
                    WHERE entity_type = ? AND entity_id = ?
                    """,
                    (event.entity_type, event.entity_id),
                ).fetchone()
                incoming_order = (event.event_created_at, event_id)
                current_order = (
                    (snapshot["event_created_at"], snapshot["event_id"])
                    if snapshot
                    else None
                )
                if current_order is None or incoming_order > current_order:
                    connection.execute(
                        """
                        INSERT INTO entity_snapshots (
                            entity_type, entity_id, event_type, event_id,
                            event_created_at, entity_status, amount_paise,
                            currency, data_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                            event_type = excluded.event_type,
                            event_id = excluded.event_id,
                            event_created_at = excluded.event_created_at,
                            entity_status = excluded.entity_status,
                            amount_paise = excluded.amount_paise,
                            currency = excluded.currency,
                            data_json = excluded.data_json
                        """,
                        (
                            event.entity_type,
                            event.entity_id,
                            event.event_type,
                            event_id,
                            event.event_created_at,
                            event.entity_status,
                            event.amount_paise,
                            event.currency,
                            json.dumps(event.data, sort_keys=True, separators=(",", ":")),
                        ),
                    )
                    outcome = WebhookOutcome.APPLIED
                    reason = "newest signed event applied to entity projection"
                else:
                    outcome = WebhookOutcome.STALE_IGNORED
                    reason = "older or lower-tiebreak event cannot roll back entity projection"

            normalised = {
                "event_type": event.event_type,
                "event_created_at": event.event_created_at,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "entity_status": event.entity_status,
                "amount_paise": event.amount_paise,
                "currency": event.currency,
                "data": event.data,
            }
            connection.execute(
                """
                INSERT INTO webhook_events (
                    event_id, event_type, entity_type, entity_id,
                    event_created_at, payload_sha256, signature_key_id,
                    received_at, outcome, normalised_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event.event_type,
                    event.entity_type,
                    event.entity_id,
                    event.event_created_at,
                    payload_sha256,
                    signature_key_id,
                    received_at,
                    outcome.value,
                    json.dumps(normalised, sort_keys=True, separators=(",", ":")),
                ),
            )
            self._append_audit(
                connection,
                event_id=event_id,
                action=outcome.value,
                reason=reason,
                payload_sha256=payload_sha256,
                signature_key_id=signature_key_id,
                occurred_at=received_at,
            )
            connection.commit()
            return WebhookReceipt(
                event_id=event_id,
                event_type=event.event_type,
                outcome=outcome,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                event_created_at=event.event_created_at,
                payload_sha256=payload_sha256,
                duplicate=False,
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_snapshot(self, entity_type: str, entity_id: str) -> EntitySnapshot | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM entity_snapshots WHERE entity_type = ? AND entity_id = ?",
                (entity_type, entity_id),
            ).fetchone()
        if row is None:
            return None
        return EntitySnapshot(
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            event_type=row["event_type"],
            event_id=row["event_id"],
            event_created_at=row["event_created_at"],
            entity_status=row["entity_status"],
            amount_paise=row["amount_paise"],
            currency=row["currency"],
            data=json.loads(row["data_json"]),
        )

    def summary(self) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            unique_events = connection.execute(
                "SELECT COUNT(*) AS count FROM webhook_events"
            ).fetchone()["count"]
            deliveries = connection.execute(
                "SELECT COALESCE(SUM(delivery_count), 0) AS count FROM webhook_events"
            ).fetchone()["count"]
            snapshots = connection.execute(
                "SELECT COUNT(*) AS count FROM entity_snapshots"
            ).fetchone()["count"]
            audit_events = connection.execute(
                "SELECT COUNT(*) AS count FROM webhook_audit"
            ).fetchone()["count"]
            outcomes = {
                row["outcome"]: row["count"]
                for row in connection.execute(
                    "SELECT outcome, COUNT(*) AS count FROM webhook_events GROUP BY outcome"
                ).fetchall()
            }
        return {
            "unique_events": unique_events,
            "deliveries": deliveries,
            "entity_snapshots": snapshots,
            "audit_events": audit_events,
            "outcomes": outcomes,
        }

    def audit_events(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT * FROM webhook_audit ORDER BY sequence"
            ).fetchall()
        return [dict(row) for row in rows]

    def verify_audit_chain(self) -> bool:
        previous_hash: str | None = None
        for row in self.audit_events():
            payload = {
                "event_id": row["event_id"],
                "action": row["action"],
                "reason": row["reason"],
                "payload_sha256": row["payload_sha256"],
                "signature_key_id": row["signature_key_id"],
                "previous_hash": previous_hash,
                "occurred_at": row["occurred_at"],
            }
            if row["previous_hash"] != previous_hash or row["event_hash"] != _hash(payload):
                return False
            previous_hash = row["event_hash"]
        return True
