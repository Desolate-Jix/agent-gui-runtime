const test = require("node:test");
const assert = require("node:assert/strict");
const { createAgentRuntimePanel, mountAgentRuntimePanel } = require("../../app/web_panel/agent_runtime_panel.js");

const sha = (letter) => letter.repeat(64);
const workflow = { workflow_id: "workflow-1", asset_id: "asset-1", asset_content_sha256: sha("a"), source_workflow_sha256: sha("b"), reviewed_revision_hash: sha("c") };
const apply = { action_id: "apply-1", semantic_action: "open_apply_flow", target_state_id: "apply-entry", expected_effect: "Open the bounded Apply Entry flow.", verification_rule_refs: ["verify:apply-entry"], risk_level: "medium", requires_user_confirmation: true };
const safeStop = { action_id: "runtime.safe_stop", semantic_action: "safe_stop", target_state_id: null, expected_effect: "Stop without dispatch.", verification_rule_refs: [], risk_level: "low", requires_user_confirmation: false };
function makeObservation(overrides = {}) {
  return { contract_version: "agent_observation_v1", session_id: "session-1", observation_id: "observation-1", workflow, state_resolution_ref: "state-resolution:1", blockers: [], available_actions: [apply, safeStop], safe_stop: { required: false, reason_code: "none" }, artifact_is_authorization: false, ...overrides };
}
function makeSafeStopObservation() {
  return makeObservation({ blockers: [{ blocker_id: "boundary-1", safe_stop_required: true }], available_actions: [safeStop], safe_stop: { required: true, reason_code: "stop_boundary" } });
}
function makeReceipt(overrides = {}) {
  return { contract_version: "runtime_result_receipt_v1", receipt_id: "receipt-1", issued_at: "2026-09-06T01:02:03Z", session_id: "session-1", observation_id: "observation-1", intent_id: "intent-1", workflow, action: { action_id: "apply-1", semantic_action: "open_apply_flow" }, outcome: "SAFE_STOP", reason_code: "stop_boundary", attempt_count: 1, gate_status: "allowed", dispatch_status: "dispatched", effect_status: "verified", destination_status: "verified", evidence: { state_resolution_ref: "state-resolution:1", trace_refs: ["trace:1"] }, next_observation_id: null, safe_stop: { required: true, reason_code: "stop_boundary" }, artifact_is_authorization: false, ...overrides };
}
function needsReview() { return { status: "NEEDS_REVIEW", reason_code: "human_confirmation_required", confirmation_id: "confirm-1" }; }
function transport(responses, calls) { return async (method, path, payload) => { calls.push({ method, path, payload }); return responses.shift(); }; }

test("construct and mount make no request; start sends the exact empty payload", async () => {
  const calls = [];
  const panel = createAgentRuntimePanel({ transport: transport([{ success: true, data: makeObservation() }], calls), createIntentId: () => "intent-1" });
  assert.equal(calls.length, 0); await panel.start();
  assert.deepEqual(calls, [{ method: "POST", path: "/runtime/agent/session/start", payload: {} }]);
  assert.equal(panel.getState().phase, "ready");
  const nodes = {};
  for (const id of ["agentRuntimeStartBtn", "agentRuntimeStepBtn", "agentRuntimeApproveBtn", "agentRuntimeDenyBtn", "agentRuntimeStatus", "agentRuntimeObservation", "agentRuntimeResult"]) nodes[id] = { disabled: false, textContent: "", addEventListener() {} };
  mountAgentRuntimePanel({ document: { getElementById: (id) => nodes[id] || null }, transport: transport([], calls) });
  assert.equal(calls.length, 1); assert.equal(nodes.agentRuntimeStatus.textContent, "idle"); assert.equal(nodes.agentRuntimeObservation.innerHTML, undefined);
});

