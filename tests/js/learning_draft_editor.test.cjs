const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const {
  buildLearningDraftDisplayProjection,
  clampBboxToImage,
  createLearningDraftEditorState,
  learningDraftEditorPointerMode,
  resizeBboxFromHandle,
} = require("../../app/web_panel/learning_draft_editor.js");
const {
  createInterfaceWorkflowReviewState,
} = require("../../app/web_panel/learning_workflow_review.js");

function loadSaveLearningDraftReview(overrides = {}) {
  const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
  const refreshStart = panelSource.indexOf("function interfaceWorkflowSourcePathsAfterReview");
  const refreshEnd = panelSource.indexOf("async function refreshCurrentInterfaceWorkflowEvidence", refreshStart);
  const saveStart = panelSource.indexOf("async function saveLearningDraftReview");
  const saveEnd = panelSource.indexOf("async function generatePathGraphCandidate", saveStart);
  const button = { disabled: false, textContent: "Save review" };
  const calls = [];
  const workflowState = {
    replaceReviewedNodeEvidenceBySource: (previousPath, reviewedPath) => {
      calls.push(`replace:${previousPath}->${reviewedPath}`);
      return { node: { node_id: "node1" } };
    },
    snapshot: () => {
      calls.push("snapshot");
      return {
        workflow: { workflow_id: "workflow-1" },
        nodes: [{ node_id: "node1", source_paths: ["artifacts/source.json"] }],
      };
    },
  };
  const context = {
    console,
    currentLanguage: "en-US",
    learningDraftEditorActive: true,
    learningDraftEditorSelected: { target_kind: "region", target_id: "r1" },
    learningDraftEditorWorkflowBinding: {
      authority: "workflow",
      workflow_id: "workflow-1",
      node_id: "node1",
      source_path: "artifacts/source.json",
      state: workflowState,
    },
    interfaceWorkflowDraftSourcePaths: ["artifacts/source.json"],
    $: () => button,
    learningDraftReviewSourcePath: () => "artifacts/source.json",
    learningDraftReviewPatch: () => ({ operations: [] }),
    applyLearningDraftEditorMetadataFromControls: () => calls.push("commit_controls"),
    api: async () => {
      assert.equal(button.disabled, true);
      assert.equal(button.textContent, "Saving review...");
      calls.push("save");
      return {
        success: true,
        data: { reviewed_template_candidate_path: "artifacts/reviewed.json" },
      };
    },
    setLearningPathGraphCandidatePaths: () => calls.push("candidate_paths"),
    setLearningDraftReviewSourcePath: (path) => calls.push(`source:${path}`),
    bumpPanelImageRevision: () => calls.push("image_revision"),
    loadLearningDraftReview: async () => {
      calls.push("parent_refresh");
      return { draft: {} };
    },
    interfaceWorkflowReviewState: workflowState,
    interfaceWorkflowWorkbenchState: {
      showWorkflowNode: (nodeId) => calls.push(`show:${nodeId}`),
    },
    saveInterfaceWorkflowReview: async () => {
      calls.push("workflow_save");
      return { workflow: {} };
    },
    closeImageInspector: () => calls.push("close"),
    loadLearningCorrectionMemoryRegistry: async () => calls.push("correction_memory"),
    renderResponse: (response) => calls.push(`response:${response.success}`),
    ...overrides,
  };
  vm.createContext(context);
  vm.runInContext(
    `${panelSource.slice(refreshStart, refreshEnd)}\n${panelSource.slice(saveStart, saveEnd)}`,
    context,
  );
  return { context, button, calls, workflowState };
}

test("learning draft editor clamps moved and resized boxes to the source image", () => {
  assert.deepEqual(
    clampBboxToImage({ x: 300, y: 220, w: 80, h: 50 }, 320, 240),
    { x: 240, y: 190, w: 80, h: 50 },
  );
  assert.deepEqual(
    clampBboxToImage({ x: 280, y: 210, w: 80, h: 50 }, 320, 240, { resize: true }),
    { x: 280, y: 210, w: 40, h: 30 },
  );
});

test("learning draft editor resizes from every edge and corner", () => {
  const bbox = { x: 40, y: 30, w: 100, h: 80 };

  assert.deepEqual(resizeBboxFromHandle(bbox, "e", 30, 0, 300, 200), {
    x: 40, y: 30, w: 130, h: 80,
  });
  assert.deepEqual(resizeBboxFromHandle(bbox, "w", 20, 0, 300, 200), {
    x: 60, y: 30, w: 80, h: 80,
  });
  assert.deepEqual(resizeBboxFromHandle(bbox, "n", 0, -20, 300, 200), {
    x: 40, y: 10, w: 100, h: 100,
  });
  assert.deepEqual(resizeBboxFromHandle(bbox, "sw", -20, 30, 300, 200), {
    x: 20, y: 30, w: 120, h: 110,
  });
  assert.deepEqual(resizeBboxFromHandle(bbox, "ne", 30, -50, 150, 100), {
    x: 40, y: 0, w: 110, h: 100,
  });
});

test("add mode takes pointer ownership even over an existing box", () => {
  assert.equal(learningDraftEditorPointerMode(true, "se"), "add");
  assert.equal(learningDraftEditorPointerMode(false, "nw"), "resize:nw");
  assert.equal(learningDraftEditorPointerMode(false, ""), "move");
});

