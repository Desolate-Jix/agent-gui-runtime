const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { createHybridReviewState } = require("../../app/web_panel/learning_workflow_review.js");
const { createLearningDraftEditorState } = require("../../app/web_panel/learning_draft_editor.js");

function serverReview() {
  return {
    contract_version: "learning_draft_review_v1",
    source: { source_path: "artifacts/replay/selection-wrapper.json", sha256: "aa".repeat(32), readonly: true },
    draft_only: true, artifact_is_authorization: false, execute_binding_enabled: false,
    final_submit_forbidden: true, real_action_requires_gate: true,
    hybrid_review_projection_ref: { id: "hybrid-selection-review/fixture", content_sha256: "cc".repeat(32) },
    draft: { regions: [], action_templates: [], page_details: { screen: { source_image_path: "artifacts/replay/screen.png", source_image_sha256: "bb".repeat(32) } } },
    hybrid_review_projection: {
      contract_version: "hybrid_selection_review_v1",
      screen_facts: { capture_id: "capture/replay", execution_origin: "replay", displayed_image: { sha256: "bb".repeat(32), image_size: { width: 320, height: 180 } } },
      selection: { selection_status: "selected", candidate_id: "candidate/a", model_proposal: { provider_id: "gui_actor", source_score: null, binding_reason: "unique_legal_candidate" } },
      refinement: { status: "not_requested", reason: "geometry_already_valid" },
      candidates: [{ candidate_id: "candidate/a", model_proposal: { bbox_original: [20, 30, 120, 70], coordinate_space: "capture_pixel_xyxy", omni_candidate: { source_item_id: "omni/a" }, selection: { provider_id: "gui_actor", source_score: null, binding_reason: "unique_legal_candidate" } }, selection: { selection_status: "selected", model_proposal: { provider_id: "gui_actor", source_score: null, binding_reason: "unique_legal_candidate" } }, refinement: { status: "not_requested", reason: "geometry_already_valid" }, reviewed_geometry: { bbox: [20, 30, 120, 70], coordinate_space: "capture_pixel_xyxy", source: "model_original", revision: 0 }, reviewed_semantics: { status: "missing", role: null, label: null, description: null, provider_id: null }, warnings: ["missing_semantics"], review_decisions: [] }],
      review_decisions: [], learning_state: "needs_semantic_review",
      artifact_is_authorization: false, execute_binding_enabled: false, final_submit_forbidden: true, real_action_requires_gate: true,
    },
  };
}

function resetHarness() {
  const source = fs.readFileSync(path.join(__dirname, "../../app/web_panel/panel.js"), "utf8");
  const start = source.indexOf("function resetLearningDraftEditorState");
  const end = source.indexOf("\nfunction syncLearningDraftReviewFromEditor", start);
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({
    globalThis: null, structuredClone,
    learningDraftEditorRevision: 0, learningDraftEditorLoadToken: 0, learningDraftEditorBaseItems: [],
    learningDraftEditorState: null, learningHybridReviewState: null, learningDraftEditorSelected: null,
    learningDraftEditorWorkflowSelection: null, learningDraftEditorActive: false, learningDraftEditorAddMode: false,
    learningDraftEditorCompactMode: true, learningDraftEditorExpandedGroupKey: "",
    LearningDraftEditorState: { createLearningDraftEditorState },
    InterfaceWorkflowReview: { createHybridReviewState },
    learningDraftArray: (value) => Array.isArray(value) ? value : [], normalizeBbox: () => null,
    renderLearningDraftOwnershipReview: () => {}, updateLearningDraftEditorControls: () => {},
  });
  context.globalThis = context;
  vm.runInContext(source.slice(start, end), context);
  return context;
}

test("server-shaped selection wrapper resets into editable candidate boxes without changing model evidence", () => {
  const context = resetHarness();
  const review = serverReview();
  context.resetLearningDraftEditorState(review);

  const item = context.learningDraftEditorState.listItems().find((entry) => entry.target_id === "candidate/a");
  assert.deepEqual(item.bbox, { x: 20, y: 30, w: 100, h: 40 });
  assert.deepEqual(context.learningHybridReviewState.currentCandidate().model_proposal.bbox_original, [20, 30, 120, 70]);
  assert.equal(context.learningHybridReviewState.currentCandidate().reviewed_semantics.status, "missing");
});

