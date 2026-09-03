from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from reconx.application.analyst import ExceptionAnalyst
from reconx.application.reconcile import reconcile_batch
from reconx.application.review import ReviewService
from reconx.domain.review import ReviewAction, ReviewStatus
from reconx.infrastructure.review_store import SQLiteReviewRepository
from reconx.synthetic.generator import build_demo_batch


class DurableReviewStoreTests(unittest.TestCase):
    def test_decision_and_hash_chain_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory(prefix="reconx-review-") as temporary:
            path = Path(temporary) / "reviews.sqlite3"
            batch = build_demo_batch()
            batch.bank_entries[0] = replace(batch.bank_entries[0], amount_paise=682_301)
            group = reconcile_batch(batch).groups[0]
            first = ReviewService(ExceptionAnalyst(), SQLiteReviewRepository(path))
            case = first.create_case(group)
            first.decide(
                case.id,
                action=ReviewAction.REJECT,
                actor="finance-reviewer",
                reason="Bank amount needs source correction.",
                expected_version=1,
            )

            reopened = ReviewService(ExceptionAnalyst(), SQLiteReviewRepository(path))
            persisted = reopened.get_case(case.id)
            events = reopened.get_events(case.id)

            self.assertEqual(persisted.status, ReviewStatus.REJECTED)
            self.assertEqual(persisted.version, 2)
            self.assertEqual(events[1].previous_event_hash, events[0].event_hash)


if __name__ == "__main__":
    unittest.main()
