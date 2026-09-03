from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from reconx.application.reconcile import policy_contract_hash
from reconx.domain.models import SCHEMA_VERSION
from reconx.synthetic.development import SCENARIOS, _base_group

HELDOUT_GENERATOR_VERSION = "heldout-generator/1.0"
HELDOUT_SEED = 20_260_901
HELDOUT_GROUP_COUNT = 110
HELDOUT_INDEX_START = 2_000
SOURCES = (
    "orders",
    "payments",
    "refunds",
    "settlements",
    "settlement_lines",
    "bank_entries",
    "ledger_entries",
)


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_heldout_dataset(
    *,
    group_count: int = HELDOUT_GROUP_COUNT,
    seed: int = HELDOUT_SEED,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build a distinct synthetic test split after the release policy is frozen.

    The held-out split uses a separate namespace, time origin, index range, amount
    distribution and shuffled scenario order. It remains public synthetic data, not a
    claim of externally sequestered or production data.
    """

    if group_count < len(SCENARIOS):
        raise ValueError(f"group_count must be at least {len(SCENARIOS)}")

    rng = random.Random(seed)
    scenario_order = [SCENARIOS[index % len(SCENARIOS)] for index in range(group_count)]
    rng.shuffle(scenario_order)

    raw: dict[str, Any] = {
        "batch_id": f"batch_heldout_{group_count}_v1",
        "schema_version": SCHEMA_VERSION,
        "synthetic": True,
        **{source: [] for source in SOURCES},
    }
    truth_groups: list[dict[str, Any]] = []
    scenario_counts: Counter[str] = Counter()
    for position, scenario in enumerate(scenario_order):
        scenario_counts[scenario.value] += 1
        source_index = HELDOUT_INDEX_START + position * 7
        group = _base_group(
            source_index,
            scenario,
            namespace="hold",
            time_origin=datetime(2026, 9, 1, 9, 30, tzinfo=UTC),
            amount_offset_paise=57_019,
        )
        for source in SOURCES:
            raw[source].extend(group[source])
        truth_groups.append(group["truth"])

    for source in SOURCES:
        rng.shuffle(raw[source])

    raw_record_count = sum(len(raw[source]) for source in SOURCES)
    ground_truth = {
        "batch_id": raw["batch_id"],
        "schema_version": SCHEMA_VERSION,
        "split": "held_out",
        "groups": truth_groups,
    }
    manifest = {
        "batch_id": raw["batch_id"],
        "schema_version": SCHEMA_VERSION,
        "split": "held_out",
        "synthetic": True,
        "generator_version": HELDOUT_GENERATOR_VERSION,
        "seed": seed,
        "group_count": group_count,
        "raw_record_count": raw_record_count,
        "scenario_count": len(SCENARIOS),
        "scenario_counts": dict(sorted(scenario_counts.items())),
        "namespace": "hold",
        "source_index_start": HELDOUT_INDEX_START,
        "policy_contract_sha256": policy_contract_hash(),
    }
    manifest["raw_batch_sha256"] = _hash(raw)
    manifest["ground_truth_sha256"] = _hash(ground_truth)
    return raw, manifest, ground_truth
