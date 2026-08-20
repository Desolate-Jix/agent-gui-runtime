const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const panelPath = path.join(__dirname, "../../app/web_panel/panel.js");
const htmlPath = path.join(__dirname, "../../app/web_panel/index.html");
function panelV2Source() {
  const source = fs.readFileSync(panelPath, "utf8");
  const start = source.indexOf("function handleInterfaceWorkflowEditorMutation");
  const end = source.indexOf("function currentInterfaceWorkflowOperation", start);
  assert.notEqual(start, -1, "v2 panel binding helper must exist");
  assert.notEqual(end, -1, "v2 panel helper boundary must exist");
  return source.slice(start, end);
}
function element(value = "") { return { value, textContent: "", disabled: false, hidden: false, dataset: {}, classList: { toggle() {} } }; }
function loadHarness({ apiResult = {} } = {}) {
  const elements = {
    interfaceWorkflowLibrarySelect: Object.assign(element("workflow_a"), { selectedOptions: [{ dataset: { applicationIdentityKey: "web:seek.com" } }] }),
    interfaceWorkflowCompileV2Btn: element(), interfaceWorkflowPublishV2Btn: element(), interfaceWorkflowReplayPreviewV2Btn: element(),
    interfaceWorkflowAssetV2Status: element(), interfaceWorkflowAssetV2Hash: element(), interfaceWorkflowAssetV2BlockedReasons: element(), interfaceWorkflowReplayObservationV2: element(),
  };
  const calls = [];
  const sandbox = { globalThis: null, interfaceWorkflowAssetV2State: null, interfaceWorkflowAssetV2Binding: { key: "", generation: 0, loaded: false }, interfaceWorkflowAssetV2Pending: { compile: false, publish: false, preview: false }, interfaceWorkflowAssetV2LastResponse: null, interfaceWorkflowHasUnsavedChanges: false,
    interfaceWorkflowLoadGuard: { begin() { return 1; } },
    interfaceWorkflowLibraryRegistry: { workflows: { workflow_a: { source_asset_sha256: "a".repeat(64) } } },
    $: (id) => elements[id] || null,
    api: async (method, route, payload) => { calls.push({ method, route, payload }); return typeof apiResult === "function" ? apiResult(method, route, payload) : apiResult; }, renderResponse() {},
  };
  sandbox.globalThis = sandbox;
  vm.runInNewContext(`function markInterfaceWorkflowUnsaved() { interfaceWorkflowHasUnsavedChanges = true; invalidateInterfaceWorkflowAssetV2Binding(); } ${panelV2Source()}; globalThis.harness = { reset: resetInterfaceWorkflowAssetV2State, render: renderInterfaceWorkflowAssetV2State, compile: compileReviewedWorkflowAssetV2, publish: publishReviewedWorkflowAssetV2, preview: previewReviewedWorkflowReplayV2, state: () => interfaceWorkflowAssetV2State, unsaved: (value) => { interfaceWorkflowHasUnsavedChanges = value; }, loaded: () => completeInterfaceWorkflowAssetV2Load(interfaceWorkflowAssetV2BindingCandidate().key), selected: handleInterfaceWorkflowLibrarySelectionChanged, beginLoad: beginInterfaceWorkflowAssetV2Load, completeLoad: (key) => completeInterfaceWorkflowAssetV2Load(key), bindingKey: () => interfaceWorkflowAssetV2BindingCandidate()?.key || "", editorMutation: handleInterfaceWorkflowEditorMutation, operationSelection: () => {}, dirty: () => interfaceWorkflowHasUnsavedChanges, clean: () => { interfaceWorkflowHasUnsavedChanges = false; } };`, sandbox);
  return { harness: sandbox.harness, elements, calls };
}
test("v2 controls and explicit observation input are visible in the workflow library", () => {
  const html = fs.readFileSync(htmlPath, "utf8");
  for (const id of ["interfaceWorkflowCompileV2Btn", "interfaceWorkflowPublishV2Btn", "interfaceWorkflowReplayPreviewV2Btn", "interfaceWorkflowAssetV2Status", "interfaceWorkflowAssetV2Hash", "interfaceWorkflowAssetV2BlockedReasons", "interfaceWorkflowReplayObservationV2"]) assert.match(html, new RegExp(`id=["']${id}["']`));
  assert.match(html, /只读预览/);
});
test("compile sends only registry-derived identity workflow and source hash", async () => {
  const { harness, calls } = loadHarness({ apiResult: { success: true, data: { result: { status: "compiled", asset: { asset_id: "asset_a", content_sha256: "b".repeat(64) } }, registry_revision: 3 } } });
  harness.loaded();
  await harness.compile();
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{ method: "POST", route: "/panel/compile_reviewed_workflow_asset", payload: { application_identity_key: "web:seek.com", workflow_id: "workflow_a", expected_source_workflow_sha256: "a".repeat(64) } }]);
  assert.equal(harness.state().compile.registry_revision, 3);
});
test("publish forwards compile registry revision and never accepts a client asset", async () => {
  const { harness, calls } = loadHarness({ apiResult: { success: true, data: { result: { status: "compiled", asset: { asset_id: "asset_a", content_sha256: "b".repeat(64) } }, registry_revision: 4 } } });
  harness.loaded(); await harness.compile(); await harness.publish();
  assert.deepEqual(JSON.parse(JSON.stringify(calls[1])), { method: "POST", route: "/panel/publish_reviewed_workflow_asset", payload: { application_identity_key: "web:seek.com", workflow_id: "workflow_a", expected_source_workflow_sha256: "a".repeat(64), expected_registry_revision: 4 } });
  assert.equal(Object.hasOwn(calls[1].payload, "asset"), false);
});
test("preview blocks malformed or missing observation locally without capture or action calls", async () => {
  const { harness, elements, calls } = loadHarness(); harness.loaded(); harness.reset({ asset_id: "asset_a", content_sha256: "b".repeat(64), published: true });
  await harness.preview(); elements.interfaceWorkflowReplayObservationV2.value = "not-json"; await harness.preview();
  assert.equal(calls.length, 0); assert.match(elements.interfaceWorkflowAssetV2Status.textContent, /JSON/);
});
test("preview renders non-authorizing backend flags and blocked reasons", async () => {
  const { harness, elements, calls } = loadHarness({ apiResult: { success: true, data: { mode: "read_only_preview", would_call_action_api: false, execution_authorized: false, blocked_reason_codes: ["no_verified_transition"] } } });
  harness.loaded(); harness.reset({ asset_id: "asset_a", content_sha256: "b".repeat(64), published: true }); elements.interfaceWorkflowReplayObservationV2.value = "{}"; await harness.preview();
  assert.equal(calls[0].route, "/panel/preview_reviewed_workflow_replay"); assert.deepEqual(JSON.parse(JSON.stringify(calls[0].payload)), { asset_id: "asset_a", expected_content_sha256: "b".repeat(64), current_observation: {} });
  assert.match(elements.interfaceWorkflowAssetV2Status.textContent, /不构成执行授权|not authorization/); assert.match(elements.interfaceWorkflowAssetV2BlockedReasons.textContent, /no_verified_transition/);
});
test("unsaved edits and workflow reset invalidate v2 state", () => {
  const { harness, elements } = loadHarness(); harness.reset({ asset_id: "asset_a", content_sha256: "b".repeat(64), published: true }); harness.unsaved(true); harness.render();
  assert.equal(harness.state(), null); assert.equal(elements.interfaceWorkflowPublishV2Btn.disabled, true); assert.equal(elements.interfaceWorkflowReplayPreviewV2Btn.disabled, true);
});
test("compile requires the exact successfully loaded workflow binding", async () => {
  const { harness, calls, elements } = loadHarness();
  await harness.compile();
  assert.equal(calls.length, 0);
  harness.loaded();
  await harness.compile();
  assert.equal(calls.length, 1);
  elements.interfaceWorkflowLibrarySelect.value = "workflow_b";
  elements.interfaceWorkflowLibrarySelect.selectedOptions = [{ dataset: { applicationIdentityKey: "web:other.example" } }];
  harness.selected();
  await harness.publish();
  assert.equal(calls.length, 1, "a compile for A must never publish after selecting B");
});

