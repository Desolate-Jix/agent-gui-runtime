const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const panelSource = fs.readFileSync(
  path.join(__dirname, "../../app/web_panel/panel.js"),
  "utf8",
);
const panelHtml = fs.readFileSync(
  path.join(__dirname, "../../app/web_panel/index.html"),
  "utf8",
);
const panelCss = fs.readFileSync(
  path.join(__dirname, "../../app/web_panel/panel.css"),
  "utf8",
);

function functionSource(startMarker, endMarker) {
  const start = panelSource.indexOf(startMarker);
  const end = panelSource.indexOf(endMarker, start);
  assert.notEqual(start, -1, `${startMarker} must exist`);
  assert.notEqual(end, -1, `${endMarker} must exist`);
  return panelSource.slice(start, end);
}

test("open correction tools make workflow evidence controls directly selectable", () => {
  const renderSource = functionSource(
    "function renderInterfaceWorkflowControlPickTargets",
    "function renderInterfaceWorkflowEvidence",
  );
  const appended = [];
  const stage = {
    querySelectorAll: () => [],
    appendChild: (target) => appended.push(target),
  };
  const evidence = { querySelector: () => stage };
  const sandbox = {
    console,
    globalThis: {
      InterfaceWorkflowReview: {
        interfaceWorkflowControlChoices: () => [{
          control_id: "quick_apply",
          label: "Quick apply",
          role: "button",
        }],
      },
      InterfaceWorkflowGraph: {
        resolveInterfaceWorkflowTargetEvidence: () => ({
          normalized: { left: 0.6, top: 0.5, width: 0.1, height: 0.05 },
        }),
      },
    },
    document: {
      createElement: () => ({
        dataset: {},
        style: {},
        setAttribute(name, value) {
          this[name] = value;
        },
      }),
    },
  };
  vm.runInNewContext(`
    let interfaceWorkflowControlPickMode = false;
    const interfaceWorkflowWorkbenchState = {
      current: () => ({ correction_open: true, evidence_mode: "workflow" }),
    };
    const $ = (id) => id === "interfaceWorkflowEvidence" ? evidence : null;
    ${renderSource}
    globalThis.renderTargets = renderInterfaceWorkflowControlPickTargets;
  `, { ...sandbox, evidence });

  sandbox.globalThis.renderTargets({ node: { node_id: "job_detail" } });

  assert.equal(appended.length, 1);
  assert.equal(appended[0].dataset.interfaceWorkflowControlId, "quick_apply");
});

test("ordinary evidence selection refreshes the review editor without applying a stale picker destination", () => {
  const selectSource = functionSource(
    "function selectInterfaceWorkflowEvidenceControl",
    "function onInterfaceWorkflowGraphPointerMove",
  );
  const attachSelect = {
    value: "keep_attach_value",
    options: [{ value: "quick_apply" }],
  };
  const operationSelect = { value: "keep_operation_value" };
  const elements = new Map([
    ["interfaceWorkflowAttachTargetControl", attachSelect],
    ["interfaceWorkflowOperationTargetControl", operationSelect],
  ]);
  const observations = { focused: "", reviewRenders: 0 };
  const sandbox = { console, globalThis: {}, elements, observations };
  vm.runInNewContext(`
    let interfaceWorkflowControlPickMode = false;
    let interfaceWorkflowControlPickDestination = "attach";
    const state = {
      focusControl: (controlId) => { observations.focused = controlId; },
    };
    const interfaceWorkflowReviewState = { graph: () => ({ nodes: [], edges: [] }) };
    const currentInterfaceWorkflowEvidenceState = () => state;
    const renderInterfaceWorkflowReviewSelection = () => { observations.reviewRenders += 1; };
    const renderActiveInterfaceWorkflowEvidence = () => {};
    const renderInterfaceWorkflowGraph = () => {};
    const closeInterfaceWorkflowControlPickerDialog = () => {};
    const renderResponse = () => {};
    const $ = (id) => elements.get(id) || null;
    ${selectSource}
    globalThis.selectControl = selectInterfaceWorkflowEvidenceControl;
  `, sandbox);

  sandbox.globalThis.selectControl("quick_apply");

  assert.equal(observations.focused, "quick_apply");
  assert.equal(observations.reviewRenders, 1);
  assert.equal(attachSelect.value, "keep_attach_value");
  assert.equal(operationSelect.value, "keep_operation_value");
});