test("compact projection keeps a credible parent and groups contained text fragments", () => {
  const projection = buildLearningDraftDisplayProjection([
    {
      target_kind: "region",
      target_id: "job_card_1",
      label: "Software Engineer",
      role: "job_card",
      bbox: { x: 100, y: 100, w: 360, h: 220 },
    },
    {
      target_kind: "region",
      target_id: "text_tile_job_card_1_title",
      label: "Software Engineer",
      role: "text",
      bbox: { x: 124, y: 122, w: 210, h: 28 },
    },
    {
      target_kind: "region",
      target_id: "ocr_job_card_1_company",
      label: "Example Ltd",
      role: "ocr_text",
      bbox: { x: 124, y: 160, w: 130, h: 24 },
    },
  ]);

  assert.deepEqual(
    projection.visibleItems.map((item) => item.target_id),
    ["job_card_1"],
  );
  assert.deepEqual(projection.groups[0].memberKeys, [
    "region:text_tile_job_card_1_title",
    "region:ocr_job_card_1_company",
  ]);
  assert.equal(projection.groups[0].reason, "contained_fragment");
});

test("compact projection preserves ambiguous overlaps and distinct actions", () => {
  const projection = buildLearningDraftDisplayProjection([
    {
      target_kind: "region",
      target_id: "card_1",
      role: "card",
      bbox: { x: 20, y: 20, w: 180, h: 120 },
    },
    {
      target_kind: "region",
      target_id: "text_1",
      role: "text",
      bbox: { x: 170, y: 80, w: 100, h: 30 },
    },
    {
      target_kind: "action",
      target_id: "open_detail",
      action_type: "open_detail",
      destination: { kind: "interface", target_interface_id: "detail" },
      bbox: { x: 30, y: 30, w: 140, h: 80 },
    },
    {
      target_kind: "action",
      target_id: "final_submit",
      action_type: "final_submit",
      risk_level: "dangerous",
      bbox: { x: 40, y: 40, w: 80, h: 30 },
    },
  ]);

  assert.deepEqual(
    projection.visibleItems.map((item) => item.target_id),
    ["card_1", "text_1", "open_detail", "final_submit"],
  );
  assert.deepEqual(projection.groups, []);
});

test("compact projection never hides selected or manually edited items", () => {
  const items = [
    {
      target_kind: "region",
      target_id: "button_parent",
      role: "button",
      bbox: { x: 20, y: 20, w: 140, h: 60 },
    },
    {
      target_kind: "region",
      target_id: "button_text",
      role: "text",
      bbox: { x: 40, y: 35, w: 80, h: 20 },
    },
  ];

  const selected = buildLearningDraftDisplayProjection(items, {
    selected: { target_kind: "region", target_id: "button_text" },
  });
  const protectedItem = buildLearningDraftDisplayProjection(items, {
    protectedKeys: ["region:button_text"],
  });
  const full = buildLearningDraftDisplayProjection(items, { compact: false });

  assert.equal(selected.visibleItems.length, 2);
  assert.equal(protectedItem.visibleItems.length, 2);
  assert.equal(full.visibleItems.length, 2);
  assert.deepEqual(full.groups, []);
});

test("display projection does not change exported review operations", () => {
  const editor = createLearningDraftEditorState([
    {
      target_kind: "region",
      target_id: "card_1",
      role: "card",
      bbox: { x: 20, y: 20, w: 180, h: 120 },
    },
    {
      target_kind: "region",
      target_id: "text_1",
      role: "text",
      bbox: { x: 40, y: 40, w: 80, h: 20 },
    },
  ]);
  editor.apply({
    op: "update_bbox",
    target_kind: "region",
    target_id: "card_1",
    after_bbox: { x: 22, y: 22, w: 180, h: 120 },
  });
  const before = editor.exportOperations();

  buildLearningDraftDisplayProjection(editor.listItems(), {
    protectedKeys: editor.editedKeys(),
  });

  assert.deepEqual(editor.exportOperations(), before);
  assert.deepEqual(editor.editedKeys(), ["region:card_1"]);
});

