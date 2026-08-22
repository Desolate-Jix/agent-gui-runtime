const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync("app/web_panel/panel.js", "utf8");

function body(name, next) {
  const start = source.indexOf(`function ${name}`);
  const end = source.indexOf(next, start);
  assert.notEqual(start, -1, `${name} is present`);
  assert.notEqual(end, -1, `${name} has a bounded body`);
  return source.slice(start, end);
}

function renderCanonical(summary) {
  const render = body("renderUeiShadowProviderSummary", "function renderScreenUnderstandingPreview");
  const elements = {
    learningDraftUeiShadowProviderSummary: { hidden: true },
    learningDraftUeiShadowProviderSummaryBody: { innerHTML: "" },
  };
  const context = { $: (id) => elements[id] || null, escapeHtml: (value) => String(value) };
  vm.createContext(context);
  vm.runInContext(`${render}\nthis.render = renderUeiShadowProviderSummary;`, context);
  context.render(summary);
  return elements.learningDraftUeiShadowProviderSummaryBody.innerHTML;
}

function summary(providerId, profileId) {
  return {
    status: "success",
    provider_id: providerId,
    profile_id: profileId,
    provider_version: "recorded-v1",
    item_count: 1,
    capture_match_status: "match",
    immutable_identity: "sha256:abcdef123456",
    registration_resolution: "resolved",
    manifest_resolution: "resolved",
    redaction: { redacted_item_count: 0, redacted_field_count: 0, secret_detected: false },
    display_only: true,
    review_only: true,
    execution_authorized: false,
    action_candidates: [],
  };
}

test("Built-in and Omni provenance render through one provider-neutral canonical model", () => {
  const canonicalRenderer = body("renderUeiShadowProviderSummary", "function renderScreenUnderstandingPreview");
  assert.doesNotMatch(canonicalRenderer, /local\.runtime\/ocr|windows[_-]uia|omniparser/i);
  const builtIn = renderCanonical(summary("local.runtime/ocr", "local.runtime/ocr/static"));
  const omni = renderCanonical(summary("local.runtime/omniparser", "local.runtime/omniparser/shadow-v2"));
  const normalizeProvenance = (html) => html
    .replace(/local\.runtime\/(?:ocr|omniparser)/g, "PROVIDER")
    .replace(/PROVIDER\/(?:static|shadow-v2)/g, "PROFILE");
  assert.equal(normalizeProvenance(builtIn), normalizeProvenance(omni));
  assert.match(builtIn, /authorized=false/);
  assert.match(omni, /authorized=false/);
});

test("canonical UEI evidence suppresses the legacy provider-specific Review model", () => {
  const reviewRenderer = body("renderLearningDraftReview", "function clearLearningDraftReviewDisplay");
  const calls = { legacy: [], canonical: [] };
  const context = {
    document: { body: { dataset: {} } },
    learningDraftReview: null,
    learningDraftOwnershipConflicts: [],
    learningDraftProviderSummary: { source: "global-legacy" },
    $: () => null,
    learningDraftSourceImagePath: () => "",
    bindLearningDraftPreviewButtons: () => {},
    learningDraftManualBboxEditSummary: () => ({}),
    learningDraftSourceFreshnessSummary: () => ({}),
    renderLearningDraftProviderSummary: (value) => calls.legacy.push(value),
    renderUeiShadowProviderSummary: (value) => calls.canonical.push(value),
    renderScreenUnderstandingPreview: () => {},
    renderLearningDraftScreenshotPanel: () => {},
    renderLearningDraftManualEditPanel: () => {},
    renderLearningDraftPathPreview: () => {},
  };
  vm.createContext(context);
  vm.runInContext(`${reviewRenderer}\nthis.render = renderLearningDraftReview;`, context);

  const canonical = { contract_version: "uei_shadow_provider_summary_v1" };
  context.render({
    draft: { page_details: { provider_summary: { source: "draft-legacy" } } },
    provider_summary: { source: "review-legacy" },
    uei_shadow_provider_summary: canonical,
  });
  assert.equal(calls.legacy.length, 1);
  assert.equal(calls.legacy[0], null);
  assert.equal(calls.canonical.length, 1);
  assert.equal(calls.canonical[0], canonical);

  const legacy = { source: "review-legacy" };
  context.render({ draft: { page_details: {} }, provider_summary: legacy });
  assert.equal(calls.legacy.length, 2);
  assert.equal(calls.legacy[1], legacy);
  assert.equal(calls.canonical.length, 2);
  assert.equal(calls.canonical[1], undefined);
});
