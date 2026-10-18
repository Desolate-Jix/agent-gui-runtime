const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "../..");
const source = fs.readFileSync(path.join(root, "app/web_panel/panel.js"), "utf8");
const html = fs.readFileSync(path.join(root, "app/web_panel/index.html"), "utf8");

test("primary navigation exposes learning, workflow library and real Agent run without dropping advanced tools", () => {
  for (const [id, stage] of [["agentModeLearnBtn", "learn_interface"], ["workflowLibraryBtn", "workflow_library"], ["agentModeExecuteBtn", "agent_runtime"]]) {
    assert.match(html, new RegExp(`<button[^>]*id="${id}"[^>]*data-stage="${stage}"`));
  }
  assert.match(html, /<details[^>]*id="advancedNavigation"[^>]*>/);
  assert.doesNotMatch(html.match(/<details[^>]*id="advancedNavigation"[^>]*>/)[0], /\bopen\b/);
  for (const stage of ["open_bind", "capture", "execute_actions", "execute_locate", "execute", "input", "template_display", "execute_task_run"]) {
    assert.ok(html.includes(`data-stage="${stage}"`), stage);
  }
  assert.match(html, /id="diagnosticsBtn"[^>]*data-stage="trace"/);
});

test("library reuses reviewed editor and run registers only Agent APIs, not PathGraph harness", () => {
  const start = source.indexOf("const PAGE_REGISTRY =");
  const end = source.indexOf("\nlet backendHybridRolloutStatus", start);
  const context = vm.createContext({});
  vm.runInContext(source.slice(start, end) + "\nglobalThis.registry = PAGE_REGISTRY;", context);
  assert.equal(context.registry.workflow_library.page, "learn_replay");
  assert.equal(context.registry.workflow_library.learnReplaySubview, "draft");
  assert.equal(context.registry.workflow_library.interfaceAssetPage, "workflow");
  assert.equal(context.registry.agent_runtime.page, "agent_runtime");
  assert.equal(context.registry.agent_runtime.showPipeline, false);
  assert.match(context.registry.agent_runtime.api, /\/runtime\/agent\/session\/start/);
  assert.doesNotMatch(context.registry.agent_runtime.api, /\/execute\/step/);
  assert.ok(html.indexOf("/panel/assets/agent_runtime_panel.js") < html.indexOf("/panel/assets/panel.js"));
  assert.match(source, /initializeAgentRuntimePanel\(\)/);
});

test("run navigation never starts a session or sends an intent", () => {
  const start = source.indexOf("function showStage(stage)");
  const end = source.indexOf("\nfunction updatePageMeta", start);
  const block = source.slice(start, end);
  assert.ok(start > 0 && end > start);
  assert.doesNotMatch(block, /agentRuntimePanel\.(start|requestStep|decide)|\/runtime\/agent|initializeAgentRuntimePanel/);
  assert.match(block, /meta\.interfaceAssetPage/);
  assert.match(block, /page === "agent_runtime"/);
});

test("actual panel initializer mounts the exported controller once without calling Agent APIs", () => {
  const nodes = {};
  const context = vm.createContext({
    AgentRuntimePanel: require("../../app/web_panel/agent_runtime_panel.js"),
    document: { getElementById: (id) => nodes[id] || null },
    $: (id) => nodes[id] || null,
    api: () => { throw new Error("initializer must not send requests"); },
  });
  const start = source.indexOf("let agentRuntimePanel = null;");
  const end = source.indexOf("\nfunction bindEvents", start);
  vm.runInContext(source.slice(start, end) + "\ninitializeAgentRuntimePanel(); initializeAgentRuntimePanel(); globalThis.phase = agentRuntimePanel.getState().phase;", context);
  assert.equal(context.phase, "idle");
  assert.match(html, /id="agentRuntimeStartBtn"[^>]*\bdisabled\b/);
});