test("opening correction tools refreshes evidence so selectable hit targets are mounted", () => {
  const correctionSource = functionSource(
    "function setInterfaceWorkflowCorrectionOpen",
    "function restoreInterfaceWorkflowOperationToolbar",
  );
  const reviewPanel = { hidden: true, parentElement: null };
  const reviewHost = {
    hidden: true,
    appendChild(panel) {
      panel.parentElement = this;
    },
  };
  const parkingHost = {};
  const operationToolbar = { hidden: true, parentElement: parkingHost };
  const toggle = { textContent: "" };
  const elements = new Map([
    ["interfaceWorkflowCurrentReviewPanel", reviewPanel],
    ["imageInspectorWorkflowReviewHost", reviewHost],
    ["interfaceWorkflowOperationToolbar", operationToolbar],
    ["interfaceWorkflowOperationToolbarParkingHost", parkingHost],
    ["interfaceWorkflowReviewToolsToggle", toggle],
  ]);
  const observations = { evidenceRenders: 0, editorRenders: 0, correctionOpen: false };
  const sandbox = { console, globalThis: {}, elements, observations };
  vm.runInNewContext(`
    const interfaceWorkflowWorkbenchState = {
      setCorrectionOpen: (open) => { observations.correctionOpen = open; },
      current: () => ({ correction_open: observations.correctionOpen }),
    };
    const currentLanguage = "zh-CN";
    const learningDraftEditorWorkflowBinding = null;
    const learningDraftEditorState = null;
    const learningDraftEditorActive = false;
    const currentInterfaceWorkflowCorrectionTarget = () => ({ view: null });
    const currentInterfaceWorkflowMutationTarget = (view) => ({ state: {}, view, reason: "" });
    const renderInterfaceWorkflowEditor = () => { observations.editorRenders += 1; };
    const renderActiveInterfaceWorkflowEvidence = () => { observations.evidenceRenders += 1; };
    const t = (value) => value;
    const $ = (id) => elements.get(id) || null;
    ${correctionSource}
    globalThis.setCorrectionOpen = setInterfaceWorkflowCorrectionOpen;
  `, sandbox);

  sandbox.globalThis.setCorrectionOpen(true, { node: { node_id: "job_detail" } });

  assert.equal(observations.correctionOpen, true);
  assert.equal(reviewPanel.hidden, false);
  assert.equal(reviewHost.hidden, false);
  assert.equal(reviewPanel.parentElement, reviewHost);
  assert.equal(operationToolbar.hidden, true);
  assert.equal(operationToolbar.parentElement, parkingHost);
  assert.equal(toggle.textContent, "收起修正与确认");
  assert.equal(observations.editorRenders, 1);
  assert.equal(observations.evidenceRenders, 1);
});

