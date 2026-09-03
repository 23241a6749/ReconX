# ReconX

Evidence-first payment and settlement reconciliation controller for Razorpay AI
Buildathon 2026, Track 4 — AI Finance Controller.

ReconX reconstructs how captured payments, refunds and inclusive fees become a bank
settlement. It auto-approves only a financially balanced, strongly identified group,
records the evidence and leaves unmatched records visible.

## Implemented capabilities

- deterministic, seeded synthetic finance batch;
- one-to-many payment settlement with a partial refund;
- Razorpay-correct fee/tax handling;
- confidence policy and financial invariant gate;
- append-only, content-hashed audit event;
- honest unmatched-ledger exception;
- FastAPI endpoint and zero-build evidence UI;
- dependency-free domain tests and CLI;
- raw validation with per-record quarantine and actionable reason codes;
- exact and conflicting duplicate handling;
- 22-scenario deterministic development generator;
- 840-record development evaluation with frozen ground truth hashes;
- missing/malformed UTR recovery using amount, date and settlement-reference evidence;
- equal-score ambiguity rejection and bank-entry non-reuse;
- exact-ID baseline comparison and machine-readable phase gates;
- provider-neutral AI exception analyst with an exact JSON contract;
- citation allow-listing, prompt-injection flags and untrusted-data separation;
- one-retry policy, deterministic fallback and failure circuit breaker;
- human review queue with explicit approve/reject confirmation;
- optimistic version checks and append-only, hash-chained review events;
- reproducible 11-check adversarial safety evaluation.
- frozen, machine-checkable reconciliation policy artifact;
- separate 1,400-record held-out split with integrity hashes;
- repeated decision-hash verification and end-to-end throughput benchmark;
- complete 45-case held-out exception ledger with zero unexpected exceptions;
- judge-facing held-out metrics and baseline comparison dashboard.
- exact-raw-body Razorpay webhook signature verification;
- current/previous webhook-secret rotation without exposing secrets;
- durable SQLite event-id idempotency across threads and restarts;
- monotonic out-of-order entity projection and deterministic timestamp tie-break;
- signed payment, refund and settlement event contracts;
- fixed-endpoint settlement-reconciliation API client and money checks;
- 19-check Phase 5 integration evidence with a safe-off runtime default.
- official OpenAI Responses API adapter with strict structured output and safe-off defaults;
- free-tier Groq adapter using strict structured output with deterministic fallback;
- all 40 actionable held-out exceptions connected to the human review queue;
- durable SQLite review cases and hash-linked decisions across restarts;
- official-shape Razorpay recon JSON plus bank/ledger CSV import;
- downloadable close pack with evidence hash, value exposure and time-saved basis;
- live Razorpay recon fetch endpoint guarded by an explicit feature flag;
- repository-aware secret scanning for tracked and unignored files.
- evidence-completion advice that names the next required evidence and risk level.

## Run the domain slice without installing dependencies

```bash
make test
make demo
make preview
make phase2
make phase3
make phase4
make phase5
make release
```

The result is written to `artifacts/demo-result.json`. The dependency-free preview is
available at `http://localhost:8000`; it exercises the same domain use case as the
FastAPI adapter.

`make phase2` writes the reproducible report to
`reports/phase2-evaluation.json`. The preview also exposes a compact summary at
`GET /api/evaluation`.

`make phase3` writes `reports/phase3-safety-report.json`. The preview exposes the
review queue at `GET /api/reviews`; decisions use
`POST /api/reviews/{case_id}/decision` with an explicit `expected_version`.

`make phase4` regenerates the distinct held-out split, verifies its raw-data,
ground-truth and policy hashes, then writes
`reports/phase4-heldout-evaluation.json`. The compact dashboard data is available at
`GET /api/heldout`.

`make phase5` writes `reports/phase5-integration-report.json`. It uses signed
official-shape fixtures and an injected HTTP transport; it does not require credentials
or make a live Razorpay call. `GET /api/integration` exposes the compact proof.

`make release` reruns the complete test and evaluation suite, then checks the submission
file set, metric gates, synthetic-data disclosure, environment safety and common secret
patterns. See the [submission answer sheet](docs/submission.md), [five-minute demo
script](docs/demo-script.md) and [owner setup checklist](docs/user-setup.md).

The main dashboard action executes the full 1,400-record held-out batch. It also exposes
every non-auto outcome, the 40 actionable review cases, and an audit-ready close-pack
download. `POST /api/import/reconcile` accepts an official-shape `razorpay_recon` object
plus `bank_csv` and `ledger_csv` strings. The browser UI supplies the same contract with
three local file pickers.

