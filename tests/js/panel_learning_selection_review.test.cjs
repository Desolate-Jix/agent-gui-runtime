const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");

const {
  createHybridReviewState,
  buildHybridSelectionReviewAudit,
  renderHybridSelectionReviewAuditHtml,
} = require("../../app/web_panel/learning_workflow_review.js");

function selectionFixture(overrides = {}) {
  const selection = {
    target_text: "apply now",
    selection_status: "selected",
    candidate_id: "candidate/selected",
    candidate_source: { provider_id: "omni", source_item_id: "item-1" },
    capture: {
      capture_id: "capture-1", image_sha256: "ab".repeat(32),
      image_size: { width: 320, height: 180 }, coordinate_space: "capture_pixel_xyxy",
      capture_lineage_ref: { id: "capture-1" },
    },
    model_proposal: {
      provider_id: "guiactor", native_profile: "gui_actor_3b",
      native_output_ref: { content_sha256: "cd".repeat(32) }, raw_output_utf8: "{}",
      source_score: 0.84, canonical_capture_pixel_point: [70, 50],
      binding_status: "bound", binding_reason: "unique_legal_candidate",
    },
    parent_refs: [], semantic: { status: "missing", provider_id: null, facts: null },
  };
  return {
    contract_version: "hybrid_selection_review_v1",
    screen_facts: {
      capture_id: "capture-1", capture_lineage_ref: { id: "capture-1" },
      displayed_image: { sha256: "ab".repeat(32), image_size: { width: 320, height: 180 } },
      coordinate_space: "capture_pixel_xyxy", execution_origin: "replay", warnings: ["semantic_evidence_missing"],
    },
    parent_refs: [], selection,
    refinement: { status: "not_requested", reason: "geometry_already_valid", candidate_id: "candidate/selected", policy_version: "v1", parent_refs: [], provider_result: null },
    candidates: [{
      candidate_id: "candidate/selected",
      model_proposal: { bbox_original: [20, 30, 120, 70], coordinate_space: "capture_pixel_xyxy", omni_candidate: {}, selection: selection.model_proposal },
      selection, refinement: { status: "not_requested", reason: "geometry_already_valid" },
      reviewed_geometry: { bbox_original: [20, 30, 120, 70], coordinate_space: "capture_pixel_xyxy", source: "model_original", revision: 0 },
      reviewed_semantics: { status: "missing", role: null, label: null, description: null, provider_id: null },
      warnings: ["semantic_missing"], review_decisions: [],
    }],
    learning_state: "needs_semantic_review",
    artifact_is_authorization: false, execute_binding_enabled: false,
    final_submit_forbidden: true, real_action_requires_gate: true,
    authorization_scope: "display_and_review_only",
    ...overrides,
  };
}

test("selection review accepts a zero-candidate abstention gracefully", () => {
  const projection = selectionFixture();
  projection.selection = { ...projection.selection, selection_status: "unbound", candidate_id: null, candidate_source: null, model_proposal: { ...projection.selection.model_proposal, source_score: null, binding_status: "unbound", binding_reason: "no_unique_legal_candidate", canonical_capture_pixel_point: null } };
  projection.candidates = [];
  const state = createHybridReviewState(projection);

  assert.equal(state.currentCandidate(), null);
  assert.deepEqual(state.candidates(), []);
  assert.equal(state.select("candidate/missing"), null);
  assert.equal(state.reviewPatch().hybrid_review_decisions.length, 0);
});

test("selection audit retains real score provenance, semantic missing, and refinement status", () => {
  const projection = selectionFixture();
  projection.screen_facts.execution_origin = "actual_model";
  const audit = buildHybridSelectionReviewAudit(projection);
  const candidate = audit.candidates[0];

  assert.equal(audit.origin_kind, "actual_model");
  assert.equal(audit.selection.target_text, "apply now");
  assert.equal(candidate.model_score.value, 0.84);
  assert.equal(candidate.model_score.source, "guiactor");
  assert.equal(candidate.selection.status, "selected");
  assert.equal(candidate.selection.reason, "unique_legal_candidate");
  assert.equal(candidate.semantics.state, "missing");
  assert.equal(candidate.refinement.status, "not_requested");
  assert.deepEqual(candidate.original_gui_actor_point.point, [70, 50]);
  assert.equal(candidate.original_gui_actor_point.provider_id, "guiactor");
  assert.equal(candidate.refinement.validated_vista_point, null);
  assert.equal(candidate.selection.binding_status, "bound");
});

