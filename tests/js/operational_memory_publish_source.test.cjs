const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
const indexSource = fs.readFileSync("app/web_panel/index.html", "utf8");

function memorySourceFunctions() {
  const start = panelSource.indexOf("function reviewedTemplateCandidatePathFromWorkflowView");
  const end = panelSource.indexOf("async function loadInterfaceWorkflowReview", start);
  assert.notEqual(start, -1, "reviewed candidate resolver must exist");
  assert.notEqual(end, -1, "workflow review boundary must exist");
  return panelSource.slice(start, end);
}

test("workflow memory handoff selects the reviewed candidate instead of the node review source", () => {
  const elements = {
    learningMemoryInterfaceId: { value: "" },
    learningMemoryGoal: { value: "" },
    learningMemoryReviewedCandidatePath: { value: "stale.json" },
    learningMemoryStatus: { textContent: "" },
    learningOperationalMemoryPanel: {
      hidden: true,
      scrollIntoView() {},
    },
  };
  const context = {
    console,
    $: (id) => elements[id] || null,
    interfaceWorkflowReviewState: {
      graph: () => ({
        workflow: {
          goal: "Open documentation",
          application_identity: { canonical_domain: "example.test" },
        },
      }),
      current: () => ({
        node: {
          surface_type: "detail",
          review_status: "human_approved",
          reviewed_by_human: true,
          editable_review_source_path: "artifacts/workflows/node-review-sources/interface_detail.json",
          source_paths: [
            "artifacts/workflows/node-review-sources/interface_detail.json",
            "artifacts/learning-draft-review/detail_old/reviewed_template_candidate.json",
          ],
          manual_revision: {
            source_path: "artifacts/learning-draft-review/detail_123/reviewed_template_candidate.json",
          },
        },
      }),
    },
  };
  vm.createContext(context);
  vm.runInContext(memorySourceFunctions(), context);

  context.openInterfaceWorkflowMemoryVerification();

  assert.equal(
    elements.learningMemoryReviewedCandidatePath.value,
    "artifacts/learning-draft-review/detail_123/reviewed_template_candidate.json",
  );
  assert.doesNotMatch(elements.learningMemoryReviewedCandidatePath.value, /node-review-sources/);
  assert.equal(elements.learningOperationalMemoryPanel.hidden, false);
});

test("workflow memory handoff clears a stale publish path when the node has no reviewed candidate", () => {
  const elements = {
    learningMemoryInterfaceId: { value: "" },
    learningMemoryGoal: { value: "" },
    learningMemoryReviewedCandidatePath: { value: "artifacts/stale/reviewed_template_candidate.json" },
    learningMemoryStatus: { textContent: "" },
    learningOperationalMemoryPanel: { hidden: true, scrollIntoView() {} },
  };
  const context = {
    console,
    $: (id) => elements[id] || null,
    interfaceWorkflowReviewState: {
      graph: () => ({ workflow: { goal: "Review", application_identity: {} } }),
      current: () => ({
        node: {
          surface_type: "detail",
          editable_review_source_path: "artifacts/workflows/node-review-sources/interface_detail.json",
          source_paths: ["artifacts/workflows/node-review-sources/interface_detail.json"],
        },
      }),
    },
  };
  vm.createContext(context);
  vm.runInContext(memorySourceFunctions(), context);

  context.openInterfaceWorkflowMemoryVerification();

  assert.equal(elements.learningMemoryReviewedCandidatePath.value, "");
  assert.match(elements.learningMemoryStatus.textContent, /未找到可发布的审阅候选/);
});

