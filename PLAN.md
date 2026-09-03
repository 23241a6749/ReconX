# ReconX delivery plan

Status: Phase 6 code and public repository complete; video and application inputs pending.

## Phase gates

| Phase | Scope | Exit criterion | Status |
|---|---|---|---|
| 1 | Synthetic grouped settlement → engine → API → evidence UI → audit | Offline domain tests pass and decision artifact is deterministic | Complete |
| 2 | Full validators, anomaly matrix, refunds and candidate policy | Development batch meets zero false-auto-match gate | Complete |
| 3 | AI analyst adapter and human-review workflow | AI failure cannot mutate ledger truth | Complete |
| 4 | Held-out evaluator, baseline and metrics UI | Frozen evaluation artifact is reproducible | Complete |
| 5 | Razorpay test adapter, webhook idempotency and security | Contract/adversarial/E2E tests green | Complete |
| 6 | Submission polish and clean-clone verification | Tagged public release and five-minute demo | In progress |

## Current vertical slice

- [x] Repository contracts and architecture boundary.
- [x] Fee-inclusive-tax accounting decision.
- [x] Canonical models and deterministic generator.
- [x] Grouped-settlement reconciliation.
- [x] Audit event and honest exception output.
- [x] FastAPI adapter and evidence UI.
- [x] Domain tests and clean commands.
- [x] Strict provider-neutral AI analysis contract.
- [x] Deterministic fallback, retry budget and circuit breaker.
- [x] Explicit versioned human review with hash-chained history.
- [x] Adversarial safety gate and machine-readable report.
- [x] Frozen v2.1 policy contract and runtime drift test.
- [x] Distinct held-out generator with raw/truth/policy integrity hashes.
- [x] Repeated decision fingerprint and hardware-separated throughput benchmark.
- [x] Exact-ID baseline, complete exception ledger and judge-facing metrics UI.
- [x] Exact-byte HMAC webhook verification and secret rotation.
- [x] Durable atomic event-id idempotency and delivery audit.
- [x] Out-of-order monotonic projection and deterministic tie-break.
- [x] Razorpay settlement-recon client with fixed endpoint and bounded timeout.
- [x] Signed HTTP E2E, contract fixtures and adversarial integration gate.
- [x] Exact Buildathon form-answer sheet and user-owned input checklist.
- [x] Timed five-minute pitch and recording shot list.
- [x] Dependency-free release verifier and CI release gate.
- [x] Public GitHub repository and green hosted CI.
- [x] Strict hosted-model adapter with default-off, on-demand execution.
- [x] Full held-out exception queue with durable SQLite review history.
- [x] Razorpay recon plus bank/ledger CSV import and close-pack export.
- [x] Immutable v1.0.0 release tag.
- [ ] Public-viewable five-minute video and final form submission.

## Change-control rule

Canonical schemas, domain policies and adapter ports are versioned. New integrations
must implement ports and pass contract tests; risky functionality remains default-off.

## Phase 2 evidence

- 840 raw synthetic records across 66 settlement groups.
- All 22 declared scenario families present with deterministic hashes.
- 36 records quarantined; exact duplicates deduplicated idempotently.
- 100% safe auto-approval precision and zero false matches.
- 100% coverage on 39 automation-eligible groups.
- Exact-ID baseline coverage: 76.9231% on the same groups.
- 100% unsafe-scenario detection recall.

## Phase 3 evidence

- 11/11 deterministic adversarial checks passed.
- Model citations are restricted to evidence IDs already present in the case.
- Malformed, extra-field and fabricated-evidence responses fall back safely.
- Repeated provider failure opens the circuit; review remains available.
- Human decisions require an expected version; stale decisions receive a conflict.
- Review history is append-only and each event links to the previous event hash.
- Reconciliation state and finance amounts remain outside model authority.
- No external-model quality or production-security claim is made by this gate.

## Phase 4 evidence

- 1,400 raw held-out records across 110 settlement groups and all 22 scenarios.
- Development and held-out record IDs are disjoint.
- 65 correct automatic matches; 100% safe-auto precision and zero false matches.
- 100% eligible-group coverage versus 76.9231% for exact-ID matching.
- 45 non-auto-resolved cases are all listed: 10 review, 30 unresolved, 5 quarantined.
- Zero unexpected exceptions and zero unsafe auto-approvals.
- Identical deterministic decision fingerprint across three full runs.
- Wall-clock throughput is reported separately and excluded from the evidence hash.
- 38 regression tests and live HTTP integration checks pass.

## Phase 5 evidence

- 19/19 deterministic Razorpay integration controls passed.
- HMAC-SHA256 is checked against exact request bytes before JSON parsing.
- Current and previous webhook secrets are supported for retry-safe rotation.
- Twelve concurrent deliveries produced one apply and eleven safe duplicates.
- Event-id reuse with changed content is rejected without changing committed state.
- Older and equal-timestamp events cannot produce arrival-order-dependent rollback.
- SQLite state and hash-chained delivery history survive process restart.
- Oversized, future-dated, duplicate-key and malformed signed payloads are rejected.
- Signed HTTP receiver returns applied, duplicate and invalid-signature outcomes correctly.
- Four official-shape settlement recon items parsed; one unsupported transfer stays visible.
- Live Razorpay calls and real credentials remain deliberately absent from the evidence.
- 58 total regression tests pass.

## Phase 6 release rule

Run `make release` from a fresh checkout. Publication is allowed only when the
command passes, the repository contains no credentials, hosted CI is green and every
submission URL works in a signed-out browser. The final Google Form confirmation is
irreversible according to the form and therefore remains a manual user action.
