const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const {
  createInterfaceWorkflowReviewState,
  createHybridReviewState,
} = require("../../app/web_panel/learning_workflow_review.js");

function fixture() {
  return {
    contract_version: "hybrid_review_projection_v2",
    screen_facts: {
      capture_lineage_ref: { id: "capture-1", content_sha256: "ab".repeat(32) },
      displayed_image: { sha256: "cd".repeat(32), image_size: { width: 200, height: 100 } },
      warnings: ["screen_warning"],
    },
    projection_id: "hybrid-review-projection/v2/fixture",
    review_decisions: [],
    candidates: [{
      candidate_id: "candidate/abc",
      model_proposal: {
        bbox_original: [8, 18, 82, 52],
        coordinate_space: "capture_pixel_xyxy",
        qwen_binding: { role: "button", label: "Apply", description: "Open flow" },
        vista_proposal: { point: { coordinate_space: "capture_pixel_xyxy", xy: [40, 30] } },
        compact_provenance: { provider_id: "omni", source_item_id: "item-1" },
      },
      review_decisions: [],
      reviewed_geometry: { bbox: [8, 18, 82, 52], source: "model_original", revision: 0 },
      reviewed_semantics: { role: "button", label: "Apply", description: "Open flow", revision: 0 },
      human_point_proposal: null,
      tombstone: null,
      warnings: ["fusion_conflict"],
      reviewed_by_human: true,
    }],
    artifact_is_authorization: false,
    execute_binding_enabled: false,
  };
}

function panelHybridHistoryHarness() {
  const panelSource = fs.readFileSync(
    path.join(__dirname, "../../app/web_panel/panel.js"),
    "utf8",
  );
  const controlsStart = panelSource.indexOf("function updateLearningDraftEditorControls()");
  const controlsEnd = panelSource.indexOf(
    "\nfunction applyLearningDraftEditorMetadataFromControls",
    controlsStart,
  );
  const listenersStart = panelSource.indexOf(
    '  $("imageInspectorHybridPointBtn")?.addEventListener("click", () => {',
  );
  const listenersEnd = panelSource.indexOf(
    '  $("imageInspectorRoleSelect")?.addEventListener("change",',
    listenersStart,
  );
  assert.ok(controlsStart >= 0 && controlsEnd > controlsStart);
  assert.ok(listenersStart >= 0 && listenersEnd > listenersStart);

  function button() {
    const listeners = new Map();
    return {
      disabled: true,
      addEventListener(type, listener) {
        listeners.set(type, listener);
      },
      click() {
        if (!this.disabled) listeners.get("click")?.({ target: this });
      },
    };
  }

  const elements = {
    imageInspectorHybridPointBtn: button(),
    imageInspectorUndoBtn: button(),
    imageInspectorRedoBtn: button(),
  };
  const hybridState = createHybridReviewState(fixture());
  const context = vm.createContext({
    learningHybridReviewState: hybridState,
    learningDraftEditorState: { canUndo: () => false, canRedo: () => false },
    learningDraftEditorSelected: { target_kind: "region", target_id: "candidate/abc" },
    learningDraftEditorWorkflowBinding: null,
    learningDraftEditorAddMode: false,
    learningDraftEditorCompactMode: true,
    imageInspectorSelection: { point: { x: 44, y: 32 } },
    learningDraftEditorSelectedItem: () => ({
      target_kind: "region",
      target_id: "candidate/abc",
    }),
    learningHybridReviewCandidate: (candidateId) => (
      hybridState.candidates().find((candidate) => candidate.candidate_id === candidateId) || null
    ),
    rebuildLearningDraftEditorHybridMirror: () => {},
    syncLearningDraftReviewFromEditor: () => {},
    renderLearningHybridReviewAudit: () => {},
    drawImageInspectorSelection: () => {},
    setSelectValueIfPresent: () => {},
    escapeAttr: String,
    escapeHtml: String,
    $: (id) => elements[id] || null,
  });
  vm.runInContext(panelSource.slice(controlsStart, controlsEnd), context);
  context.renderLearningDraftEditorBoxes = () => context.updateLearningDraftEditorControls();
  vm.runInContext(
    `function bindHybridHistoryControls() {\n${panelSource.slice(listenersStart, listenersEnd)}\n}\nbindHybridHistoryControls();`,
    context,
  );
  context.updateLearningDraftEditorControls();
  return { context, elements, hybridState };
}