## Phase 2 measured results

| Metric | Candidate engine | Exact-ID baseline |
|---|---:|---:|
| Safe auto-approval precision | 100% | 100% |
| Auto-reconciliation coverage | 100% | 76.9231% |
| False-match rate | 0% | 0% |
| Unsafe auto-approvals | 0 | 0 |

These are development results on synthetic data, not production claims. The final
submission will report a separately seeded held-out batch.

## Phase 3 safety result

All 11 deterministic adversarial checks pass. They cover malformed and fabricated
model output, timeout/fallback behavior, circuit opening, instruction-like evidence,
strict evidence citations, human confirmation, stale-decision rejection, audit-chain
continuity and the rule that AI cannot change finance state.

No external model was called for this result. Scripted provider responses exercise
the adapter contract. Runtime analysis uses deterministic fallback unless
`ENABLE_LLM=true` and the selected provider key are configured; Groq is the recommended
free option and OpenAI remains supported. Model calls are always on-demand.
This is a software-control result, not a claim that prompt injection is solved or
that any hosted model is production-ready.

## Phase 4 held-out result

The v2.1 policy was frozen before the release held-out run. The test split changes the
seed, record namespace, time origin, source-index range, amount distribution and
scenario ordering. It contains 1,400 raw records across 110 settlement groups and all
22 scenario families.

| Metric | ReconX candidate | Exact-ID baseline |
|---|---:|---:|
| Safe auto-approval precision | 100% | 100% |
| Eligible-group coverage | 100% | 76.9231% |
| False matches | 0 | 0 |
| Unsafe auto-approvals | 0 | 0 |

ReconX correctly auto-resolved 65 safe groups. It did not auto-resolve the other 45
groups: 10 require review, 30 remain unresolved and 5 were quarantined. All 45 were
deliberately unsafe scenarios in ground truth, so unexpected exceptions are zero.
Overall automatic match rate is therefore 59.0909%; eligible coverage is 100%.

Throughput is measured over the complete validation, normalisation and candidate
reconciliation path. It is reported but not used as a pass threshold because it is
hardware-dependent. These are public synthetic held-out results, not externally
sequestered data or production-performance claims.

## Phase 5 Razorpay integration result

All 19 integration controls pass. The receiver verifies HMAC-SHA256 over the exact raw
request bytes before JSON parsing, accepts current and previous secrets during
rotation, atomically deduplicates `X-Razorpay-Event-Id`, prevents older deliveries from
rolling back entity state and records a hash-chained delivery audit.

The contract suite includes `payment.captured`, `refund.processed` and
`settlement.processed` fixtures plus a four-item settlement-reconciliation response.
Payments, refunds and adjustments pass the adapter contract; the transfer item remains
visible as unsupported instead of being silently coerced.

The webhook endpoint is `POST /api/webhooks/razorpay`. It stays disabled until
`RAZORPAY_WEBHOOK_SECRET` is configured. Docker Compose persists the delivery and audit
ledger in the `reconx-runtime` named volume. No live Razorpay API call, real credential
or real-money movement is claimed in Phase 5. See [integration operations](docs/integration.md).

Live settlement recon is exposed at `POST /api/import/razorpay/{YYYY-MM-DD}` and remains
disabled unless `ENABLE_RAZORPAY_IMPORT=true`. Fetching does not auto-close anything:
bank and ledger evidence must still be imported and the deterministic policy must pass.

## Run the web application

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
make run
```

Open `http://localhost:8000`. Docker users can run `docker compose up --build`.

## Deploy free on Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/23241a6749/ReconX)

The Blueprint uses Groq `openai/gpt-oss-20b` for optional advisory reanalysis and asks
for the Groq key plus Razorpay Test Mode API credentials directly in Render. Local `.env`
values are never uploaded automatically. Read the [deployment and privacy notes](docs/render-deployment.md)
before applying the Blueprint; Render's free filesystem is ephemeral, so SQLite review
history is demo-only on that plan.

## Trust boundaries

- Amounts are integer paise.
- `fee` includes its `tax` component and is deducted once.
- AI is advisory only; it cannot post, approve, calculate or mutate ledger truth.
- Model output is untrusted and must pass an exact schema and evidence allow-list.
- Provider failure never blocks deterministic classification or human review.
- Synthetic data is clearly labelled.
- Unbalanced or ambiguous groups cannot auto-approve.

See [architecture](docs/architecture.md), [evaluation](docs/evaluation.md),
[security model](docs/security.md), [Render deployment](docs/render-deployment.md), and
[delivery plan](PLAN.md).
