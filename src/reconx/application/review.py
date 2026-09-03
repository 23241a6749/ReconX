from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol

from reconx.application.analyst import ExceptionAnalyst
from reconx.application.reconcile import ReconciliationGroup
from reconx.domain.analysis import AnalysisRequest
from reconx.domain.review import ReviewAction, ReviewCase, ReviewEvent, ReviewStatus


class ReviewNotFoundError(LookupError):
    pass


class ReviewConflictError(RuntimeError):
    pass


class ReviewValidationError(ValueError):
    pass


class ReviewRepository(Protocol):
    def create(self, case: ReviewCase, event: ReviewEvent) -> ReviewCase: ...

    def list_cases(self) -> list[ReviewCase]: ...

    def get(self, case_id: str) -> ReviewCase: ...

    def update(
        self, case: ReviewCase, event: ReviewEvent, expected_version: int
    ) -> ReviewCase: ...

    def events(self, case_id: str) -> list[ReviewEvent]: ...


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class InMemoryReviewRepository:
    def __init__(self) -> None:
        self._cases: dict[str, ReviewCase] = {}
        self._events: dict[str, list[ReviewEvent]] = {}
        self._lock = Lock()

    def create(self, case: ReviewCase, event: ReviewEvent) -> ReviewCase:
        with self._lock:
            if case.id in self._cases:
                return copy.deepcopy(self._cases[case.id])
            self._cases[case.id] = copy.deepcopy(case)
            self._events[case.id] = [copy.deepcopy(event)]
            return copy.deepcopy(case)

    def list_cases(self) -> list[ReviewCase]:
        with self._lock:
            return [copy.deepcopy(case) for case in self._cases.values()]

    def get(self, case_id: str) -> ReviewCase:
        with self._lock:
            if case_id not in self._cases:
                raise ReviewNotFoundError(case_id)
            return copy.deepcopy(self._cases[case_id])

    def update(self, case: ReviewCase, event: ReviewEvent, expected_version: int) -> ReviewCase:
        with self._lock:
            current = self._cases.get(case.id)
            if current is None:
                raise ReviewNotFoundError(case.id)
            if current.version != expected_version:
                raise ReviewConflictError(
                    f"stale review version: expected {expected_version}, current {current.version}"
                )
            self._cases[case.id] = copy.deepcopy(case)
            self._events[case.id].append(copy.deepcopy(event))
            return copy.deepcopy(case)

    def events(self, case_id: str) -> list[ReviewEvent]:
        with self._lock:
            if case_id not in self._events:
                raise ReviewNotFoundError(case_id)
            return [copy.deepcopy(event) for event in self._events[case_id]]