test("review and correction use one primary entry that opens the full-image workbench", () => {
  assert.doesNotMatch(panelHtml, /id="interfaceWorkflowReviewPanelToggle"/);
  assert.doesNotMatch(panelHtml, /显示审核工具|收起审核工具/);
  assert.match(panelHtml, /id="interfaceWorkflowReviewToolsToggle"[^>]*>修正与确认</);
  assert.match(panelHtml, /id="imageInspectorWorkflowReviewHost"/);
  assert.match(panelHtml, /id="interfaceWorkflowCurrentReviewPanel"/);
  assert.match(panelHtml, /id="imageInspectorConfirmAndStoreBtn"[^>]*>确认并入库</);
  assert.match(panelSource, /on\("interfaceWorkflowReviewToolsToggle", "click", openCurrentInterfaceWorkflowBoxEditor\)/);
  assert.doesNotMatch(panelSource, /on\("interfaceWorkflowReviewToolsToggle", "click", \(\) => \{\s*setInterfaceWorkflowCorrectionOpen\(/);
  assert.doesNotMatch(panelHtml, /id="interfaceWorkflowEditBoxesBtn"/);
});

test("full-image workbench separates interface, selected-box, and operation responsibilities", () => {
  const start = panelHtml.indexOf('id="interfaceWorkflowCurrentReviewPanel"');
  const end = panelHtml.indexOf('id="interfaceWorkflowOperationToolbarParkingHost"', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const currentReview = panelHtml.slice(start, end);
  assert.match(currentReview, /id="interfaceWorkflowNodeName"/);
  assert.match(currentReview, /id="interfaceWorkflowSurfaceType"/);
  assert.doesNotMatch(currentReview, /id="interfaceWorkflowContentEditor"/);
  assert.doesNotMatch(currentReview, /id="interfaceWorkflowOperationToolbar"/);
  assert.doesNotMatch(currentReview, /id="interfaceWorkflowGenerateV2Btn"/);
  assert.doesNotMatch(currentReview, /id="interfaceWorkflowMemoryBtn"/);
  assert.doesNotMatch(currentReview, /id="interfaceWorkflowOperationDryRunBtn"/);

  const boxStart = panelHtml.indexOf('id="imageInspectorSelectedBoxPanel"');
  const boxEnd = panelHtml.indexOf('id="imageInspectorFooterActions"', boxStart);
  assert.notEqual(boxStart, -1);
  assert.notEqual(boxEnd, -1);
  const boxReview = panelHtml.slice(boxStart, boxEnd);
  assert.match(boxReview, /id="imageInspectorEditorControls"/);
  assert.match(boxReview, /id="interfaceWorkflowContentEditor"/);
  assert.match(boxReview, /id="imageInspectorProviderActionSuggestion"/);
  assert.doesNotMatch(boxReview, /id="interfaceWorkflowOperationToolbar"/);

  assert.match(panelHtml, /id="imageInspectorOpenOperationBtn"[^>]*>查看关联操作</);
  assert.match(panelHtml, /id="interfaceWorkflowOperationToolbarParkingHost"/);
});

test("selected-box provider action suggestions become read-only in workflow review", () => {
  const controlsSource = functionSource(
    "function updateLearningDraftEditorControls",
    "function applyLearningDraftEditorMetadataFromControls",
  );
  assert.match(controlsSource, /workflowBound/);
  assert.match(controlsSource, /imageInspectorProviderActionSuggestion/);
  for (const name of ["actionType", "destinationKind", "destinationValue", "verificationRule", "riskLevel"]) {
    assert.match(controlsSource, new RegExp(`${name}\\.disabled = !selected \\|\\| workflowBound`));
  }
});

test("linked operation opens only in the dedicated workflow link dialog", () => {
  const openSource = functionSource(
    "function openInterfaceWorkflowLinkedOperationDialog",
    "function interfaceWorkflowSourcePathsAfterReview",
  );
  assert.match(openSource, /openInterfaceWorkflowLinkDialog\(edge, \{ scope: "scoped" \}\)/);
  assert.match(panelSource, /on\("imageInspectorOpenOperationBtn", "click", openCurrentImageInspectorWorkflowOperationDialog\)/);
  const restoreSource = functionSource(
    "function restoreInterfaceWorkflowOperationToolbar",
    "function closeInterfaceWorkflowLinkDialog",
  );
  assert.match(restoreSource, /interfaceWorkflowOperationToolbarParkingHost/);
  assert.match(restoreSource, /parkingHost\.appendChild\(toolbar\)/);
  assert.match(restoreSource, /toolbar\.hidden = true/);
});

test("full-image linked operation entry fails closed on stale or ambiguous bindings", () => {
  const openSource = functionSource(
    "function openInterfaceWorkflowLinkedOperationDialog",
    "function interfaceWorkflowSourcePathsAfterReview",
  );
  const calls = [];
  const state = {
    snapshot: () => ({ workflow: { workflow_id: "seek_flow" } }),
  };
  const edge = {
    edge_id: "job_detail_to_apply",
    source_node_id: "job_detail",
    target_node_id: "apply_entry",
    target_control_id: "quick_apply",
    action_template_id: "open_apply_flow_candidate",
    action_type: "open_apply_flow",
  };
  const view = { node: { node_id: "job_detail" }, outgoing_edges: [edge] };
  const sandbox = { console, globalThis: {}, calls, state, view };
  vm.runInNewContext(`
    let interfaceWorkflowSelectedOperationId = "";
    let currentState = state;
    let learningDraftEditorWorkflowBinding = {
      authority: "workflow",
      workflow_id: "seek_flow",
      node_id: "job_detail",
      state,
    };
    let learningDraftEditorWorkflowSelection = {
      status: "matched",
      node_id: "job_detail",
      control_id: "quick_apply",
      action_template_id: "open_apply_flow_candidate",
      edge_id: "job_detail_to_apply",
      target_node_id: "apply_entry",
    };
    const currentInterfaceWorkflowMutationTarget = () => ({ state: currentState, view });
    const learningDraftEditorSelectedItem = () => ({ semantic_action: "open_apply_flow" });
    const renderInterfaceWorkflowOperationEditor = () => calls.push(["render"]);
    const openInterfaceWorkflowLinkDialog = (selectedEdge, options) => calls.push([
      "open",
      selectedEdge.edge_id,
      options?.scope,
    ]);
    const renderResponse = (response) => calls.push(["blocked", response.message]);
    ${openSource}
    globalThis.openLinked = openInterfaceWorkflowLinkedOperationDialog;
    globalThis.setScenario = (name) => {
      currentState = state;
      learningDraftEditorWorkflowBinding = {
        authority: "workflow",
        workflow_id: "seek_flow",
        node_id: "job_detail",
        state,
      };
      learningDraftEditorWorkflowSelection = {
        status: "matched",
        node_id: "job_detail",
        control_id: "quick_apply",
        action_template_id: "open_apply_flow_candidate",
        edge_id: "job_detail_to_apply",
        target_node_id: "apply_entry",
      };
      if (name === "ambiguous") learningDraftEditorWorkflowSelection.status = "ambiguous";
      if (name === "state_drift") currentState = {};
      if (name === "workflow_drift") learningDraftEditorWorkflowBinding.workflow_id = "other_flow";
      if (name === "control_drift") learningDraftEditorWorkflowSelection.control_id = "other_control";
      if (name === "action_drift") learningDraftEditorWorkflowSelection.action_template_id = "other_action";
    };
  `, sandbox);

  assert.equal(sandbox.globalThis.openLinked().edge_id, edge.edge_id);
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0])), ["render"]);
  assert.deepEqual(JSON.parse(JSON.stringify(calls[1])), ["open", edge.edge_id, "scoped"]);

  for (const scenario of ["ambiguous", "state_drift", "workflow_drift", "control_drift", "action_drift"]) {
    const isolatedCalls = calls.length;
    sandbox.globalThis.setScenario(scenario);
    assert.equal(sandbox.globalThis.openLinked(), null);
    assert.equal(calls.slice(isolatedCalls).some((entry) => entry[0] === "open"), false);
  }
});