test("Large Review Hybrid history controls follow edit undo and redo state", () => {
  const { context, elements, hybridState } = panelHybridHistoryHarness();
  assert.deepEqual(
    [elements.imageInspectorUndoBtn.disabled, elements.imageInspectorRedoBtn.disabled],
    [true, true],
  );
  assert.equal(elements.imageInspectorHybridPointBtn.disabled, false);

  elements.imageInspectorHybridPointBtn.click();
  assert.deepEqual(hybridState.currentCandidate().human_point_proposal.xy, [44, 32]);
  assert.deepEqual(
    [elements.imageInspectorUndoBtn.disabled, elements.imageInspectorRedoBtn.disabled],
    [false, true],
  );

  elements.imageInspectorUndoBtn.click();
  assert.equal(hybridState.currentCandidate().human_point_proposal, null);
  assert.deepEqual(
    [elements.imageInspectorUndoBtn.disabled, elements.imageInspectorRedoBtn.disabled],
    [true, false],
  );

  elements.imageInspectorRedoBtn.click();
  assert.deepEqual(hybridState.currentCandidate().human_point_proposal.xy, [44, 32]);
  assert.deepEqual(
    [elements.imageInspectorUndoBtn.disabled, elements.imageInspectorRedoBtn.disabled],
    [false, true],
  );

  context.learningHybridReviewState = null;
  context.learningDraftEditorState = { canUndo: () => false, canRedo: () => true };
  context.updateLearningDraftEditorControls();
  assert.deepEqual(
    [elements.imageInspectorUndoBtn.disabled, elements.imageInspectorRedoBtn.disabled],
    [true, false],
  );
});

test("rebox preserves model bbox, appends a decision, and revokes current approval", () => {
  const state = createHybridReviewState(fixture());
  state.select("candidate/abc");
  state.rebox("candidate/abc", [10, 20, 80, 50]);

  const candidate = state.currentCandidate();
  assert.deepEqual(candidate.model_proposal.bbox_original, [8, 18, 82, 52]);
  assert.deepEqual(candidate.reviewed_geometry.bbox, [10, 20, 80, 50]);
  assert.equal(candidate.review_decisions.length, 1);
  assert.equal(candidate.review_decisions[0].decision_type, "rebox");
  assert.equal(candidate.reviewed_by_human, false);
  assert.deepEqual(state.screenFacts().warnings, ["screen_warning"]);
  assert.deepEqual(candidate.warnings, ["fusion_conflict"]);
});

test("unchanged canonical semantics are a no-op across repeated save snapshots", () => {
  const state = createHybridReviewState(fixture());
  const before = state.snapshot();
  const candidate = state.currentCandidate();

  state.editSemantics(candidate.candidate_id, {
    role: ` ${candidate.reviewed_semantics.role} `,
    label: candidate.reviewed_semantics.label,
    description: candidate.reviewed_semantics.description,
  });

  assert.deepEqual(state.snapshot(), before);
  assert.equal(state.canUndo(), false);
  assert.equal(state.reviewPatch().hybrid_review_decisions.length, 0);
});

test("snapshot reload preserves append-only decisions without aliasing model evidence", () => {
  const state = createHybridReviewState(fixture());
  state.rebox("candidate/abc", [10, 20, 80, 50]);
  const saved = state.snapshot();
  saved.candidates[0].model_proposal.bbox_original[0] = 999;

  assert.deepEqual(state.currentCandidate().model_proposal.bbox_original, [8, 18, 82, 52]);
  const reloaded = createHybridReviewState(state.snapshot());
  assert.deepEqual(reloaded.currentCandidate().reviewed_geometry.bbox, [10, 20, 80, 50]);
  assert.equal(reloaded.currentCandidate().review_decisions.length, 1);
});

