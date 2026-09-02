# ADR 0006: Verify, claim, then project Razorpay events

Status: Accepted on 1 September 2026.

## Context

Razorpay webhooks are signed, retried, potentially duplicated and not guaranteed to
arrive in order. A finance controller cannot treat delivery arrival as a unique,
ordered command stream.

## Decision

Process each delivery in this order:

1. bound the exact raw body size;
2. validate event-id format;
3. verify HMAC-SHA256 with current or previous webhook secret;
4. parse bounded JSON with duplicate-key rejection;
5. atomically claim the event ID and body hash;
6. update the entity projection only when `(created_at, event_id)` is newer;
7. append a hash-linked delivery audit event;
8. return a minimal receipt.

Persist the body hash and minimum normalised finance fields, not the raw body or
customer contact information. Keep the settlement API credentials and webhook secrets
as separate capabilities. Keep the receiver disabled when its secret is absent.

## Consequences

- Retries are safe across threads, processes and restarts on one SQLite-backed node.
- A reused event ID with changed content is treated as a conflict.
- Old events remain auditable but cannot roll back current state.
- Equal timestamps produce the same final state regardless of arrival order.
- Real Razorpay test-mode validation still requires account-owned credentials and a
  public HTTPS endpoint; offline fixtures do not prove network configuration.