test("operation dialog keeps input staged and cancel restores its opening snapshot", () => {
  const mutationSource = functionSource(
    "function handleInterfaceWorkflowOperationEditorMutation",
    "function interfaceWorkflowAssetV2BindingCandidate",
  );
  const dialogSource = functionSource(
    "function restoreInterfaceWorkflowOperationToolbar",
    "function restoreInterfaceWorkflowEvidence",
  );
  const originalSnapshot = {
    workflow: { workflow_id: "seek_flow" },
    nodes: [{ node_id: "job_detail" }],
    edges: [{ edge_id: "edge_open", display_name: "Original" }],
  };
  const mutatedState = {
    snapshot: () => ({ ...originalSnapshot, edges: [{ edge_id: "edge_open", display_name: "Mutated" }] }),
  };
  const restoredState = {
    selected: "",
    select(nodeId) { this.selected = nodeId; },
    snapshot: () => originalSnapshot,
  };
  const toolbar = { hidden: false, parentElement: null };
  const parkingHost = { appendChild(node) { node.parentElement = this; } };
  const dialog = {
    open: true,
    dataset: { mode: "edit", scope: "scoped" },
    close() { this.open = false; },
  };
  const status = { textContent: "" };
  const elements = new Map([
    ["interfaceWorkflowOperationToolbar", toolbar],
    ["interfaceWorkflowOperationToolbarParkingHost", parkingHost],
    ["interfaceWorkflowLinkDialog", dialog],
    ["interfaceWorkflowOperationStatus", status],
  ]);
  const calls = [];
  const sandbox = { console, globalThis: {}, originalSnapshot, mutatedState, restoredState, elements, calls };
  vm.runInNewContext(`
    let interfaceWorkflowReviewState = mutatedState;
    let interfaceWorkflowReview = mutatedState.snapshot();
    let interfaceWorkflowSelectedOperationId = "edge_open";
    let interfaceWorkflowHasUnsavedChanges = false;
    let interfaceWorkflowSavedReviewPath = "workflow.json";
    let learningDraftEditorWorkflowBinding = { authority: "workflow", state: mutatedState };
    let interfaceWorkflowOperationDialogSession = {
      state: mutatedState,
      snapshot: originalSnapshot,
      node_id: "job_detail",
      selected_operation_id: "edge_open",
      had_unsaved_changes: false,
      saved_review_path: "workflow.json",
      dirty: false,
    };
    const currentLanguage = "zh-CN";
    const currentInterfaceWorkflowMutationTarget = () => ({ state: interfaceWorkflowReviewState, view: null });
    const clearInterfaceWorkflowNodeHumanReviewConfirmation = () => calls.push("clear");
    const commitInterfaceWorkflowOperationEditor = () => calls.push("commit");
    const markInterfaceWorkflowUnsaved = () => calls.push("dirty");
    const currentInterfaceWorkflowOperation = () => ({ edge_id: "edge_open" });
    const renderInterfaceWorkflowOperationGranularStatus = () => calls.push("badges");
    const renderInterfaceWorkflowReviewSelection = () => calls.push("render");
    const setInterfaceWorkflowGraphLinkStatus = () => {};
    const interfaceWorkflowWorkbenchState = { clearLink: () => {} };
    globalThis.InterfaceWorkflowReview = {
      createInterfaceWorkflowReviewState: () => restoredState,
    };
    const $ = (id) => elements.get(id) || null;
    ${mutationSource}
    ${dialogSource}
    globalThis.stageInput = handleInterfaceWorkflowOperationEditorMutation;
    globalThis.cancelDialog = cancelInterfaceWorkflowLinkDialog;
    globalThis.snapshot = () => ({
      state: interfaceWorkflowReviewState,
      bindingState: learningDraftEditorWorkflowBinding.state,
      selectedOperationId: interfaceWorkflowSelectedOperationId,
      dirty: interfaceWorkflowHasUnsavedChanges,
    });
  `, sandbox);

  sandbox.globalThis.stageInput();
  assert.deepEqual(calls, []);
  assert.match(status.textContent, /尚未保存/);

  let prevented = 0;
  sandbox.globalThis.cancelDialog({ preventDefault: () => { prevented += 1; } });
  const restored = sandbox.globalThis.snapshot();
  assert.equal(prevented, 1);
  assert.equal(restored.state, restoredState);
  assert.equal(restored.bindingState, restoredState);
  assert.equal(restored.selectedOperationId, "edge_open");
  assert.equal(restored.dirty, false);
  assert.equal(dialog.open, false);
  assert.equal(toolbar.parentElement, parkingHost);
});