test("deferred compile and double click cannot resurrect state or duplicate the API call", async () => {
  let resolveCompile;
  const pending = new Promise((resolve) => { resolveCompile = resolve; });
  const { harness, calls } = loadHarness({ apiResult: () => pending });
  harness.loaded();
  const first = harness.compile();
  const second = harness.compile();
  assert.equal(calls.length, 1);
  harness.reset();
  resolveCompile({ success: true, data: { result: { status: "compiled", asset: { asset_id: "old", content_sha256: "c".repeat(64) } }, registry_revision: 1 } });
  await Promise.all([first, second]);
  assert.equal(harness.state(), null);
});

test("real backend blocked response shapes are deduplicated and shown", () => {
  const { harness, elements } = loadHarness();
  harness.render({ success: false, error: { code: "reviewed_workflow_preview_unresolved" }, data: { state_resolution: { failure_code: "no_matching_state" }, blocked_reason_codes: ["no_matching_state"], result: { blocked_reasons: [{ code: "no_matching_state" }] } } });
  assert.equal(elements.interfaceWorkflowAssetV2BlockedReasons.textContent, "reviewed_workflow_preview_unresolved, no_matching_state");
  harness.render({ success: false, error: { code: "reviewed_workflow_preview_hash_mismatch" }, data: { compile_result: { blocked_reasons: [{ code: "registry_revision_mismatch" }] } } });
  assert.match(elements.interfaceWorkflowAssetV2BlockedReasons.textContent, /reviewed_workflow_preview_hash_mismatch/);
  assert.match(elements.interfaceWorkflowAssetV2BlockedReasons.textContent, /registry_revision_mismatch/);
});