test("panel flow preserves selection evidence through semantic edit, rebox, save patch, and saved reload", () => {
  const source = fs.readFileSync(path.join(__dirname, "../../app/web_panel/panel.js"), "utf8");
  const context = resetHarness();
  const review = serverReview();
  const controls = {
    imageInspectorLabel: { value: "Apply now" },
    imageInspectorRoleSelect: { value: "button" },
    imageInspectorDescription: { value: "Human supplied description" },
    imageInspectorDestinationKind: { value: "none" }, imageInspectorDestinationValue: { value: "" },
    imageInspectorActionTypeSelect: { value: "read_only" }, imageInspectorRiskLevel: { value: "normal" },
    imageInspectorInputSemantics: { value: "" }, imageInspectorVerificationRule: { value: "" },
    imageInspectorReason: { value: "review" }, imageInspectorDestinationValue: { value: "" },
    learningDraftReviewStatusSelect: { value: "needs_human_review" },
    learningDraftReviewBlockers: { value: "" }, learningDraftReviewVerificationRules: { value: "" },
    learningDraftManualRegionLabel: { value: "" }, learningDraftManualRegionRole: { value: "" }, learningDraftManualRegionSection: { value: "" }, learningDraftManualOperation: { value: "" }, learningDraftManualEnterPathGraph: { checked: false }, learningDraftManualNeedsRecalibration: { checked: false }, learningDraftManualNotes: { value: "" },
  };
  context.$ = (id) => controls[id] || null;
  context.learningDraftReview = review;
  context.resetLearningDraftEditorState(review);
  context.learningDraftReviewBboxEdits = { regions: {}, actions: {} };
  context.learningDraftEditorSelected = { target_kind: "region", target_id: "candidate/a" };
  context.learningDraftManualCandidate = () => ({ targetRegionId: "candidate/a", targetActionTemplateId: "" });
  context.learningReviewTextareaItems = () => [];
  context.learningDraftOwnershipOperations = () => [];
  context.learningDraftEditorOperations = () => [];
  context.learningDraftSourceImagePath = () => "artifacts/replay/screen.png";
  context.learningDraftSourceImageSha256 = () => "bb".repeat(32);
  context.syncImageInspectorConfirmAndStoreButton = () => {};
  context.renderLearningHybridReviewAudit = () => {};
  context.renderLearningDraftEditorBoxes = () => {};
  const hybridCandidateStart = source.indexOf("function learningHybridReviewCandidate");
  const hybridCandidateEnd = source.indexOf("\nfunction renderLearningHybridReviewAudit", hybridCandidateStart);
  const syncStart = source.indexOf("function syncLearningDraftReviewFromEditor");
  const syncEnd = source.indexOf("\nfunction learningDraftEditorOperations", syncStart);
  const applyStart = source.indexOf("function applyLearningDraftEditorMetadataFromControls");
  const applyEnd = source.indexOf("\nfunction renderLearningDraftEditorBoxes", applyStart);
  const patchStart = source.indexOf("function learningDraftReviewPatch");
  const patchEnd = source.indexOf("\nfunction learningDraftArray", patchStart);
  assert.ok(hybridCandidateStart >= 0 && syncStart >= 0 && applyStart >= 0 && patchStart >= 0);
  vm.runInContext(`${source.slice(hybridCandidateStart, hybridCandidateEnd)}\n${source.slice(syncStart, syncEnd)}\n${source.slice(applyStart, applyEnd)}\n${source.slice(patchStart, patchEnd)}`, context);

  context.applyLearningDraftEditorMetadataFromControls();
  context.learningHybridReviewState.rebox("candidate/a", [25, 31, 125, 71]);
  context.rebuildLearningDraftEditorHybridMirror();
  const patch = context.learningDraftReviewPatch();
  const savedProjection = context.learningHybridReviewState.snapshot();

  assert.deepEqual(savedProjection.candidates[0].model_proposal.bbox_original, [20, 30, 120, 70]);
  assert.deepEqual(savedProjection.candidates[0].reviewed_geometry.bbox, [25, 31, 125, 71]);
  assert.deepEqual(savedProjection.candidates[0].reviewed_semantics, {
    role: "button", label: "Apply now", description: "Human supplied description",
    status: "human_supplied", provider_id: null, revision: 1,
  });
  assert.deepEqual(patch.hybrid_review_decisions.map((decision) => decision.decision_type), ["semantic_edit", "rebox"]);
  assert.equal(patch.hybrid_review_decisions[1].bbox[0], 25);
  assert.deepEqual(patch.expected_hybrid_review_projection_ref, review.hybrid_review_projection_ref);
  for (const legacyField of ["manual_edit", "operations", "region_bbox_updates", "action_bbox_updates"]) {
    assert.equal(Object.hasOwn(patch, legacyField), false, `selection patch must not include ${legacyField}`);
  }

  review.hybrid_review_projection = savedProjection;
  context.resetLearningDraftEditorState(review);
  const reloaded = context.learningHybridReviewState.currentCandidate();
  assert.equal(reloaded.reviewed_semantics.status, "human_supplied");
  assert.equal(reloaded.reviewed_semantics.label, "Apply now");
  assert.deepEqual(reloaded.reviewed_geometry.bbox, [25, 31, 125, 71]);
  assert.deepEqual(reloaded.model_proposal.bbox_original, [20, 30, 120, 70]);
});