test("all Link Dialog cancellation routes use the restoring cancel handler", () => {
  const bindSource = functionSource("function bindEvents", "async function boot");
  assert.match(bindSource, /interfaceWorkflowLinkDialogCancelBtn[\s\S]*cancelInterfaceWorkflowLinkDialog/);
  assert.match(bindSource, /interfaceWorkflowLinkDialogCloseBtn[\s\S]*cancelInterfaceWorkflowLinkDialog/);
  assert.match(bindSource, /addEventListener\("cancel"[\s\S]*cancelInterfaceWorkflowLinkDialog/);
  assert.match(bindSource, /event\.target === \$\("interfaceWorkflowLinkDialog"\)[\s\S]*cancelInterfaceWorkflowLinkDialog/);
});

test("Link Dialog add update and delete controls stage intent until the dialog save action", () => {
  const bindSource = functionSource("function bindEvents", "async function boot");
  assert.match(bindSource, /interfaceWorkflowOperationAddBtn", "click", stageInterfaceWorkflowOperationCreate/);
  assert.match(bindSource, /interfaceWorkflowOperationUpdateBtn", "click", stageInterfaceWorkflowOperationUpdate/);
  assert.match(bindSource, /interfaceWorkflowOperationDeleteBtn", "click", stageInterfaceWorkflowOperationDelete/);
  const saveStart = bindSource.indexOf('on("interfaceWorkflowLinkDialogSaveBtn"');
  const saveEnd = bindSource.indexOf('on("interfaceWorkflowLinkDialogCancelBtn"', saveStart);
  const saveHandler = bindSource.slice(saveStart, saveEnd);
  assert.match(saveHandler, /pendingAction === "delete"/);
  assert.match(saveHandler, /removeInterfaceWorkflowOperation\(\)/);
  assert.match(saveHandler, /updateInterfaceWorkflowOperation\(\)/);
  assert.match(saveHandler, /addInterfaceWorkflowOperation\(\)/);
});

test("canonical operation editor saves and rerenders success and failure conditions", () => {
  assert.match(panelHtml, /id="interfaceWorkflowOperationSuccessConditions"/);
  assert.match(panelHtml, /id="interfaceWorkflowOperationFailureConditions"/);
  const patchSource = functionSource(
    "function interfaceWorkflowConditionLines",
    "function markInterfaceWorkflowUnsaved",
  );
  const success = { value: "detail title is visible\nURL remains same-site", disabled: false };
  const failure = { value: "login dialog appears\ncontrol is ambiguous", disabled: false };
  const patchElements = new Map([
    ["interfaceWorkflowOperationSuccessConditions", success],
    ["interfaceWorkflowOperationFailureConditions", failure],
  ]);
  const patchSandbox = { globalThis: {}, patchElements };
  vm.runInNewContext(`
    const interfaceWorkflowReviewState = { current: () => ({ node: { controls: [], regions: [] } }) };
    const $ = (id) => patchElements.get(id) || null;
    ${patchSource}
    globalThis.readPatch = interfaceWorkflowOperationPatch;
  `, patchSandbox);
  const patch = JSON.parse(JSON.stringify(patchSandbox.globalThis.readPatch()));
  assert.deepEqual(patch.success_conditions, ["detail title is visible", "URL remains same-site"]);
  assert.deepEqual(patch.failure_conditions, ["login dialog appears", "control is ambiguous"]);

  success.value = "";
  failure.value = "";
  const renderSource = functionSource(
    "function renderInterfaceWorkflowOperationEditor",
    "function createInterfaceWorkflowPlaceholderNode",
  );
  const renderSandbox = { globalThis: {}, patchElements };
  vm.runInNewContext(`
    let interfaceWorkflowSelectedOperationId = "edge_open";
    const interfaceWorkflowOperationDialogSession = null;
    const operation = {
      edge_id: "edge_open",
      success_conditions: ["detail title is visible", "URL remains same-site"],
      failure_conditions: ["login dialog appears", "control is ambiguous"],
    };
    const currentInterfaceWorkflowOperation = () => operation;
    const interfaceWorkflowReviewState = { graph: () => ({ nodes: [] }) };
    const renderInterfaceWorkflowOperationGranularStatus = () => {};
    const fillInterfaceWorkflowControlSelect = () => {};
    const escapeHtml = (value) => String(value);
    const $ = (id) => patchElements.get(id) || null;
    ${renderSource}
    globalThis.renderOperation = renderInterfaceWorkflowOperationEditor;
  `, renderSandbox);
  renderSandbox.globalThis.renderOperation({ node: { node_id: "job_detail" }, outgoing_edges: [{}] });
  assert.equal(success.value, "detail title is visible\nURL remains same-site");
  assert.equal(failure.value, "login dialog appears\ncontrol is ambiguous");
});

test("scoped operation edit fixes the exact edge and removes duplicate mutation controls", () => {
  const configureSource = functionSource(
    "function configureInterfaceWorkflowOperationDialogScope",
    "function openInterfaceWorkflowLinkDialog",
  );
  assert.match(configureSource, /scope === "scoped"/);
  assert.match(configureSource, /interfaceWorkflowOperationList/);
  assert.match(configureSource, /interfaceWorkflowOperationAddBtn/);
  assert.match(configureSource, /interfaceWorkflowOperationDeleteBtn/);
});

test("full-image review panel preserves heading and interface fields before review sections", () => {
  assert.match(
    panelCss,
    /\.interface-workflow-current-review-panel\s*>\s*\*\s*\{[^}]*order:\s*0;/s,
  );
});

test("standalone source preview cannot acquire workflow mutation authority", () => {
  const authoritySource = functionSource(
    "function currentInterfaceWorkflowMutationTarget",
    "function interfaceWorkflowEditableImagePath",
  );
  const workflowB = { node: { node_id: "workflow_b" } };
  const sourceA = { node: { node_id: "asset_a" } };
  const sandbox = { globalThis: {} };
  vm.runInNewContext(`
    const interfaceWorkflowWorkbenchState = {
      current: () => ({ evidence_mode: "source_preview", evidence_node_id: "asset_a" }),
    };
    const interfaceWorkflowReviewState = { current: () => workflowB };
    ${authoritySource}
    globalThis.resolveMutation = currentInterfaceWorkflowMutationTarget;
  `, { ...sandbox, workflowB });

  const target = sandbox.globalThis.resolveMutation(sourceA);

  assert.equal(target.state, null);
  assert.equal(target.view.node.node_id, "asset_a");
  assert.equal(target.reason, "source_preview_requires_workflow_attachment");
});

test("standalone source preview exposes box correction but disables workflow review controls", () => {
  const renderSource = functionSource(
    "function renderInterfaceWorkflowEditor",
    "function clearInterfaceWorkflowNodeHumanReviewConfirmation",
  );
  const elements = new Map([
    ["interfaceWorkflowNodeName", { value: "", disabled: false }],
    ["interfaceWorkflowSurfaceType", { value: "", disabled: false }],
    ["imageInspectorConfirmAndStoreBtn", { disabled: false }],
    ["interfaceWorkflowReviewToolsToggle", { disabled: false }],
    ["interfaceWorkflowRefreshEvidenceBtn", { disabled: false }],
    ["interfaceWorkflowRemoveSourceBtn", { disabled: false }],
    ["interfaceWorkflowMemoryBtn", { disabled: false }],
    ["interfaceWorkflowSaveStatus", { textContent: "" }],
    ["interfaceWorkflowOperationToolbar", { hidden: false }],
  ]);
  const calls = { contentEditable: null, operationEditable: null };
  const sandbox = { globalThis: {}, elements, calls };
  vm.runInNewContext(`
    let interfaceWorkflowHasUnsavedChanges = false;
    const interfaceWorkflowWorkbenchState = { current: () => ({ correction_open: true }) };
    const currentInterfaceWorkflowMutationTarget = (view) => ({
      state: null,
      view,
      reason: "source_preview_requires_workflow_attachment",
    });
    const renderInterfaceWorkflowContentEditor = (_view, options) => {
      calls.contentEditable = options?.editable;
    };
    const renderInterfaceWorkflowOperationEditor = (_view, options) => {
      calls.operationEditable = options?.editable;
    };
    const syncImageInspectorConfirmAndStoreButton = () => {
      elements.get("imageInspectorConfirmAndStoreBtn").disabled = true;
    };
    const t = (key) => key;
    const $ = (id) => elements.get(id) || null;
    ${renderSource}
    globalThis.renderEditor = renderInterfaceWorkflowEditor;
  `, sandbox);

  sandbox.globalThis.renderEditor({
    node: { node_id: "asset_a", display_name: "Asset A", review_status: "needs_human_review" },
  });

  assert.equal(elements.get("interfaceWorkflowNodeName").disabled, true);
  assert.equal(elements.get("imageInspectorConfirmAndStoreBtn").disabled, true);
  assert.equal(elements.get("interfaceWorkflowRefreshEvidenceBtn").disabled, true);
  assert.equal(elements.get("interfaceWorkflowReviewToolsToggle").disabled, false);
  assert.equal(elements.get("interfaceWorkflowOperationToolbar").hidden, true);
  assert.match(elements.get("interfaceWorkflowSaveStatus").textContent, /加入软件流程/);
  assert.equal(calls.contentEditable, false);
  assert.equal(calls.operationEditable, false);
});

test("workflow mutation handlers reject a displayed standalone source preview", () => {
  const guardedFunctions = [
    ["function saveInterfaceWorkflowContentDescriptor", "function renderInterfaceWorkflowEditor"],
    ["function commitInterfaceWorkflowOperationEditor", "function confirmCurrentInterfaceWorkflowOperationBundle"],
    ["function approveCurrentInterfaceWorkflowNode", "async function approveAndSaveCurrentInterfaceWorkflowNode"],
    ["function commitInterfaceWorkflowEditorToState", "async function saveInterfaceWorkflowReview"],
  ];
  for (const [start, end] of guardedFunctions) {
    assert.match(
      functionSource(start, end),
      /currentInterfaceWorkflowMutationTarget\(/,
      `${start} must fail closed unless the displayed evidence owns workflow authority`,
    );
  }
  assert.match(
    functionSource(
      "async function confirmAndStoreCurrentInterfaceWorkflowReview",
      "async function publishLearningOperationalMemory",
    ),
    /binding\?\.authority !== "workflow"/,
  );
});

test("refresh current evidence rejects a displayed standalone source preview without saving workflow B", async () => {
  const refreshSource = functionSource(
    "async function refreshCurrentInterfaceWorkflowEvidence",
    "function closeImageInspector",
  );
  let refreshes = 0;
  const button = { disabled: false, textContent: "刷新当前证据" };
  const sandbox = {
    globalThis: {},
    currentInterfaceWorkflowMutationTarget: () => ({
      state: null,
      view: { node: { node_id: "asset_a" } },
      reason: "source_preview_requires_workflow_attachment",
    }),
    refreshSavedLearningDraftReview: async () => { refreshes += 1; return {}; },
    renderResponse: () => {},
    $: (id) => id === "interfaceWorkflowRefreshEvidenceBtn" ? button : null,
  };
  vm.runInNewContext(
    `${refreshSource}; globalThis.refreshEvidence = refreshCurrentInterfaceWorkflowEvidence;`,
    sandbox,
  );

  const result = await sandbox.globalThis.refreshEvidence();

  assert.equal(result, null);
  assert.equal(refreshes, 0);
  assert.equal(button.disabled, true);
});

test("refresh current evidence preserves workflow-bound refresh and save", async () => {
  const refreshSource = functionSource(
    "async function refreshCurrentInterfaceWorkflowEvidence",
    "function closeImageInspector",
  );
  const reviewState = { snapshot: () => ({ workflow: { workflow_id: "workflow_b" } }) };
  const workflowView = {
    node: {
      node_id: "workflow_b",
      editable_review_source_path: "artifacts/workflow-b/review.json",
    },
  };
  const button = { disabled: false, textContent: "刷新当前证据" };
  const calls = [];
  const sandbox = {
    globalThis: {},
    currentInterfaceWorkflowMutationTarget: () => ({ state: reviewState, view: workflowView, reason: "" }),
    interfaceWorkflowEditableReviewSourcePath: () => "artifacts/workflow-b/review.json",
    buildLearningDraftEditorBinding: (options) => { calls.push(["binding", options]); return options; },
    refreshSavedLearningDraftReview: async (options) => {
      calls.push(["refresh", options]);
      return { review: {}, workflow: { workflow_id: "workflow_b" } };
    },
    renderResponse: () => {},
    $: (id) => id === "interfaceWorkflowRefreshEvidenceBtn" ? button : null,
  };
  vm.runInNewContext(
    `${refreshSource}; globalThis.refreshEvidence = refreshCurrentInterfaceWorkflowEvidence;`,
    sandbox,
  );

  const result = await sandbox.globalThis.refreshEvidence();

  assert.equal(result.workflow.workflow_id, "workflow_b");
  assert.equal(calls[0][0], "binding");
  assert.equal(calls[0][1].authority, "workflow");
  assert.equal(calls[0][1].state, reviewState);
  assert.equal(calls[1][0], "refresh");
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "刷新当前证据");
});

test("switching the box editor source preserves the workflow review that owns it", () => {
  const sourceBindingFunctions = functionSource(
    "function invalidateLearningDraftReviewSource",
    "async function loadLearningDraftFreshnessDemo",
  );
  const openEditorSource = functionSource(
    "async function openCurrentInterfaceWorkflowBoxEditor",
    "function interfaceWorkflowSourcePathsAfterReview",
  );
  const sourceInput = { value: "old-review.json" };
  const observations = { clearOptions: null };
  const sandbox = { console, globalThis: {}, sourceInput, observations };
  vm.runInNewContext(`
    let learningDraftReviewLoadRequestToken = 4;
    let learningDraftReviewLoadAbortController = null;
    const clearLearningDraftReviewDisplay = (_reason, options) => {
      observations.clearOptions = options;
    };
    const $ = (id) => id === "learningDraftReviewSourcePath" ? sourceInput : null;
    ${sourceBindingFunctions}
    globalThis.setSourcePath = setLearningDraftReviewSourcePath;
  `, sandbox);

  sandbox.globalThis.setSourcePath("job-detail-review.json", { preserveWorkflowReview: true });

  assert.equal(sourceInput.value, "job-detail-review.json");
  assert.equal(observations.clearOptions?.preserveWorkflowReview, true);
  assert.equal(
    openEditorSource.match(/setLearningDraftReviewSourcePath\(sourcePath, \{ preserveWorkflowReview: true \}\);/g)?.length,
    2,
  );
  assert.match(
    openEditorSource,
    /supersedePendingLoad:\s*true/,
    "an explicit full-image review must supersede a stale in-flight load, even for the same source",
  );
});

test("annotated derivative cannot become the editable full-image review base", () => {
  const resolverSource = functionSource(
    "function interfaceWorkflowEditableImageSource",
    "function interfaceWorkflowEditableReviewSourcePath",
  );
  const sandbox = { globalThis: {} };
  vm.runInNewContext(`
    ${resolverSource}
    globalThis.resolveEditableImage = interfaceWorkflowEditableImageSource;
  `, sandbox);

  const derivative = sandbox.globalThis.resolveEditableImage({
    node: {
      evidence: {
        source_screenshot_path: "artifacts/job-detail-overlay.png",
        source_image_kind: "privacy_redacted_derivative",
        editable_base_allowed: false,
      },
    },
  });
  assert.equal(derivative.editable, false);
  assert.equal(derivative.path, "");
  assert.equal(derivative.reason, "annotated_derivative_not_editable");

  const unclassified = sandbox.globalThis.resolveEditableImage({
    node: {
      evidence: {
        source_screenshot_path: "artifacts/job-detail-unknown.png",
      },
    },
  });
  assert.equal(unclassified.editable, false);
  assert.equal(unclassified.path, "");
  assert.equal(unclassified.reason, "editable_source_kind_unclassified");

  const clean = sandbox.globalThis.resolveEditableImage({
    node: {
      evidence: {
        source_screenshot_path: "artifacts/job-detail-clean.png",
        source_image_kind: "sanitized_clean_capture",
        editable_base_allowed: true,
      },
    },
  });
  assert.equal(clean.editable, true);
  assert.equal(clean.path, "artifacts/job-detail-clean.png");
  assert.equal(clean.reason, "");
});

test("selecting a full-image draft box focuses its exact workflow control and operation", () => {
  const selectionSource = functionSource(
    "function syncLearningDraftEditorWorkflowSelection",
    "function selectLearningDraftEditorItem",
  );
  const observations = { focused: "", cleared: 0, renders: 0, status: [] };
  const workflowState = {
    current: () => ({
      node: { node_id: "job_detail" },
      outgoing_edges: [{ edge_id: "job_detail_to_choose_documents" }],
    }),
    focusControl: (controlId) => { observations.focused = controlId; },
    clearFocus: () => { observations.cleared += 1; },
  };
  const sandbox = { console, globalThis: {}, observations, workflowState };
  vm.runInNewContext(`
    let interfaceWorkflowSelectedOperationId = "";
    let learningDraftEditorWorkflowSelection = null;
    const learningDraftEditorWorkflowBinding = {
      authority: "workflow",
      workflow_id: "workflow_seek",
      node_id: "job_detail",
      state: workflowState,
    };
    const currentInterfaceWorkflowMutationTarget = () => ({
      state: workflowState,
      view: workflowState.current(),
      reason: "",
    });
    globalThis.InterfaceWorkflowReview = {
      resolveDraftItemWorkflowBinding: () => ({
        status: "matched",
        reason: "",
        control_id: "apply",
        control_label: "Quick apply",
        action_template_id: "open_apply_flow",
        edge_id: "job_detail_to_choose_documents",
        target_node_id: "choose_documents",
      }),
    };
    const setInterfaceWorkflowBoxEditorStatus = (message, tone) => observations.status.push([message, tone]);
    const renderInterfaceWorkflowReviewSelection = () => { observations.renders += 1; };
    const syncImageInspectorConfirmAndStoreButton = () => {};
    const $ = () => null;
    ${selectionSource}
    globalThis.syncSelection = syncLearningDraftEditorWorkflowSelection;
    globalThis.snapshot = () => ({
      operationId: interfaceWorkflowSelectedOperationId,
      selection: learningDraftEditorWorkflowSelection,
    });
  `, sandbox);

  const result = sandbox.globalThis.syncSelection({
    target_kind: "region",
    target_id: "manual_region_1",
    label: "Manual region 1",
    semantic_action: "open_apply_flow",
  });

  assert.equal(result.status, "matched");
  assert.equal(observations.focused, "apply");
  assert.equal(observations.cleared, 0);
  assert.equal(observations.renders, 1);
  assert.equal(sandbox.globalThis.snapshot().operationId, "job_detail_to_choose_documents");
  assert.equal(sandbox.globalThis.snapshot().selection.control_id, "apply");
  assert.match(observations.status.at(-1)[0], /Quick apply/);
});

test("ambiguous full-image mapping clears stale focus and blocks confirmation", () => {
  const selectionSource = functionSource(
    "function syncLearningDraftEditorWorkflowSelection",
    "function selectLearningDraftEditorItem",
  );
  const observations = { focused: "", cleared: 0, renders: 0, status: [] };
  const workflowState = {
    current: () => ({ node: { node_id: "job_detail" }, outgoing_edges: [{ edge_id: "edge_old" }] }),
    focusControl: (controlId) => { observations.focused = controlId; },
    clearFocus: () => { observations.cleared += 1; },
  };
  const sandbox = { console, globalThis: {}, observations, workflowState };
  vm.runInNewContext(`
    let interfaceWorkflowSelectedOperationId = "edge_old";
    let learningDraftEditorWorkflowSelection = { status: "matched", control_id: "stale" };
    const learningDraftEditorWorkflowBinding = {
      authority: "workflow",
      workflow_id: "workflow_seek",
      node_id: "job_detail",
      state: workflowState,
    };
    const currentInterfaceWorkflowMutationTarget = () => ({ state: workflowState, view: workflowState.current(), reason: "" });
    globalThis.InterfaceWorkflowReview = {
      resolveDraftItemWorkflowBinding: () => ({
        status: "ambiguous",
        reason: "workflow_control_mapping_ambiguous",
        control_id: "",
        edge_id: "",
      }),
    };
    const setInterfaceWorkflowBoxEditorStatus = (message, tone) => observations.status.push([message, tone]);
    const renderInterfaceWorkflowReviewSelection = () => { observations.renders += 1; };
    const syncImageInspectorConfirmAndStoreButton = () => {};
    const $ = () => null;
    ${selectionSource}
    globalThis.syncSelection = syncLearningDraftEditorWorkflowSelection;
    globalThis.snapshot = () => ({
      operationId: interfaceWorkflowSelectedOperationId,
      selection: learningDraftEditorWorkflowSelection,
    });
  `, sandbox);

  const result = sandbox.globalThis.syncSelection({
    target_kind: "region",
    target_id: "manual_region_1",
    semantic_action: "open_apply_flow",
  });

  assert.equal(result.status, "ambiguous");
  assert.equal(observations.focused, "");
  assert.equal(observations.cleared, 1);
  assert.equal(sandbox.globalThis.snapshot().operationId, "");
  assert.equal(sandbox.globalThis.snapshot().selection.reason, "workflow_control_mapping_ambiguous");
  assert.equal(observations.status.at(-1)[1], "error");
  assert.match(observations.status.at(-1)[0], /唯一绑定/);
});

test("outgoing workflow cannot be confirmed until its full-image target was inspected", () => {
  const buttonSource = functionSource(
    "function syncImageInspectorConfirmAndStoreButton",
    "function syncInterfaceWorkflowCorrectionToggleLabel",
  );
  const button = { hidden: true, disabled: false, textContent: "", title: "" };
  const view = {
    node: { node_id: "job_detail", review_status: "needs_human_review" },
    outgoing_edges: [{ edge_id: "job_detail_to_choose_documents" }],
  };
  const state = { snapshot: () => ({ workflow: { workflow_id: "workflow_seek" } }) };
  const sandbox = { globalThis: {}, button, view, state };
  vm.runInNewContext(`
    const learningDraftEditorWorkflowBinding = {
      authority: "workflow",
      workflow_id: "workflow_seek",
      node_id: "job_detail",
    };
    let learningDraftEditorWorkflowSelection = null;
    const learningDraftEditorState = { exportOperations: () => [] };
    const learningDraftEditorActive = true;
    const interfaceWorkflowHasUnsavedChanges = false;
    const currentLanguage = "zh-CN";
    const currentInterfaceWorkflowMutationTarget = () => ({ state, view });
    const $ = (id) => id === "imageInspectorConfirmAndStoreBtn" ? button : null;
    ${buttonSource}
    globalThis.syncButton = syncImageInspectorConfirmAndStoreButton;
    globalThis.markInspected = () => {
      learningDraftEditorWorkflowSelection = {
        status: "matched",
        node_id: "job_detail",
        control_id: "apply",
        edge_id: "job_detail_to_choose_documents",
      };
    };
  `, sandbox);

  sandbox.globalThis.syncButton(view);
  assert.equal(button.disabled, true);
  assert.match(button.title, /选择并核对/);

  sandbox.globalThis.markInspected();
  sandbox.globalThis.syncButton(view);
  assert.equal(button.disabled, false);
});