test("selection audit renders the exact canonical recognition target without using it as a review field", () => {
  const projection = selectionFixture();
  projection.selection.target_text = "  Apply <now>  ";

  const audit = buildHybridSelectionReviewAudit(projection);
  const html = renderHybridSelectionReviewAuditHtml(audit);

  assert.equal(audit.selection.target_text, "  Apply <now>  ");
  assert.match(html, /识别目标=  Apply &lt;now&gt;  /);
  assert.equal(createHybridReviewState(projection).reviewPatch().hybrid_review_decisions.length, 0);
});

test("selection audit does not invent scores, marks human semantics, and escapes labels", () => {
  const projection = selectionFixture();
  projection.selection.model_proposal.source_score = null;
  projection.candidates[0].reviewed_semantics = {
    status: "human_supplied", role: "button", label: "<unsafe>", description: "human supplied", provider_id: "human_review",
  };
  const audit = buildHybridSelectionReviewAudit(projection);
  const html = renderHybridSelectionReviewAuditHtml(audit);

  assert.equal(audit.candidates[0].model_score.value, null);
  assert.equal(audit.candidates[0].model_score.source, "missing");
  assert.equal(audit.candidates[0].semantics.state, "human_supplied");
  assert.equal(audit.candidates[0].semantics.label, "<unsafe>");
  assert.match(html, /&lt;unsafe&gt;/);
  assert.doesNotMatch(html, /<unsafe>/);
  assert.match(html, /score=未提供/);
});

test("selection audit distinguishes immutable GUIActor and validated VISTA points", () => {
  const projection = selectionFixture();
  projection.refinement = {
    status: "validated", reason: "validated_inside_original_candidate_and_roi",
    candidate_id: "candidate/selected", policy_version: "selection_refinement_modes_v1",
    policy: { policy_version: "selection_refinement_modes_v1", mode: "always", geometric_trigger: true },
    parent_refs: [], provider_result: {
      provider_id: "vista_4b", canonical_capture_pixel_point: [72.12349, 52.98765], source_score: null,
    },
  };
  projection.candidates[0].refinement = structuredClone(projection.refinement);

  const audit = buildHybridSelectionReviewAudit(projection);
  const html = renderHybridSelectionReviewAuditHtml(audit);
  const candidate = audit.candidates[0];

  assert.deepEqual(candidate.original_gui_actor_point.point, [70, 50]);
  assert.equal(candidate.original_gui_actor_point.provider_id, "guiactor");
  assert.deepEqual(candidate.refinement.validated_vista_point, [72.12349, 52.98765]);
  assert.equal(candidate.refinement.provider_id, "vista_4b");
  assert.equal(candidate.refinement.trigger, "true");
  assert.match(html, /点位图例：原始 GUIActor 点与已验证 VISTA 精修点仅展示，不是人工运行点/);
  assert.match(html, /原始 GUIActor 点=\(70, 50\) · source=guiactor/);
  assert.match(html, /已验证 VISTA 精修点=\(72\.123, 52\.988\) · source=vista_4b · status=validated · trigger=true/);
});

test("selection audit marks a successful bound proposal without inventing its absent reason", () => {
  const projection = selectionFixture();
  delete projection.selection.model_proposal.binding_reason;
  delete projection.candidates[0].selection.model_proposal.binding_reason;
  delete projection.candidates[0].model_proposal.selection.binding_reason;

  const html = renderHybridSelectionReviewAuditHtml(buildHybridSelectionReviewAudit(projection));

  assert.match(html, /binding=bound · reason=已绑定\(未提供原因\)/);
  assert.doesNotMatch(html, /reason=missing|reason=not_provided/);
});

