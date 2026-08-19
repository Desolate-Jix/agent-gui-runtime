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


test("learning observation evidence preserves canonical OmniParser results from either observe shape", () => {
  const topLevel = {
    contract_version: "screen_parser_result_v1",
    provider: "omniparser",
    status: "success",
    elements: [{ element_id: "omniparser_0001", interactivity: true }],
  };
  const fromTopLevel = loadEvidenceBuilder({ omniparser: topLevel })();
  assert.deepEqual(JSON.parse(JSON.stringify(fromTopLevel.omniparser)), topLevel);

  const nested = {
    contract_version: "screen_parser_result_v1",
    provider: "omniparser",
    status: "failed",
    error: { code: "weights_missing", details: "weights are unavailable" },
  };
  const fromNested = loadEvidenceBuilder({ sources: { omniparser: nested } })();
  assert.deepEqual(JSON.parse(JSON.stringify(fromNested.omniparser)), nested);
  assert.deepEqual(topLevel.elements, [{ element_id: "omniparser_0001", interactivity: true }]);
});
