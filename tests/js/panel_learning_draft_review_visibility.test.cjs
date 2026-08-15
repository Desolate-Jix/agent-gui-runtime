const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const indexSource = fs.readFileSync(
  path.join(__dirname, "../../app/web_panel/index.html"),
  "utf8",
);
const panelSource = fs.readFileSync(
  path.join(__dirname, "../../app/web_panel/panel.js"),
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

function createReviewHarness() {
  const renderSource = functionSource(
    "function renderLearningDraftReview(review)",
    "function clearLearningDraftReviewDisplay",
  );
  const clearSource = functionSource(
    "function clearLearningDraftReviewDisplay",
    "function renderLearningCorrectionMemoryRegistry",
  );
  const elements = new Map([
    ["learningDraftReviewPanel", { hidden: true }],
    ["learningDraftReviewVerificationRules", { value: "stale" }],
    ["learningDraftReviewStatus", { textContent: "" }],
    ["learningDraftReviewStatusSelect", { value: "" }],
  ]);
  const sandbox = {
    elements,
    globalThis: {},
    document: { body: { dataset: {} } },
    console,
  };
  vm.runInNewContext(`
    let learningDraftReview = null;
    let learningDraftReviewBboxEdits = {};
    const learningDraftOwnershipConflicts = [];
    const $ = (id) => elements.get(id) || null;
    const t = (value) => value;
    const escapeHtml = (value) => String(value);
    const learningDraftSourceImagePath = () => "";
    const renderLearningReviewItems = () => "";
    const bindLearningDraftPreviewButtons = () => {};
    const learningReviewLines = (items) => items.map((item) => item.rule_id || item).join("\\n");
    const learningDraftManualBboxEditSummary = () => ({});
    const learningDraftSourceFreshnessSummary = () => ({});
    const renderLearningDraftManualBboxEditSummary = () => "";
    const renderLearningDraftSourceFreshnessSummary = () => "";
    const renderScreenUnderstandingPreview = () => {};
    const renderLearningDraftScreenshotPanel = () => {};
    const renderLearningDraftManualEditPanel = () => {};
    const renderLearningDraftPathPreview = () => {};
    const clearInterfaceWorkflowReview = () => {};
    const resetLearningDraftEditorState = () => {};
    const clearLearningDraftSimpleReviewPanels = () => {};
    const clearLearningDraftPathPreview = () => {};
    ${renderSource}
    ${clearSource}
    globalThis.renderReview = renderLearningDraftReview;
    globalThis.clearReview = clearLearningDraftReviewDisplay;
  `, sandbox);
  return sandbox;
}

function createScreenshotPanelHarness() {
  const renderSource = functionSource(
    "function renderLearningDraftScreenshotPanel(review)",
    "function learningDraftManualCandidate",
  );
  const elements = new Map([
    ["learningDraftScreenshotPanel", { hidden: true }],
    ["learningDraftScreenshotPreview", { innerHTML: "" }],
  ]);
  const sandbox = { elements, console, globalThis: {} };
  vm.runInNewContext(`
    const $ = (id) => elements.get(id) || null;
    const escapeHtml = (value) => String(value);
    const t = (value) => value;
    const learningDraftNumberedMapImagePath = (review) => review?.draft?.page_details?.screen?.image_path || "";
    const learningDraftSourceImagePath = () => "";
    const learningDraftSourceImageSha256 = () => "";
    const renderLearningDraftScreenshotPath = () => {};
    ${renderSource}
    globalThis.renderScreenshotPanel = renderLearningDraftScreenshotPanel;
  `, sandbox);
  return sandbox;
}

test("learning draft review starts hidden until a candidate is loaded", () => {
  const panelStart = indexSource.indexOf('id="learningDraftReviewPanel"');
  assert.notEqual(panelStart, -1, "learning review panel must exist");
  const sectionStart = indexSource.lastIndexOf("<section", panelStart);
  const section = indexSource.slice(sectionStart, panelStart + 80);
  assert.match(section, /\bhidden\b/);
});

test("loading a learning draft reveals its human verification controls", () => {
  const sandbox = createReviewHarness();
  sandbox.globalThis.renderReview({
    review_status: "needs_human_review",
    no_click_authorization: true,
    draft: { verification_rules: [] },
  });
  assert.equal(sandbox.elements.get("learningDraftReviewPanel").hidden, false);
  assert.equal(sandbox.document.body.dataset.learningDraftReviewOpen, "true");
  assert.equal(sandbox.elements.get("learningDraftReviewVerificationRules").value, "");
  assert.match(sandbox.elements.get("learningDraftReviewStatus").textContent, /no_click_authorization=true/);
});

test("clearing a learning draft hides review controls again", () => {
  const sandbox = createReviewHarness();
  sandbox.globalThis.renderReview({ draft: { verification_rules: [{ rule_id: "detail_visible" }] } });
  sandbox.globalThis.clearReview("loading another candidate");
  assert.equal(sandbox.elements.get("learningDraftReviewPanel").hidden, true);
  assert.equal(sandbox.document.body.dataset.learningDraftReviewOpen, undefined);
});

test("an opened review overrides clean-stage visibility suppression only for the review panel", () => {
  assert.match(
    panelCss,
    /body\[data-learning-draft-review-open="true"\]\s+#learningDraftReviewPanel:not\(\[hidden\]\)\s*\{\s*display:\s*grid\s*!important;/,
  );
});

test("a reviewed draft with a screen image reveals the screenshot edit panel", () => {
  const sandbox = createScreenshotPanelHarness();
  sandbox.globalThis.renderScreenshotPanel({ draft: { page_details: { screen: { image_path: "capture.png" } } } });
  assert.equal(sandbox.elements.get("learningDraftScreenshotPanel").hidden, false);
});

test("an opened review overrides clean-stage suppression for the visible screenshot panel", () => {
  assert.match(
    panelCss,
    /body\[data-learning-draft-review-open="true"\]\s+#learningDraftScreenshotPanel:not\(\[hidden\]\)\s*\{\s*display:\s*grid\s*!important;/,
  );
});

test("clearing a reviewed draft hides the screenshot edit panel", () => {
  const sandbox = createScreenshotPanelHarness();
  sandbox.globalThis.renderScreenshotPanel({ draft: { page_details: { screen: { image_path: "capture.png" } } } });
  sandbox.globalThis.renderScreenshotPanel({ draft: { page_details: { screen: { image_path: "" } } } });
  assert.equal(sandbox.elements.get("learningDraftScreenshotPanel").hidden, true);
});
