const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function loadEvidenceBuilder(observeResult) {
  const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
  const start = panelSource.indexOf("function buildLearningDraftObservationEvidence");
  const end = panelSource.indexOf("\nfunction setLearningTrialResultPath", start);
  const source = panelSource.slice(start, end);
  const context = {
    lastLearningDeepCalibrationResponse: null,
    lastResponse: {},
    lastLearningDraftObserveResponse: observeResult,
    learningSourceImagePath: "",
    currentImagePath: "",
    resultOf: (value) => value || {},
    nestedGet: (value, path) => path.reduce(
      (current, key) => current && current[key],
      value,
    ),
    screenMapEvidenceCount: () => 0,
    compactLearningDraftTargets: () => [],
    compactVistaCoordinateValidation: () => null,
    firstLearningSourceImagePath: (...values) => values.find(Boolean) || "",
    isLearningDisplayOverlayPath: () => false,
    $: () => null,
  };
  vm.createContext(context);
  vm.runInContext(`${source}\nthis.buildEvidence = buildLearningDraftObservationEvidence;`, context);
  return context.buildEvidence;
}

function loadProviderRenderer() {
  const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
  const start = panelSource.indexOf("function renderLearningDraftProviderSummary");
  const end = panelSource.indexOf("\nfunction renderScreenUnderstandingPreview", start);
  const source = panelSource.slice(start, end);
  const elements = {
    learningDraftProviderSummary: { hidden: true },
    learningDraftProviderSummaryBody: { innerHTML: "" },
  };
  const context = {
    $: (id) => elements[id] || null,
    escapeHtml: (value) => String(value),
  };
  vm.createContext(context);
  vm.runInContext(`${source}\nthis.renderProvider = renderLearningDraftProviderSummary;`, context);
  return { renderProvider: context.renderProvider, elements, panelSource };
}


test("learning observation evidence preserves actual model classification", () => {
  const classification = {
    category: "feed_workspace",
    confidence: 1,
    reason: "visible grid of news articles",
    structure_signals: {
      feed_items: true,
      news_items: true,
    },
  };
  const buildEvidence = loadEvidenceBuilder({
    image_path: "artifacts/screenshots/news.png",
    interface_classification: classification,
  });

  const evidence = buildEvidence();

  assert.deepEqual(
    JSON.parse(JSON.stringify(evidence.interface_classification)),
    classification,
  );
});


test("learning observation evidence drops raw OmniParser shapes without a server UEI ref", () => {
  const topLevel = {
    contract_version: "screen_parser_result_v1",
    provider: "omniparser",
    status: "success",
    elements: [{ element_id: "omniparser_0001", interactivity: true }],
  };
  const fromTopLevel = loadEvidenceBuilder({ omniparser: topLevel })();
  assert.equal(Object.prototype.hasOwnProperty.call(fromTopLevel, "omniparser"), false);

  const nested = {
    contract_version: "screen_parser_result_v1",
    provider: "omniparser",
    status: "failed",
    error: { code: "weights_missing", details: "weights are unavailable" },
  };
  const fromNested = loadEvidenceBuilder({ sources: { omniparser: nested } })();
  assert.equal(Object.prototype.hasOwnProperty.call(fromNested, "omniparser"), false);
  assert.equal(JSON.stringify(fromNested).includes("weights_missing"), false);
  assert.deepEqual(topLevel.elements, [{ element_id: "omniparser_0001", interactivity: true }]);
});


test("provider renderer uses readable Chinese state labels and never offers execution", () => {
  const { renderProvider, elements, panelSource } = loadProviderRenderer();
  assert.equal(panelSource.includes("\uFFFD"), false);

  renderProvider({
    provider_status: "success",
    provider: "omniparser",
    element_total: 43,
    interactive_evidence_count: 35,
    grounding_eligible_count: 4,
    review_only_count: 39,
    invalid_bbox_count: 0,
    execution_authorized: false,
    lineage_complete: true,
    capture_id_present: true,
    screenshot_sha256_present: true,
    profile_id: "omniparser_v2",
    model_revision: "v.2.0.1",
    lineage_warnings: [],
  });

  assert.equal(elements.learningDraftProviderSummary.hidden, false);
  assert.match(elements.learningDraftProviderSummaryBody.innerHTML, /供应商成功/);
  assert.match(elements.learningDraftProviderSummaryBody.innerHTML, /已生成候选/);
  assert.match(elements.learningDraftProviderSummaryBody.innerHTML, /Grounding 资格/);
  assert.match(elements.learningDraftProviderSummaryBody.innerHTML, /执行授权/);
  assert.match(elements.learningDraftProviderSummaryBody.innerHTML, /authorized=false/);
  assert.doesNotMatch(elements.learningDraftProviderSummaryBody.innerHTML, /<button/i);

  renderProvider({
    provider_status: "failed",
    provider_error: { code: "weights_missing", details: "weights are unavailable" },
    lineage_complete: false,
    lineage_warnings: ["provider_status_failed", "capture_id_mismatch"],
    execution_authorized: false,
  });
  assert.match(elements.learningDraftProviderSummaryBody.innerHTML, /status=failed/);
  assert.match(elements.learningDraftProviderSummaryBody.innerHTML, /供应商错误/);
  assert.match(elements.learningDraftProviderSummaryBody.innerHTML, /capture_id_mismatch/);
  assert.doesNotMatch(elements.learningDraftProviderSummaryBody.innerHTML, /<button/i);
});


test("learning pipeline mode surface defaults to incumbent and marks Hybrid disabled", () => {
  const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
  assert.match(panelSource, /const LEARNING_PIPELINE_MODE = "incumbent";/);
  const start = panelSource.indexOf("function learningPipelineModeStatus");
  const end = panelSource.indexOf("\nfunction ", start + 10);
  const source = panelSource.slice(start, end);
  const context = {};
  vm.createContext(context);
  vm.runInContext(`${source}\nthis.modeStatus = learningPipelineModeStatus;`, context);

  assert.deepEqual(
    JSON.parse(JSON.stringify(context.modeStatus("incumbent"))),
    { learning_pipeline_mode: "incumbent", rollout: "active" },
  );
  assert.deepEqual(
    JSON.parse(JSON.stringify(context.modeStatus("hybrid_v1_1"))),
    {
      learning_pipeline_mode: "hybrid_v1_1",
      rollout: "disabled",
      reason: "hybrid_rollout_disabled",
    },
  );
});