class ReviewService:
    def __init__(
        self,
        analyst: ExceptionAnalyst,
        repository: ReviewRepository | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.analyst = analyst
        self.repository = repository or InMemoryReviewRepository()
        self.clock = clock

    def _timestamp(self) -> str:
        return self.clock().isoformat().replace("+00:00", "Z")

    def _event(
        self,
        *,
        case_id: str,
        version: int,
        actor: str,
        action: str,
        reason: str,
        previous_status: str | None,
        new_status: str,
        previous_event_hash: str | None,
        occurred_at: str,
    ) -> ReviewEvent:
        payload = {
            "case_id": case_id,
            "version": version,
            "actor": actor,
            "action": action,
            "reason": reason,
            "previous_status": previous_status,
            "new_status": new_status,
            "occurred_at": occurred_at,
            "previous_event_hash": previous_event_hash,
        }
        event_hash = _hash(payload)
        return ReviewEvent(
            id=f"review_event_{event_hash[:16]}",
            event_hash=event_hash,
            **payload,
        )

    def create_case(
        self,
        group: ReconciliationGroup,
        *,
        evidence_excerpts: dict[str, str] | None = None,
        occurred_at: str | None = None,
    ) -> ReviewCase:
        if group.state.value == "auto_approved":
            raise ReviewValidationError("auto-approved groups do not belong in the review queue")
        case_id = f"review_{_hash([group.settlement_id, group.reason_codes, group.evidence_ids])[:16]}"
        try:
            return self.repository.get(case_id)
        except ReviewNotFoundError:
            pass
        analysis = self.analyst.analyse(
            AnalysisRequest(
                case_id=case_id,
                reason_codes=group.reason_codes,
                evidence_ids=group.evidence_ids,
                deterministic_facts={
                    "settlement_id": group.settlement_id,
                    "state": group.state.value,
                    "expected_bank_credit_paise": group.expected_bank_credit_paise,
                    "actual_bank_credit_paise": group.actual_bank_credit_paise,
                    "difference_paise": group.difference_paise,
                    "confidence": group.confidence,
                },
                evidence_excerpts=evidence_excerpts or {},
            )
        )
        timestamp = occurred_at or self._timestamp()
        case = ReviewCase(
            id=case_id,
            settlement_id=group.settlement_id,
            version=1,
            status=ReviewStatus.PENDING,
            reason_codes=group.reason_codes,
            evidence_ids=group.evidence_ids,
            deterministic_state=group.state.value,
            expected_bank_credit_paise=group.expected_bank_credit_paise,
            actual_bank_credit_paise=group.actual_bank_credit_paise,
            difference_paise=group.difference_paise,
            analysis=analysis,
            created_at=timestamp,
            updated_at=timestamp,
        )
        event = self._event(
            case_id=case.id,
            version=1,
            actor="reconx-system",
            action="create",
            reason="deterministic policy requires human review",
            previous_status=None,
            new_status=ReviewStatus.PENDING.value,
            previous_event_hash=None,
            occurred_at=timestamp,
        )
        return self.repository.create(case, event)

    def list_cases(self) -> list[ReviewCase]:
        return sorted(self.repository.list_cases(), key=lambda case: (case.created_at, case.id))

    def get_case(self, case_id: str) -> ReviewCase:
        return self.repository.get(case_id)

    def get_events(self, case_id: str) -> list[ReviewEvent]:
        return self.repository.events(case_id)

    def reanalyse(
        self,
        case_id: str,
        *,
        actor: str,
        expected_version: int,
    ) -> ReviewCase:
        """Refresh advisory analysis without changing the financial decision state."""

        actor = actor.strip()
        if len(actor) < 2 or len(actor) > 80:
            raise ReviewValidationError("actor must contain 2-80 characters")
        current = self.repository.get(case_id)
        if current.version != expected_version:
            raise ReviewConflictError(
                f"stale review version: expected {expected_version}, current {current.version}"
            )
        previous_events = self.repository.events(case_id)
        analysis = self.analyst.analyse(
            AnalysisRequest(
                case_id=current.id,
                reason_codes=current.reason_codes,
                evidence_ids=current.evidence_ids,
                deterministic_facts={
                    "settlement_id": current.settlement_id,
                    "state": current.deterministic_state,
                    "expected_bank_credit_paise": current.expected_bank_credit_paise,
                    "actual_bank_credit_paise": current.actual_bank_credit_paise,
                    "difference_paise": current.difference_paise,
                },
            )
        )
        timestamp = self._timestamp()
        current.version += 1
        current.analysis = analysis
        current.updated_at = timestamp
        event = self._event(
            case_id=case_id,
            version=current.version,
            actor=actor,
            action="analyse",
            reason=f"advisory analysis refreshed via {analysis.provider}",
            previous_status=current.status.value,
            new_status=current.status.value,
            previous_event_hash=previous_events[-1].event_hash,
            occurred_at=timestamp,
        )
        return self.repository.update(current, event, expected_version)

    def decide(
        self,
        case_id: str,
        *,
        action: ReviewAction,
        actor: str,
        reason: str,
        expected_version: int,
    ) -> ReviewCase:
        actor = actor.strip()
        reason = reason.strip()
        if len(actor) < 2 or len(actor) > 80:
            raise ReviewValidationError("actor must contain 2-80 characters")
        if len(reason) < 5 or len(reason) > 500:
            raise ReviewValidationError("decision reason must contain 5-500 characters")

        current = self.repository.get(case_id)
        if current.version != expected_version:
            raise ReviewConflictError(
                f"stale review version: expected {expected_version}, current {current.version}"
            )
        if action is ReviewAction.REOPEN:
            if current.status is ReviewStatus.PENDING:
                raise ReviewConflictError("pending review case cannot be reopened")
            next_status = ReviewStatus.PENDING
        else:
            if current.status is not ReviewStatus.PENDING:
                raise ReviewConflictError("only pending review cases can be approved or rejected")
            next_status = (
                ReviewStatus.APPROVED if action is ReviewAction.APPROVE else ReviewStatus.REJECTED
            )

        previous_status = current.status
        previous_events = self.repository.events(case_id)
        timestamp = self._timestamp()
        current.version += 1
        current.status = next_status
        current.updated_at = timestamp
        current.decided_by = None if action is ReviewAction.REOPEN else actor
        current.decision_reason = None if action is ReviewAction.REOPEN else reason
        event = self._event(
            case_id=case_id,
            version=current.version,
            actor=actor,
            action=action.value,
            reason=reason,
            previous_status=previous_status.value,
            new_status=next_status.value,
            previous_event_hash=previous_events[-1].event_hash,
            occurred_at=timestamp,
        )
        return self.repository.update(current, event, expected_version)