test("learning draft box editor exposes compact display controls and overlap selection", () => {
  const indexSource = fs.readFileSync("app/web_panel/index.html", "utf8");
  const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
  const cssSource = fs.readFileSync("app/web_panel/panel.css", "utf8");

  assert.match(indexSource, /id="imageInspectorCompactBoxesBtn"/);
  assert.match(panelSource, /buildLearningDraftDisplayProjection\(/);
  assert.match(panelSource, /data-editor-overlap-owner/);
  assert.match(panelSource, /data-editor-overlap-member/);
  assert.match(cssSource, /\.image-inspector-overlap-menu/);
});

test("learning draft editor supports update, undo, and redo", () => {
  const editor = createLearningDraftEditorState([
    {
      target_kind: "region",
      target_id: "r1",
      label: "Search input",
      role: "text_input",
      parent_region_id: "",
      bbox: { x: 8, y: 18, w: 100, h: 30 },
    },
  ]);

  editor.apply({
    op: "update_bbox",
    target_kind: "region",
    target_id: "r1",
    after_bbox: { x: 12, y: 22, w: 140, h: 36 },
  });
  assert.deepEqual(editor.getItem("region", "r1").bbox, { x: 12, y: 22, w: 140, h: 36 });
  assert.equal(editor.canUndo(), true);
  editor.undo();
  assert.deepEqual(editor.getItem("region", "r1").bbox, { x: 8, y: 18, w: 100, h: 30 });
  assert.equal(editor.exportOperations().length, 0);
  editor.redo();
  assert.deepEqual(editor.getItem("region", "r1").bbox, { x: 12, y: 22, w: 140, h: 36 });
  assert.deepEqual(editor.exportOperations()[0].before_bbox, { x: 8, y: 18, w: 100, h: 30 });
});

test("learning draft editor supports add, delete, role, and parent edits", () => {
  const editor = createLearningDraftEditorState([
    {
      target_kind: "region",
      target_id: "r1",
      label: "Search input",
      role: "text_input",
      parent_region_id: "",
      bbox: { x: 8, y: 18, w: 100, h: 30 },
    },
    {
      target_kind: "action",
      target_id: "a1",
      label: "Type query",
      bbox: { x: 10, y: 20, w: 80, h: 24 },
    },
  ]);

  editor.apply({
    op: "add",
    target_kind: "region",
    target_id: "r2",
    item: { label: "Results", role: "review_only", bbox: { x: 160, y: 40, w: 140, h: 160 } },
  });
  editor.apply({ op: "update_role", target_kind: "region", target_id: "r1", after_value: "input" });
  editor.apply({ op: "update_parent", target_kind: "region", target_id: "r1", after_value: "r2" });
  editor.apply({ op: "delete", target_kind: "action", target_id: "a1" });

  assert.equal(editor.getItem("region", "r2").candidate_only, true);
  assert.equal(editor.getItem("region", "r1").role, "input");
  assert.equal(editor.getItem("region", "r1").parent_region_id, "r2");
  assert.equal(editor.getItem("action", "a1"), null);
  assert.equal(editor.exportOperations().length, 4);
  editor.undo();
  assert.ok(editor.getItem("action", "a1"));
});

test("learning draft editor preserves agent-readable metadata with undo", () => {
  const editor = createLearningDraftEditorState([
    {
      target_kind: "region",
      target_id: "r1",
      label: "Unknown control",
      role: "review_only",
      bbox: { x: 8, y: 18, w: 100, h: 30 },
    },
  ]);

  editor.apply({
    op: "update_metadata",
    target_kind: "region",
    target_id: "r1",
    after_metadata: {
      label: "Search button",
      description: "Opens the application search surface.",
      semantic_action: "open_search",
      input_semantics: "none",
      destination: { kind: "interface", target_interface_id: "search_surface" },
      verification_rule: "Search input becomes visible.",
      risk_level: "normal",
      requires_confirmation: false,
    },
  });

  const updated = editor.getItem("region", "r1");
  assert.equal(updated.label, "Search button");
  assert.equal(updated.description, "Opens the application search surface.");
  assert.equal(updated.destination.target_interface_id, "search_surface");
  assert.equal(updated.artifact_is_authorization, false);
  assert.equal(updated.execute_binding_enabled, false);
  editor.undo();
  assert.equal(editor.getItem("region", "r1").label, "Unknown control");
  editor.redo();
  assert.equal(editor.getItem("region", "r1").semantic_action, "open_search");
});

test("provider-safe review region remains non-authorizing in LearningDraftEditorState", () => {
  const editor = createLearningDraftEditorState([
    {
      target_kind: "region",
      target_id: "uei_review_region_1234",
      label: "Quick Apply",
      role: "review_only",
      kind: "text",
      bbox: { x: 10, y: 20, w: 100, h: 30 },
      provider_evidence: {
        provider_id: "local.runtime/builtin-ocr",
        profile_id: "local.runtime/builtin-ocr/v1",
        provider_version: "built-in-v1",
        confidence: 0.88,
        safe_role: null,
        safe_states: [],
      },
      candidate_only: true,
      requires_human_review: true,
      review_only: true,
      grounding_eligible: false,
      artifact_is_authorization: false,
      execute_binding_enabled: false,
      action_candidates: [],
      final_submit_forbidden: true,
      real_action_requires_gate: true,
    },
  ]);

  const region = editor.getItem("region", "uei_review_region_1234");
  assert.equal(region.role, "review_only");
  assert.equal(region.candidate_only, true);
  assert.equal(region.requires_human_review, true);
  assert.equal(region.artifact_is_authorization, false);
  assert.equal(region.execute_binding_enabled, false);
  assert.equal(region.final_submit_forbidden, true);
  assert.equal(region.real_action_requires_gate, true);
  assert.deepEqual(region.action_candidates, []);
  assert.equal(Object.prototype.hasOwnProperty.call(region, "semantic_action"), false);
});

test("learning draft editor save refreshes the parent before closing", async () => {
  const { context, calls } = loadSaveLearningDraftReview();

  const result = await context.saveLearningDraftReview();

  assert.equal(result.reviewed_template_candidate_path, "artifacts/reviewed.json");
  assert.deepEqual(calls, [
    "commit_controls",
    "save",
    "candidate_paths",
    "source:artifacts/reviewed.json",
    "image_revision",
    "parent_refresh",
    "snapshot",
    "replace:artifacts/source.json->artifacts/reviewed.json",
    "show:node1",
    "snapshot",
    "workflow_save",
    "snapshot",
    "close",
    "correction_memory",
    "response:true",
  ]);
});

test("workflow box save keeps the exact originating workflow binding across draft refresh", async () => {
  const { context, calls, workflowState } = loadSaveLearningDraftReview();
  context.learningDraftEditorWorkflowBinding = {
    authority: "workflow",
    workflow_id: "workflow-1",
    node_id: "node1",
    source_path: "artifacts/source.json",
    state: workflowState,
  };
  context.loadLearningDraftReview = async () => {
    calls.push("parent_refresh");
    context.interfaceWorkflowReviewState = null;
    return { draft: {} };
  };

  const result = await context.saveLearningDraftReview();

  assert.equal(result.reviewed_template_candidate_path, "artifacts/reviewed.json");
  assert.ok(calls.includes("replace:artifacts/source.json->artifacts/reviewed.json"));
  assert.ok(calls.includes("workflow_save"));
});

test("workflow evidence merge attaches a uniquely matched reviewed bbox to the existing control", () => {
  const review = {
    contract_version: "single_application_workflow_review_v1",
    workflow: {
      workflow_id: "portfolio_v1_seek_apply_entry",
      entry_node_id: "job_detail",
      node_ids: ["job_detail", "apply_entry"],
      edge_ids: ["open_apply_flow"],
    },
    nodes: [
      {
        node_id: "job_detail",
        editable_review_source_path: "artifacts/source.json",
        source_paths: ["artifacts/source.json"],
        controls: [{ control_id: "apply", label: "Quick apply", role: "button" }],
        action_candidates: [{
          action_template_id: "open_apply_flow",
          semantic_action: "open_apply_flow",
          target_control_id: "apply",
          target_interface_id: "apply_entry",
        }],
        regions: [],
      },
      { node_id: "apply_entry", controls: [], action_candidates: [], regions: [] },
    ],
    edges: [{
      edge_id: "open_apply_flow",
      source_node_id: "job_detail",
      target_node_id: "apply_entry",
      action_type: "open_apply_flow",
    }],
  };
  const state = createInterfaceWorkflowReviewState(review);

  state.replaceReviewedNodeEvidenceBySource(
    "artifacts/source.json",
    "artifacts/reviewed.json",
    {
      regions: [{
        region_id: "manual_region_1",
        label: "Manual region 1",
        role: "button",
        semantic_action: "open_apply_flow",
        bbox: { x: 1127, y: 630, w: 97, h: 38 },
      }],
      action_candidates: review.nodes[0].action_candidates,
    },
  );

  const savedNode = state.snapshot().nodes.find((node) => node.node_id === "job_detail");
  assert.equal(savedNode.controls[0].control_id, "apply");
  assert.equal(savedNode.controls[0].label, "Quick apply");
  assert.equal(savedNode.controls[0].role, "button");
  assert.deepEqual(savedNode.controls[0].bbox, { x: 1127, y: 630, w: 97, h: 38 });
  assert.equal(savedNode.action_candidates[0].target_interface_id, "apply_entry");
});

test("workflow evidence merge refuses an ambiguous semantic action", () => {
  const review = {
    contract_version: "single_application_workflow_review_v1",
    workflow: { workflow_id: "workflow_a", entry_node_id: "node1", node_ids: ["node1"], edge_ids: [] },
    nodes: [{
      node_id: "node1",
      editable_review_source_path: "artifacts/source.json",
      source_paths: ["artifacts/source.json"],
      controls: [
        { control_id: "apply_a", label: "Quick apply" },
        { control_id: "apply_b", label: "Apply" },
      ],
      action_candidates: [
        { action_template_id: "a", semantic_action: "open_apply_flow", target_control_id: "apply_a" },
        { action_template_id: "b", semantic_action: "open_apply_flow", target_control_id: "apply_b" },
      ],
      regions: [],
    }],
    edges: [],
  };
  const state = createInterfaceWorkflowReviewState(review);

  assert.throws(() => state.replaceReviewedNodeEvidenceBySource(
    "artifacts/source.json",
    "artifacts/reviewed.json",
    { regions: [{ region_id: "manual_region_1", semantic_action: "open_apply_flow", bbox: { x: 1, y: 2, w: 3, h: 4 } }] },
  ), /must match exactly one action candidate/);
  assert.equal(state.snapshot().nodes[0].controls.some((control) => control.bbox), false);
});

test("workflow evidence merge refuses multiple reviewed regions for one semantic action", () => {
  const review = {
    contract_version: "single_application_workflow_review_v1",
    workflow: { workflow_id: "workflow_a", entry_node_id: "node1", node_ids: ["node1"], edge_ids: [] },
    nodes: [{
      node_id: "node1",
      editable_review_source_path: "artifacts/source.json",
      source_paths: ["artifacts/source.json"],
      controls: [{ control_id: "apply", label: "Quick apply" }],
      action_candidates: [{
        action_template_id: "open_apply_flow",
        semantic_action: "open_apply_flow",
        target_control_id: "apply",
      }],
      regions: [],
    }],
    edges: [],
  };
  const state = createInterfaceWorkflowReviewState(review);

  assert.throws(() => state.replaceReviewedNodeEvidenceBySource(
    "artifacts/source.json",
    "artifacts/reviewed.json",
    { regions: [
      { region_id: "r1", semantic_action: "open_apply_flow", bbox: { x: 1, y: 2, w: 3, h: 4 } },
      { region_id: "r2", semantic_action: "open_apply_flow", bbox: { x: 5, y: 6, w: 7, h: 8 } },
    ] },
  ), /must match exactly one reviewed region/);
  assert.equal(state.snapshot().nodes[0].controls.some((control) => control.bbox), false);
});

test("workflow evidence merge refuses invalid reviewed bbox geometry", () => {
  const review = {
    contract_version: "single_application_workflow_review_v1",
    workflow: { workflow_id: "workflow_a", entry_node_id: "node1", node_ids: ["node1"], edge_ids: [] },
    nodes: [{
      node_id: "node1",
      editable_review_source_path: "artifacts/source.json",
      source_paths: ["artifacts/source.json"],
      controls: [{ control_id: "apply", label: "Quick apply" }],
      action_candidates: [{ semantic_action: "open_apply_flow", target_control_id: "apply" }],
      regions: [],
    }],
    edges: [],
  };
  const state = createInterfaceWorkflowReviewState(review);

  assert.throws(() => state.replaceReviewedNodeEvidenceBySource(
    "artifacts/source.json",
    "artifacts/reviewed.json",
    { regions: [{
      region_id: "r1",
      semantic_action: "open_apply_flow",
      bbox: { x: -1, y: 2, w: "bad", h: 4 },
    }] },
  ), /finite non-negative position and positive size/);
  assert.equal(state.snapshot().nodes[0].controls.some((control) => control.bbox), false);
});

test("learning draft editor saves standalone candidate without workflow binding", async () => {
  const calls = [];
  const { context, button } = loadSaveLearningDraftReview({
    learningDraftEditorWorkflowBinding: null,
    interfaceWorkflowReviewState: {
      snapshot: () => ({ nodes: [{ node_id: "other", source_paths: ["artifacts/other.json"] }] }),
      replaceReviewedNodeEvidenceBySource: () => {
        calls.push("replace");
        return { node: null };
      },
    },
    closeImageInspector: () => calls.push("close"),
    renderResponse: (response) => calls.push(`response:${response.success}`),
  });

  const result = await context.saveLearningDraftReview();

  assert.equal(result.reviewed_template_candidate_path, "artifacts/reviewed.json");
  assert.deepEqual(calls, ["close", "response:true"]);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Draft saved");
});

test("learning draft editor stays open and reports failure when parent refresh fails", async () => {
  const calls = [];
  const { context, button } = loadSaveLearningDraftReview({
    loadLearningDraftReview: async () => {
      calls.push("parent_refresh");
      return null;
    },
    closeImageInspector: () => calls.push("close"),
    renderResponse: (response) => calls.push(`response:${response.success}`),
  });

  const result = await context.saveLearningDraftReview();

  assert.equal(result, null);
  assert.deepEqual(calls, ["parent_refresh", "response:false"]);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Save draft only");
});

test("learning draft editor stays open when workflow evidence replacement fails", async () => {
  const calls = [];
  const failingState = {
    snapshot: () => ({
      workflow: { workflow_id: "workflow-1" },
      nodes: [{ node_id: "node1", source_paths: ["artifacts/source.json"] }],
    }),
    replaceReviewedNodeEvidenceBySource: () => {
      calls.push("replace");
      return { node: null };
    },
  };
  const { context, button } = loadSaveLearningDraftReview({
    interfaceWorkflowReviewState: failingState,
    learningDraftEditorWorkflowBinding: {
      authority: "workflow",
      workflow_id: "workflow-1",
      node_id: "node1",
      source_path: "artifacts/source.json",
      state: failingState,
    },
    closeImageInspector: () => calls.push("close"),
    renderResponse: (response) => calls.push(`response:${response.success}`),
  });

  const result = await context.saveLearningDraftReview();

  assert.equal(result, null);
  assert.deepEqual(calls, ["replace", "response:false"]);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Save draft only");
});

test("workflow-context save stays open when the exact origin node is not bound", async () => {
  const calls = [];
  const mismatchedState = {
    snapshot: () => ({
      workflow: { workflow_id: "workflow-1" },
      nodes: [{ node_id: "other", source_paths: ["artifacts/other.json"] }],
    }),
    replaceReviewedNodeEvidenceBySource: () => {
      calls.push("replace");
      return { node: null };
    },
  };
  const { context, button } = loadSaveLearningDraftReview({
    interfaceWorkflowReviewState: mismatchedState,
    learningDraftEditorWorkflowBinding: {
      authority: "workflow",
      workflow_id: "workflow-1",
      node_id: "node1",
      source_path: "artifacts/source.json",
      state: mismatchedState,
    },
    closeImageInspector: () => calls.push("close"),
    renderResponse: (response) => calls.push(`response:${response.success}`),
  });

  const result = await context.saveLearningDraftReview();

  assert.equal(result, null);
  assert.deepEqual(calls, ["response:false"]);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Save draft only");
});

test("workflow-context save rejects source drift before writing a derivative", async () => {
  const calls = [];
  const { context, button } = loadSaveLearningDraftReview({
    learningDraftReviewSourcePath: () => "artifacts/other.json",
    api: async () => {
      calls.push("save");
      return { success: true, data: { reviewed_template_candidate_path: "artifacts/reviewed.json" } };
    },
    renderResponse: (response) => calls.push(`response:${response.success}:${response.message}`),
  });

  const result = await context.saveLearningDraftReview();

  assert.equal(result, null);
  assert.deepEqual(calls, ["response:false:Learning draft review source changed while the editor was open"]);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Save draft only");
});

test("workflow-context save rejects a binding without captured state", async () => {
  const calls = [];
  const { context, button } = loadSaveLearningDraftReview({
    learningDraftEditorWorkflowBinding: {
      authority: "workflow",
      workflow_id: "workflow-1",
      node_id: "node1",
      source_path: "artifacts/source.json",
      state: null,
    },
    renderResponse: (response) => calls.push(`response:${response.success}`),
  });

  const result = await context.saveLearningDraftReview();

  assert.equal(result, null);
  assert.deepEqual(calls.filter((call) => call === "workflow_save" || call.startsWith("replace:")), []);
  assert.ok(calls.includes("response:false"));
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Save draft only");
});

test("learning draft editor stays open when workflow save fails", async () => {
  const calls = [];
  const { context, button } = loadSaveLearningDraftReview({
    saveInterfaceWorkflowReview: async () => {
      calls.push("workflow_save");
      return null;
    },
    closeImageInspector: () => calls.push("close"),
    renderResponse: (response) => calls.push(`response:${response.success}`),
  });

  const result = await context.saveLearningDraftReview();

  assert.equal(result, null);
  assert.deepEqual(calls, ["workflow_save", "response:false"]);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Save draft only");
});

test("learning draft editor saves standalone candidate without current workflow", async () => {
  const calls = [];
  const { context, button } = loadSaveLearningDraftReview({
    learningDraftEditorWorkflowBinding: null,
    interfaceWorkflowReviewState: null,
    closeImageInspector: () => calls.push("close"),
    renderResponse: (response) => calls.push(`response:${response.success}`),
  });

  const result = await context.saveLearningDraftReview();

  assert.equal(result.reviewed_template_candidate_path, "artifacts/reviewed.json");
  assert.deepEqual(calls, ["close", "response:true"]);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Draft saved");
});

test("reviewed operational memory publish uses the current registry revision", async () => {
  const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
  const start = panelSource.indexOf("async function publishLearningOperationalMemory");
  const end = panelSource.indexOf("async function loadLearningOperationalMemory", start);
  const calls = [];
  const elements = {
    learningMemoryInterfaceId: { value: "python_org_documentation" },
    learningMemoryReviewedCandidatePath: { value: "artifacts/reviewed.json" },
    learningMemoryStatus: { textContent: "" },
    learningDraftReviewStatusSelect: { value: "approved_as_assisted_template" },
  };
  const context = {
    console,
    $: (id) => elements[id] || null,
    learningOperationalMemoryReviewedCandidatePath: () => elements.learningMemoryReviewedCandidatePath.value,
    api: async (method, path, payload = null) => {
      calls.push({ method, path, payload });
      if (method === "GET") {
        return { success: true, data: { registry_revision: 7 } };
      }
      return { success: true, data: { interface_id: "python_org_documentation" } };
    },
    loadLearningOperationalMemory: async () => calls.push({ method: "LOAD" }),
    renderResponse: () => {},
  };
  vm.createContext(context);
  vm.runInContext(panelSource.slice(start, end), context);

  await context.publishLearningOperationalMemory();

  assert.deepEqual(calls[0], {
    method: "GET",
    path: "/memory/reviewed_interfaces/registry",
    payload: null,
  });
  assert.deepEqual(JSON.parse(JSON.stringify(calls[1])), {
    method: "POST",
    path: "/memory/reviewed_interfaces/publish",
    payload: {
      source_path: "artifacts/reviewed.json",
      interface_id: "python_org_documentation",
      expected_registry_revision: 7,
    },
  });
  assert.equal(calls[2].method, "LOAD");
});

test("continuous task handoff separates screenshot readiness from resume readiness", () => {
  const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
  const start = panelSource.indexOf("function renderContinuousTaskHandoff");
  const end = panelSource.indexOf("async function loadContinuousTaskHandoff", start);
  const elements = {
    continuousTaskHandoffStatus: { textContent: "" },
    continuousTaskHandoffSummary: { innerHTML: "" },
    continuousTaskHandoffScreenshot: {
      hidden: true,
      src: "",
      removeAttribute(name) {
        if (name === "src") this.src = "";
      },
    },
    continuousTaskUseForLearningBtn: { disabled: true },
    continuousTaskResumeBtn: { disabled: true },
    continuousTaskRunDir: { value: "" },
  };
  const context = {
    console,
    continuousTaskHandoff: null,
    $: (id) => elements[id] || null,
    t: (key) => key,
    escapeHtml: (value) => String(value),
    panelFileUrl: (path) => `/panel/file?path=${path}`,
  };
  vm.createContext(context);
  vm.runInContext(panelSource.slice(start, end), context);

  context.renderContinuousTaskHandoff({
    run_dir: "logs/demo",
    pending_interface_id: "seek_quick_apply_form",
    pending_surface_type: "quick_apply",
    checkpoint_phase: "quick_apply",
    screenshot_path: "artifacts/paused.png",
    screenshot_valid: true,
    resume_ready: false,
    resume_blocker: "reviewed_memory_not_published",
  });

  assert.equal(elements.continuousTaskUseForLearningBtn.disabled, false);
  assert.equal(elements.continuousTaskResumeBtn.disabled, true);
  assert.equal(elements.continuousTaskHandoffScreenshot.hidden, false);
  assert.equal(elements.continuousTaskRunDir.value, "logs/demo");

  context.renderContinuousTaskHandoff({
    run_dir: "logs/live-confirmation",
    status: "awaiting_apply_entry_confirmation",
    pending_interface_id: "seek_job_detail_runtime_profile",
    pending_surface_type: "seek_job_detail",
    checkpoint_phase: "awaiting_apply_confirmation",
    screenshot_path: "artifacts/current-detail.png",
    screenshot_valid: true,
    resume_ready: true,
    resume_action: "confirm_apply_entry",
    resume_blocker: null,
  });

  assert.equal(elements.continuousTaskResumeBtn.disabled, false);
  assert.equal(elements.continuousTaskResumeBtn.textContent, "确认进入 Quick Apply");
  assert.match(elements.continuousTaskHandoffStatus.textContent, /awaiting confirmation/);
  assert.match(elements.continuousTaskHandoffSummary.innerHTML, /Quick Apply 学习草稿尚未生成/);
});

test("draft subview auto-loads the selected source once", async () => {
  const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
  const start = panelSource.indexOf("async function maybeLoadCurrentLearningDraftReview");
  const end = panelSource.indexOf("function setLearnReplaySubview", start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);

  const calls = [];
  const context = {
    console,
    currentLearnReplaySubview: "draft",
    learningDraftReview: null,
    $: (id) => id === "learningDraftReviewSourcePath"
      ? { value: "artifacts/learning-runs/latest/trial_result.json" }
      : null,
    loadLearningDraftReview: async (options) => {
      calls.push(options);
      return { draft: { states: [{ state_id: "screen" }] } };
    },
  };
  vm.createContext(context);
  vm.runInContext(panelSource.slice(start, end), context);

  await context.maybeLoadCurrentLearningDraftReview();
  context.learningDraftReview = { draft: {} };
  await context.maybeLoadCurrentLearningDraftReview();

  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{
    skipResponse: true,
    discoverRelatedSidecars: false,
  }]);
});