test("editor mutation invalidates v2 state without treating operation selection as an edit", () => {
  const { harness } = loadHarness();
  harness.loaded();
  harness.reset({ asset_id: "asset_a", content_sha256: "b".repeat(64), published: true });
  harness.editorMutation();
  assert.equal(harness.state(), null);
  assert.equal(harness.dirty(), true);
  harness.clean();
  harness.reset({ asset_id: "asset_a", content_sha256: "b".repeat(64), published: true });
  harness.operationSelection();
  assert.equal(harness.dirty(), false);
  assert.equal(harness.state().published, true);
});
test("one global v2 busy lock blocks cross-operation calls", async () => {
  let resolveRequest;
  const pending = new Promise((resolve) => { resolveRequest = resolve; });
  const { harness, calls, elements } = loadHarness({ apiResult: () => pending });
  harness.loaded();
  const compile = harness.compile();
  await harness.publish();
  await harness.preview();
  assert.equal(calls.length, 1);
  assert.equal(elements.interfaceWorkflowCompileV2Btn.disabled, true);
  assert.equal(elements.interfaceWorkflowPublishV2Btn.disabled, true);
  assert.equal(elements.interfaceWorkflowReplayPreviewV2Btn.disabled, true);
  resolveRequest({ success: false, error: { code: "reviewed_workflow_compile_blocked" }, data: { result: { blocked_reasons: [{ code: "unreviewed_node" }] } } });
  await compile;
  assert.match(elements.interfaceWorkflowAssetV2BlockedReasons.textContent, /reviewed_workflow_compile_blocked/);
  assert.match(elements.interfaceWorkflowAssetV2BlockedReasons.textContent, /unreviewed_node/);
});

test("actual handler retains backend preview and publish blocked codes after pending cleanup", async () => {
  const responses = [
    { success: true, data: { result: { status: "compiled", asset: { asset_id: "asset_a", content_sha256: "b".repeat(64) } }, registry_revision: 2 } },
    { success: false, error: { code: "reviewed_workflow_publish_failed" }, data: { compile_result: { blocked_reasons: [{ code: "registry_revision_mismatch" }] } } },
  ];
  const { harness, elements } = loadHarness({ apiResult: () => responses.shift() });
  harness.loaded(); await harness.compile(); await harness.publish();
  assert.match(elements.interfaceWorkflowAssetV2BlockedReasons.textContent, /reviewed_workflow_publish_failed/);
  assert.match(elements.interfaceWorkflowAssetV2BlockedReasons.textContent, /registry_revision_mismatch/);
});

test("panel source binds content descriptor mutations and cancels stale load selection", () => {
  const source = fs.readFileSync(panelPath, "utf8");
  for (const id of ["interfaceWorkflowContentBehavior", "interfaceWorkflowContentAgentUsage", "interfaceWorkflowContentReadPolicy", "interfaceWorkflowContentDescription"]) assert.match(source, new RegExp(`\\["${id}",`));
  assert.match(source, /function handleInterfaceWorkflowLibrarySelectionChanged\(\) \{\s*interfaceWorkflowLoadGuard\.begin\(\);/);
  assert.match(source, /const expectedBinding = interfaceWorkflowAssetV2BindingCandidate\(\);/);
  assert.match(source, /completeInterfaceWorkflowAssetV2Load\(expectedBinding\.key\)/);
});
test("deferred A load cannot complete after selection switches to B", () => {
  const { harness, elements } = loadHarness();
  harness.beginLoad();
  const aKey = harness.bindingKey();
  elements.interfaceWorkflowLibrarySelect.value = "workflow_b";
  elements.interfaceWorkflowLibrarySelect.selectedOptions = [{ dataset: { applicationIdentityKey: "web:other.example" } }];
  harness.selected();
  assert.equal(harness.completeLoad(aKey), false);
  assert.equal(harness.state(), null);
});