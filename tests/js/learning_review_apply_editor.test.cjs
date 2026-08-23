const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
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

test("full-image confirmation is the only user-facing approval gesture while keeping granular receipts", () => {
  assert.doesNotMatch(html, /id="interfaceWorkflowOperationApproveBundleBtn"/);
  assert.doesNotMatch(html, /id="interfaceWorkflowOperationApproveTargetControlBtn"/);
  assert.doesNotMatch(html, /id="interfaceWorkflowOperationApproveActionCandidateBtn"/);
  assert.doesNotMatch(html, /id="interfaceWorkflowOperationApproveEdgeBtn"/);
  assert.match(source, /confirmNodeAndOutgoingHumanReview/);
  assert.match(html, /id="imageInspectorConfirmAndStoreBtn"/);
  assert.match(html, /确认并入库/);
  assert.match(html, /id="imageInspectorApplyBoxBtn"[^>]*>仅保存草稿/);
  assert.doesNotMatch(html, /id="interfaceWorkflowContentSaveBtn"/);
  assert.doesNotMatch(html, /id="interfaceWorkflowApproveAndSaveBtn"/);
  assert.doesNotMatch(html, /id="interfaceWorkflowNodeReviewStatus"/);
  assert.doesNotMatch(html, /id="interfaceWorkflowNodeApproveBtn"/);
  assert.doesNotMatch(html, /id="interfaceWorkflowNodeHumanReviewConfirmed"/);
});

test("confirm and store saves the current evidence before approving its workflow revision", async () => {
  const start = source.indexOf("async function confirmAndStoreCurrentInterfaceWorkflowReview");
  const end = source.indexOf("async function publishLearningOperationalMemory", start);
  assert.notEqual(start, -1, "confirm-and-store handler must exist");
  const calls = [];
  const button = { disabled: false, textContent: "确认并入库" };
  const reviewState = {
    contentDescription: "old description",
    snapshot() {
      return {
        workflow: { workflow_id: "seek_flow" },
        nodes: [{
          node_id: "job_detail",
          content_descriptors: [{
            source_id: "apply",
            agent_description: this.contentDescription,
          }],
        }],
      };
    },
  };
  const contentDescription = { value: "Read the current Quick Apply control" };
  const sandbox = {
    currentLanguage: "zh-CN",
    learningDraftEditorActive: true,
    learningDraftEditorWorkflowBinding: {
      authority: "workflow",
      workflow_id: "seek_flow",
      node_id: "job_detail",
    },
    currentInterfaceWorkflowMutationTarget: () => ({
      state: reviewState,
      view: {
        node: { node_id: "job_detail" },
        selected_control: { control_id: "apply" },
      },
      reason: "",
    }),
    saveInterfaceWorkflowContentDescriptor: () => {
      reviewState.contentDescription = contentDescription.value;
      calls.push(["commit_content", reviewState.snapshot().nodes[0].content_descriptors[0]]);
      return reviewState.snapshot().nodes[0].content_descriptors[0];
    },
    saveLearningDraftReview: async (options) => {
      calls.push(["save_evidence", options, reviewState.snapshot().nodes[0].content_descriptors[0]]);
      return { reviewed_template_candidate_path: "reviewed.json" };
    },
    approveAndSaveCurrentInterfaceWorkflowNode: async () => {
      calls.push(["approve_and_save", reviewState.snapshot().nodes[0].content_descriptors[0]]);
      return { path: "workflow.json" };
    },
    closeImageInspector: () => calls.push(["close"]),
    renderResponse: () => {},
    $: (id) => id === "imageInspectorConfirmAndStoreBtn"
      ? button
      : (id === "imageInspectorOverlay"
        ? { style: { display: "none" } }
        : (id === "interfaceWorkflowContentDescription" ? contentDescription : null)),
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.result = confirmAndStoreCurrentInterfaceWorkflowReview();`,
    sandbox,
  );

  assert.deepEqual(JSON.parse(JSON.stringify(await sandbox.result)), { path: "workflow.json" });
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    ["commit_content", { source_id: "apply", agent_description: "Read the current Quick Apply control" }],
    [
      "save_evidence",
      { closeEditor: false, preserveWorkflowBinding: true },
      { source_id: "apply", agent_description: "Read the current Quick Apply control" },
    ],
    ["approve_and_save", { source_id: "apply", agent_description: "Read the current Quick Apply control" }],
    ["close"],
  ]);
});

test("confirm and store never approves or closes when the selected content descriptor cannot commit", async () => {
  const start = source.indexOf("async function confirmAndStoreCurrentInterfaceWorkflowReview");
  const end = source.indexOf("async function publishLearningOperationalMemory", start);
  const calls = [];
  const sandbox = {
    currentLanguage: "zh-CN",
    learningDraftEditorActive: true,
    learningDraftEditorWorkflowBinding: {
      authority: "workflow",
      workflow_id: "seek_flow",
      node_id: "job_detail",
    },
    currentInterfaceWorkflowMutationTarget: () => ({
      state: { snapshot: () => ({ workflow: { workflow_id: "seek_flow" } }) },
      view: {
        node: { node_id: "job_detail" },
        selected_control: { control_id: "apply" },
      },
    }),
    saveInterfaceWorkflowContentDescriptor: () => null,
    saveLearningDraftReview: async () => { calls.push("save_evidence"); return {}; },
    approveAndSaveCurrentInterfaceWorkflowNode: async () => { calls.push("approve"); return {}; },
    closeImageInspector: () => calls.push("close"),
    renderResponse: () => {},
    $: () => null,
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.result = confirmAndStoreCurrentInterfaceWorkflowReview();`,
    sandbox,
  );

  assert.equal(await sandbox.result, null);
  assert.deepEqual(calls, []);
});

