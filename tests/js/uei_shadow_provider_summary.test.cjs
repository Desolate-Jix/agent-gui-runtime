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

function asyncBody(name, next) {
  const start = source.indexOf(`async function ${name}`);
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
  assert.match(setter, /invalidateLearningDraftReviewSource\(options\)/);
  assert.match(source, /on\("learningDraftReviewSourcePath", "input", invalidateLearningDraftReviewSource\)/);
});

test("manual source input invalidates the previous summary and any in-flight load", () => {
  const invalidate = body("invalidateLearningDraftReviewSource", "function setLearningDraftReviewSourcePath");
  const context = {};
  vm.createContext(context);
  vm.runInContext(`
    let learningDraftReviewLoadRequestToken = 4;
    let aborted = false;
    let learningDraftReviewLoadAbortController = {
      signal: { aborted: false },
      abort() { aborted = true; this.signal.aborted = true; },
    };
    let clearedReason = "";
    function clearLearningDraftReviewDisplay(reason) { clearedReason = reason; }
    ${invalidate}
    invalidateLearningDraftReviewSource();
    this.observed = { token: learningDraftReviewLoadRequestToken, clearedReason, aborted };
  `, context);
  assert.deepEqual(JSON.parse(JSON.stringify(context.observed)), {
    token: 5,
    clearedReason: "source changed",
    aborted: true,
  });
});

test("explicit draft load aborts deferred auto-load and waits for request-key cleanup", async () => {
  const apiSource = asyncBody("api", "function requestTimeoutSeconds");
  const sourcePath = body("learningDraftReviewSourcePath", "function invalidateLearningDraftReviewSource");
  const sourceInvalidation = body("invalidateLearningDraftReviewSource", "async function loadLearningDraftFreshnessDemo");
  const load = asyncBody("loadLearningDraftReview", "async function saveLearningDraftReview");
  const sourceInput = { value: "artifacts/boot-auto.json" };
  const renders = [];
  const sandbox = {
    AbortController,
    AbortSignal,
    DOMException,
    console,
    sourceInput,
    setTimeout,
    clearTimeout,
    window: { setTimeout, clearTimeout },
  };
  sandbox.globalThis = sandbox;
  sandbox.__renders = renders;
  vm.createContext(sandbox);
  vm.runInContext(`
    let pendingRequests = new Set();
    let learningDraftReview = null;
    let learningDraftProviderSummary = null;
    let learningDraftReviewLoadPromise = null;
    let learningDraftReviewLoadSourcePath = "";
    let learningDraftReviewLoadRequestToken = 0;
    let learningDraftReviewLoadActiveToken = 0;
    let learningDraftReviewLoadAbortController = null;
    let learningDraftReviewBboxEdits = { regions: {}, actions: {} };
    const requests = [];
    const renders = globalThis.__renders;
    const $ = (id) => id === "learningDraftReviewSourcePath" ? sourceInput : null;
    const t = (value) => value;
    const baseUrl = () => "http://panel.test";
    const requestTimeoutSeconds = () => 30;
    const setStatus = () => {};
    const statusTextForResponse = () => "ok";
    const renderResponse = () => {};
    const clearLearningDraftReviewDisplay = () => { learningDraftReview = null; };
    const resetLearningDraftEditorState = () => {};
    const renderLearningDraftReview = (review) => renders.push(review.source.source_path);
    const fetch = (_url, request) => {
      const source = JSON.parse(request.body).source_path;
      let resolveFetch;
      let rejectFetch;
      const promise = new Promise((resolve, reject) => {
        resolveFetch = resolve;
        rejectFetch = reject;
      });
      const record = {
        source,
        signal: request.signal,
        resolve(data) {
          resolveFetch({ ok: true, text: async () => JSON.stringify({ success: true, data }) });
        },
      };
      request.signal.addEventListener("abort", () => {
        rejectFetch(new DOMException("aborted", "AbortError"));
      }, { once: true });
      requests.push(record);
      return promise;
    };
    ${apiSource}
    ${sourcePath}
    ${sourceInvalidation}
    ${load}
    globalThis.loadDraft = loadLearningDraftReview;
    globalThis.invalidateDraft = invalidateLearningDraftReviewSource;
    globalThis.requests = requests;
    globalThis.snapshot = () => ({
      pendingRequestCount: pendingRequests.size,
      promise: learningDraftReviewLoadPromise,
      sourcePath: learningDraftReviewLoadSourcePath,
      controller: learningDraftReviewLoadAbortController,
      activeToken: learningDraftReviewLoadActiveToken,
      renderedSource: learningDraftReview?.source?.source_path || "",
    });
  `, sandbox);

  const bootLoad = sandbox.loadDraft({ skipResponse: true });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(sandbox.requests.length, 1);
  sandbox.sourceInput.value = "artifacts/user-explicit.json";
  sandbox.invalidateDraft();
  const explicitLoad = sandbox.loadDraft({ skipResponse: true, supersedePendingLoad: true });
  try {
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(sandbox.requests[0].signal.aborted, true);
    assert.equal(sandbox.requests.length, 2, "new POST starts after the aborted request releases its workflowStep key");
    assert.equal(sandbox.requests[1].source, "artifacts/user-explicit.json");
    sandbox.requests[1].resolve({
      source: { source_path: "artifacts/user-explicit.json" },
      draft: { regions: [], action_templates: [] },
    });
    assert.equal(await bootLoad, null);
    assert.equal((await explicitLoad).source.source_path, "artifacts/user-explicit.json");
  } finally {
    if (!sandbox.requests[0].signal.aborted) {
      sandbox.requests[0].resolve({
        source: { source_path: "artifacts/boot-auto.json" },
        draft: { regions: [], action_templates: [] },
      });
    }
    await Promise.allSettled([bootLoad, explicitLoad]);
  }

  assert.deepEqual(renders, ["artifacts/user-explicit.json"]);
  assert.deepEqual(JSON.parse(JSON.stringify(sandbox.snapshot())), {
    pendingRequestCount: 0,
    promise: null,
    sourcePath: "",
    controller: null,
    activeToken: 0,
    renderedSource: "artifacts/user-explicit.json",
  });
});

