# ADR 0005: Freeze policy before held-out evaluation

Status: Accepted on 31 August 2026, before the first Phase 4 held-out run.

## Context

The Buildathon requires measured accuracy, throughput and an honest exception list
over a 50+ record synthetic batch. Reusing development records or changing thresholds
after observing test outcomes would make the result weak evidence.

## Decision

Store the v2 policy as a machine-checkable JSON contract and bind its SHA-256 into a
separately generated held-out manifest. Use a distinct seed, namespace, source-index
range, date origin, amount distribution and scenario order. Reject modified inputs
before scoring. Compare against exact-ID matching, publish every non-auto-resolved
group, and repeat the full decision run three times.

Hash deterministic decisions and evidence separately from throughput. Throughput is
still measured end to end but remains host-dependent and is not a phase gate.

## Consequences

- Policy drift breaks a regression test and held-out input verification.
- Development and held-out records cannot share IDs.
- Unsafe cases reduce overall match rate instead of being hidden.
- The report remains honest about synthetic, publicly generated data.
- Stronger evidence would still require externally sequestered data or real merchant
  records under appropriate privacy controls.
