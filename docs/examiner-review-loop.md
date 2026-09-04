# ReconX examiner review loop

This is an internal, evidence-based rehearsal rubric, not an official Razorpay score or
a guarantee of selection. It exists to force each submission revision to answer the
official Track 4 bar with visible proof.

## Official target

Razorpay asks Track 4 builders to close one finance-operations loop across 50+ synthetic
records and report throughput, measured accuracy and unresolved exceptions. The general
submission asks for a public repository, a five-minute pitch video and architecture.

Source: <https://razorpay.com/buildathon/>

## Weighted rehearsal rubric

| Criterion | Weight | Evidence expected |
|---|---:|---|
| Track 4 problem fit | 15 | A consequential finance-ops problem and a complete close loop |
| Working end-to-end product | 20 | Input, reconciliation, exception handling, review and close output |
| Measurement quality | 15 | Synthetic batch, ground truth, baseline, throughput and honest metrics |
| Financial correctness and safety | 15 | Integer units, invariants, bounded authority and failure handling |
| Meaningful AI use | 10 | AI adds contextual value without owning accounting truth |
| Innovation and differentiation | 10 | Defensible mechanism beyond a generic matcher or chatbot |
| Five-minute demo clarity | 10 | Problem, live proof, architecture, results and limitations are legible |
| Submission readiness | 5 | Public links, reproducible repository, CI, security and no secret leakage |

## Iterations

### Version 1 — original narrated slideshow: 8.7/10

Strengths: accurate claims, strong held-out evidence, explicit synthetic-data disclosure,
clear finance boundary and clean 1080p output.

Deductions:

- too many static slides and too little visible product interaction;
- the 100% eligible-coverage result could be confused with the 59.1% whole-batch
  auto-match rate;
- business value and the close-pack outcome appeared too late;
- webhook controls were listed without showing a concrete failed/replayed-delivery story;
- the distinctive evidence and policy controls were not separated sharply enough from
  other deterministic-plus-LLM reconciliation entries.

### Version 2 — corrected product and judge narrative: 9.3/10

Changes:

- added the whole-batch auto-match rate and 65-of-110 denominator directly to the UI;
- relabelled uploaded-file processing accurately as server-side with no AI;
- moved the official Track 4 contract and the business outcome into the first minute;
- centered the narrative on the frozen policy, ground-truth separation, complete
  exception ledger and verifiable close pack;
- added live before/after review evidence and a concrete duplicate-webhook failure path.

Remaining deduction: the final video still needed timing, neural-voice, subtitle,
legibility and representative-frame verification.

### Version 3 — submission master: 9.7/10

Acceptance evidence:

- under five minutes, 1920×1080 H.264 with AAC audio and English subtitles;
- shows the live product, a safe money proof, a recovered missing-reference case, the
  complete exception ledger, live Groq advisory output, human authority boundary,
  close-pack outcome, webhook replay safety and architecture;
- says both 59.1% whole-batch auto-match and 100% eligible coverage with denominators;
- says the data is public repository-generated synthetic evidence and makes no
  production-accuracy, live-money or real-merchant claim;
- explains why `settlement.processed` is not treated as bank-credit proof;
- closes with a concise, memorable product thesis.

Residual limitations that keep the score below 10:

- no Razorpay-originated Test Mode webhook delivery is claimed;
- model explanation quality is not independently benchmarked because AI has no finance
  authority in this build;
- Render's free filesystem is ephemeral and the public demo has no production identity
  or role system;
- the held-out generator is public, not independently sequestered.

## Claim ledger used by the final video

| Claim | Repository evidence |
|---|---|
| 1,400 raw synthetic records, 110 groups, 22 scenarios | `data/heldout/manifest.json` |
| 65/110 whole-batch auto-match, 65/65 eligible coverage | `reports/phase4-heldout-evaluation.json` |
| 45 non-auto outcomes, all listed | `reports/phase4-heldout-evaluation.json` |
| 100% safe precision and zero false matches | `reports/phase4-heldout-evaluation.json` |
| 19/19 delivery controls | `reports/phase5-integration-report.json` |
| 11/11 analyst/review safety checks | `reports/phase3-safety-report.json` |
| 72 regression tests and 18/18 release checks | local and CI verification output |
| ₹10.57 lakh safely auto-closed and 260 estimated minutes saved | held-out close pack; explicit four-minute-per-safe-group assumption |

