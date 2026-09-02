# Security model

ReconX treats every uploaded record, webhook field and model response as untrusted.
The current implementation is a buildathon prototype: it demonstrates enforceable
control boundaries, not production certification.

## Assets and trust boundaries

| Asset | Owner | Model access | Write path |
|---|---|---:|---|
| Source finance records | Deterministic core | Selected excerpts only | Ingestion adapters |
| Money calculations | Reconciliation policy | None as authority | Deterministic code |
| Auto-approval state | Policy gate | Read-only facts | Deterministic code |
| Exception classification | Analyst adapter | Advisory | Strict validated object |
| Human decision | Review service | No authority | Versioned explicit request |
| Audit history | Review repository | None | Append-only event API |

The analyst has no tools, credentials, payment methods or ledger-write interface.
Its suggested action is displayed as advice and cannot execute itself.

## Implemented controls

| Threat | Control | Evidence |
|---|---|---|
| Prompt injection in bank narration or metadata | Instruction-like text is flagged; instructions and untrusted JSON are separated | `test_prompt_injection_is_flagged_and_kept_inside_untrusted_data` |
| Fabricated citations | Citations must be a unique subset of the case evidence allow-list | `test_hallucinated_evidence_falls_back_safely` |
| Malformed or over-broad output | Exact keys, enum values, type/range and text-length validation | `test_extra_output_fields_are_rejected` |
| Provider outage or timeout | Bounded attempts, deterministic fallback and circuit breaker | `test_timeout_and_open_circuit_do_not_block_fallback` |
| AI mutates finance truth | No write port; analyst receives copied facts and returns an advisory value object | `test_analyst_cannot_mutate_the_reconciliation_group` |
| Accidental or stale human action | Confirmation UI, expected-version comparison and HTTP 409 conflict | `test_stale_version_and_double_decision_are_rejected` |
| Decision history tampering | Append-only event history with previous-event hash linkage | `test_review_case_requires_explicit_versioned_human_decision` |
| Silent forced match | Ambiguous/unbalanced cases remain visible and cannot auto-approve | Phase 2 policy tests |
| Forged Razorpay webhook | HMAC-SHA256 over exact raw bytes with constant-time comparison | Phase 5 signature tests |
| Retry duplicates | Atomic durable claim on `X-Razorpay-Event-Id` and payload hash | Concurrent-delivery test |
| Event-id collision with changed content | Conflict rejection and transaction rollback | Phase 5 conflict test |
| Out-of-order delivery | Monotonic timestamp plus deterministic event-id tie-break | Phase 5 ordering test |
| Secret rotation breaks retries | Current and previous webhook secret verification | Phase 5 rotation test |
| Parser/resource abuse | 256 KiB stream limit, depth, array, field and duplicate-key limits | Phase 5 adversarial tests |
| Credential leakage | Secrets stay in environment/private fields and errors retain only types/codes | Secret-absence gate |

## Data minimisation and logging

Only allow-listed evidence excerpts are placed in the analyst prompt. Excerpts are
limited to 500 characters and non-printable control characters are removed. Runtime
provider errors retain only the exception type in the result, avoiding accidental
credential or payload leakage. Accepted analysis is content-hashed and records its
provider, source, attempts, security flags and fallback reason.

## Residual risks before production

- Prompt-injection pattern detection is supplemental and cannot detect every attack.
- The provider port has no live hosted-model implementation or provider-specific
  retention configuration yet.
- Review state is in memory; concurrent production deployment requires transactional
  persistence, authentication, authorization and durable append-only storage.
- Event hashes provide tamper evidence only when an external trusted anchor or signed
  log protects the chain head.
- The demo actor is hard-coded. Production decisions require verified identities,
  role-based permissions and separation of duties.
- Rate limits, CSRF protection, secure headers, encrypted persistence, secret rotation,
  dependency scanning and incident monitoring remain production work. Webhook secret
  rotation is implemented, but automated key-vault lifecycle management is not.
- Synthetic safety results cannot establish behavior on real merchant data.
- SQLite is durable for this single-node prototype, but multi-region deployment would
  require a transactional shared store and a globally consistent idempotency key.
- A reverse proxy should enforce request-rate and body-size limits before application
  code, even though the application also limits streamed bodies.
- Test-mode dashboard configuration and an actual Razorpay delivery remain pending
  until the user supplies account-owned test credentials and a public HTTPS endpoint.

## Design references

The boundary follows Razorpay's published principles of merchant control, explicit
approval and traceability, OWASP guidance to isolate untrusted content and validate
model output, and NIST's emphasis on human oversight, provenance and monitoring. The
links are recorded here so reviewers can distinguish implemented controls from design
inspiration:

- <https://razorpay.com/blog/razorpay-agent-studio-principles-guardrails-and-merchant-control/>
- <https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html>
- <https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html>
- <https://genai.owasp.org/llmrisk/llm01-prompt-injection/>
- <https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence>
