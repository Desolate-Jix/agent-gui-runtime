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
  const editorState = {};
  const sandbox = {
    currentLanguage: "zh-CN",
    learningDraftEditorActive: true,
    learningDraftEditorWorkflowBinding: {
      authority: "workflow",
      workflow_id: "seek_flow",
      node_id: "job_detail",
      source_path: "draft.json",
      state: reviewState,
    },
    learningDraftEditorWorkflowSelection: {
      status: "matched",
      node_id: "job_detail",
      control_id: "apply",
      edge_id: "edge_apply",
      action_template_id: "open_apply_flow_candidate",
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
    },
    learningDraftEditorState: editorState,
    learningDraftEditorSelected: {
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
    },
    learningDraftReviewSourcePath: () => "draft.json",
    learningDraftEditorSelectedItem: () => ({
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
      action_template_id: "open_apply_flow_candidate",
    }),
    currentInterfaceWorkflowMutationTarget: () => ({
      state: reviewState,
      view: {
        node: { node_id: "job_detail" },
        selected_control: { control_id: "apply" },
        outgoing_edges: [{
          edge_id: "edge_apply",
          source_node_id: "job_detail",
          target_control_id: "apply",
          action_template_id: "open_apply_flow_candidate",
        }],
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
  const reviewState = {
    snapshot: () => ({ workflow: { workflow_id: "seek_flow" } }),
  };
  const sandbox = {
    currentLanguage: "zh-CN",
    learningDraftEditorActive: true,
    learningDraftEditorWorkflowBinding: {
      authority: "workflow",
      workflow_id: "seek_flow",
      node_id: "job_detail",
      source_path: "draft.json",
      state: reviewState,
    },
    learningDraftEditorWorkflowSelection: {
      status: "matched",
      node_id: "job_detail",
      control_id: "apply",
      edge_id: "edge_apply",
      action_template_id: "open_apply_flow_candidate",
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
    },
    learningDraftReviewSourcePath: () => "draft.json",
    learningDraftEditorSelectedItem: () => ({
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
      action_template_id: "open_apply_flow_candidate",
    }),
    currentInterfaceWorkflowMutationTarget: () => ({
      state: reviewState,
      view: {
        node: { node_id: "job_detail" },
        selected_control: { control_id: "apply" },
        outgoing_edges: [{
          edge_id: "edge_apply",
          source_node_id: "job_detail",
          target_control_id: "apply",
          action_template_id: "open_apply_flow_candidate",
        }],
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

test("confirm and store fails closed when the displayed workflow was replaced by a same-id state", async () => {
  const start = source.indexOf("async function confirmAndStoreCurrentInterfaceWorkflowReview");
  const end = source.indexOf("async function publishLearningOperationalMemory", start);
  const calls = [];
  const boundState = {
    snapshot: () => ({ workflow: { workflow_id: "seek_flow" } }),
  };
  const replacementState = {
    snapshot: () => ({ workflow: { workflow_id: "seek_flow" } }),
  };
  const sandbox = {
    currentLanguage: "zh-CN",
    learningDraftEditorActive: true,
    learningDraftEditorWorkflowBinding: {
      authority: "workflow",
      workflow_id: "seek_flow",
      node_id: "job_detail",
      source_path: "draft.json",
      state: boundState,
    },
    learningDraftEditorWorkflowSelection: {
      status: "matched",
      node_id: "job_detail",
      control_id: "apply",
      edge_id: "edge_apply",
      action_template_id: "open_apply_flow_candidate",
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
    },
    learningDraftReviewSourcePath: () => "draft.json",
    learningDraftEditorSelectedItem: () => ({
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
      action_template_id: "open_apply_flow_candidate",
    }),
    currentInterfaceWorkflowMutationTarget: () => ({
      state: replacementState,
      view: {
        node: { node_id: "job_detail" },
        selected_control: { control_id: "apply" },
        outgoing_edges: [{
          edge_id: "edge_apply",
          source_node_id: "job_detail",
          target_control_id: "apply",
          action_template_id: "open_apply_flow_candidate",
        }],
      },
    }),
    saveInterfaceWorkflowContentDescriptor: () => { calls.push("content"); return {}; },
    saveLearningDraftReview: async () => { calls.push("evidence"); return {}; },
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

test("confirm and store rejects source-path and selected-box revision drift before mutation", async () => {
  const start = source.indexOf("async function confirmAndStoreCurrentInterfaceWorkflowReview");
  const end = source.indexOf("async function publishLearningOperationalMemory", start);
  for (const scenario of ["source_drift", "selection_drift"]) {
    const calls = [];
    const state = { snapshot: () => ({ workflow: { workflow_id: "seek_flow" } }) };
    const selection = {
      status: "matched",
      node_id: "job_detail",
      control_id: "apply",
      edge_id: "edge_apply",
      action_template_id: "open_apply_flow_candidate",
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
    };
    if (scenario === "selection_drift") selection.target_id = "stale_candidate";
    const sandbox = {
      currentLanguage: "zh-CN",
      learningDraftEditorActive: true,
      learningDraftEditorWorkflowBinding: {
        authority: "workflow",
        workflow_id: "seek_flow",
        node_id: "job_detail",
        source_path: "draft.json",
        state,
      },
      learningDraftEditorWorkflowSelection: selection,
      learningDraftReviewSourcePath: () => scenario === "source_drift" ? "other.json" : "draft.json",
      learningDraftEditorSelectedItem: () => ({
        target_kind: "action",
        target_id: "open_apply_flow_candidate",
        action_template_id: "open_apply_flow_candidate",
      }),
      currentInterfaceWorkflowMutationTarget: () => ({
        state,
        view: {
          node: { node_id: "job_detail" },
          selected_control: { control_id: "apply" },
          outgoing_edges: [{
            edge_id: "edge_apply",
            source_node_id: "job_detail",
            target_control_id: "apply",
            action_template_id: "open_apply_flow_candidate",
          }],
        },
      }),
      saveInterfaceWorkflowContentDescriptor: () => { calls.push("content"); return {}; },
      saveLearningDraftReview: async () => { calls.push("evidence"); return {}; },
      approveAndSaveCurrentInterfaceWorkflowNode: async () => { calls.push("approve"); return {}; },
      closeImageInspector: () => calls.push("close"),
      renderResponse: () => {},
      $: () => null,
    };
    vm.runInNewContext(
      `${source.slice(start, end)}; globalThis.result = confirmAndStoreCurrentInterfaceWorkflowReview();`,
      sandbox,
    );
    assert.equal(await sandbox.result, null, scenario);
    assert.deepEqual(calls, [], scenario);
  }
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

test("draft evidence save stops before merge when the captured workflow state is replaced in flight", async () => {
  const start = source.indexOf("function normalizedInterfaceWorkflowReviewSourcePath");
  const helperEnd = source.indexOf("async function refreshCurrentInterfaceWorkflowEvidence", start);
  const saveStart = source.indexOf("async function saveLearningDraftReview");
  const saveEnd = source.indexOf("async function confirmAndStoreCurrentInterfaceWorkflowReview", saveStart);
  assert.notEqual(start, -1, "workflow session identity guard must exist");
  assert.notEqual(saveEnd, -1, "workflow session guard boundary must exist");
  const body = source.slice(start, helperEnd) + source.slice(saveStart, saveEnd);
  const calls = [];
  const state = { snapshot: () => ({ workflow: { workflow_id: "seek_flow" } }) };
  const replacementState = { snapshot: () => ({ workflow: { workflow_id: "seek_flow" } }) };
  const binding = {
    authority: "workflow",
    workflow_id: "seek_flow",
    node_id: "job_detail",
    source_path: "draft.json",
    state,
  };
  const sandbox = { globalThis: {}, state, replacementState, binding, calls };
  vm.runInNewContext(`
    let interfaceWorkflowReviewState = state;
    let learningDraftEditorWorkflowBinding = binding;
    let learningDraftEditorActive = true;
    let learningDraftEditorState = state;
    let learningDraftEditorSelected = { target_kind: "action", target_id: "open_apply_flow_candidate" };
    let learningDraftEditorWorkflowSelection = {
      status: "matched",
      node_id: "job_detail",
      control_id: "apply",
      edge_id: "edge_apply",
      action_template_id: "open_apply_flow_candidate",
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
    };
    const currentInterfaceWorkflowMutationTarget = () => ({
      state: interfaceWorkflowReviewState,
      view: { node: { node_id: "job_detail" } },
    });
    const learningDraftReviewSourcePath = () => "draft.json";
    const learningDraftReviewPatch = () => ({});
    const applyLearningDraftEditorMetadataFromControls = () => {};
    const api = async () => {
      interfaceWorkflowReviewState = replacementState;
      return { success: true, data: { reviewed_template_candidate_path: "reviewed.json" } };
    };
    const setLearningPathGraphCandidatePaths = () => calls.push("paths");
    const setLearningDraftReviewSourcePath = () => calls.push("merge");
    const bumpPanelImageRevision = () => {};
    const loadLearningDraftReview = async () => null;
    const renderResponse = () => {};
    const loadLearningCorrectionMemoryRegistry = async () => {};
    const buildLearningDraftEditorBinding = () => null;
    const syncImageInspectorWorkflowReviewPanel = () => {};
    const closeImageInspector = () => {};
    const $ = () => null;
    ${body}
    const session = {
      state,
      binding,
      workflow_id: "seek_flow",
      node_id: "job_detail",
      source_path: "draft.json",
      expected_source_path: "draft.json",
      editor_state: state,
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
      selection_key: JSON.stringify({
        target_kind: "action",
        target_id: "open_apply_flow_candidate",
        control_id: "apply",
        action_template_id: "open_apply_flow_candidate",
        edge_id: "edge_apply",
      }),
      phase: "draft",
    };
    globalThis.result = saveLearningDraftReview({ closeEditor: false, preserveWorkflowBinding: true }, session);
  `, sandbox);

  assert.equal(await sandbox.globalThis.result, null);
  assert.deepEqual(calls, []);
});

for (const drift of ["selection", "source_editor"]) {
  test(`draft evidence save rejects in-flight ${drift} drift without refresh or approval`, async () => {
    const start = source.indexOf("function normalizedInterfaceWorkflowReviewSourcePath");
    const helperEnd = source.indexOf("async function refreshCurrentInterfaceWorkflowEvidence", start);
    const saveStart = source.indexOf("async function saveLearningDraftReview");
    const saveEnd = source.indexOf("async function confirmAndStoreCurrentInterfaceWorkflowReview", saveStart);
    const body = source.slice(start, helperEnd) + source.slice(saveStart, saveEnd);
    let resolveApi;
    const apiPromise = new Promise((resolve) => { resolveApi = resolve; });
    const calls = [];
    const state = { snapshot: () => ({ workflow: { workflow_id: "seek_flow" } }) };
    const binding = {
      authority: "workflow",
      workflow_id: "seek_flow",
      node_id: "job_detail",
      source_path: "draft.json",
      state,
    };
    const editorState = {};
    const replacementEditorState = {};
    const selection = {
      status: "matched",
      node_id: "job_detail",
      control_id: "apply",
      edge_id: "edge_apply",
      action_template_id: "open_apply_flow_candidate",
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
    };
    const sandbox = {
      globalThis: {}, state, binding, editorState, replacementEditorState, selection, apiPromise, calls,
    };
    vm.runInNewContext(`
      let interfaceWorkflowReviewState = state;
      let learningDraftEditorWorkflowBinding = binding;
      let learningDraftEditorWorkflowSelection = selection;
      let learningDraftEditorState = editorState;
      let learningDraftEditorRevision = 1;
      let learningDraftEditorSelected = { target_kind: "action", target_id: "open_apply_flow_candidate" };
      let currentSource = "draft.json";
      let learningDraftEditorActive = true;
      const selectedItem = {
        target_kind: "action",
        target_id: "open_apply_flow_candidate",
        action_template_id: "open_apply_flow_candidate",
      };
      const learningDraftEditorSelectedItem = () => selectedItem;
      const currentInterfaceWorkflowMutationTarget = () => ({
        state,
        view: { node: { node_id: "job_detail" } },
      });
      const learningDraftReviewSourcePath = () => currentSource;
      const learningDraftReviewPatch = () => ({});
      const applyLearningDraftEditorMetadataFromControls = () => {};
      const api = async () => apiPromise;
      const setLearningPathGraphCandidatePaths = () => calls.push("paths");
      const setLearningDraftReviewSourcePath = () => calls.push("refresh");
      const bumpPanelImageRevision = () => {};
      const loadLearningDraftReview = async () => null;
      const renderResponse = () => {};
      const loadLearningCorrectionMemoryRegistry = async () => {};
      const buildLearningDraftEditorBinding = () => null;
      const syncImageInspectorWorkflowReviewPanel = () => {};
      const closeImageInspector = () => {};
      const $ = () => null;
      ${body}
      const session = {
        state,
        binding,
        workflow_id: "seek_flow",
        node_id: "job_detail",
        source_path: "draft.json",
        expected_source_path: "draft.json",
        editor_state: editorState,
        editor_revision: 1,
        target_kind: "action",
        target_id: "open_apply_flow_candidate",
        selection_key: JSON.stringify({
          target_kind: "action",
          target_id: "open_apply_flow_candidate",
          control_id: "apply",
          action_template_id: "open_apply_flow_candidate",
          edge_id: "edge_apply",
        }),
        phase: "draft",
      };
      globalThis.result = saveLearningDraftReview({ closeEditor: false, preserveWorkflowBinding: true }, session);
      globalThis.drift = (kind) => {
        if (kind === "selection") {
          learningDraftEditorWorkflowSelection = { ...selection, target_id: "other_candidate" };
        } else {
          currentSource = "other.json";
          learningDraftEditorState = replacementEditorState;
          learningDraftEditorRevision += 1;
        }
      };
    `, sandbox);

    sandbox.globalThis.drift(drift);
    resolveApi({ success: true, data: { reviewed_template_candidate_path: "reviewed.json" } });
    assert.equal(await sandbox.globalThis.result, null);
    assert.deepEqual(calls, []);
  });
}

test("reviewed evidence transition advances its session explicitly and preserves the exact selection", async () => {
  const guardStart = source.indexOf("function normalizedInterfaceWorkflowReviewSourcePath");
  const refreshStart = source.indexOf("async function refreshSavedLearningDraftReview");
  const refreshEnd = source.indexOf("async function refreshCurrentInterfaceWorkflowEvidence", refreshStart);
  assert.notEqual(guardStart, -1, "full review session guard must exist");
  const guardSource = source.slice(guardStart, refreshStart);
  const refreshSource = source.slice(refreshStart, refreshEnd);
  const state = { snapshot: () => ({ workflow: { workflow_id: "seek_flow" } }) };
  const binding = {
    authority: "workflow",
    workflow_id: "seek_flow",
    node_id: "job_detail",
    source_path: "draft.json",
    state,
  };
  const draftEditor = {};
  const reviewedEditor = {
    getItem: () => ({
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
      action_template_id: "open_apply_flow_candidate",
    }),
  };
  const calls = [];
  const sandbox = { globalThis: {}, state, binding, draftEditor, reviewedEditor, calls };
  vm.runInNewContext(`
    let interfaceWorkflowReviewState = state;
    let learningDraftEditorWorkflowBinding = binding;
    let learningDraftEditorState = draftEditor;
    let learningDraftEditorRevision = 1;
    let learningDraftEditorLoadToken = 0;
    let learningDraftReviewLoadRequestToken = 0;
    let learningDraftReview = null;
    let learningDraftEditorSelected = { target_kind: "action", target_id: "open_apply_flow_candidate" };
    let learningDraftEditorWorkflowSelection = {
      status: "matched",
      node_id: "job_detail",
      control_id: "apply",
      edge_id: "edge_apply",
      action_template_id: "open_apply_flow_candidate",
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
    };
    let currentSource = "draft.json";
    const currentInterfaceWorkflowMutationTarget = () => ({
      state,
      view: { node: { node_id: "job_detail" } },
    });
    const learningDraftReviewSourcePath = () => currentSource;
    const learningDraftEditorSelectedItem = () => learningDraftEditorState?.getItem?.(
      learningDraftEditorSelected?.target_kind,
      learningDraftEditorSelected?.target_id,
    ) || null;
    const setLearningDraftReviewSourcePath = (value, options) => {
      calls.push(["source", value, options?.preserveWorkflowReview === true]);
      currentSource = value;
      learningDraftEditorState = null;
      learningDraftEditorSelected = null;
      learningDraftEditorWorkflowSelection = null;
    };
    const bumpPanelImageRevision = () => {};
    const loadLearningDraftReview = async () => {
      learningDraftReviewLoadRequestToken += 1;
      learningDraftEditorRevision += 1;
      learningDraftEditorState = reviewedEditor;
      learningDraftReview = { draft: {} };
      learningDraftEditorLoadToken = learningDraftReviewLoadRequestToken;
      return learningDraftReview;
    };
    const selectLearningDraftEditorItem = (kind, id) => {
      learningDraftEditorSelected = { target_kind: kind, target_id: id };
      learningDraftEditorWorkflowSelection = {
        status: "matched",
        node_id: "job_detail",
        control_id: "apply",
        edge_id: "edge_apply",
        action_template_id: "open_apply_flow_candidate",
        target_kind: kind,
        target_id: id,
      };
      calls.push(["select", kind, id]);
    };
    const applyReviewedEvidenceToCurrentWorkflowNode = () => { calls.push(["merge"]); return true; };
    const saveInterfaceWorkflowReview = async () => { calls.push(["persist"]); return { path: "workflow.json" }; };
    const $ = () => null;
    ${guardSource}
    ${refreshSource}
    const selectionKey = JSON.stringify({
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
      control_id: "apply",
      action_template_id: "open_apply_flow_candidate",
      edge_id: "edge_apply",
    });
    const session = {
      state,
      binding,
      workflow_id: "seek_flow",
      node_id: "job_detail",
      source_path: "draft.json",
      expected_source_path: "draft.json",
      editor_state: draftEditor,
      editor_revision: 1,
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
      opening_selection_key: selectionKey,
      selection_key: selectionKey,
      phase: "draft",
    };
    globalThis.session = session;
    globalThis.beginAgain = () => beginInterfaceWorkflowReviewedEvidenceTransition(session, "reviewed.json");
    globalThis.result = refreshSavedLearningDraftReview({
      previousSourcePath: "draft.json",
      reviewedPath: "reviewed.json",
      workflowBinding: binding,
      workflowSession: session,
    });
  `, sandbox);

  const result = await sandbox.globalThis.result;
  assert.equal(result.workflow.workflow.workflow_id, "seek_flow");
  assert.equal(sandbox.globalThis.session.phase, "reviewed");
  assert.equal(sandbox.globalThis.session.expected_source_path, "reviewed.json");
  assert.equal(sandbox.globalThis.session.editor_state, reviewedEditor);
  assert.equal(sandbox.globalThis.session.opening_selection_key, sandbox.globalThis.session.selection_key);
  assert.equal(sandbox.globalThis.beginAgain(), false);
  assert.equal(JSON.stringify(calls), JSON.stringify([
    ["source", "reviewed.json", true],
    ["select", "action", "open_apply_flow_candidate"],
    ["merge"],
    ["persist"],
  ]));
});

test("reviewed evidence transition rejects a changed control or edge mapping without replacing the opening key", () => {
  const start = source.indexOf("function normalizedInterfaceWorkflowReviewSourcePath");
  const end = source.indexOf("async function refreshSavedLearningDraftReview", start);
  const helperSource = source.slice(start, end);
  const state = { snapshot: () => ({ workflow: { workflow_id: "seek_flow" } }) };
  const binding = {
    authority: "workflow",
    workflow_id: "seek_flow",
    node_id: "job_detail",
    source_path: "draft.json",
    state,
  };
  const refreshedReview = { draft: {} };
  const reviewedEditor = {
    getItem: () => ({
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
      action_template_id: "open_apply_flow_candidate",
    }),
  };
  const openingSelectionKey = JSON.stringify({
    target_kind: "action",
    target_id: "open_apply_flow_candidate",
    control_id: "apply",
    action_template_id: "open_apply_flow_candidate",
    edge_id: "edge_apply",
  });
  const calls = [];
  const sandbox = {
    globalThis: {}, state, binding, refreshedReview, reviewedEditor, openingSelectionKey, calls,
  };
  vm.runInNewContext(`
    let interfaceWorkflowReviewState = state;
    let learningDraftEditorWorkflowBinding = binding;
    let learningDraftEditorState = reviewedEditor;
    let learningDraftEditorRevision = 2;
    let learningDraftEditorLoadToken = 2;
    let learningDraftReviewLoadRequestToken = 2;
    let learningDraftReview = refreshedReview;
    let learningDraftEditorSelected = null;
    let learningDraftEditorWorkflowSelection = null;
    const currentInterfaceWorkflowMutationTarget = () => ({
      state,
      view: { node: { node_id: "job_detail" } },
    });
    const learningDraftReviewSourcePath = () => "reviewed.json";
    const selectLearningDraftEditorItem = (kind, id) => {
      learningDraftEditorSelected = { target_kind: kind, target_id: id };
      learningDraftEditorWorkflowSelection = {
        status: "matched",
        node_id: "job_detail",
        control_id: "different_control",
        edge_id: "different_edge",
        action_template_id: "open_apply_flow_candidate",
        target_kind: kind,
        target_id: id,
      };
      calls.push("select");
    };
    ${helperSource}
    const session = {
      state,
      binding,
      workflow_id: "seek_flow",
      node_id: "job_detail",
      source_path: "draft.json",
      expected_source_path: "reviewed.json",
      editor_state: {},
      editor_revision: 1,
      target_kind: "action",
      target_id: "open_apply_flow_candidate",
      opening_selection_key: openingSelectionKey,
      selection_key: openingSelectionKey,
      phase: "loading_reviewed",
      transition_load_token_before: 1,
    };
    globalThis.session = session;
    globalThis.result = completeInterfaceWorkflowReviewedEvidenceTransition(
      session,
      "reviewed.json",
      refreshedReview,
    );
  `, sandbox);

  assert.equal(sandbox.globalThis.result, false);
  assert.equal(sandbox.globalThis.session.opening_selection_key, openingSelectionKey);
  assert.equal(sandbox.globalThis.session.selection_key, openingSelectionKey);
  assert.deepEqual(calls, ["select"]);
});

test("workflow-bound evidence refresh preserves the captured workflow while switching to reviewed evidence", () => {
  const start = source.indexOf("async function refreshSavedLearningDraftReview");
  const end = source.indexOf("async function refreshCurrentInterfaceWorkflowEvidence", start);
  const body = source.slice(start, end);
  assert.match(body, /setLearningDraftReviewSourcePath\(sourcePath, \{ preserveWorkflowReview: true \}\)/);
});

test("learning draft reset clears both editor selection layers before reviewed evidence reselection", () => {
  const start = source.indexOf("function resetLearningDraftEditorState");
  const end = source.indexOf("\nfunction ", start + 1);
  assert.notEqual(start, -1, "learning draft reset lifecycle must exist");
  assert.notEqual(end, -1, "learning draft reset lifecycle must have a stable extraction boundary");
  const sandbox = {
    globalThis: {},
    learningDraftEditorRevision: 1,
    learningDraftEditorLoadToken: 1,
    learningDraftEditorState: {},
    learningDraftEditorSelected: { target_kind: "action", target_id: "candidate_a" },
    learningDraftEditorWorkflowSelection: {
      status: "matched",
      target_kind: "action",
      target_id: "candidate_a",
      control_id: "apply",
    },
    learningDraftEditorActive: true,
    learningDraftEditorAddMode: true,
    learningDraftEditorCompactMode: false,
    learningDraftEditorExpandedGroupKey: "overlap_group",
    learningDraftArray: (value) => Array.isArray(value) ? value : [],
    normalizeBbox: () => null,
    renderLearningDraftOwnershipReview: () => {},
    updateLearningDraftEditorControls: () => {},
  };
  vm.runInNewContext(`${source.slice(start, end)}\nresetLearningDraftEditorState();`, sandbox);

  assert.equal(sandbox.learningDraftEditorSelected, null);
  assert.equal(sandbox.learningDraftEditorWorkflowSelection, null);
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
  const originalSnapshot = {
    workflow: { workflow_id: "seek_flow" },
    nodes: [{ node_id: "job_detail" }],
  };
  const reviewState = {
    snapshot: () => structuredClone(originalSnapshot),
    select: () => {},
  };
  const draftState = {
    snapshot: () => structuredClone(originalSnapshot),
    select: () => {},
  };
  const approvedReview = {
    nodes: [{ node_id: "job_detail", review_status: "human_approved" }],
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
    InterfaceWorkflowReview: { createInterfaceWorkflowReviewState: () => draftState },
    approveCurrentInterfaceWorkflowNode: (options) => {
      calls.push(["approve", options?.state === draftState, options?.isolated === true]);
      return approvedReview;
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
  assert.deepEqual(calls[0], ["approve", true, true]);
  assert.equal(calls[1][0], "save");
  assert.equal(calls[1][1].commitEditor, false);
  assert.equal(calls[1][1].requireDisplayedWorkflow, true);
  assert.equal(calls[1][1].expectedState, reviewState);
  assert.equal(calls[1][1].expectedBinding, null);
  assert.equal(calls[1][1].expectedSnapshotKey, JSON.stringify(originalSnapshot));
  assert.equal(calls[1][1].preserveStateSession, true);
  assert.equal(calls[1][1].reviewOverride, approvedReview);
  assert.equal(sandbox.interfaceWorkflowReviewState, draftState);
});

test("non-session approval stays hidden until persistence succeeds and then rerenders approved state", async () => {
  const start = source.indexOf("function approveCurrentInterfaceWorkflowNode");
  const end = source.indexOf("function commitInterfaceWorkflowEditorToState", start);
  const originalSnapshot = {
    contract_version: "single_application_workflow_review_v1",
    workflow: { workflow_id: "seek_flow" },
    nodes: [{ node_id: "job_detail", review_status: "needs_human_review" }],
    edges: [],
  };
  const createState = () => ({
    approved: false,
    select: () => {},
    current() {
      return { node: this.snapshot().nodes[0], outgoing_edges: [] };
    },
    confirmNodeAndOutgoingHumanReview() {
      this.approved = true;
    },
    snapshot() {
      const value = structuredClone(originalSnapshot);
      if (this.approved) value.nodes[0].review_status = "human_approved";
      return value;
    },
  });
  const liveState = createState();
  const draftState = createState();
  const binding = { authority: "workflow", state: liveState };
  const renderStatuses = [];
  let resolveSave;
  let savedOptions = null;
  const savePending = new Promise((resolve) => { resolveSave = resolve; });
  const sandbox = {
    interfaceWorkflowReviewState: liveState,
    interfaceWorkflowReview: liveState.snapshot(),
    interfaceWorkflowHasUnsavedChanges: true,
    interfaceWorkflowSavedReviewPath: "workflow.json",
    learningDraftEditorWorkflowBinding: binding,
    InterfaceWorkflowReview: { createInterfaceWorkflowReviewState: () => draftState },
    window: {
      InterfaceWorkflowReview: {
        commitInterfaceWorkflowReviewForSave: ({ state, commitOperation }) => {
          commitOperation();
          return state.snapshot();
        },
      },
    },
    currentInterfaceWorkflowOperation: () => null,
    commitInterfaceWorkflowOperationEditor: () => null,
    markInterfaceWorkflowUnsaved: () => {},
    saveInterfaceWorkflowReview: async (options) => {
      savedOptions = options;
      return savePending;
    },
    renderInterfaceWorkflowReviewSelection: () => {
      renderStatuses.push(
        sandbox.interfaceWorkflowReviewState.current().node.review_status,
      );
    },
    $: (id) => ({
      interfaceWorkflowNodeName: { value: "Job Detail" },
      interfaceWorkflowSurfaceType: { value: "detail" },
    }[id] || null),
  };
  sandbox.currentInterfaceWorkflowMutationTarget = () => ({
    state: sandbox.interfaceWorkflowReviewState,
    view: sandbox.interfaceWorkflowReviewState.current(),
    reason: "",
  });
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.result = approveAndSaveCurrentInterfaceWorkflowNode();`,
    sandbox,
  );

  const rendersBeforePersistence = [...renderStatuses];
  resolveSave({ path: "reviewed_workflow.json" });
  assert.deepEqual(JSON.parse(JSON.stringify(await sandbox.result)), {
    path: "reviewed_workflow.json",
  });
  assert.deepEqual(rendersBeforePersistence, []);
  assert.equal(savedOptions.reviewOverride.nodes[0].review_status, "human_approved");
  assert.equal(sandbox.interfaceWorkflowReviewState, draftState);
  assert.equal(sandbox.learningDraftEditorWorkflowBinding.state, draftState);
  assert.deepEqual(renderStatuses, ["human_approved"]);
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

test("session approval is built in an isolated state and persistence failure leaves live state unapproved", async () => {
  const start = source.indexOf("async function approveAndSaveCurrentInterfaceWorkflowNode");
  const end = source.indexOf("function commitInterfaceWorkflowEditorToState", start);
  const originalSnapshot = {
    contract_version: "single_application_workflow_review_v1",
    workflow: { workflow_id: "seek_flow" },
    nodes: [{ node_id: "job_detail", review_status: "needs_human_review" }],
    edges: [],
  };
  const liveState = { snapshot: () => structuredClone(originalSnapshot) };
  const draftState = {
    approved: false,
    select: () => {},
    current() {
      return {
        node: {
          node_id: "job_detail",
          review_status: this.approved ? "human_approved" : "needs_human_review",
        },
      };
    },
    snapshot() {
      const value = structuredClone(originalSnapshot);
      if (this.approved) value.nodes[0].review_status = "human_approved";
      return value;
    },
  };
  const binding = { authority: "workflow", state: liveState };
  const calls = [];
  const sandbox = {
    interfaceWorkflowReviewState: liveState,
    interfaceWorkflowReview: originalSnapshot,
    interfaceWorkflowHasUnsavedChanges: true,
    interfaceWorkflowSavedReviewPath: "workflow.json",
    learningDraftEditorWorkflowBinding: binding,
    interfaceWorkflowReviewSessionIsCurrent: () => true,
    currentInterfaceWorkflowMutationTarget: () => ({
      state: liveState,
      view: { node: { node_id: "job_detail" } },
    }),
    InterfaceWorkflowReview: { createInterfaceWorkflowReviewState: () => draftState },
    approveCurrentInterfaceWorkflowNode: (options) => {
      calls.push(["approve_state", options?.state === draftState]);
      draftState.approved = true;
      return draftState.snapshot();
    },
    saveInterfaceWorkflowReview: async (options) => {
      calls.push(["persist", options?.reviewOverride?.nodes?.[0]?.review_status || "missing_override"]);
      return null;
    },
    renderInterfaceWorkflowReviewSelection: () => calls.push(["render"]),
  };
  const session = {
    state: liveState,
    binding,
    workflow_id: "seek_flow",
    node_id: "job_detail",
    source_path: "draft.json",
  };
  sandbox.session = session;
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.result = approveAndSaveCurrentInterfaceWorkflowNode(session);`,
    sandbox,
  );

  assert.equal(await sandbox.result, null);
  assert.equal(sandbox.interfaceWorkflowReviewState, liveState);
  assert.equal(sandbox.learningDraftEditorWorkflowBinding.state, liveState);
  assert.equal(liveState.snapshot().nodes[0].review_status, "needs_human_review");
  assert.deepEqual(calls.slice(0, 2), [["approve_state", true], ["persist", "human_approved"]]);
  assert.equal(calls.some(([name]) => name === "render"), false);
});

test("successful session approval rerenders the canonical approved live state after persistence", async () => {
  const start = source.indexOf("async function approveAndSaveCurrentInterfaceWorkflowNode");
  const end = source.indexOf("function commitInterfaceWorkflowEditorToState", start);
  const originalSnapshot = {
    contract_version: "single_application_workflow_review_v1",
    workflow: { workflow_id: "seek_flow" },
    nodes: [{ node_id: "job_detail", review_status: "needs_human_review" }],
    edges: [],
  };
  const liveState = { snapshot: () => structuredClone(originalSnapshot) };
  const draftState = {
    approved: false,
    select: () => {},
    current() {
      return {
        node: {
          node_id: "job_detail",
          review_status: this.approved ? "human_approved" : "needs_human_review",
        },
      };
    },
    snapshot() {
      const value = structuredClone(originalSnapshot);
      if (this.approved) value.nodes[0].review_status = "human_approved";
      return value;
    },
  };
  const binding = { authority: "workflow", state: liveState };
  const renderStatuses = [];
  const sandbox = {
    interfaceWorkflowReviewState: liveState,
    interfaceWorkflowReview: originalSnapshot,
    learningDraftEditorWorkflowBinding: binding,
    interfaceWorkflowReviewSessionIsCurrent: () => true,
    InterfaceWorkflowReview: { createInterfaceWorkflowReviewState: () => draftState },
    approveCurrentInterfaceWorkflowNode: () => {
      draftState.approved = true;
      return draftState.snapshot();
    },
    saveInterfaceWorkflowReview: async () => ({ path: "reviewed_workflow.json" }),
    renderInterfaceWorkflowReviewSelection: () => {
      renderStatuses.push(
        sandbox.interfaceWorkflowReviewState.current().node.review_status,
      );
    },
  };
  const session = {
    state: liveState,
    binding,
    workflow_id: "seek_flow",
    node_id: "job_detail",
    source_path: "draft.json",
  };
  sandbox.session = session;
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.result = approveAndSaveCurrentInterfaceWorkflowNode(session);`,
    sandbox,
  );

  assert.deepEqual(JSON.parse(JSON.stringify(await sandbox.result)), {
    path: "reviewed_workflow.json",
  });
  assert.equal(sandbox.interfaceWorkflowReviewState, draftState);
  assert.equal(sandbox.learningDraftEditorWorkflowBinding.state, draftState);
  assert.deepEqual(renderStatuses, ["human_approved"]);
});

test("approve and save leaves the original unapproved revision untouched when persistence fails", async () => {
  const start = source.indexOf("async function approveAndSaveCurrentInterfaceWorkflowNode");
  const end = source.indexOf("function commitInterfaceWorkflowEditorToState", start);
  const originalSnapshot = {
    workflow: { workflow_id: "seek_flow" },
    nodes: [{ node_id: "job_detail", review_status: "needs_human_review" }],
  };
  const originalState = { snapshot: () => originalSnapshot, select: () => {} };
  const draftState = { snapshot: () => originalSnapshot, select: () => {} };
  const binding = { authority: "workflow", state: originalState };
  let renders = 0;
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
    InterfaceWorkflowReview: { createInterfaceWorkflowReviewState: () => draftState },
    approveCurrentInterfaceWorkflowNode: () => ({
      nodes: [{ node_id: "job_detail", review_status: "human_approved" }],
    }),
    saveInterfaceWorkflowReview: async () => null,
    renderInterfaceWorkflowReviewSelection: () => { renders += 1; },
  };
  vm.runInNewContext(
    `${source.slice(start, end)}; globalThis.result = approveAndSaveCurrentInterfaceWorkflowNode();`,
    sandbox,
  );

  assert.equal(await sandbox.result, null);
  assert.equal(sandbox.interfaceWorkflowReviewState, originalState);
  assert.equal(sandbox.learningDraftEditorWorkflowBinding.state, originalState);
  assert.equal(sandbox.interfaceWorkflowReview.nodes[0].review_status, "needs_human_review");
  assert.equal(renders, 0);
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