test("existing draft-load entry switches a prepared selection replay to its server trial path", async () => {
  const source = fs.readFileSync(path.join(__dirname, "../../app/web_panel/panel.js"), "utf8");
  const start = source.indexOf("async function loadLearningDraftReview");
  const end = source.indexOf("async function saveLearningDraftReview", start);
  const sourceWrites = [];
  const context = {
    console, structuredClone, AbortController, learningDraftReviewLoadPromise: null, learningDraftReviewLoadSourcePath: "",
    learningDraftReviewLoadRequestToken: 0, learningDraftReviewLoadAbortController: null,
    learningDraftReviewLoadActiveToken: 0, learningDraftProviderSummary: null,
    learningDraftReviewBboxEdits: { regions: {}, actions: {} }, learningDraftReview: null,
    learningDraftEditorLoadToken: 0,
    currentLearningWorkflowRunId: "",
    learningDraftReviewSourcePath: () => "artifacts/replay/raw-selection-payload.json",
    clearLearningDraftReviewDisplay: () => {},
    setLearningDraftReviewSourcePath: (value, options) => sourceWrites.push({ value, options }),
    api: async () => ({ success: true, data: { ...serverReview(), prepared_from_selection_replay: true, trial_path: "artifacts/replay/prepared-selection-trial.json" } }),
    resetLearningDraftEditorState: () => {}, renderLearningDraftReview: () => {}, renderResponse: (value) => { context.response = value; },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(start, end), context);
  const loaded = await context.loadLearningDraftReview({});

  assert.ok(loaded, JSON.stringify(context.response));
  assert.equal(loaded.source.source_path, "artifacts/replay/selection-wrapper.json");
  assert.deepEqual(JSON.parse(JSON.stringify(sourceWrites)), [{
    value: "artifacts/replay/prepared-selection-trial.json", options: { preserveWorkflowReview: false },
  }]);
});

test("selection box editor executes selected and abstention opening branches", () => {
  const source = fs.readFileSync(path.join(__dirname, "../../app/web_panel/panel.js"), "utf8");
  const start = source.indexOf("function openLearningDraftBoxEditor");
  const end = source.indexOf("\nfunction currentLearningDraftReviewMatchesSource", start);
  const selected = []; let audits = 0;
  const controls = { imageInspectorEditorControls: { style: {} }, imageInspectorApplyBoxBtn: {}, imageInspectorImage: { naturalWidth: 1 }, imageInspectorBox: { scrollIntoView() {} } };
  const context = vm.createContext({
    learningDraftReview: { draft: {} }, learningDraftEditorState: {}, learningDraftEditorWorkflowBinding: null,
    learningDraftEditorActive: false, learningDraftEditorAddMode: true, learningDraftEditorCompactMode: false, learningDraftEditorExpandedGroupKey: "x",
    currentLanguage: "en-US", $: (id) => controls[id] || null,
    learningDraftSourceImagePath: () => "", openImageInspector: () => {}, updateLearningDraftEditorControls: () => {}, syncImageInspectorWorkflowReviewPanel: () => {},
    learningHybridReviewCandidate: (id) => id === "candidate/a" ? {} : null,
    selectLearningDraftEditorItem: (...args) => selected.push(args), renderLearningHybridReviewAudit: () => { audits += 1; },
    learningHybridReviewState: { snapshot: () => ({ contract_version: "hybrid_selection_review_v1", selection: { candidate_id: "candidate/a" } }) },
  });
  vm.runInContext(source.slice(start, end), context);
  assert.equal(context.openLearningDraftBoxEditor("image.png"), true);
  assert.deepEqual(selected, [["region", "candidate/a"]]);
  context.learningHybridReviewState = { snapshot: () => ({ contract_version: "hybrid_selection_review_v1", selection: { candidate_id: null } }) };
  assert.equal(context.openLearningDraftBoxEditor("image.png"), true);
  assert.equal(audits, 1);
});

