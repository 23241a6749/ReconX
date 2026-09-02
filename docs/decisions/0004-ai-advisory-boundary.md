# ADR 0004: Keep model analysis advisory

Status: Accepted on 31 August 2026.

## Context

Ambiguous settlement exceptions benefit from language-based classification and
explanation. The same component may receive attacker-controlled bank descriptions or
malformed provider output, and finance actions are high impact.

## Decision

The model is an outbound advisory provider behind `AnalysisProvider`. It receives
deterministic facts and bounded evidence excerpts, returns one schema-constrained
object, and has no tool or ledger-write capability. Reconciliation remains the only
source of finance truth. Provider errors, invalid output or a circuit-open state use a
deterministic reason-code classifier. A human must explicitly decide review cases
using optimistic version control.

## Consequences

- A model provider can be replaced without changing finance policy.
- A successful prompt injection cannot directly execute a payment or ledger action.
- Availability is preserved when the provider fails.
- Model output may improve triage but cannot increase automatic reconciliation
  coverage by itself.
- Any future action-taking feature requires a new ADR, narrower permissions and new
  adversarial gates.