test("selection audit never presents failed or review-required VISTA data as a refined point", () => {
  const projection = selectionFixture();
  projection.refinement = {
    status: "review_required", reason: "VISTA point is not strictly inside original candidate and ROI",
    candidate_id: "candidate/selected", policy_version: "selection_refinement_modes_v1",
    policy: { policy_version: "selection_refinement_modes_v1", mode: "always", geometric_trigger: true },
    parent_refs: [], provider_result: {
      provider_id: "vista_4b", canonical_capture_pixel_point: [72, 52], source_score: null,
    },
  };
  projection.candidates[0].refinement = structuredClone(projection.refinement);

  const audit = buildHybridSelectionReviewAudit(projection);
  const html = renderHybridSelectionReviewAuditHtml(audit);

  assert.equal(audit.candidates[0].refinement.validated_vista_point, null);
  assert.match(html, /已验证 VISTA 精修点=未提供 · source=vista_4b · status=review_required/);
  assert.doesNotMatch(html, /已验证 VISTA 精修点=\(72, 52\)/);
  assert.match(html, /原始 GUIActor 点=\(70, 50\)/);
});

test("selection point audit is display-only and does not append a review ledger operation", () => {
  const projection = selectionFixture();
  const before = structuredClone(projection);

  renderHybridSelectionReviewAuditHtml(buildHybridSelectionReviewAudit(projection));
  const state = createHybridReviewState(projection);

  assert.deepEqual(projection, before);
  assert.deepEqual(state.reviewPatch().hybrid_review_decisions, []);
});

test("selection audit shows only the selected candidate while retaining total count", () => {
  const projection = selectionFixture();
  projection.candidates.push({
    ...structuredClone(projection.candidates[0]), candidate_id: "candidate/" + "b".repeat(56),
    selection: null, model_proposal: { ...projection.candidates[0].model_proposal, selection: null },
  });
  const html = renderHybridSelectionReviewAuditHtml(buildHybridSelectionReviewAudit(projection));
  assert.match(html, /candidates=2/);
  assert.match(html, /view=current candidate only/);
  assert.doesNotMatch(html, new RegExp("b".repeat(56)));
});

test("panel reset and audit renderer mount the selection projection through the existing hybrid UI", () => {
  const panelSource = require("node:fs").readFileSync(
    require("node:path").join(__dirname, "../../app/web_panel/panel.js"), "utf8",
  );
  const resetStart = panelSource.indexOf("function resetLearningDraftEditorState");
  const resetEnd = panelSource.indexOf("\nfunction rebuildLearningDraftEditorHybridMirror", resetStart);
  const renderStart = panelSource.indexOf("function renderLearningHybridReviewAudit");
  const renderEnd = panelSource.indexOf("\nfunction setLearningDraftOwnershipSelection", renderStart);
  assert.ok(resetStart >= 0 && resetEnd > resetStart && renderStart >= 0 && renderEnd > renderStart);
  const screenHost = { hidden: true, innerHTML: "" };
  const candidateHost = { hidden: true, innerHTML: "" };
  const context = vm.createContext({
    globalThis: null,
    learningDraftEditorRevision: 0, learningDraftEditorLoadToken: 0,
    learningDraftEditorBaseItems: [], learningDraftEditorState: null,
    learningHybridReviewState: null, learningDraftEditorSelected: null,
    learningDraftEditorWorkflowSelection: null, learningDraftEditorActive: false,
    learningDraftEditorAddMode: false, learningDraftEditorCompactMode: true,
    learningDraftEditorExpandedGroupKey: "",
    LearningDraftEditorState: null,
    InterfaceWorkflowReview: { createHybridReviewState, buildHybridSelectionReviewAudit, renderHybridSelectionReviewAuditHtml },
    learningDraftArray: (value) => Array.isArray(value) ? value : [],
    normalizeBbox: () => null, structuredClone,
    renderLearningDraftOwnershipReview: () => {}, updateLearningDraftEditorControls: () => {},
    rebuildLearningDraftEditorHybridMirror: () => {},
    learningHybridReviewCandidate: () => null,
    $: (id) => id === "imageInspectorHybridScreenFacts" ? screenHost : id === "imageInspectorHybridCandidateFacts" ? candidateHost : null,
    escapeHtml: (value) => String(value),
  });
  context.globalThis = context;
  vm.runInContext(`${panelSource.slice(resetStart, resetEnd)}\n${panelSource.slice(renderStart, renderEnd)}`, context);
  const projection = selectionFixture();
  projection.candidates[0].reviewed_semantics = { status: "human_supplied", role: "button", label: "<unsafe>", description: null, provider_id: "human_review" };
  context.resetLearningDraftEditorState({ draft: {}, hybrid_review_projection: projection });
  context.renderLearningHybridReviewAudit();

  assert.equal(context.learningHybridReviewState.snapshot().contract_version, "hybrid_selection_review_v1");
  assert.equal(screenHost.hidden, false);
  assert.match(screenHost.innerHTML, /&lt;unsafe&gt;/);
  assert.equal(candidateHost.hidden, true);
});