test("background draft load preserves workflow when rendering a successful response throws", async () => {
  const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
  const start = panelSource.indexOf("async function loadLearningDraftReview");
  const end = panelSource.indexOf("async function saveLearningDraftReview", start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);

  const clearCalls = [];
  const context = {
    console,
    AbortController,
    learningDraftReviewLoadPromise: null,
    learningDraftReviewLoadSourcePath: "",
    learningDraftReviewLoadRequestToken: 0,
    learningDraftReviewLoadAbortController: null,
    learningDraftReviewLoadActiveToken: 0,
    learningDraftProviderSummary: null,
    learningDraftReviewBboxEdits: { regions: {}, actions: {} },
    learningDraftReview: null,
    learningDraftEditorLoadToken: 0,
    learningDraftReviewSourcePath: () => "artifacts/background-review.json",
    clearLearningDraftReviewDisplay: (reason, options = {}) => clearCalls.push({ reason, options }),
    api: async () => ({
      success: true,
      data: { draft: { states: [{ state_id: "screen" }] } },
    }),
    resetLearningDraftEditorState: () => {},
    renderLearningDraftReview: () => {
      throw new Error("render failed");
    },
    renderResponse: () => {
      throw new Error("background loads must not render a response");
    },
  };
  vm.createContext(context);
  vm.runInContext(panelSource.slice(start, end), context);

  const result = await context.loadLearningDraftReview({
    skipResponse: true,
    skipWorkflowReview: true,
  });

  assert.equal(result, null);
  assert.deepEqual(clearCalls.map((call) => call.options.preserveWorkflowReview), [true, true]);
});

