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

test("operation editor exposes one primary review gesture while keeping granular receipts", () => {
  assert.match(html, /id="interfaceWorkflowOperationApproveBundleBtn"/);
  assert.match(html, /批准这条操作路径/);
  assert.doesNotMatch(html, /id="interfaceWorkflowOperationApproveTargetControlBtn"/);
  assert.doesNotMatch(html, /id="interfaceWorkflowOperationApproveActionCandidateBtn"/);
  assert.doesNotMatch(html, /id="interfaceWorkflowOperationApproveEdgeBtn"/);
  assert.match(source, /confirmOperationHumanReviewBundle/);
  assert.match(html, /id="interfaceWorkflowApproveAndSaveBtn"/);
  assert.match(html, /批准并保存当前界面/);
  assert.match(html, /id="interfaceWorkflowSaveBtn"[^>]*>仅保存草稿/);
  assert.doesNotMatch(html, /id="interfaceWorkflowNodeApproveBtn"/);
  assert.doesNotMatch(html, /id="interfaceWorkflowNodeHumanReviewConfirmed"/);
});

test("operation review bundle aborts when the operation editor commit fails", () => {
  const vm = require("node:vm");
  const start = source.indexOf("function confirmCurrentInterfaceWorkflowOperationBundle");
  const end = source.indexOf("async function dryRunInterfaceWorkflowOperation", start);
  let confirmations = 0;
  const sandbox = {
    interfaceWorkflowReviewState: {
      confirmOperationHumanReviewBundle: () => { confirmations += 1; },
    },
    interfaceWorkflowSelectedOperationId: "edge_open",
    commitInterfaceWorkflowOperationEditor: () => null,
    $: () => null,
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.result = confirmCurrentInterfaceWorkflowOperationBundle();`,
    sandbox,
  );

  assert.equal(sandbox.result, null);
  assert.equal(confirmations, 0);
});

test("operation review bundle commits once and records one user gesture", () => {
  const vm = require("node:vm");
  const start = source.indexOf("function confirmCurrentInterfaceWorkflowOperationBundle");
  const end = source.indexOf("async function dryRunInterfaceWorkflowOperation", start);
  const calls = [];
  const sandbox = {
    interfaceWorkflowReviewState: {
      confirmOperationHumanReviewBundle: (edgeId) => {
        calls.push(["confirm_bundle", edgeId]);
        return { edge_id: edgeId };
      },
      snapshot: () => ({ saved: false }),
    },
    interfaceWorkflowSelectedOperationId: "edge_open",
    interfaceWorkflowReview: null,
    commitInterfaceWorkflowOperationEditor: (options) => {
      calls.push(["commit", options.silent]);
      return { edge_id: "edge_open" };
    },
    markInterfaceWorkflowUnsaved: (message) => calls.push(["dirty", message]),
    renderInterfaceWorkflowReviewSelection: () => calls.push(["render"]),
    $: () => null,
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.result = confirmCurrentInterfaceWorkflowOperationBundle();`,
    sandbox,
  );

  assert.equal(sandbox.result.edge_id, "edge_open");
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    ["commit", true],
    ["confirm_bundle", "edge_open"],
    ["dirty", "已批准当前操作路径 · 内部审核事实已记录 · 尚未保存"],
    ["render"],
  ]);
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
    interfaceWorkflowApproveAndSaveBtn: {},
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
  assert.equal(elements.interfaceWorkflowApproveAndSaveBtn.disabled, true);
});

test("approve and save persists exactly the approved revision without a second editor commit", async () => {
  const vm = require("node:vm");
  const start = source.indexOf("async function approveAndSaveCurrentInterfaceWorkflowNode");
  const end = source.indexOf("function commitInterfaceWorkflowEditorToState", start);
  assert.notEqual(start, -1, "approve-and-save handler must exist");
  const calls = [];
  const sandbox = {
    approveCurrentInterfaceWorkflowNode: () => {
      calls.push(["approve"]);
      return { nodes: [{ node_id: "job_detail", review_status: "human_approved" }] };
    },
    saveInterfaceWorkflowReview: async (options) => {
      calls.push(["save", options]);
      return { path: "reviewed_workflow.json" };
    },
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.result = approveAndSaveCurrentInterfaceWorkflowNode();`,
    sandbox,
  );

  assert.deepEqual(JSON.parse(JSON.stringify(await sandbox.result)), {
    path: "reviewed_workflow.json",
  });
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    ["approve"],
    ["save", { commitEditor: false }],
  ]);
});

test("approve and save does not save when node approval is blocked", async () => {
  const vm = require("node:vm");
  const start = source.indexOf("async function approveAndSaveCurrentInterfaceWorkflowNode");
  const end = source.indexOf("function commitInterfaceWorkflowEditorToState", start);
  assert.notEqual(start, -1, "approve-and-save handler must exist");
  let saves = 0;
  const sandbox = {
    approveCurrentInterfaceWorkflowNode: () => null,
    saveInterfaceWorkflowReview: async () => { saves += 1; return {}; },
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.result = approveAndSaveCurrentInterfaceWorkflowNode();`,
    sandbox,
  );

  assert.equal(await sandbox.result, null);
  assert.equal(saves, 0);
});

test("approving the current interface commits its revision once without a status gesture", () => {
  const vm = require("node:vm");
  const start = source.indexOf("function approveCurrentInterfaceWorkflowNode");
  const end = source.indexOf("function commitInterfaceWorkflowEditorToState", start);
  const calls = [];
  const elements = {
    interfaceWorkflowNodeName: { value: "Job Detail" },
    interfaceWorkflowSurfaceType: { value: "detail" },
  };
  const sandbox = {
    interfaceWorkflowReviewState: {
      current: () => ({ node: { node_id: "job_detail", review_status: "needs_human_review" } }),
    },
    interfaceWorkflowReview: null,
    window: {
      InterfaceWorkflowReview: {
        commitInterfaceWorkflowReviewForSave: (options) => {
          calls.push(["commit", options.nodeId, options.nodePatch, options.humanReviewConfirmed]);
          options.commitOperation();
          return { nodes: [{ node_id: options.nodeId, review_status: "human_approved" }] };
        },
      },
    },
    commitInterfaceWorkflowOperationEditor: (options) => calls.push(["commit_operation", options.silent]),
    markInterfaceWorkflowUnsaved: (message) => calls.push(["dirty", message]),
    renderInterfaceWorkflowReviewSelection: () => calls.push(["render"]),
    $: (id) => elements[id] || null,
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.result = approveCurrentInterfaceWorkflowNode();`,
    sandbox,
  );

  assert.equal(sandbox.result.nodes[0].review_status, "human_approved");
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    ["commit", "job_detail", {
      display_name: "Job Detail",
      surface_type: "detail",
      review_status: "needs_human_review",
    }, true],
    ["commit_operation", true],
    ["dirty", "当前界面 Revision 已批准 · 尚未保存"],
    ["render"],
  ]);
});