test("semantic, point, tombstone, and add decisions preserve evidence and unique human ids", () => {
  const state = createHybridReviewState(fixture());
  state.editSemantics("candidate/abc", {
    role: "button", label: "Continue", description: "Advance",
  });
  state.proposeHumanPoint("candidate/abc", [40, 30]);
  state.tombstone("candidate/abc", "not_available");
  const first = state.add([100, 20, 140, 50], {
    role: "button", label: "Next", description: "",
  });
  state.tombstone(first.candidate_id, "deleted_by_reviewer");
  const reloaded = createHybridReviewState(state.snapshot());
  const second = reloaded.add([145, 20, 190, 50], {
    role: "button", label: "Next", description: "",
  });

  const original = reloaded.candidates().find((candidate) => candidate.candidate_id === "candidate/abc");
  assert.equal(original.reviewed_semantics.label, "Continue");
  assert.deepEqual(original.human_point_proposal.xy, [40, 30]);
  assert.deepEqual(original.model_proposal.vista_proposal.point.xy, [40, 30]);
  assert.equal(original.tombstone.reason, "not_available");
  assert.match(first.candidate_id, /^human\//);
  assert.match(second.candidate_id, /^human\//);
  assert.notEqual(first.candidate_id, second.candidate_id);
  assert.equal(reloaded.candidates().find((candidate) => candidate.candidate_id === first.candidate_id).tombstone.reason, "deleted_by_reviewer");
});

test("undo and redo rebuild derived state without rewriting model evidence", () => {
  const state = createHybridReviewState(fixture());
  state.rebox("candidate/abc", [10, 20, 80, 50]);
  state.editSemantics("candidate/abc", {
    role: "button", label: "Continue", description: "Advance",
  });

  assert.equal(state.currentCandidate().reviewed_semantics.label, "Continue");
  assert.equal(state.undo(), true);
  assert.equal(state.currentCandidate().reviewed_semantics.label, "Apply");
  assert.deepEqual(state.currentCandidate().reviewed_geometry.bbox, [10, 20, 80, 50]);
  assert.equal(state.undo(), true);
  assert.deepEqual(state.currentCandidate().reviewed_geometry.bbox, [8, 18, 82, 52]);
  assert.deepEqual(state.currentCandidate().model_proposal.bbox_original, [8, 18, 82, 52]);
  assert.equal(state.redo(), true);
  assert.deepEqual(state.currentCandidate().reviewed_geometry.bbox, [10, 20, 80, 50]);
});

test("one Hybrid history keeps mixed bbox point semantic and add edits aligned", () => {
  const state = createHybridReviewState(fixture());
  state.rebox("candidate/abc", [10, 20, 80, 50]);
  state.proposeHumanPoint("candidate/abc", [40, 30]);
  state.editSemantics("candidate/abc", {
    role: "button", label: "Continue", description: "Advance",
  });
  const added = state.add([100, 20, 140, 50], {
    role: "button", label: "Next", description: "",
  });

  assert.equal(state.undo(), true);
  assert.equal(state.candidates().some((candidate) => candidate.candidate_id === added.candidate_id), false);
  assert.equal(state.undo(), true);
  assert.equal(state.currentCandidate().reviewed_semantics.label, "Apply");
  assert.equal(state.undo(), true);
  assert.equal(state.currentCandidate().human_point_proposal, null);
  assert.equal(state.undo(), true);
  assert.deepEqual(state.currentCandidate().reviewed_geometry.bbox, [8, 18, 82, 52]);
  assert.equal(state.reviewPatch().hybrid_review_decisions.length, 0);

  for (let index = 0; index < 4; index += 1) assert.equal(state.redo(), true);
  assert.equal(state.currentCandidate().candidate_id, added.candidate_id);
  assert.equal(state.reviewPatch().hybrid_review_decisions.length, 4);
});

test("review patch exports append-only Hybrid decisions and remains non-authorizing", () => {
  const state = createHybridReviewState(fixture());
  state.rebox("candidate/abc", [10, 20, 80, 50]);
  state.proposeHumanPoint("candidate/abc", [40, 30]);
  const patch = state.reviewPatch();

  assert.equal(patch.artifact_is_authorization, false);
  assert.equal(patch.execute_binding_enabled, false);
  assert.equal(patch.hybrid_review_decisions.length, 2);
  assert.deepEqual(patch.hybrid_review_decisions[0].bbox, [10, 20, 80, 50]);
  assert.deepEqual(patch.hybrid_review_decisions[1].human_point_proposal.xy, [40, 30]);
});

test("hybrid source edits revoke only affected granular facts and node approval", () => {
  const projection = fixture();
  const candidateId = projection.candidates[0].candidate_id;
  const source = "artifacts/hybrid/reviewed.json";
  const state = createInterfaceWorkflowReviewState({
    contract_version: "single_application_workflow_review_v1",
    workflow: { workflow_id: "workflow/hybrid", goal: "review", application_identity: {} },
    nodes: [
      {
        node_id: "node/source", source_paths: [source], editable_review_source_path: source,
        display_name: "Source", surface_type: "page",
        regions: [{ region_id: candidateId, label: "Apply", bbox: { x: 10, y: 20, width: 100, height: 50 } }],
        controls: [{ control_id: candidateId, semantic_name: "Apply", purpose: "open", role: "button" }],
        action_candidates: [{
          action_template_id: "action/open", semantic_action: "open_detail",
          target_control_id: candidateId, target_region_id: "", target_interface_id: "node/target",
        }],
        blockers: [], content_descriptors: [], verification_rules: [],
      },
      {
        node_id: "node/target", source_paths: [], display_name: "Target", surface_type: "page",
        regions: [], controls: [], action_candidates: [], blockers: [], content_descriptors: [], verification_rules: [],
      },
    ],
    edges: [{
      edge_id: "edge/open", source_node_id: "node/source", target_node_id: "node/target",
      action_template_id: "action/open", action_type: "open_detail",
      target_control_id: candidateId, target_region_id: "",
    }],
  });
  state.confirmOperationHumanReviewBundle("edge/open");
  state.confirmNodeHumanReview("node/source");

  const hybrid = createHybridReviewState(projection);
  hybrid.rebox(candidateId, [20, 24, 100, 64]);
  state.replaceReviewedNodeEvidenceBySource(source, source, {
    regions: [{
      region_id: candidateId,
      label: "Apply",
      reviewed_geometry: hybrid.currentCandidate().reviewed_geometry,
      review_decisions: hybrid.currentCandidate().review_decisions,
    }],
  });
  let status = state.operationGranularReview("edge/open");
  assert.deepEqual(
    [status.target_control.current, status.action_candidate.current, status.edge.current],
    [true, true, true],
  );
  assert.equal(state.snapshot().nodes[0].reviewed_by_human, false);

  state.updateNode("node/source", {
    controls: [{ control_id: candidateId, semantic_name: "Apply revised", purpose: "open", role: "button" }],
  });
  status = state.operationGranularReview("edge/open");
  assert.deepEqual(
    [status.target_control.current, status.action_candidate.current, status.edge.current],
    [false, true, true],
  );
  assert.throws(() => state.confirmNodeHumanReview("node/source"), /granular human approval/i);

  state.confirmOperationTargetControlHumanReview("edge/open");
  state.confirmNodeHumanReview("node/source");
  assert.equal(state.snapshot().nodes[0].reviewed_by_human, true);
  assert.equal("approved" in state.snapshot().nodes[0], false);
});
