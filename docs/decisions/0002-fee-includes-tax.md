# ADR-002: Treat tax as a component of the Razorpay fee

## Status

Accepted after documentation review on 30 August 2026.

## Context

Razorpay's payment entity describes `fee` as including GST, with `tax` reporting the
GST component. Subtracting both fee and tax would understate the bank credit.

## Decision

Subtract `fee` exactly once. Validate `0 <= tax <= fee` and expose fee and tax
separately for evidence, but never treat tax as an additional deduction.

## Consequence

The correction is confined to the canonical settlement equation and its tests; source
adapters and UI contracts remain unchanged.