test("same-source supersede marks the old generation stale before abort can race with success", async () => {
  const sourcePath = body("learningDraftReviewSourcePath", "function invalidateLearningDraftReviewSource");
  const load = asyncBody("loadLearningDraftReview", "async function saveLearningDraftReview");
  const sourceInput = { value: "artifacts/same-source.json" };
  const renders = [];
  const sandbox = { AbortController, console, sourceInput, renders };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(`
    let learningDraftReview = null;
    let learningDraftProviderSummary = null;
    let learningDraftReviewLoadPromise = null;
    let learningDraftReviewLoadSourcePath = "";
    let learningDraftReviewLoadRequestToken = 0;
    let learningDraftReviewLoadActiveToken = 0;
    let learningDraftReviewLoadAbortController = null;
    let learningDraftReviewBboxEdits = { regions: {}, actions: {} };
    let requestKeyBusy = false;
    let duplicateRequestCount = 0;
    const requests = [];
    const $ = (id) => id === "learningDraftReviewSourcePath" ? sourceInput : null;
    const clearLearningDraftReviewDisplay = () => { learningDraftReview = null; };
    const resetLearningDraftEditorState = () => {};
    const renderLearningDraftReview = (review) => renders.push(review.source.source_path);
    const renderResponse = () => {};
    const api = async (_method, _path, payload, options) => {
      if (requestKeyBusy) {
        duplicateRequestCount += 1;
        return { success: false, message: "request_already_running" };
      }
      requestKeyBusy = true;
      let resolveRequest;
      const response = new Promise((resolve) => { resolveRequest = resolve; });
      const record = {
        source: payload.source_path,
        signal: options.signal,
        resolve(source) {
          resolveRequest({
            success: true,
            data: { source: { source_path: source }, draft: { regions: [], action_templates: [] } },
          });
        },
      };
      options.signal.addEventListener("abort", () => {
        if (requests.length === 1) record.resolve("artifacts/old-race-winner.json");
      }, { once: true });
      requests.push(record);
      const result = await response;
      requestKeyBusy = false;
      return result;
    };
    ${sourcePath}
    ${load}
    globalThis.loadDraft = loadLearningDraftReview;
    globalThis.requests = requests;
    globalThis.snapshot = () => ({
      promise: learningDraftReviewLoadPromise,
      controller: learningDraftReviewLoadAbortController,
      activeToken: learningDraftReviewLoadActiveToken,
      duplicateRequestCount,
      renderedSource: learningDraftReview?.source?.source_path || "",
    });
  `, sandbox);

  const autoLoad = sandbox.loadDraft({ skipResponse: true });
  await new Promise((resolve) => setImmediate(resolve));
  const explicitLoad = sandbox.loadDraft({ skipResponse: true, supersedePendingLoad: true });
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(sandbox.requests[0].signal.aborted, true);
  assert.equal(sandbox.requests.length, 2);
  sandbox.requests[1].resolve("artifacts/same-source.json");

  assert.equal(await autoLoad, null);
  assert.equal((await explicitLoad).source.source_path, "artifacts/same-source.json");
  assert.deepEqual(renders, ["artifacts/same-source.json"]);
  assert.deepEqual(JSON.parse(JSON.stringify(sandbox.snapshot())), {
    promise: null,
    controller: null,
    activeToken: 0,
    duplicateRequestCount: 0,
    renderedSource: "artifacts/same-source.json",
  });
});

test("draft Load button passes explicit supersede options instead of the click Event", () => {
  const registration = source.match(
    /on\("learningDraftReviewLoadBtn",\s*"click",\s*[^;]+\);/,
  )?.[0];
  assert.ok(registration);
  const sandbox = {
    observed: null,
    loadLearningDraftReview: (options) => { sandbox.observed = options; },
    on: (_id, _event, handler) => { sandbox.handler = handler; },
  };
  vm.runInNewContext(`${registration};`, sandbox);
  sandbox.handler({ type: "click", currentTarget: {} });
  assert.deepEqual(JSON.parse(JSON.stringify(sandbox.observed)), {
    supersedePendingLoad: true,
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
