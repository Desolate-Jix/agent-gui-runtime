const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const source = fs.readFileSync(path.join(__dirname, "../../app/web_panel/panel.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "../../app/web_panel/index.html"), "utf8");
test("learning review render binds dynamically inserted region/action preview buttons", () => {
  const start = source.indexOf("function renderLearningDraftReview(review)");
  const end = source.indexOf("function clearLearningDraftReviewDisplay", start);
  const body = source.slice(start, end);
  assert.match(body, /bindLearningDraftPreviewButtons\(\$\("learningDraftReviewRegions"\)\)/);
  assert.match(body, /bindLearningDraftPreviewButtons\(\$\("learningDraftReviewActions"\)\)/);
});
test("image inspector uses mandatory open_apply_flow taxonomy", () => {
  assert.match(html, /value="open_apply_flow"/);
  assert.doesNotMatch(html, /value="open_flow"/);
});

test("operation editor exposes three separate non-execution granular approval gestures", () => {
  assert.match(html, /id="interfaceWorkflowOperationApproveTargetControlBtn"/);
  assert.match(html, /id="interfaceWorkflowOperationApproveActionCandidateBtn"/);
  assert.match(html, /id="interfaceWorkflowOperationApproveEdgeBtn"/);
  assert.match(source, /confirmOperationTargetControlHumanReview/);
  assert.match(source, /confirmOperationActionCandidateHumanReview/);
  assert.match(source, /confirmOperationEdgeHumanReview/);
});

test("granular approval aborts when the operation editor commit fails", () => {
  const vm = require("node:vm");
  const start = source.indexOf("function confirmCurrentInterfaceWorkflowOperationGranular");
  const end = source.indexOf("async function dryRunInterfaceWorkflowOperation", start);
  let confirmations = 0;
  const sandbox = {
    interfaceWorkflowReviewState: {
      confirmOperationEdgeHumanReview: () => { confirmations += 1; },
    },
    interfaceWorkflowSelectedOperationId: "edge_open",
    commitInterfaceWorkflowOperationEditor: () => null,
    $: () => null,
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.result = confirmCurrentInterfaceWorkflowOperationGranular("edge");`,
    sandbox,
  );

  assert.equal(sandbox.result, null);
  assert.equal(confirmations, 0);
});

test("operation editor mutation commits or revokes before rerendering approval badges", () => {
  const vm = require("node:vm");
  const start = source.indexOf("function handleInterfaceWorkflowOperationEditorMutation");
  const end = source.indexOf("function interfaceWorkflowAssetV2BindingCandidate", start);
  assert.notEqual(start, -1);
  const calls = [];
  const sandbox = {
    interfaceWorkflowReviewState: {
      revokeOperationEdgeHumanReview: (edgeId) => calls.push(["revoke", edgeId]),
      snapshot: () => ({ current: true }),
    },
    interfaceWorkflowSelectedOperationId: "edge_open",
    interfaceWorkflowReview: null,
    commitInterfaceWorkflowOperationEditor: () => null,
    clearInterfaceWorkflowNodeHumanReviewConfirmation: () => calls.push(["clear"]),
    currentInterfaceWorkflowOperation: () => ({ edge_id: "edge_open" }),
    markInterfaceWorkflowUnsaved: () => calls.push(["dirty"]),
    renderInterfaceWorkflowOperationGranularStatus: () => calls.push(["render_badges"]),
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; handleInterfaceWorkflowOperationEditorMutation();`,
    sandbox,
  );

  assert.deepEqual(calls, [["clear"], ["revoke", "edge_open"], ["dirty"], ["render_badges"]]);
});

test("needs_learning renders as a locked stop boundary instead of an approvable node", () => {
  const vm = require("node:vm");
  const start = source.indexOf("function renderInterfaceWorkflowEditor");
  const end = source.indexOf("function clearInterfaceWorkflowNodeHumanReviewConfirmation", start);
  const elements = {
    interfaceWorkflowNodeName: {},
    interfaceWorkflowSurfaceType: {},
    interfaceWorkflowNodeReviewStatus: {},
    interfaceWorkflowNodeHumanReviewConfirmed: {},
    interfaceWorkflowSaveStatus: {},
  };
  const sandbox = {
    $: (id) => elements[id] || null,
    interfaceWorkflowHasUnsavedChanges: false,
    renderInterfaceWorkflowContentEditor: () => {},
    renderInterfaceWorkflowOperationEditor: () => {},
    t: () => "saved",
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; renderInterfaceWorkflowEditor({ node: { node_id: "stop", review_status: "needs_learning" } });`,
    sandbox,
  );

  assert.match(html, /option value="needs_learning"/);
  assert.equal(elements.interfaceWorkflowNodeReviewStatus.value, "needs_learning");
  assert.equal(elements.interfaceWorkflowNodeReviewStatus.disabled, true);
  assert.equal(elements.interfaceWorkflowNodeHumanReviewConfirmed.disabled, true);
});
