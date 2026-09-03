# Evaluation contract

Phase 1 proves one deterministic grouped settlement and one honest unmatched ledger
exception. Phase 2 adds a seeded development batch, 22 scenario families, raw-record
quarantine, an exact-ID baseline and a versioned evidence-candidate policy.

Final formulas:

- auto-match precision = correct auto-approved groups / all auto-approved groups;
- coverage = correctly auto-reconciled eligible groups / all eligible groups;
- false-match rate = incorrect auto-approved groups / all auto-approved groups;
- anomaly recall = detected seeded anomalies / all seeded anomalies;
- throughput = source records / reconciliation wall-clock seconds.

Ground truth is stored separately from engine input. Thresholds are frozen before the
held-out run, and raw predictions are retained alongside metric output.

## Phase 2 development result

The default seed (`20260830`) produces 840 raw records across 66 settlement groups.
It exercises every scenario three times. Ingestion accepted valid canonical records,
deduplicated exact duplicates and quarantined 36 malformed, conflicting or
unsupported-currency records.

| Metric | Candidate engine | Exact-ID baseline |
|---|---:|---:|
| Automation-eligible groups | 39 | 39 |
| Correctly auto-reconciled | 39 | 30 |
| Coverage | 100% | 76.9231% |
| Safe auto-approval precision | 100% | 100% |
| False-match rate | 0% | 0% |
| Unsafe-scenario detection recall | 100% | 100% |

The generated [machine-readable report](../reports/phase2-evaluation.json) contains
the scenario manifest, raw/ground-truth hashes, ingestion outcomes, policy gates and
per-scenario decisions. These are synthetic development results. They are not the
final held-out result and do not demonstrate production performance.

## Phase 3 safety contract

`make phase3` evaluates the analyst and review boundary without network access. The
[machine-readable safety report](../reports/phase3-safety-report.json) records 11/11
passing checks:

- exact valid output is accepted;
- malformed output is retried once;
- fabricated evidence citations are rejected;
- provider timeout falls back deterministically;
- repeated failure opens the circuit;
- instruction-like evidence is flagged and remains inside the untrusted-data block;
- human decisions are explicit and versioned;
- review events are hash-chained;
- stale decisions are rejected; and
- advisory analysis cannot change deterministic finance state.

This suite uses scripted provider behavior and synthetic records. It verifies local
control behavior, not the intelligence, uptime or security of a real model provider.
Prompt injection remains a residual risk; the primary protection is lack of model
authority plus deterministic validation and human review.

## Phase 4 held-out contract

The v2.2 reconciliation policy is stored in
`policies/reconciliation-policy-v2.2.json`. A regression test requires the file to match
the runtime policy exactly, and its SHA-256 is embedded in the held-out manifest. The
evaluator refuses to run if the raw batch, ground truth, policy hash, batch identity or
split label has changed.

The held-out generator uses seed `20260901`, namespace `hold`, source indices starting
at 2000, a new time origin, a shifted amount distribution and shuffled scenario order.
This makes its record IDs and values distinct from development data. The generator is
public, so “held-out” means untouched by policy tuning before the first run—not secret
or independently administered data.

### Metric definitions

- safe auto-approval precision = correct and automation-eligible auto approvals / all
  auto approvals;
- eligible-group coverage = correct auto approvals / all groups labelled safe for
  automation;
- overall automatic match rate = correct auto approvals / every settlement group,
  including intentionally unsafe groups;
- false-match rate = incorrectly linked auto approvals / all auto approvals;
- exception count = every group whose actual state is not `auto_approved`;
- throughput = raw source records / wall-clock seconds for ingestion plus candidate
  reconciliation.

### Held-out result

| Measure | Result |
|---|---:|
| Raw records | 1,400 |
| Settlement groups | 110 |
| Correct automatic matches | 65 |
| Overall automatic match rate | 59.0909% |
| Eligible-group coverage | 100% |
| Exact-ID eligible coverage | 76.9231% |
| Safe auto-approval precision | 100% |
| False matches / unsafe approvals | 0 / 0 |
| Listed non-auto-resolved cases | 45 |
| Unexpected exceptions | 0 |

The 45 exceptions comprise 10 review-required cases, 30 unresolved cases and 5
quarantined groups. Each report entry includes the scenario, state, reason codes,
expected bank relationship and actual relationship. The deterministic evidence hash
excludes wall-clock timing, so it remains stable across hardware while throughput is
still reported honestly. Three evaluation runs produced the same decision fingerprint.

The [Phase 4 machine-readable report](../reports/phase4-heldout-evaluation.json) is the
authoritative artifact.
