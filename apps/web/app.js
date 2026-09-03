const $ = (id) => document.getElementById(id);

const money = (paise) => {
  if (paise === null || paise === undefined) return "Not found";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
  }).format(paise / 100);
};

const label = (value) => value.replaceAll("_", " ").toUpperCase();
const percent = (value) => `${(Number(value ?? 0) * 100).toFixed(1)}%`;
const integer = (value) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(value ?? 0);
const escapeHtml = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[character],
  );

function render(result) {
  const group = result.groups[0];
  const audit = result.audit_events[0];

  $("decision").textContent = label(group.state);
  $("confidence").textContent = `${(group.confidence * 100).toFixed(0)}% policy confidence`;
  $("expected").textContent = money(group.expected_bank_credit_paise);
  $("difference").textContent = money(group.difference_paise);
  $("unresolved").textContent = result.metrics.unresolved;
  $("settlement-id").textContent = group.settlement_id;
  $("gross").textContent = money(group.gross_payments_paise);
  $("refunds").textContent = money(group.refunds_paise);
  $("fees").textContent = money(group.inclusive_fees_paise);
  $("bank").textContent = money(group.actual_bank_credit_paise);
  $("tax-note").textContent = `${money(group.tax_component_paise)} GST is reported inside the fee and is not deducted twice.`;
  $("evidence-count").textContent = group.evidence_ids.length;

  $("reason-codes").innerHTML = group.reason_codes
    .map((reason) => `<span class="reason">${escapeHtml(reason)}</span>`)
    .join("");

  const auditRows = [
    ["Event", audit.id],
    ["Actor", audit.actor],
    ["Action", audit.action],
    ["Policy", audit.policy_version],
    ["Input hash", audit.input_hash.slice(0, 24) + "…"],
    ["Decision hash", audit.decision_hash.slice(0, 24) + "…"],
  ];
  $("audit-details").innerHTML = auditRows
    .map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`)
    .join("");

  $("exceptions").innerHTML = result.exceptions.length
    ? result.exceptions
        .map(
          (item) => `<div class="exception"><strong>${escapeHtml(label(item.code))}</strong><p>${escapeHtml(item.message)}<br>${escapeHtml(item.source_record_ids.join(", "))}</p></div>`,
        )
        .join("")
    : '<p class="tax-note">No open exceptions.</p>';

  $("loading").classList.add("hidden");
  $("dashboard").classList.remove("hidden");
}

let activeReview = null;
let reviewCases = [];
let latestClosePack = null;

async function loadHeldout() {
  const response = await fetch("/api/heldout");
  if (!response.ok) throw new Error(`Held-out API returned ${response.status}`);
  const report = await response.json();
  const summary = report.business_summary;
  const candidateCoverage = report.candidate_engine.auto_reconciliation_coverage;
  const baselineCoverage = report.exact_id_baseline.auto_reconciliation_coverage;
  const gate = $("heldout-gate");
  gate.textContent = report.phase_gate_passed ? "ALL GATES PASSED" : "GATE FAILED";
  gate.classList.add(report.phase_gate_passed ? "gate-pass" : "gate-fail");
  $("heldout-records").textContent = integer(summary.raw_records);
  $("heldout-groups").textContent = `${integer(summary.settlement_groups)} settlement groups`;
  $("heldout-precision").textContent = percent(summary.safe_auto_precision);
  $("heldout-coverage").textContent = percent(summary.eligible_group_coverage);
  $("heldout-delta").textContent = `+${(report.coverage_delta_vs_baseline * 100).toFixed(1)} percentage points vs exact-ID baseline`;
  $("heldout-throughput").textContent = integer(report.throughput.median_records_per_second);
  $("heldout-exceptions").textContent = integer(summary.exceptions_not_auto_resolved);
  $("heldout-unexpected").textContent = integer(summary.unexpected_exceptions);
  $("heldout-repro").textContent = `${report.decision_reproducibility.runs}/${report.decision_reproducibility.runs}`;
  $("candidate-value").textContent = percent(candidateCoverage);
  $("baseline-value").textContent = percent(baselineCoverage);
  $("candidate-bar").style.width = `${Math.max(0, Math.min(100, candidateCoverage * 100))}%`;
  $("baseline-bar").style.width = `${Math.max(0, Math.min(100, baselineCoverage * 100))}%`;
  const stateCounts = report.exception_summary.by_state;
  $("heldout-exception-list").innerHTML = Object.entries(stateCounts)
    .map(([state, count]) => `<span class="exception-chip">${escapeHtml(label(state))}: ${escapeHtml(count)}</span>`)
    .join("");
  $("heldout-exception-table").innerHTML = report.exceptions
    .map(
      (item) => `<div class="exception-row"><strong>${escapeHtml(item.settlement_id)}</strong><span>${escapeHtml(label(item.scenario))} · ${escapeHtml(label(item.state))}</span><span>${escapeHtml(item.reason_codes.join(", "))}</span></div>`,
    )
    .join("");
  $("heldout-proof-hash").textContent = `Evidence hash: ${report.deterministic_evidence_sha256} · Policy: ${report.policy_contract_sha256}`;
}

async function loadIntegration() {
  const response = await fetch("/api/integration");
  if (!response.ok) throw new Error(`Integration API returned ${response.status}`);
  const report = await response.json();
  const gate = $("integration-gate");
  gate.textContent = report.phase_gate_passed ? "ALL CONTROLS PASSED" : "CONTROL GATE FAILED";
  gate.classList.add(report.phase_gate_passed ? "gate-pass" : "gate-fail");
  $("integration-checks").textContent = `${report.passed}/${report.total}`;
  $("integration-events").textContent = integer(report.webhook_summary.unique_events);
  $("integration-deliveries").textContent = `${integer(report.webhook_summary.deliveries)} signed deliveries`;
  $("integration-recon").textContent = integer(report.recon_fixture_summary.fixture_items);
  $("integration-supported").textContent = `${integer(report.recon_fixture_summary.supported_items)} supported · ${integer(report.recon_fixture_summary.unsupported_items)} visible`;
  $("integration-runtime").textContent = report.runtime.webhook_configured ? "CONFIGURED" : "SAFE-OFF";
  $("integration-controls").innerHTML = report.security_controls
    .map((control) => `<span class="control-chip">${escapeHtml(label(control))}</span>`)
    .join("");
  $("integration-note").textContent = report.live_razorpay_call_made
    ? "Live Razorpay call recorded."
    : "Contract-tested with official-shape fixtures. No live Razorpay call or real money movement.";
}

async function loadReview() {
  const response = await fetch("/api/reviews");
  if (!response.ok) throw new Error(`Review API returned ${response.status}`);
  const payload = await response.json();
  const previousId = activeReview?.id;
  reviewCases = payload.cases;
  activeReview = reviewCases.find((item) => item.id === previousId) ?? reviewCases[0] ?? null;
  const selector = $("review-selector");
  selector.innerHTML = reviewCases
    .map((item, index) => `<option value="${escapeHtml(item.id)}">${index + 1}. ${escapeHtml(item.settlement_id)} · ${escapeHtml(label(item.status))}</option>`)
    .join("");
  if (activeReview) selector.value = activeReview.id;
  const runtime = payload.runtime ?? { enabled: false, provider: "disabled", mode: "deterministic_fallback" };
  $("analyst-runtime").textContent = `AI runtime: ${runtime.enabled ? runtime.provider : "safe deterministic fallback"}`;
  if (!activeReview) {
    $("review-status").textContent = "Empty";
    $("review-case").innerHTML = '<p class="tax-note">No cases require review.</p>';
    return;
  }
  $("review-status").textContent = label(activeReview.status);
  $("review-case").innerHTML = `
    <div class="review-block"><span>Deterministic finding</span><strong>${escapeHtml(label(activeReview.deterministic_state))}</strong><p>${escapeHtml(activeReview.reason_codes.join(", "))}</p></div>
    <div class="review-block"><span>Advisory analysis · ${escapeHtml(label(activeReview.analysis.risk_level))} risk</span><strong>${escapeHtml(label(activeReview.analysis.category))}</strong><p>${escapeHtml(activeReview.analysis.explanation)}<br>Next evidence: ${escapeHtml(activeReview.analysis.missing_evidence_types.map(label).join(", "))}</p></div>
    <div class="review-block"><span>Expected / actual</span><strong>${money(activeReview.expected_bank_credit_paise)} / ${money(activeReview.actual_bank_credit_paise)}</strong><p>Difference: ${money(activeReview.difference_paise)}</p></div>
    <div class="review-block"><span>Safety boundary</span><strong>${escapeHtml(activeReview.analysis.source)}</strong><p>AI cannot post or mutate this ledger. Version ${activeReview.version}.</p></div>`;
  const pending = activeReview.status === "pending";
  $("approve-review").disabled = !pending;
  $("reject-review").disabled = !pending;
  $("analyse-review").disabled = false;
}

function selectReview(caseId) {
  activeReview = reviewCases.find((item) => item.id === caseId) ?? null;
  if (!activeReview) return;
  $("review-status").textContent = label(activeReview.status);
  $("review-case").innerHTML = `
    <div class="review-block"><span>Deterministic finding</span><strong>${escapeHtml(label(activeReview.deterministic_state))}</strong><p>${escapeHtml(activeReview.reason_codes.join(", "))}</p></div>
    <div class="review-block"><span>Advisory analysis · ${escapeHtml(label(activeReview.analysis.risk_level))} risk</span><strong>${escapeHtml(label(activeReview.analysis.category))}</strong><p>${escapeHtml(activeReview.analysis.explanation)}<br>Next evidence: ${escapeHtml(activeReview.analysis.missing_evidence_types.map(label).join(", "))}</p></div>
    <div class="review-block"><span>Expected / actual</span><strong>${money(activeReview.expected_bank_credit_paise)} / ${money(activeReview.actual_bank_credit_paise)}</strong><p>Difference: ${money(activeReview.difference_paise)}</p></div>
    <div class="review-block"><span>Safety boundary</span><strong>${escapeHtml(activeReview.analysis.source)}</strong><p>AI cannot post or mutate this ledger. Version ${activeReview.version}.</p></div>`;
  const pending = activeReview.status === "pending";
  $("approve-review").disabled = !pending;
  $("reject-review").disabled = !pending;
}

async function analyseReview() {
  if (!activeReview) return;
  $("analyse-review").disabled = true;
  const response = await fetch(`/api/reviews/${encodeURIComponent(activeReview.id)}/analyse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor: "demo-reviewer", expected_version: activeReview.version }),
  });
  if (!response.ok) throw new Error(`Analysis API returned ${response.status}`);
  await loadReview();
}

