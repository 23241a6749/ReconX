# Razorpay AI Builder Internship 2026 — submission answer sheet

Do not submit the final form until the repository, video and signed-out link checks pass.
The form states that the official final submission cannot be changed after submission.

## Razorpay Dashboard is not a Track 4 submission dependency

Track 4 asks for a working finance-operations loop across 50+ synthetic records, with
throughput, measured accuracy and an honest exception list. Unlike Track 1, it does not
require the project to run on Razorpay Test Mode APIs. ReconX's signed webhook receiver
and guarded Test API import are additional integration evidence. If merchant-dashboard
onboarding is unavailable, submit the deterministic 1,400-record product and disclose
that a Razorpay-originated webhook delivery was not demonstrated.

Official track wording: <https://razorpay.com/buildathon/>

## Personal and internship fields

| Form field | Answer |
|---|---|
| Email | `[NEEDED FROM OWNER]` |
| Full Name | Neela Sai Mohaneesh |
| College Name | `[NEEDED FROM OWNER]` |
| Graduation Year | 2027 |
| In-person availability from September | Yes |
| Preferred Internship Duration | `[CHOOSE: 6-Month or 12-Month]` |

## Project fields

| Form field | Answer |
|---|---|
| Selected Track | Track 4: AI Finance Controller |
| Project Name / Title | ReconX — Evidence-First AI Finance Controller |
| GitHub Repository URL | `https://github.com/23241a6749/ReconX` |
| Live Demo URL | `https://reconx-ai-finance-controller.onrender.com` |
| 5-min Pitch Video Link | `[NEEDED AFTER RECORDING AND PUBLIC-VIEW TEST]` |

### Project Objectives — paste-ready answer

ReconX closes the multi-source payment-settlement reconciliation loop across Razorpay
payments, refunds, inclusive fees and taxes, bank credits and the internal ledger. It
uses deterministic integer-paise accounting for financial truth, safely auto-resolves
only high-confidence balanced groups, sends ambiguous cases to explicit human review,
and preserves a complete audit and exception trail. On a separately seeded synthetic
held-out batch of 1,400 records across 110 settlement groups, it achieved 100% precision
on 65 safely automated groups, 100% coverage of eligible groups versus 76.9231% for an
exact-ID baseline, zero false matches and a complete list of 45 non-automated cases.
All 40 actionable exceptions enter a durable human-review queue; quarantined input cases
remain visible. The system also converts exported Razorpay, bank and ledger evidence into
a hash-verifiable close pack without giving AI authority over financial state.

### Build Challenges & Technical Obstacles — paste-ready answer

The hardest challenge was preventing an AI-assisted finance tool from silently making
unsafe accounting decisions. We separated deterministic financial invariants from the
advisory AI analyst: money arithmetic, matching, confidence gates, permissions and state
transitions stay in deterministic code, while AI can only classify and explain an
already-detected exception using allow-listed evidence. We also handled noisy or missing
references, partial refunds, one-to-many settlements, duplicates, malformed records and
inclusive fee/tax accounting without forcing uncertain matches. For Razorpay delivery
risks, we verify HMAC-SHA256 against exact raw webhook bytes before parsing, atomically
deduplicate event IDs, prevent out-of-order rollback, support current/previous webhook
secrets and keep a hash-chained delivery audit. Provider failure, malformed AI output and
unsupported settlement items fail safely into review or unresolved states.

## Final submission gate

- Public GitHub repository opens while signed out.
- Live Render demo and `/health` endpoint open while signed out.
- README setup succeeds from a fresh checkout.
- Hosted CI is green on the submitted commit.
- `make release` passes without credentials.
- No `.env`, API secret, webhook secret, token or private customer data is committed.
- Video is five minutes or less and opens while signed out.
- Video shows the 1,400-record run, metrics, exception queue, human review, audit trail
  and one handled webhook failure.
- GitHub and video URLs are pasted into a temporary note and opened once more.
- Only then select the irreversible final-submission confirmation.

Official sources:

- <https://razorpay.com/buildathon/>
- <https://forms.gle/d9r2gvxp8cmoZhon9>