test("confirm and store rejects a standalone source preview", async () => {
  const start = source.indexOf("async function confirmAndStoreCurrentInterfaceWorkflowReview");
  const end = source.indexOf("async function publishLearningOperationalMemory", start);
  assert.notEqual(start, -1, "confirm-and-store handler must exist");
  let saves = 0;
  const sandbox = {
    learningDraftEditorActive: true,
    learningDraftEditorWorkflowBinding: { authority: "source_preview", node_id: "asset_a" },
    saveLearningDraftReview: async () => { saves += 1; return {}; },
    approveAndSaveCurrentInterfaceWorkflowNode: async () => { saves += 1; return {}; },
    closeImageInspector: () => {},
    renderResponse: () => {},
    $: () => null,
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.result = confirmAndStoreCurrentInterfaceWorkflowReview();`,
    sandbox,
  );

  assert.equal(await sandbox.result, null);
  assert.equal(saves, 0);
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
    currentInterfaceWorkflowMutationTarget: () => ({
      state: sandbox.interfaceWorkflowReviewState,
      view: null,
      reason: "",
    }),
    interfaceWorkflowSelectedOperationId: "edge_open",
    interfaceWorkflowOperationDialogSession: null,
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
    interfaceWorkflowOperationDialogSession: null,
    currentInterfaceWorkflowMutationTarget: () => ({
      state: sandbox.interfaceWorkflowReviewState,
      view: null,
      reason: "",
    }),
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
    interfaceWorkflowOperationDialogSession: null,
    currentInterfaceWorkflowMutationTarget: () => ({ state: {}, view: null, reason: "" }),
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

test("editing a previously approved interface refreshes confirm-and-store eligibility", () => {
  const start = source.indexOf("function handleInterfaceWorkflowEditorMutation");
  const end = source.indexOf("function handleInterfaceWorkflowOperationEditorMutation", start);
  assert.notEqual(start, -1);
  let eligibilityRefreshes = 0;
  const sandbox = {
    interfaceWorkflowReviewState: {
      current: () => ({
        node: {
          node_id: "job_detail",
          review_status: "human_approved",
          reviewed_by_human: true,
        },
      }),
    },
    clearInterfaceWorkflowNodeHumanReviewConfirmation: () => {},
    currentInterfaceWorkflowMutationTarget: () => ({ state: {}, view: null, reason: "" }),
    markInterfaceWorkflowUnsaved: () => {},
    syncImageInspectorConfirmAndStoreButton: () => { eligibilityRefreshes += 1; },
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; handleInterfaceWorkflowEditorMutation();`,
    sandbox,
  );

  assert.equal(eligibilityRefreshes, 1);
});

