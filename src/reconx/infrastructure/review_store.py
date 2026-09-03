from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from reconx.application.analyst import fallback_evidence_and_risk
from reconx.application.review import ReviewConflictError, ReviewNotFoundError
from reconx.domain.analysis import ExceptionAnalysis, ExceptionCategory, SuggestedAction
from reconx.domain.review import ReviewCase, ReviewEvent, ReviewStatus


def _analysis(payload: dict[str, Any], reason_codes: list[str]) -> ExceptionAnalysis:
    missing_evidence, risk_level = fallback_evidence_and_risk(reason_codes)
    return ExceptionAnalysis(
        **{
            "missing_evidence_types": missing_evidence,
            "risk_level": risk_level,
            **payload,
            "category": ExceptionCategory(payload["category"]),
            "suggested_action": SuggestedAction(payload["suggested_action"]),
        }
    )


def _case(payload: dict[str, Any]) -> ReviewCase:
    return ReviewCase(
        **{
            **payload,
            "status": ReviewStatus(payload["status"]),
            "analysis": _analysis(payload["analysis"], payload["reason_codes"]),
        }
    )


class SQLiteReviewRepository:
    """Thread-safe, optimistic review storage with durable audit history."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS review_cases (
                    case_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_events (
                    event_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(case_id) REFERENCES review_cases(case_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS review_event_version
                    ON review_events(case_id, version);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def create(self, case: ReviewCase, event: ReviewEvent) -> ReviewCase:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload_json FROM review_cases WHERE case_id = ?", (case.id,)
            ).fetchone()
            if existing:
                connection.commit()
                return _case(json.loads(existing["payload_json"]))
            connection.execute(
                "INSERT INTO review_cases(case_id, version, payload_json) VALUES (?, ?, ?)",
                (case.id, case.version, self._json(case.to_dict())),
            )
            connection.execute(
                """
                INSERT INTO review_events(event_id, case_id, version, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (event.id, case.id, event.version, self._json(event.to_dict())),
            )
            connection.commit()
            return _case(case.to_dict())
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_cases(self) -> list[ReviewCase]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM review_cases ORDER BY case_id"
            ).fetchall()
        return [_case(json.loads(row["payload_json"])) for row in rows]

    def get(self, case_id: str) -> ReviewCase:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload_json FROM review_cases WHERE case_id = ?", (case_id,)
            ).fetchone()
        if row is None:
            raise ReviewNotFoundError(case_id)
        return _case(json.loads(row["payload_json"]))

    def update(self, case: ReviewCase, event: ReviewEvent, expected_version: int) -> ReviewCase:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """
                UPDATE review_cases SET version = ?, payload_json = ?
                WHERE case_id = ? AND version = ?
                """,
                (case.version, self._json(case.to_dict()), case.id, expected_version),
            )
            if updated.rowcount != 1:
                exists = connection.execute(
                    "SELECT version FROM review_cases WHERE case_id = ?", (case.id,)
                ).fetchone()
                if not exists:
                    raise ReviewNotFoundError(case.id)
                raise ReviewConflictError(
                    f"stale review version: expected {expected_version}, current {exists['version']}"
                )
            connection.execute(
                """
                INSERT INTO review_events(event_id, case_id, version, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (event.id, case.id, event.version, self._json(event.to_dict())),
            )
            connection.commit()
            return _case(case.to_dict())
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def events(self, case_id: str) -> list[ReviewEvent]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM review_events WHERE case_id = ? ORDER BY version",
                (case_id,),
            ).fetchall()
        if not rows and not self._exists(case_id):
            raise ReviewNotFoundError(case_id)
        return [ReviewEvent(**json.loads(row["payload_json"])) for row in rows]

    def _exists(self, case_id: str) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT 1 FROM review_cases WHERE case_id = ?", (case_id,)
            ).fetchone()
        return row is not None
