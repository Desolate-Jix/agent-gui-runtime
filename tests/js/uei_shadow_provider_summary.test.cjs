const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync("app/web_panel/panel.js", "utf8");
const html = fs.readFileSync("app/web_panel/index.html", "utf8");

function body(name, next) {
  const start = source.indexOf(`function ${name}`);
  const end = source.indexOf(next, start);
  assert.notEqual(start, -1, `${name} is present`);
  assert.notEqual(end, -1, `${name} has a bounded body`);
  return source.slice(start, end);
}

function shadowRenderer() {
  const render = body("renderUeiShadowProviderSummary", "function renderScreenUnderstandingPreview");
  const elements = {
    learningDraftUeiShadowProviderSummary: { hidden: true },
    learningDraftUeiShadowProviderSummaryBody: { innerHTML: "" },
  };
  const context = { $: (id) => elements[id] || null, escapeHtml: (value) => String(value) };
  vm.createContext(context);
  vm.runInContext(`${render}\nthis.render = renderUeiShadowProviderSummary;`, context);
  return { elements, render: context.render };
}

test("UEI Shadow provider subsection whitelists compact non-authorizing summary fields", () => {
  const render = body("renderUeiShadowProviderSummary", "function renderScreenUnderstandingPreview");
  assert.match(html, /id="learningDraftUeiShadowProviderSummary"/);
  assert.match(render, /display_only/);
  assert.match(render, /action_candidates/);
  assert.doesNotMatch(render, /source_bbox|safe_text|opaque_attributes|coordinate_transform_ref|result_ref/);
  const legacyStart = html.indexOf('id="learningDraftProviderSummary"');
  const shadowStart = html.indexOf('id="learningDraftUeiShadowProviderSummary"');
  assert.ok(legacyStart !== -1 && shadowStart !== -1 && shadowStart > legacyStart);
  assert.doesNotMatch(html.slice(legacyStart, shadowStart), /learningDraftUeiShadowProviderSummary/);
});

test("UEI Shadow subsection clears with review state and stale loads cannot render", () => {
  const clear = body("clearLearningDraftReviewDisplay", "function renderLearningCorrectionMemoryRegistry");
  const load = body("loadLearningDraftReview", "async function saveLearningDraftReview");
  assert.match(clear, /renderUeiShadowProviderSummary\(null\)/);
  assert.match(load, /loadRequestToken !== learningDraftReviewLoadRequestToken/);
  assert.match(load, /uei_shadow_provider_summary/);
  const setter = body("setLearningDraftReviewSourcePath", "async function loadLearningDraftFreshnessDemo");
  assert.match(setter, /invalidateLearningDraftReviewSource\(\)/);
  assert.match(source, /on\("learningDraftReviewSourcePath", "input", invalidateLearningDraftReviewSource\)/);
});

test("manual source input invalidates the previous summary and any in-flight load", () => {
  const invalidate = body("invalidateLearningDraftReviewSource", "function setLearningDraftReviewSourcePath");
  const context = {};
  vm.createContext(context);
  vm.runInContext(`
    let learningDraftReviewLoadRequestToken = 4;
    let clearedReason = "";
    function clearLearningDraftReviewDisplay(reason) { clearedReason = reason; }
    ${invalidate}
    invalidateLearningDraftReviewSource();
    this.observed = { token: learningDraftReviewLoadRequestToken, clearedReason };
  `, context);
  assert.deepEqual(JSON.parse(JSON.stringify(context.observed)), {
    token: 5,
    clearedReason: "source changed",
  });
});

test("UEI Shadow renderer displays only compact review facts", () => {
  const { elements, render } = shadowRenderer();
  render({
    status: "success", provider_id: "local.runtime/omniparser", profile_id: "local.runtime/omniparser/shadow-v2",
    provider_version: "v2.0.1", item_count: 2, capture_match_status: "historical", immutable_identity: "sha256:abcdef",
    registration_resolution: "resolved", manifest_resolution: "resolved", redaction: { redacted_item_count: 0, redacted_field_count: 0 },
    display_only: true, review_only: true, execution_authorized: false, action_candidates: [],
    safe_text: "must never render", source_bbox: [1, 2, 3, 4],
  });
  assert.equal(elements.learningDraftUeiShadowProviderSummary.hidden, false);
  assert.match(elements.learningDraftUeiShadowProviderSummaryBody.innerHTML, /authorized=false/);
  assert.doesNotMatch(elements.learningDraftUeiShadowProviderSummaryBody.innerHTML, /must never render|source_bbox|<button/i);
});