test("an edited approved interface becomes eligible for confirm and store", () => {
  const start = source.indexOf("function syncImageInspectorConfirmAndStoreButton");
  const end = source.indexOf("function syncInterfaceWorkflowCorrectionToggleLabel", start);
  const button = { hidden: true, disabled: true, textContent: "", title: "" };
  const sandbox = {
    currentLanguage: "zh-CN",
    learningDraftEditorActive: true,
    learningDraftEditorWorkflowBinding: {
      authority: "workflow",
      workflow_id: "seek_flow",
      node_id: "job_detail",
    },
    learningDraftEditorState: { exportOperations: () => [] },
    interfaceWorkflowHasUnsavedChanges: false,
    currentInterfaceWorkflowMutationTarget: () => ({
      state: { snapshot: () => ({ workflow: { workflow_id: "seek_flow" } }) },
      view: {
        node: {
          node_id: "job_detail",
          review_status: "human_approved",
          reviewed_by_human: true,
        },
      },
    }),
    $: (id) => id === "imageInspectorConfirmAndStoreBtn" ? button : null,
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.sync = syncImageInspectorConfirmAndStoreButton;`,
    sandbox,
  );

  sandbox.sync();
  assert.equal(button.disabled, true);
  sandbox.interfaceWorkflowHasUnsavedChanges = true;
  sandbox.sync();
  assert.equal(button.disabled, false);
});

test("needs_learning renders as a locked stop boundary instead of an approvable node", () => {
  const start = source.indexOf("function renderInterfaceWorkflowEditor");
  const end = source.indexOf("function clearInterfaceWorkflowNodeHumanReviewConfirmation", start);
  const elements = {
    interfaceWorkflowNodeName: {},
    interfaceWorkflowSurfaceType: {},
    imageInspectorConfirmAndStoreBtn: { disabled: false },
    interfaceWorkflowSaveStatus: {},
  };
  const sandbox = {
    $: (id) => elements[id] || null,
    interfaceWorkflowHasUnsavedChanges: false,
    interfaceWorkflowWorkbenchState: { current: () => ({ correction_open: true }) },
    currentInterfaceWorkflowMutationTarget: (view) => ({ state: {}, view, reason: "" }),
    renderInterfaceWorkflowContentEditor: () => {},
    renderInterfaceWorkflowOperationEditor: () => {},
    syncImageInspectorConfirmAndStoreButton: (view) => {
      elements.imageInspectorConfirmAndStoreBtn.disabled = view?.node?.review_status === "needs_learning";
    },
    t: () => "saved",
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; renderInterfaceWorkflowEditor({ node: { node_id: "stop", review_status: "needs_learning" } });`,
    sandbox,
  );

  assert.equal(elements.imageInspectorConfirmAndStoreBtn.disabled, true);
});

test("approve and save persists exactly the approved revision without a second editor commit", async () => {
  const vm = require("node:vm");
  const start = source.indexOf("async function approveAndSaveCurrentInterfaceWorkflowNode");
  const end = source.indexOf("function commitInterfaceWorkflowEditorToState", start);
  assert.notEqual(start, -1, "approve-and-save handler must exist");
  const calls = [];
  const reviewState = {
    snapshot: () => ({ workflow: { workflow_id: "seek_flow" }, nodes: [{ node_id: "job_detail" }] }),
    select: () => {},
  };
  const sandbox = {
    currentInterfaceWorkflowMutationTarget: () => ({
      state: reviewState,
      view: { node: { node_id: "job_detail" } },
    }),
    interfaceWorkflowReviewState: reviewState,
    interfaceWorkflowReview: reviewState.snapshot(),
    interfaceWorkflowHasUnsavedChanges: false,
    interfaceWorkflowSavedReviewPath: "",
    learningDraftEditorWorkflowBinding: null,
    renderInterfaceWorkflowReviewSelection: () => {},
    InterfaceWorkflowReview: { createInterfaceWorkflowReviewState: () => reviewState },
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
    ["save", { commitEditor: false, requireDisplayedWorkflow: true }],
  ]);
});