test("recommended draft source discovery preserves an already-open workflow review", () => {
  const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
  const start = panelSource.indexOf("function setRecommendedLearningDraftReviewSource");
  const end = panelSource.indexOf("function setLearningPathGraphCandidatePaths", start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);

  const sourceInput = { value: "" };
  const workflowReview = { workflow_id: "portfolio_v1_seek_apply_entry" };
  const observed = [];
  const context = {
    interfaceWorkflowReviewState: workflowReview,
    $: (id) => id === "learningDraftReviewSourcePath" ? sourceInput : null,
    preferredLearningDraftReviewSource: (items) => items[0],
    learningDraftSourceLoadPath: (item) => item.load_path,
    setLearningDraftReviewSourcePath: (path, options = {}) => {
      observed.push({ path, options });
      sourceInput.value = path;
      if (options.preserveWorkflowReview !== true) {
        context.interfaceWorkflowReviewState = null;
      }
    },
  };
  vm.createContext(context);
  vm.runInContext(panelSource.slice(start, end), context);

  context.setRecommendedLearningDraftReviewSource([
    { load_path: "artifacts/recommended/pathgraph_candidate.json" },
  ]);

  assert.equal(context.interfaceWorkflowReviewState, workflowReview);
  assert.deepEqual(JSON.parse(JSON.stringify(observed)), [{
    path: "artifacts/recommended/pathgraph_candidate.json",
    options: { preserveWorkflowReview: true },
  }]);
});