test("selection review hides the legacy manual form and restores it for legacy drafts", () => {
  const source = fs.readFileSync(path.join(__dirname, "../../app/web_panel/panel.js"), "utf8");
  const start = source.indexOf("function renderLearningDraftManualEditPanel");
  const end = source.indexOf("\nfunction clearLearningDraftSimpleReviewPanels", start);
  const host = { hidden: false };
  const context = vm.createContext({
    $: (id) => id === "learningDraftManualEditPanel" ? host : null,
    learningDraftManualCandidate: () => ({}), setSelectValueIfPresent: () => {},
  });
  vm.runInContext(source.slice(start, end), context);
  context.renderLearningDraftManualEditPanel(serverReview());
  assert.equal(host.hidden, true);
  context.renderLearningDraftManualEditPanel({ draft: {} });
  assert.equal(host.hidden, false);
});

test("selection review summary separates candidate boxes from audited semantic learning regions", () => {
  const source = fs.readFileSync(path.join(__dirname, "../../app/web_panel/panel.js"), "utf8");
  const helperStart = source.indexOf("function selectionReviewSummaryCounts");
  const renderStart = source.indexOf("function renderLearningDraftReview", helperStart);
  const renderEnd = source.indexOf("\nfunction clearLearningDraftReviewDisplay", renderStart);
  assert.ok(helperStart >= 0 && renderStart > helperStart && renderEnd > renderStart);
  const summaryHost = { innerHTML: "" };
  const context = vm.createContext({
    document: { body: { dataset: {} } }, learningDraftReview: null,
    learningDraftOwnershipConflicts: [], learningDraftProviderSummary: null,
    interfaceAssetWorkspaceState: { activePage: "assets" },
    $: (id) => id === "learningDraftReviewSummary" ? summaryHost : null,
    t: (key) => ({
      learning_draft_summary: "学习结果摘要", learning_draft_states: "状态",
      learning_draft_regions: "区域", learning_draft_actions: "动作模板",
      learning_draft_blockers: "阻断条件", learning_draft_verification_rules: "验证规则",
    })[key] || key,
    escapeHtml: (value) => String(value), learningDraftSourceImagePath: () => "",
    renderLearningReviewItems: () => "", bindLearningDraftPreviewButtons: () => {},
    learningReviewLines: () => "", learningDraftManualBboxEditSummary: () => ({}),
    learningDraftSourceFreshnessSummary: () => ({}), renderLearningDraftManualBboxEditSummary: () => "",
    renderLearningDraftSourceFreshnessSummary: () => "", renderLearningDraftProviderSummary: () => {},
    renderUeiShadowProviderSummary: () => {}, renderScreenUnderstandingPreview: () => {},
    renderLearningDraftScreenshotPanel: () => {}, renderLearningDraftManualEditPanel: () => {},
    renderLearningDraftPathPreview: () => {},
  });
  vm.runInContext(source.slice(helperStart, renderEnd), context);
  const review = serverReview();
  review.draft.regions = Array.from({ length: 56 }, (_unused, index) => ({ region_id: `candidate/${index}` }));
  review.hybrid_review_projection.candidates = Array.from({ length: 56 }, (_unused, index) => ({ candidate_id: `candidate/${index}` }));
  review.audit = { precise_understanding_summary: {
    contract_version: "precise_understanding_summary_v1", candidate_only: true,
    candidate_count: 56, region_count: 1,
    region_count_scope: "semantically_reviewed_selected_candidates",
  } };

  context.renderLearningDraftReview(review);

  assert.match(summaryHost.innerHTML, /候选框数量: 56/);
  assert.match(summaryHost.innerHTML, /已具备语义的学习区域: 1/);
  assert.doesNotMatch(summaryHost.innerHTML, /区域: 56/);
});