test("workflow editor commits preserve the current review status without a removed status selector", () => {
  const start = source.indexOf("function commitInterfaceWorkflowEditorToState");
  const end = source.indexOf("async function saveInterfaceWorkflowReview", start);
  let patch = null;
  const reviewState = { snapshot: () => ({}) };
  const sandbox = {
    currentInterfaceWorkflowMutationTarget: () => ({
      state: reviewState,
      view: {
        node: {
          node_id: "job_detail",
          review_status: "human_approved",
        },
      },
    }),
    window: {
      InterfaceWorkflowReview: {
        commitInterfaceWorkflowReviewForSave: (options) => {
          patch = options.nodePatch;
          return { nodes: [] };
        },
      },
    },
    commitInterfaceWorkflowOperationEditor: () => null,
    $: (id) => ({
      interfaceWorkflowNodeName: { value: "Job Detail" },
      interfaceWorkflowSurfaceType: { value: "detail" },
    }[id] || null),
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; commitInterfaceWorkflowEditorToState();`,
    sandbox,
  );

  assert.equal(patch.review_status, "human_approved");
});

test("approve and save does not save when node approval is blocked", async () => {
  const vm = require("node:vm");
  const start = source.indexOf("async function approveAndSaveCurrentInterfaceWorkflowNode");
  const end = source.indexOf("function commitInterfaceWorkflowEditorToState", start);
  assert.notEqual(start, -1, "approve-and-save handler must exist");
  let saves = 0;
  const reviewState = {
    snapshot: () => ({ workflow: { workflow_id: "seek_flow" }, nodes: [{ node_id: "job_detail" }] }),
    select: () => {},
  };
  const sandbox = {
    currentInterfaceWorkflowMutationTarget: () => ({
      state: reviewState,
      view: { node: { node_id: "job_detail" } },
    }),
    interfaceWorkflowReviewState: reviewState,
    interfaceWorkflowReview: reviewState.snapshot(),
    interfaceWorkflowHasUnsavedChanges: false,
    interfaceWorkflowSavedReviewPath: "",
    learningDraftEditorWorkflowBinding: null,
    renderInterfaceWorkflowReviewSelection: () => {},
    InterfaceWorkflowReview: { createInterfaceWorkflowReviewState: () => reviewState },
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

test("approve and save restores the unapproved revision when persistence fails", async () => {
  const start = source.indexOf("async function approveAndSaveCurrentInterfaceWorkflowNode");
  const end = source.indexOf("function commitInterfaceWorkflowEditorToState", start);
  const originalSnapshot = {
    workflow: { workflow_id: "seek_flow" },
    nodes: [{ node_id: "job_detail", review_status: "needs_human_review" }],
  };
  const originalState = { snapshot: () => originalSnapshot, select: () => {} };
  const restoredState = { snapshot: () => originalSnapshot, select: () => {} };
  const binding = { authority: "workflow", state: originalState };
  const sandbox = {
    currentInterfaceWorkflowMutationTarget: () => ({
      state: originalState,
      view: { node: { node_id: "job_detail" } },
    }),
    interfaceWorkflowReviewState: originalState,
    interfaceWorkflowReview: originalSnapshot,
    interfaceWorkflowHasUnsavedChanges: false,
    interfaceWorkflowSavedReviewPath: "workflow.json",
    learningDraftEditorWorkflowBinding: binding,
    InterfaceWorkflowReview: { createInterfaceWorkflowReviewState: () => restoredState },
    approveCurrentInterfaceWorkflowNode: () => ({
      nodes: [{ node_id: "job_detail", review_status: "human_approved" }],
    }),
    saveInterfaceWorkflowReview: async () => null,
    renderInterfaceWorkflowReviewSelection: () => {},
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.result = approveAndSaveCurrentInterfaceWorkflowNode();`,
    sandbox,
  );

  assert.equal(await sandbox.result, null);
  assert.equal(sandbox.interfaceWorkflowReviewState, restoredState);
  assert.equal(sandbox.learningDraftEditorWorkflowBinding.state, restoredState);
  assert.equal(sandbox.interfaceWorkflowReview.nodes[0].review_status, "needs_human_review");
});

test("approving the current interface commits then confirms the node and all outgoing paths", () => {
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
      confirmNodeAndOutgoingHumanReview: (nodeId) => calls.push(["confirm_all", nodeId]),
      snapshot: () => ({ nodes: [{ node_id: "job_detail", review_status: "human_approved" }] }),
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
  sandbox.currentInterfaceWorkflowMutationTarget = () => ({
    state: sandbox.interfaceWorkflowReviewState,
    view: sandbox.interfaceWorkflowReviewState.current(),
    reason: "",
  });
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
    }, false],
    ["commit_operation", true],
    ["confirm_all", "job_detail"],
    ["dirty", "当前界面及操作路径已确认 · 尚未入库"],
    ["render"],
  ]);
});
