# ADR-001: Keep the finance domain independent

## Status

Accepted.

## Decision

Place canonical models and reconciliation policies in dependency-free modules. APIs,
files, databases and model providers depend on domain-defined contracts.

## Consequence

We can replace the Phase 1 UI, API or persistence adapter without rewriting or
revalidating the money engine.