test("only the exact confirmed bounded apply action creates the server payload and retains confirmation", async () => {
  const calls = [];
  const panel = createAgentRuntimePanel({ transport: transport([{ success: true, data: makeObservation() }, { success: true, data: needsReview() }], calls), createIntentId: () => "intent-1" });
  await panel.start(); await panel.requestStep();
  assert.deepEqual(calls[1], { method: "POST", path: "/runtime/agent/intent/submit", payload: { intent_id: "intent-1", session_id: "session-1", observation_id: "observation-1", action_id: "apply-1" } });
  assert.equal(panel.getState().phase, "needs_review");
  assert.equal(panel.getState().confirmation.intent.workflow.workflow_id, "workflow-1");
});

test("mounted result visibly renders the explicit confirmation before approval", async () => {
  const calls = []; const nodes = {};
  for (const id of ["agentRuntimeStartBtn", "agentRuntimeStepBtn", "agentRuntimeApproveBtn", "agentRuntimeDenyBtn", "agentRuntimeStatus", "agentRuntimeObservation", "agentRuntimeResult"]) {
    nodes[id] = { disabled: false, textContent: "", addEventListener(_event, listener) { this.listener = listener; } };
  }
  const panel = mountAgentRuntimePanel({ document: { getElementById: (id) => nodes[id] || null }, transport: transport([{ success: true, data: makeObservation() }, { success: true, data: needsReview() }], calls), createIntentId: () => "intent-1" });
  await panel.start(); await panel.requestStep();
  assert.match(nodes.agentRuntimeResult.textContent, /"confirmation_id": "confirm-1"/);
  assert.equal(nodes.agentRuntimeApproveBtn.disabled, false);
});

test("failed approval displays current server error without losing pending identity", async () => {
  const calls = []; const nodes = {};
  for (const id of ["agentRuntimeStartBtn", "agentRuntimeStepBtn", "agentRuntimeApproveBtn", "agentRuntimeDenyBtn", "agentRuntimeStatus", "agentRuntimeObservation", "agentRuntimeResult"]) {
    nodes[id] = { disabled: false, textContent: "", addEventListener() {} };
  }
  const panel = mountAgentRuntimePanel({ document: { getElementById: (id) => nodes[id] }, request: transport([
    { success: true, data: makeObservation() }, { success: true, data: needsReview() },
    { success: false, error: { code: "agent_runtime_recovery_required", details: "dispatch indeterminate" } },
  ], calls), createIntentId: () => "intent-1" });
  await panel.start(); await panel.requestStep(); await panel.decide("approved");
  const visible = JSON.parse(nodes.agentRuntimeResult.textContent);
  assert.equal(visible.error.code, "agent_runtime_recovery_required");
  assert.equal(visible.confirmation.confirmation_id, "confirm-1");
  assert.equal(visible.intent.intent_id, "intent-1");
  assert.equal(nodes.agentRuntimeApproveBtn.disabled, true);
  await panel.decide("approved"); await panel.start();
  assert.equal(calls.length, 3);
});

test("returned state snapshots cannot mutate the controller's server binding", async () => {
  const calls = [];
  const panel = createAgentRuntimePanel({ request: transport([
    { success: true, data: makeObservation() }, { success: true, data: needsReview() },
  ], calls), createIntentId: () => "intent-1" });
  const snapshot = await panel.start();
  snapshot.observation.available_actions[0].action_id = "injected-action";
  snapshot.observation.workflow.asset_id = "injected-asset";
  await panel.requestStep();
  assert.equal(calls[1].payload.action_id, "apply-1");
  assert.equal(panel.getState().intent.workflow.asset_id, "asset-1");
});

test("approval is exactly confirmation-bound and duplicate approval while in flight cannot dispatch twice", async () => {
  const calls = []; let resolveDecision;
  const panel = createAgentRuntimePanel({ transport: async (method, path, payload) => {
    calls.push({ method, path, payload });
    if (path.endsWith("start")) return { success: true, data: makeObservation() };
    if (path.endsWith("submit")) return { success: true, data: needsReview() };
    return new Promise((resolve) => { resolveDecision = resolve; });
  }, createIntentId: () => "intent-1" });
  await panel.start(); await panel.requestStep();
  const first = panel.decide("approved"); const duplicate = panel.decide("approved");
  assert.equal(calls.length, 3); assert.deepEqual(calls[2], { method: "POST", path: "/runtime/agent/confirmation/decide", payload: { confirmation_id: "confirm-1", decision: "approved" } });
  resolveDecision({ success: true, data: makeReceipt() }); await Promise.all([first, duplicate]);
  assert.equal(panel.getState().phase, "terminal"); assert.equal(calls.length, 3);
});