test("legacy draft links produce a display-only hierarchy projection", () => {
  const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
  const start = panelSource.indexOf("function buildLearningDraftDisplayHierarchy");
  const end = panelSource.indexOf("function renderLearningDraftHierarchy", start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const context = {
    console,
    learningDraftArray: (value) => Array.isArray(value) ? value : [],
  };
  vm.createContext(context);
  vm.runInContext(panelSource.slice(start, end), context);

  const hierarchy = context.learningDraftUiHierarchy({
    states: [{
      state_id: "main",
      label: "Main content",
      region_refs: ["search"],
      bbox: { x: 0, y: 0, w: 100, h: 80 },
    }],
    regions: [{
      region_id: "search",
      state_id: "main",
      label: "Search box",
      role: "input",
      bbox: { x: 10, y: 10, w: 60, h: 20 },
    }],
    action_templates: [{
      action_template_id: "fill_search",
      state_id: "main",
      target_region_id: "search",
      label: "Fill search",
      action_type: "fill_field",
    }],
  });

  assert.equal(hierarchy.contract_version, "ui_hierarchy_display_projection_v1");
  assert.equal(hierarchy.display_only, true);
  assert.equal(hierarchy.execute_binding_enabled, false);
  assert.equal(hierarchy.nodes.length, 4);
  assert.deepEqual(
    JSON.parse(JSON.stringify(hierarchy.nodes.find((node) => node.node_id === "draft:region:search").children)),
    ["draft:action:fill_search"],
  );
  assert.equal(
    hierarchy.nodes.find((node) => node.node_id === "draft:action:fill_search").parent_id,
    "draft:region:search",
  );
});

test("paused task screenshot is loaded into learning without target-app actions", () => {
  const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
  const start = panelSource.indexOf("function useContinuousTaskHandoffForLearning");
  const end = panelSource.indexOf("async function resumeContinuousTaskHandoff", start);
  const calls = [];
  const elements = {
    learningTrialApp: { value: "" },
    learningTrialState: { value: "" },
    learningTrialGoal: { value: "" },
    learningMemoryInterfaceId: { value: "" },
    learningInterfacePrepStatus: { textContent: "" },
  };
  const context = {
    console,
    continuousTaskHandoff: {
      run_dir: "logs/demo",
      pending_interface_id: "seek_quick_apply_form",
      pending_surface_type: "quick_apply",
      screenshot_path: "artifacts/paused.png",
      screenshot_sha256: "abc123",
      screenshot_valid: true,
    },
    $: (id) => elements[id] || null,
    setLearningSourceImagePath: (path) => calls.push(["source", path]),
    setCurrentImage: (path) => calls.push(["current", path]),
    renderLearningDraftScreenshotPath: (...args) => calls.push(["preview", ...args]),
    renderResponse: (response) => calls.push(["response", response.success]),
  };
  vm.createContext(context);
  vm.runInContext(panelSource.slice(start, end), context);

  const result = context.useContinuousTaskHandoffForLearning();

  assert.equal(result.pending_interface_id, "seek_quick_apply_form");
  assert.equal(elements.learningMemoryInterfaceId.value, "seek_quick_apply_form");
  assert.equal(elements.learningTrialState.value, "quick_apply");
  assert.deepEqual(calls[0], ["source", "artifacts/paused.png"]);
  assert.deepEqual(calls[1], ["current", "artifacts/paused.png"]);
  assert.equal(calls.some(([kind]) => kind === "api"), false);
});

test("reviewed operational memory execution returns failures to human review", async () => {
  const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
  const start = panelSource.indexOf("async function executeLearningOperationalMemory");
  const end = panelSource.indexOf("function returnLearningOperationalMemoryToReview", start);
  const elements = {
    learningMemoryInterfaceId: { value: "python_org_documentation" },
    learningMemoryActionSelect: { value: "python_org_documentation::action::open_documentation" },
    learningMemoryGoal: { value: "Open Documentation" },
    learningMemoryStatus: { textContent: "" },
    learningDraftReviewStatusSelect: { value: "approved_as_assisted_template" },
    bindProcess: { value: "msedge.exe" },
  };
  let payload = null;
  const context = {
    console,
    $: (id) => elements[id] || null,
    selectedWindowCandidate: () => ({ process_name: "msedge.exe" }),
    requestTimeoutSeconds: () => 30,
    api: async (_method, _path, nextPayload) => {
      payload = nextPayload;
      return { success: false, message: "surface mismatch" };
    },
    renderResponse: () => {},
  };
  vm.createContext(context);
  vm.runInContext(panelSource.slice(start, end), context);

  await context.executeLearningOperationalMemory(false);

  assert.equal(payload.capture_live, true);
  assert.equal(payload.max_execution_attempts, 1);
  assert.equal(payload.interface_memory_id, "python_org_documentation");
  assert.equal(payload.interface_memory_action_id, "python_org_documentation::action::open_documentation");
  assert.equal(elements.learningDraftReviewStatusSelect.value, "needs_human_review");
  assert.match(elements.learningMemoryStatus.textContent, /return_to_human_review/);
});

test("reviewed operational memory lets the agent resolve an action and reloads persisted feedback", async () => {
  const panelSource = fs.readFileSync("app/web_panel/panel.js", "utf8");
  const start = panelSource.indexOf("async function executeLearningOperationalMemory");
  const end = panelSource.indexOf("function returnLearningOperationalMemoryToReview", start);
  const elements = {
    learningMemoryInterfaceId: { value: "python_org_documentation" },
    learningMemoryActionSelect: { value: "" },
    learningMemoryGoal: { value: "Open Documentation" },
    learningMemoryStatus: { textContent: "" },
    learningDraftReviewStatusSelect: { value: "approved_as_assisted_template" },
    bindProcess: { value: "msedge.exe" },
  };
  let payload = null;
  const calls = [];
  const context = {
    console,
    $: (id) => elements[id] || null,
    selectedWindowCandidate: () => ({ process_name: "msedge.exe" }),
    requestTimeoutSeconds: () => 30,
    api: async (_method, _path, nextPayload) => {
      payload = nextPayload;
      return {
        success: false,
        message: "surface mismatch",
        data: {
          learning_review_feedback: {
            feedback_path: "artifacts/agent-memory/execution-feedback/failure.json",
            review_target: {
              reviewed_candidate_path: "artifacts/learning-draft-review/python/reviewed_template_candidate.json",
            },
          },
        },
      };
    },
    setLearningDraftReviewSourcePath: (path) => calls.push(`source:${path}`),
    loadLearningDraftReview: async (options) => calls.push(`reload:${options.skipResponse}`),
    renderResponse: () => {},
  };
  vm.createContext(context);
  vm.runInContext(panelSource.slice(start, end), context);

  await context.executeLearningOperationalMemory(false);

  assert.equal(Object.hasOwn(payload, "interface_memory_action_id"), false);
  assert.deepEqual(calls, [
    "source:artifacts/learning-draft-review/python/reviewed_template_candidate.json",
    "reload:true",
  ]);
  assert.match(elements.learningMemoryStatus.textContent, /feedback_recorded/);
});