test("workflow memory handoff does not select lineage from an unapproved node", () => {
  const elements = {
    learningMemoryInterfaceId: { value: "" },
    learningMemoryGoal: { value: "" },
    learningMemoryReviewedCandidatePath: { value: "artifacts/stale/reviewed_template_candidate.json" },
    learningMemoryStatus: { textContent: "" },
    learningOperationalMemoryPanel: { hidden: true, scrollIntoView() {} },
  };
  const context = {
    console,
    $: (id) => elements[id] || null,
    interfaceWorkflowReviewState: {
      graph: () => ({ workflow: { goal: "Review", application_identity: {} } }),
      current: () => ({
        node: {
          surface_type: "detail",
          review_status: "needs_human_review",
          reviewed_by_human: false,
          source_paths: ["artifacts/learning-draft-review/detail_123/reviewed_template_candidate.json"],
        },
      }),
    },
  };
  vm.createContext(context);
  vm.runInContext(memorySourceFunctions(), context);

  context.openInterfaceWorkflowMemoryVerification();

  assert.equal(elements.learningMemoryReviewedCandidatePath.value, "");
  assert.match(elements.learningMemoryStatus.textContent, /未找到可发布的审阅候选/);
});

test("operational memory publish uses its explicit reviewed candidate path", async () => {
  const start = panelSource.indexOf("async function publishLearningOperationalMemory");
  const end = panelSource.indexOf("async function loadLearningOperationalMemory", start);
  const calls = [];
  const elements = {
    learningMemoryInterfaceId: { value: "example_detail" },
    learningMemoryReviewedCandidatePath: {
      value: "artifacts/learning-draft-review/detail_123/reviewed_template_candidate.json",
    },
    learningMemoryStatus: { textContent: "" },
    learningDraftReviewStatusSelect: { value: "needs_human_review" },
  };
  const context = {
    console,
    $: (id) => elements[id] || null,
    learningOperationalMemoryReviewedCandidatePath: () => elements.learningMemoryReviewedCandidatePath.value,
    learningDraftReviewSourcePath: () => "artifacts/workflows/node-review-sources/interface_detail.json",
    api: async (method, path, payload = null) => {
      calls.push({ method, path, payload });
      if (method === "GET") return { success: true, data: { registry_revision: 11 } };
      return { success: true, data: { interface_id: "example_detail" } };
    },
    loadLearningOperationalMemory: async () => {},
    renderResponse: () => {},
  };
  vm.createContext(context);
  vm.runInContext(panelSource.slice(start, end), context);

  await context.publishLearningOperationalMemory();

  assert.equal(
    calls[1].payload.source_path,
    "artifacts/learning-draft-review/detail_123/reviewed_template_candidate.json",
  );
  assert.doesNotMatch(calls[1].payload.source_path, /node-review-sources/);
});

test("operational memory publish leaves candidate approval validation to the backend contract", async () => {
  const start = panelSource.indexOf("async function publishLearningOperationalMemory");
  const end = panelSource.indexOf("async function loadLearningOperationalMemory", start);
  const calls = [];
  const elements = {
    learningMemoryInterfaceId: { value: "example_detail" },
    learningMemoryReviewedCandidatePath: {
      value: "artifacts/learning-draft-review/detail_123/reviewed_template_candidate.json",
    },
    learningMemoryStatus: { textContent: "" },
    learningDraftReviewStatusSelect: { value: "needs_human_review" },
  };
  const context = {
    console,
    $: (id) => elements[id] || null,
    learningOperationalMemoryReviewedCandidatePath: () => elements.learningMemoryReviewedCandidatePath.value,
    api: async (method, path, payload = null) => {
      calls.push({ method, path, payload });
      if (method === "GET") return { success: true, data: { registry_revision: 12 } };
      return { success: false, message: "backend rejected candidate approval contract" };
    },
    loadLearningOperationalMemory: async () => {
      throw new Error("must not load rejected memory");
    },
    renderResponse: () => {},
  };
  vm.createContext(context);
  vm.runInContext(panelSource.slice(start, end), context);

  const result = await context.publishLearningOperationalMemory();

  assert.equal(result, null);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].path, "/memory/reviewed_interfaces/registry");
  assert.equal(calls[1].path, "/memory/reviewed_interfaces/publish");
  assert.equal(elements.learningMemoryStatus.textContent, "publish_failed · backend_candidate_validation_required");
});

test("operational memory panel exposes the reviewed candidate path", () => {
  assert.match(indexSource, /id="learningMemoryReviewedCandidatePath"/);
  assert.match(indexSource, /reviewed_template_candidate\.json/);
});
