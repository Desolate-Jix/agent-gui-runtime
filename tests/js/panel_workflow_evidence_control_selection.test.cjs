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
  const operationToolbar = { hidden: true };
  const toggle = { textContent: "" };
  const elements = new Map([
    ["interfaceWorkflowCurrentReviewPanel", reviewPanel],
    ["imageInspectorWorkflowReviewHost", reviewHost],
    ["interfaceWorkflowOperationToolbar", operationToolbar],
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
  assert.equal(operationToolbar.hidden, false);
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

test("full-image workbench contains current-interface review but excludes workflow release tools", () => {
  const start = panelHtml.indexOf('id="interfaceWorkflowCurrentReviewPanel"');
  const end = panelHtml.indexOf('id="interfaceWorkflowGenerateV2Btn"', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const currentReview = panelHtml.slice(start, end);
  for (const id of [
    "interfaceWorkflowNodeName",
    "interfaceWorkflowContentEditor",
    "interfaceWorkflowOperationToolbar",
  ]) {
    assert.match(currentReview, new RegExp(`id="${id}"`));
  }
  assert.doesNotMatch(currentReview, /id="interfaceWorkflowGenerateV2Btn"/);
  assert.doesNotMatch(currentReview, /id="interfaceWorkflowMemoryBtn"/);
  assert.doesNotMatch(currentReview, /id="interfaceWorkflowOperationDryRunBtn"/);
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
});