test("selection rebox exports the established append-only decision grammar", () => {
  const state = createHybridReviewState(selectionFixture());
  state.rebox("candidate/selected", [25, 31, 121, 71]);
  const candidate = state.currentCandidate();
  const patch = state.reviewPatch();

  assert.deepEqual(candidate.model_proposal.bbox_original, [20, 30, 120, 70]);
  assert.deepEqual(candidate.reviewed_geometry.bbox, [25, 31, 121, 71]);
  assert.equal(candidate.reviewed_geometry.source, "human_rebox");
  assert.deepEqual(patch.hybrid_review_decisions, [{
    decision_id: "decision/candidate/selected/1", decision_type: "rebox",
    candidate_id: "candidate/selected", bbox: [25, 31, 121, 71],
  }]);
});


test("selection review keeps semantic edits but rejects unsupported candidate mutations", () => {
  const state = createHybridReviewState(selectionFixture());
  state.editSemantics("candidate/selected", { role: "button", label: "Apply", description: "human supplied" });
  const candidate = state.currentCandidate();

  assert.equal(candidate.reviewed_semantics.status, "human_supplied");
  assert.equal(candidate.reviewed_semantics.provider_id, null);
  assert.equal(state.reviewPatch().hybrid_review_decisions[0].decision_type, "semantic_edit");
  assert.throws(() => state.add([1, 1, 2, 2], { role: "button", label: "new" }), /does not support/i);
  assert.throws(() => state.tombstone("candidate/selected"), /does not support/i);
  assert.throws(() => state.proposeHumanPoint("candidate/selected", [40, 40]), /does not support/i);
});

test("unselected candidates never inherit selected model evidence", () => {
  const projection = selectionFixture();
  projection.candidates.push({
    candidate_id: "candidate/unselected",
    model_proposal: {
      bbox_original: [180, 30, 280, 70], coordinate_space: "capture_pixel_xyxy",
      omni_candidate: {
        source_item_id: "omni/unselected",
        provenance: { provider_result_ref: { id: "omni-result-b" }, source_item_id: "omni/unselected" },
      },
      selection: null,
    },
    selection: null,
    refinement: { status: "not_requested", reason: "candidate_not_selected" },
    reviewed_geometry: { bbox: [180, 30, 280, 70], coordinate_space: "capture_pixel_xyxy", source: "model_original", revision: 0 },
    reviewed_semantics: { status: "missing", role: null, label: null, description: null, provider_id: null },
    warnings: ["missing_semantics"], review_decisions: [],
  });

  const audit = buildHybridSelectionReviewAudit(projection);
  const unselected = audit.candidates.find((candidate) => candidate.candidate_id === "candidate/unselected");
  assert.equal(unselected.selection.status, "candidate_not_selected");
  assert.equal(unselected.selection.reason, "未提供原因");
  assert.equal(unselected.refinement.reason, "candidate_not_selected");
  assert.equal(unselected.model_score.value, null);
  assert.equal(unselected.model_score.source, "missing");
  assert.equal(unselected.omni_provenance.source_item_id, "omni/unselected");
});
