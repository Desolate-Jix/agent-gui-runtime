(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.AgentRuntimePanel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const START = "/runtime/agent/session/start";
  const INTENT = "/runtime/agent/intent/submit";
  const DECIDE = "/runtime/agent/confirmation/decide";
  const SHA256 = /^[0-9a-f]{64}$/;
  const RECEIPT_OUTCOMES = new Set(["VERIFIED", "DISPATCHED", "BLOCKED", "SAFE_STOP", "EXECUTION_FAILED", "VERIFICATION_FAILED", "INDETERMINATE"]);

  function clone(value) { return value == null ? value : JSON.parse(JSON.stringify(value)); }
  function text(value) { return typeof value === "string" ? value.trim() : ""; }
  function defaultIntentId() {
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") return globalThis.crypto.randomUUID();
    throw new Error("A UUID generator is required for agent intents.");
  }
  function safeJson(value) {
    try { return JSON.stringify(value, null, 2); } catch (_error) { return "{\"error\":\"unserializable response\"}"; }
  }
  function validWorkflow(workflow) {
    return workflow && typeof workflow === "object"
      && text(workflow.workflow_id) && text(workflow.asset_id)
      && SHA256.test(text(workflow.asset_content_sha256))
      && SHA256.test(text(workflow.source_workflow_sha256))
      && SHA256.test(text(workflow.reviewed_revision_hash));
  }
  function sameWorkflow(left, right) {
    return validWorkflow(left) && validWorkflow(right)
      && left.workflow_id === right.workflow_id
      && left.asset_id === right.asset_id
      && left.asset_content_sha256 === right.asset_content_sha256
      && left.source_workflow_sha256 === right.source_workflow_sha256
      && left.reviewed_revision_hash === right.reviewed_revision_hash;
  }
  function validSafeStopAction(action) {
    return action && typeof action === "object"
      && action.action_id === "runtime.safe_stop"
      && action.semantic_action === "safe_stop"
      && action.target_state_id === null
      && action.risk_level === "low"
      && action.requires_user_confirmation === false
      && Array.isArray(action.verification_rule_refs)
      && action.verification_rule_refs.length === 0;
  }
  function validOpenApplyAction(action) {
    return action && typeof action === "object"
      && text(action.action_id)
      && action.semantic_action === "open_apply_flow"
      && text(action.target_state_id)
      && text(action.expected_effect)
      && Array.isArray(action.verification_rule_refs)
      && action.verification_rule_refs.length > 0
      && new Set(action.verification_rule_refs).size === action.verification_rule_refs.length
      && ["medium", "high"].includes(action.risk_level)
      && action.requires_user_confirmation === true;
  }
  function observationBase(data) {
    return data && typeof data === "object"
      && data.contract_version === "agent_observation_v1"
      && text(data.session_id) && text(data.observation_id)
      && validWorkflow(data.workflow)
      && data.artifact_is_authorization === false
      && data.safe_stop && typeof data.safe_stop === "object"
      && typeof data.safe_stop.required === "boolean"
      && text(data.safe_stop.reason_code)
      && Array.isArray(data.blockers);
  }
  function observationBinding(data) {
    if (!observationBase(data) || data.safe_stop.required !== false || data.safe_stop.reason_code !== "none") return null;
    if (!data.blockers.every((blocker) => blocker && typeof blocker === "object" && blocker.safe_stop_required === false)) return null;
    const actions = data.available_actions;
    if (!Array.isArray(actions) || actions.length !== 2) return null;
    const ids = actions.map((action) => text(action && action.action_id));
    if (ids.some((id) => !id) || new Set(ids).size !== ids.length) return null;
    const applyActions = actions.filter((action) => action && action.semantic_action === "open_apply_flow");
    const safeActions = actions.filter((action) => action && action.semantic_action === "safe_stop");
    if (applyActions.length !== 1 || safeActions.length !== 1 || !validOpenApplyAction(applyActions[0]) || !validSafeStopAction(safeActions[0])) return null;
    return { session_id: text(data.session_id), observation_id: text(data.observation_id), workflow: clone(data.workflow), action_id: text(applyActions[0].action_id) };
  }
  function safeStopBinding(data) {
    if (!observationBase(data) || data.safe_stop.required !== true || data.safe_stop.reason_code === "none") return null;
    if (!data.blockers.some((blocker) => blocker && typeof blocker === "object" && blocker.safe_stop_required === true)) return null;
    if (!Array.isArray(data.available_actions) || data.available_actions.length !== 1 || !validSafeStopAction(data.available_actions[0])) return null;
    return { session_id: text(data.session_id), observation_id: text(data.observation_id), workflow: clone(data.workflow) };
  }
  function validReceipt(receipt, intent, observation) {
    if (!receipt || typeof receipt !== "object" || !intent || !observation) return false;
    if (receipt.contract_version !== "runtime_result_receipt_v1" || !text(receipt.receipt_id) || !text(receipt.issued_at)) return false;
    if (receipt.session_id !== intent.session_id || receipt.session_id !== observation.session_id || receipt.observation_id !== intent.observation_id || receipt.observation_id !== observation.observation_id || receipt.intent_id !== intent.intent_id || !sameWorkflow(receipt.workflow, intent.workflow) || !sameWorkflow(receipt.workflow, observation.workflow) || receipt.artifact_is_authorization !== false) return false;
    if (!receipt.action || receipt.action.action_id !== intent.action_id || receipt.action.semantic_action !== "open_apply_flow") return false;
    if (!RECEIPT_OUTCOMES.has(receipt.outcome) || !text(receipt.reason_code) || ![0, 1].includes(receipt.attempt_count)) return false;
    if (!["not_evaluated", "allowed", "blocked"].includes(receipt.gate_status) || !["not_started", "dispatched", "indeterminate"].includes(receipt.dispatch_status) || !["not_evaluated", "verified", "not_verified", "indeterminate"].includes(receipt.effect_status) || !["not_evaluated", "verified", "not_verified", "indeterminate"].includes(receipt.destination_status)) return false;
    if (!receipt.safe_stop || typeof receipt.safe_stop.required !== "boolean" || receipt.safe_stop.reason_code !== receipt.reason_code) return false;
    if (!receipt.evidence || receipt.evidence.state_resolution_ref !== observation.state_resolution_ref || !Array.isArray(receipt.evidence.trace_refs) || receipt.evidence.trace_refs.length === 0) return false;
    if (receipt.outcome === "SAFE_STOP") return receipt.attempt_count === 1 && receipt.gate_status === "allowed" && receipt.dispatch_status === "dispatched" && receipt.effect_status === "verified" && receipt.destination_status === "verified" && receipt.safe_stop.required === true;
    if (receipt.outcome === "VERIFIED") return receipt.attempt_count === 1 && receipt.gate_status === "allowed" && receipt.dispatch_status === "dispatched" && receipt.effect_status === "verified" && receipt.destination_status === "verified" && receipt.safe_stop.required === false && text(receipt.next_observation_id);
    if (receipt.outcome === "DISPATCHED") return receipt.attempt_count === 1 && receipt.gate_status === "allowed" && receipt.dispatch_status === "dispatched" && receipt.effect_status === "verified" && receipt.destination_status === "not_evaluated" && receipt.safe_stop.required === true;
    if (receipt.outcome === "BLOCKED") return receipt.attempt_count === 0 && receipt.dispatch_status === "not_started" && receipt.safe_stop.required === true;
    return receipt.attempt_count === 1 && receipt.safe_stop.required === true;
  }
  function decision(data, intent, observation) {
    if (!data || typeof data !== "object") return null;
    if (data.status === "NEEDS_REVIEW" && data.reason_code === "human_confirmation_required" && text(data.confirmation_id)) return { kind: "needs_review", confirmation_id: text(data.confirmation_id) };
    if (data.status === "REJECTED" && text(data.reason_code)) return { kind: "rejected" };
    if (validReceipt(data, intent, observation)) return { kind: "receipt" };
    return null;
  }

  function createAgentRuntimePanel(options) {
    if (!options || (typeof options.request !== "function" && typeof options.transport !== "function")) throw new Error("AgentRuntimePanel requires a request(method, path, payload).");
    const transport = options.request || options.transport;
    const makeIntentId = typeof options.createIntentId === "function" ? options.createIntentId : defaultIntentId;
    let state = { phase: "idle", observation: null, intent: null, confirmation_id: "", confirmation: null, receipt: null, raw_response: null, error: "", error_code: "", error_details: "", busy: false };
    const listeners = new Set();
    function publish(next) { state = Object.freeze({ ...state, ...next }); listeners.forEach((listener) => listener(getState())); return getState(); }
    function lock(message, response, observation) {
      const serverError = response && response.error && typeof response.error === "object" ? response.error : null;
      return publish({ phase: "locked", busy: false, error: message, error_code: text(serverError && serverError.code) || "client_contract_invalid", error_details: serverError && serverError.details != null ? String(serverError.details) : message, raw_response: response == null ? state.raw_response : clone(response), observation: observation === undefined ? state.observation : observation });
    }
    function getState() { return clone(state); }
    function subscribe(listener) { if (typeof listener !== "function") throw new Error("listener must be a function"); listeners.add(listener); listener(getState()); return () => listeners.delete(listener); }
    async function call(path, payload) { try { return await transport("POST", path, payload); } catch (error) { return { success: false, error: { code: "transport_error", details: error && error.message ? error.message : "transport failed" } }; } }
    async function start() {
      if (state.busy || !["idle", "stopped"].includes(state.phase)) return getState();
      publish({ phase: "starting", busy: true, error: "", error_code: "", error_details: "", receipt: null, raw_response: null });
      const response = await call(START, {});
      if (!response || response.success !== true) return lock("Session start failed; recover before requesting an action.", response);
      if (observationBinding(response.data)) return publish({ phase: "ready", busy: false, observation: clone(response.data), intent: null, confirmation_id: "", confirmation: null, raw_response: clone(response), error: "" });
      if (safeStopBinding(response.data)) return publish({ phase: "stopped", busy: false, observation: clone(response.data), raw_response: clone(response), error: "", error_code: "", error_details: "" });
      return lock("Session start returned an unsafe or ambiguous observation; no action will be sent.", response, response.data);
    }
    async function requestStep() {
      if (state.busy || state.phase !== "ready") return getState();
      const binding = observationBinding(state.observation);
      if (!binding) return lock("Current observation is unsafe or ambiguous; recover before requesting another step.");
      let intentId;
      try { intentId = text(makeIntentId()); } catch (error) { return lock(error.message || "Could not create an intent id."); }
      if (!intentId) return lock("Could not create an intent id.");
      const intent = { intent_id: intentId, ...binding };
      const payload = { intent_id: intent.intent_id, session_id: intent.session_id, observation_id: intent.observation_id, action_id: intent.action_id };
      publish({ phase: "submitting", busy: true, intent, confirmation_id: "", confirmation: null, error: "", error_code: "", error_details: "" });
      const response = await call(INTENT, payload);
      const result = response && response.success === true ? decision(response.data, intent, state.observation) : null;
      if (!result || result.kind !== "needs_review") return lock("Intent response was unexpected; no further action will be sent.", response);
      const confirmation = { confirmation_id: result.confirmation_id, intent: clone(intent), response: clone(response.data) };
      return publish({ phase: "needs_review", busy: false, confirmation_id: result.confirmation_id, confirmation, raw_response: clone(response), error: "", error_code: "", error_details: "" });
    }
    async function decide(value) {
      const choice = text(value);
      if (state.busy || state.phase !== "needs_review" || !["approved", "denied"].includes(choice) || !text(state.confirmation_id) || !state.intent) return getState();
      const payload = { confirmation_id: state.confirmation_id, decision: choice };
      publish({ phase: "deciding", busy: true, error: "", error_code: "", error_details: "" });
      const response = await call(DECIDE, payload);
      const result = response && response.success === true ? decision(response.data, state.intent, state.observation) : null;
      if (!result || (choice === "approved" && result.kind !== "receipt") || (choice === "denied" && result.kind !== "rejected")) return lock("Confirmation response was unexpected; recover before any further action.", response);
      return publish({ phase: result.kind === "receipt" ? "terminal" : "rejected", busy: false, receipt: result.kind === "receipt" ? clone(response.data) : null, raw_response: clone(response), error: "", error_code: "", error_details: "" });
    }
    return Object.freeze({ getState, subscribe, start, requestStep, decide });
  }

  function mountAgentRuntimePanel(options) {
    const documentRef = options && options.document;
    if (!documentRef || typeof documentRef.getElementById !== "function") throw new Error("mountAgentRuntimePanel requires document.");
    const controller = createAgentRuntimePanel(options);
    const ids = { start: "agentRuntimeStartBtn", step: "agentRuntimeStepBtn", approve: "agentRuntimeApproveBtn", deny: "agentRuntimeDenyBtn", status: "agentRuntimeStatus", observation: "agentRuntimeObservation", receipt: "agentRuntimeResult", error: "agentRuntimeStatus", ...(options.ids || {}) };
    const element = (name) => documentRef.getElementById(ids[name]);
    const render = (state) => {
      const needsReview = state.phase === "needs_review";
      if (element("start")) element("start").disabled = state.busy || !["idle", "stopped"].includes(state.phase);
      if (element("step")) element("step").disabled = state.busy || state.phase !== "ready";
      if (element("approve")) element("approve").disabled = state.busy || !needsReview;
      if (element("deny")) element("deny").disabled = state.busy || !needsReview;
      if (element("status")) element("status").textContent = state.error ? `${state.phase}: ${state.error}` : state.phase === "stopped" ? "stopped: safe-stop boundary; no action will be sent" : state.phase;
      if (element("observation")) element("observation").textContent = safeJson(state.observation);
      if (element("receipt")) element("receipt").textContent = safeJson(state.phase === "locked"
        ? { error: { code: state.error_code, details: state.error_details }, intent: state.intent, confirmation: state.confirmation, response: state.raw_response }
        : state.receipt || (state.phase === "rejected" ? state.raw_response : state.confirmation));
      if (ids.error !== ids.status && element("error")) element("error").textContent = state.error ? safeJson({ code: state.error_code, details: state.error_details }) : "";
    };
    controller.subscribe(render);
    const bind = (name, action) => { const node = element(name); if (node && typeof node.addEventListener === "function") node.addEventListener("click", action); };
    bind("start", () => { void controller.start(); }); bind("step", () => { void controller.requestStep(); }); bind("approve", () => { void controller.decide("approved"); }); bind("deny", () => { void controller.decide("denied"); });
    return controller;
  }

  return Object.freeze({ createAgentRuntimePanel, mountAgentRuntimePanel });
});