async function importFiles() {
  const [reconFile, bankFile, ledgerFile] = [$("recon-file").files[0], $("bank-file").files[0], $("ledger-file").files[0]];
  if (!reconFile || !bankFile || !ledgerFile) throw new Error("Choose all three input files first.");
  $("import-button").disabled = true;
  $("import-status").textContent = "Reconciling";
  const response = await fetch("/api/import/reconcile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      batch_id: `upload_${new Date().toISOString()}`,
      synthetic: false,
      razorpay_recon: JSON.parse(await reconFile.text()),
      bank_csv: await bankFile.text(),
      ledger_csv: await ledgerFile.text(),
    }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail ?? `Import API returned ${response.status}`);
  latestClosePack = payload.close_pack;
  render(payload.result);
  $("import-status").textContent = `${payload.result.metrics.auto_approved} auto-closed · ${payload.import_issues.length} quarantined`;
  $("import-status").classList.add("gate-pass");
  const blob = new Blob([JSON.stringify(latestClosePack, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${payload.result.batch_id}-close-pack.json`;
  link.click();
  URL.revokeObjectURL(link.href);
  $("import-button").disabled = false;
}

async function decideReview(action) {
  if (!activeReview || activeReview.status !== "pending") return;
  const labelText = action === "approve" ? "approve" : "reject";
  if (!window.confirm(`Confirm ${labelText} for ${activeReview.settlement_id}? This appends an audit event.`)) return;
  const response = await fetch(`/api/reviews/${encodeURIComponent(activeReview.id)}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action,
      actor: "demo-reviewer",
      reason: `Evidence reviewed during the ReconX demo: ${labelText}`,
      expected_version: activeReview.version,
    }),
  });
  if (!response.ok) throw new Error(`Decision API returned ${response.status}`);
  await loadReview();
}

