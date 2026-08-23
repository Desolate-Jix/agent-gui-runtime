const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const panelSource = fs.readFileSync(
  path.join(__dirname, "../../app/web_panel/panel.js"),
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
  const tools = { hidden: true };
  const operationToolbar = { hidden: true };
  const toggle = { textContent: "" };
  const elements = new Map([
    ["interfaceWorkflowReviewToolsColumn", tools],
    ["interfaceWorkflowOperationToolbar", operationToolbar],
    ["interfaceWorkflowReviewToolsToggle", toggle],
  ]);
  const observations = { evidenceRenders: 0, editorRenders: 0, correctionOpen: false };
  const sandbox = { console, globalThis: {}, elements, observations };
  vm.runInNewContext(`
    const interfaceWorkflowWorkbenchState = {
      setCorrectionOpen: (open) => { observations.correctionOpen = open; },
    };
    const currentInterfaceWorkflowCorrectionTarget = () => ({ view: null });
    const renderInterfaceWorkflowEditor = () => { observations.editorRenders += 1; };
    const renderActiveInterfaceWorkflowEvidence = () => { observations.evidenceRenders += 1; };
    const t = (value) => value;
    const $ = (id) => elements.get(id) || null;
    ${correctionSource}
    globalThis.setCorrectionOpen = setInterfaceWorkflowCorrectionOpen;
  `, sandbox);

  sandbox.globalThis.setCorrectionOpen(true, { node: { node_id: "job_detail" } });

  assert.equal(observations.correctionOpen, true);
  assert.equal(tools.hidden, false);
  assert.equal(operationToolbar.hidden, false);
  assert.equal(observations.editorRenders, 1);
  assert.equal(observations.evidenceRenders, 1);
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