test("denial is distinct and unknown final-submit cannot create a request", async () => {
  const calls = [];
  const panel = createAgentRuntimePanel({ transport: transport([{ success: true, data: makeObservation() }, { success: true, data: needsReview() }, { success: true, data: { status: "REJECTED", reason_code: "confirmation_denied" } }], calls), createIntentId: () => "intent-1" });
  await panel.start(); await panel.requestStep(); await panel.decide("denied"); await panel.decide("final_submit");
  assert.equal(calls.length, 3); assert.equal(panel.getState().phase, "rejected");
});

test("unsafe observations and malformed or mismatched receipts lock without false success", async () => {
  for (const data of [
    makeObservation({ available_actions: [{ ...apply, risk_level: "low" }, safeStop] }),
    makeObservation({ available_actions: [apply, { ...apply, action_id: "apply-2" }, safeStop] }),
    makeObservation({ blockers: [{ blocker_id: "blocked", safe_stop_required: true }] }),
    makeObservation({ safe_stop: { required: false, reason_code: "stop_boundary" } }),
    makeObservation({ available_actions: [{ ...apply, semantic_action: "final_submit" }, safeStop] }),
  ]) {
    const calls = []; const panel = createAgentRuntimePanel({ transport: transport([{ success: true, data }], calls) }); await panel.start();
    assert.equal(panel.getState().phase, "locked"); assert.equal(calls.length, 1);
  }
  const calls = []; const panel = createAgentRuntimePanel({ transport: transport([{ success: true, data: makeObservation() }, { success: true, data: needsReview() }, { success: true, data: makeReceipt({ intent_id: "other-intent" }) }], calls), createIntentId: () => "intent-1" });
  await panel.start(); await panel.requestStep(); await panel.decide("approved");
  assert.equal(panel.getState().phase, "locked"); assert.equal(panel.getState().intent.intent_id, "intent-1"); assert.equal(panel.getState().confirmation_id, "confirm-1"); assert.equal(panel.getState().raw_response.data.intent_id, "other-intent");
});

test("safe-stop start is stopped and non-actionable rather than a bad start", async () => {
  const calls = []; const panel = createAgentRuntimePanel({ transport: transport([{ success: true, data: makeSafeStopObservation() }], calls) });
  await panel.start(); assert.equal(panel.getState().phase, "stopped"); await panel.requestStep(); assert.equal(calls.length, 1);
});

test("a known initial safe stop permits only a new explicit observation request, never an automatic retry", async () => {
  const calls = [];
  const panel = createAgentRuntimePanel({ request: transport([
    { success: true, data: makeSafeStopObservation() },
    { success: true, data: makeObservation({ session_id: "session-2" }) },
  ], calls) });
  await panel.start();
  assert.equal(calls.length, 1);
  await panel.requestStep(); await panel.decide("approved");
  assert.equal(calls.length, 1);
  await panel.start();
  assert.equal(calls.length, 2);
  assert.equal(panel.getState().observation.session_id, "session-2");
});

test("transport rejection and timeout-shaped failure lock with preserved server error details", async () => {
  const rejected = createAgentRuntimePanel({ transport: async () => { throw new Error("network down"); } });
  await rejected.start();
  assert.equal(rejected.getState().phase, "locked"); assert.equal(rejected.getState().error_code, "transport_error"); assert.equal(rejected.getState().error_details, "network down");
  const timeout = createAgentRuntimePanel({ transport: async () => ({ success: false, error: { code: "request_timeout", details: "timed out" } }) });
  await timeout.start();
  assert.equal(timeout.getState().phase, "locked"); assert.equal(timeout.getState().error_code, "request_timeout"); assert.equal(timeout.getState().error_details, "timed out");
});
