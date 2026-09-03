# ReconX five-minute pitch and demo script

Target duration: 4 minutes 45 seconds. Keep 15 seconds of safety margin.

## Recording setup

- Use 1080p landscape recording and readable browser zoom.
- Turn off notifications and close tabs containing private information.
- Start ReconX before recording and pre-open the dashboard, architecture and report.
- Do not show terminals containing environment variables or Razorpay credentials.
- Record one continuous primary take; edit only dead time or accidental exposure.

## Timed script

### 0:00–0:25 — problem and promise

**Show:** Title and dashboard overview.

**Say:** “Finance teams must reconcile payment captures, refunds, fees, taxes, gateway
settlements, bank credits and their own ledger. Exact-ID matching breaks when references
are missing, settlements group many payments, refunds are partial or records arrive late.
ReconX is an evidence-first AI Finance Controller that closes this loop without silently
forcing uncertain matches.”

### 0:25–0:55 — what makes it safe

**Show:** Architecture diagram or trust-boundary section.

**Say:** “All money calculations use deterministic integer-paise accounting. AI is
advisory only: it can classify and explain exceptions, but it cannot calculate balances,
post entries or approve finance state. Every automatic decision must satisfy identity,
amount, fee, tax, currency and non-reuse invariants.”

### 0:55–1:50 — batch result

**Show:** Held-out dashboard panel.

**Say:** “This is a separately seeded held-out batch: 1,400 raw records across 110
settlement groups and 22 scenario families. ReconX safely automated 65 eligible groups
with 100% precision and zero false matches. Eligible coverage is 100%, compared with
76.9231% for exact-ID matching. The other 45 cases are not hidden: 10 require review,
30 remain unresolved and 5 are quarantined.”

### 1:50–2:35 — one reconciliation proof

**Show:** A group’s expected bank credit, payment gross, refunds, fee, tax and evidence.

**Say:** “Here ReconX reconstructs the bank credit from gross captured payments minus
refunds and the inclusive Razorpay fee. GST is reported inside the fee and is not
subtracted twice. The result includes reason codes, source record IDs, confidence and a
content-hashed audit event.”

### 2:35–3:20 — exception and human control

**Show:** Select two of the 40 review cases, refresh one advisory diagnosis, then show
approve/reject controls and the model-safe runtime label.

**Say:** “When evidence is ambiguous, the system stops. The analyst cites only evidence
already in the case. Invalid model JSON, fabricated citations, prompt-like record text or
provider timeout falls back deterministically. A human decision requires explicit
confirmation and an expected version, and is appended to a hash-chained history.”

### 3:20–4:05 — input-to-close and Razorpay boundary

**Show:** Three-file import panel, close-pack download, then Phase 5 controls.

**Say:** “ReconX accepts Razorpay recon exports plus bank and ledger evidence and emits a
hash-verifiable close pack. The Razorpay boundary verifies HMAC-SHA256 over exact raw webhook bytes before
JSON parsing. Event IDs are atomically deduplicated, and older events cannot roll state
back. In the concurrency test, 12 deliveries created one application and 11 safe
duplicates. A changed body reusing the same event ID is rejected. Unsupported settlement
types remain visible instead of being coerced.”

### 4:05–4:35 — engineering evidence

**Show:** Repository tree, CI workflow and reports.

**Say:** “The repository contains seeded generators, frozen policy, held-out ground truth,
machine-readable reports, 60+ regression tests, Docker configuration, CI and a one-command
release gate. The Phase 3 safety suite passes 11 checks and the Razorpay contract suite
passes 19.”

### 4:35–4:45 — close

**Show:** Product title and final metrics.

**Say:** “ReconX turns reconciliation from an opaque AI guess into a measurable,
reviewable finance workflow: automate what is provably safe and expose everything else.”

## Recording acceptance checklist

- Duration is at most 5:00.
- Text and metrics are readable at normal playback speed.
- Synthetic/held-out status is said aloud.
- The public Render demo is buildathon infrastructure, not a claim of production-grade
  persistence, real merchant results or live money movement.
- No secret, email inbox, phone number or private dashboard is visible.
- Link permissions allow anyone with the link to view without sign-in.
