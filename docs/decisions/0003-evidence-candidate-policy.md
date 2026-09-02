# ADR-003: Evidence candidate policy for missing references

## Status

Accepted for development evaluation.

## Context

Exact UTR matching has excellent precision but leaves safe coverage on the table when
a bank narration loses or corrupts the UTR. Amount-only matching is unsafe because
unrelated settlements can collide.

## Decision

Candidate matching is allowed only when currency and amount are exact, the value date
is within seven days, the normalised narration contains the settlement identifier,
the score is at least 0.98, and the winning candidate exceeds the runner-up by at
least 0.15. A bank entry is reserved after any group claims it and cannot be reused.
Final auto-approval still requires an exact ledger reference and conserved money.

## Consequence

Missing and malformed UTR cases can close safely, while amount collisions and
equal-score candidates remain unresolved. Thresholds are versioned and will be frozen
before held-out evaluation.