async function run() {
  $("dashboard").classList.add("hidden");
  $("loading").classList.remove("hidden");
  try {
    const response = await fetch("/api/reconcile/heldout");
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    render(await response.json());
  } catch (error) {
    $("loading").innerHTML = `<span>Unable to run demo: ${escapeHtml(error.message)}</span>`;
  }
}

$("run-button").addEventListener("click", run);
$("approve-review").addEventListener("click", () => decideReview("approve").catch(console.error));
$("reject-review").addEventListener("click", () => decideReview("reject").catch(console.error));
$("analyse-review").addEventListener("click", () => analyseReview().catch((error) => {
  $("analyst-runtime").textContent = error.message;
  $("analyse-review").disabled = false;
}));
$("review-selector").addEventListener("change", (event) => selectReview(event.target.value));
$("import-button").addEventListener("click", () => importFiles().catch((error) => {
  $("import-status").textContent = error.message;
  $("import-status").classList.add("gate-fail");
  $("import-button").disabled = false;
}));
run();
loadReview().catch((error) => {
  $("review-status").textContent = "Unavailable";
  $("review-case").textContent = error.message;
});
loadHeldout().catch((error) => {
  $("heldout-gate").textContent = "Evidence unavailable";
  $("heldout-gate").classList.add("gate-fail");
  $("heldout-proof-hash").textContent = error.message;
});
loadIntegration().catch((error) => {
  $("integration-gate").textContent = "Evidence unavailable";
  $("integration-gate").classList.add("gate-fail");
  $("integration-note").textContent = error.message;
});
