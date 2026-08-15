const test = require("node:test");
const assert = require("node:assert/strict");

const {
  createEmptyInterfaceWorkflowReview,
  createLatestInterfaceWorkflowLoadGuard,
  buildAttachDialogModel,
  buildInterfaceAssetLibrary,
  buildLearningResultsReviewGroups,
  commitInterfaceWorkflowReviewForSave,
  createInterfaceWorkflowWorkbenchState,
  createInterfaceWorkflowReviewState,
  interfaceWorkflowControlChoices,
  mergeEditableWorkflowReview,
  projectLiveSafeFillPreflightReview,
  projectInterfaceWorkflowStepAudit,
  projectLearningDraftOwnershipConflicts,
  buildLearningDraftOwnershipOperations,
  resolveInterfaceAssetOpenTarget,
  resolveInterfaceWorkflowCorrectionTarget,
  userFacingLearningLabel,
} = require("../../app/web_panel/learning_workflow_review.js");

function ownershipDraftFixture({ conflicting = true } = {}) {
  return {
    page_details: {
      two_stage_understanding: {
        stage2_numbering: {
          regions: [{
            region_id: "structure_region_top_bar",
            numbered_items: [{
              item_id: "visual_control_1_6",
              number: "1.9",
              label: "Search control",
            }],
            subregion_groups: [
              {
                group_id: "topbar_control_strip_4",
                label: "Top bar",
                member_item_ids: [],
              },
              {
                group_id: "topbar_control_cluster_4_1",
                label: "Control cluster",
                parent_group_id: "topbar_control_strip_4",
                member_item_ids: ["visual_control_1_6"],
              },
              ...(conflicting ? [{
                group_id: "topbar_semantic_group_4_1",
                label: "Semantic group",
                parent_group_id: "topbar_control_strip_4",
                member_item_ids: ["visual_control_1_6"],
              }] : []),
            ],
          }],
        },
      },
    },
  };
}

test("ownership conflicts list the leaf and every current leaf parent without choosing one", () => {
  const conflicts = projectLearningDraftOwnershipConflicts(ownershipDraftFixture());

  assert.deepEqual(conflicts, [{
    conflict_id: "structure_region_top_bar:visual_control_1_6",
    region_id: "structure_region_top_bar",
    target_id: "visual_control_1_6",
    item_number: "1.9",
    item_label: "Search control",
    before_parent_group_ids: [
      "topbar_control_cluster_4_1",
      "topbar_semantic_group_4_1",
    ],
    parent_groups: [
      { group_id: "topbar_control_cluster_4_1", label: "Control cluster" },
      { group_id: "topbar_semantic_group_4_1", label: "Semantic group" },
    ],
  }]);
  assert.equal(Object.hasOwn(conflicts[0], "after_parent_group_id"), false);
});

test("ownership conflict projection is empty when every leaf has one parent", () => {
  assert.deepEqual(
    projectLearningDraftOwnershipConflicts(ownershipDraftFixture({ conflicting: false })),
    [],
  );
});

test("explicit ownership choice builds the backend resolve_ownership operation", () => {
  const conflicts = projectLearningDraftOwnershipConflicts(ownershipDraftFixture());

  const operations = buildLearningDraftOwnershipOperations({
    conflicts,
    selections: {
      "structure_region_top_bar:visual_control_1_6": "topbar_semantic_group_4_1",
    },
    reason: "人工依据截图选择唯一父组",
  });

  assert.deepEqual(operations, [{
    op: "resolve_ownership",
    target_kind: "ownership",
    target_id: "visual_control_1_6",
    region_id: "structure_region_top_bar",
    before_parent_group_ids: [
      "topbar_control_cluster_4_1",
      "topbar_semantic_group_4_1",
    ],
    after_parent_group_id: "topbar_semantic_group_4_1",
    reason: "人工依据截图选择唯一父组",
  }]);
});

test("ownership operation generation fails closed without an explicit parent choice", () => {
  const conflicts = projectLearningDraftOwnershipConflicts(ownershipDraftFixture());

  assert.throws(
    () => buildLearningDraftOwnershipOperations({ conflicts, selections: {} }),
    /explicit parent selection is required/,
  );
});

test("panel review patch includes ownership resolution and remains review-only", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const vm = require("node:vm");
  const panelSource = fs.readFileSync(path.join(__dirname, "../../app/web_panel/panel.js"), "utf8");
  const start = panelSource.indexOf("function learningDraftEditorOperations");
  const end = panelSource.indexOf("function learningDraftArray", start);
  const elements = {
    learningDraftReviewStatusSelect: { value: "approved_as_assisted_template" },
    learningDraftReviewBlockers: { value: "" },
    learningDraftReviewVerificationRules: { value: "" },
    imageInspectorReason: { value: "人工依据截图选择唯一父组" },
  };
  const sandbox = {
    globalThis: null,
    InterfaceWorkflowReview: {
      buildLearningDraftOwnershipOperations,
    },
    learningDraftReview: { draft: ownershipDraftFixture() },
    learningDraftEditorState: { exportOperations: () => [] },
    learningDraftReviewBboxEdits: { regions: {}, actions: {} },
    learningDraftOwnershipConflicts: projectLearningDraftOwnershipConflicts(ownershipDraftFixture()),
    learningDraftOwnershipSelections: {
      "structure_region_top_bar:visual_control_1_6": "topbar_control_cluster_4_1",
    },
    learningDraftManualCandidate: () => ({ targetRegionId: "", targetActionTemplateId: "" }),
    learningReviewTextareaItems: () => [],
    learningDraftSourceImagePath: () => "artifacts/source.png",
    learningDraftSourceImageSha256: () => "a".repeat(64),
    $: (id) => elements[id] || null,
  };
  sandbox.globalThis = sandbox;
  vm.runInNewContext(
    `${panelSource.slice(start, end)}; globalThis.patch = learningDraftReviewPatch();`,
    sandbox,
  );

  assert.equal(sandbox.patch.review_status, "needs_human_review");
  assert.equal(sandbox.patch.artifact_is_authorization, false);
  assert.equal(sandbox.patch.execute_binding_enabled, false);
  assert.deepEqual(JSON.parse(JSON.stringify(sandbox.patch.operations)), [{
    op: "resolve_ownership",
    target_kind: "ownership",
    target_id: "visual_control_1_6",
    region_id: "structure_region_top_bar",
    before_parent_group_ids: [
      "topbar_control_cluster_4_1",
      "topbar_semantic_group_4_1",
    ],
    after_parent_group_id: "topbar_control_cluster_4_1",
    reason: "人工依据截图选择唯一父组",
  }]);
});

test("panel ownership section is hidden without conflicts and never preselects a parent", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const vm = require("node:vm");
  const panelSource = fs.readFileSync(path.join(__dirname, "../../app/web_panel/panel.js"), "utf8");
  const start = panelSource.indexOf("function renderLearningDraftOwnershipReview");
  const end = panelSource.indexOf("function learningDraftReviewPatch", start);
  assert.notEqual(start, -1, "panel ownership renderer must exist");
  const host = { hidden: true, innerHTML: "" };
  const statusSelect = { value: "approved_as_assisted_template" };
  const sandbox = {
    globalThis: null,
    InterfaceWorkflowReview: { projectLearningDraftOwnershipConflicts },
    learningDraftOwnershipConflicts: [],
    learningDraftOwnershipSelections: {},
    escapeHtml: (value) => String(value),
    $: (id) => ({
      imageInspectorOwnershipReview: host,
      learningDraftReviewStatusSelect: statusSelect,
    }[id] || null),
  };
  sandbox.globalThis = sandbox;
  vm.runInNewContext(`${panelSource.slice(start, end)}; globalThis.renderOwnership = renderLearningDraftOwnershipReview;`, sandbox);

  sandbox.renderOwnership({ draft: ownershipDraftFixture() });
  assert.equal(host.hidden, false);
  assert.match(host.innerHTML, /visual_control_1_6/);
  assert.match(host.innerHTML, /topbar_control_cluster_4_1/);
  assert.match(host.innerHTML, /topbar_semantic_group_4_1/);
  assert.doesNotMatch(host.innerHTML, /option[^>]+selected/);
  assert.equal(statusSelect.value, "needs_human_review");

  sandbox.renderOwnership({ draft: ownershipDraftFixture({ conflicting: false }) });
  assert.equal(host.hidden, true);
  assert.equal(host.innerHTML, "");
});

test("panel records only an explicit valid ownership parent selection", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const vm = require("node:vm");
  const panelSource = fs.readFileSync(path.join(__dirname, "../../app/web_panel/panel.js"), "utf8");
  const start = panelSource.indexOf("function setLearningDraftOwnershipSelection");
  const end = panelSource.indexOf("function renderLearningDraftOwnershipReview", start);
  assert.notEqual(start, -1, "panel ownership selection handler must exist");
  const conflicts = projectLearningDraftOwnershipConflicts(ownershipDraftFixture());
  const sandbox = {
    globalThis: null,
    learningDraftOwnershipConflicts: conflicts,
    learningDraftOwnershipSelections: {},
  };
  sandbox.globalThis = sandbox;
  vm.runInNewContext(`
    ${panelSource.slice(start, end)}
    globalThis.choose = setLearningDraftOwnershipSelection;
    globalThis.selections = () => learningDraftOwnershipSelections;
  `, sandbox);

  assert.equal(sandbox.choose(
    "structure_region_top_bar:visual_control_1_6",
    "topbar_semantic_group_4_1",
  ), true);
  assert.deepEqual(JSON.parse(JSON.stringify(sandbox.selections())), {
    "structure_region_top_bar:visual_control_1_6": "topbar_semantic_group_4_1",
  });
  assert.throws(
    () => sandbox.choose("structure_region_top_bar:visual_control_1_6", "not_a_current_parent"),
    /not a current parent/,
  );
  assert.equal(sandbox.choose("structure_region_top_bar:visual_control_1_6", ""), false);
  assert.deepEqual(JSON.parse(JSON.stringify(sandbox.selections())), {});
});

test("buildAttachDialogModel keeps unreviewed assets blocked for Agent use", () => {
  const model = buildAttachDialogModel({
    asset_key: "path:artifacts/learning/detail.json",
    display_name: "Detail",
    source_path: "artifacts/learning/detail.json",
    review_status: "needs_human_review",
    agent_usable: false,
  }, [
    { workflow_id: "flow_a", label: "Flow A" },
  ]);

  assert.equal(model.source_path, "artifacts/learning/detail.json");
  assert.equal(model.agent_usable, false);
  assert.equal(model.can_attach, true);
  assert.equal(model.can_agent_use, false);
  assert.match(model.warning, /未审核界面/);
  assert.deepEqual(model.workflows, [{ workflow_id: "flow_a", label: "Flow A" }]);
});

test("buildInterfaceAssetLibrary deduplicates one interface across workflows", () => {
  const shared = {
    node_id: "detail",
    display_name: "Detail",
    review_status: "human_approved",
    reviewed_by_human: true,
    agent_usable: true,
    agent_eligibility_reason: "human_reviewed_current_revision",
    editable_review_source_path: "artifacts/reviews/detail.json",
    source_paths: ["artifacts/learning/detail.json"],
  };
  const library = buildInterfaceAssetLibrary({
    applications: {
      "web:example.com": {
        application_identity: { name: "Example" },
        workflow_ids: ["flow_a", "flow_b"],
      },
    },
    workflows: {
      flow_a: { goal: "A", review_groups: { reviewed: [shared], unreviewed: [] } },
      flow_b: { goal: "B", review_groups: { reviewed: [shared], unreviewed: [] } },
    },
  }, []);

  assert.equal(library.reviewed.length, 1);
  assert.deepEqual(
    library.reviewed[0].workflow_memberships.map((item) => item.workflow_id),
    ["flow_a", "flow_b"],
  );
  assert.equal(library.reviewed[0].agent_usable, true);
});

test("buildInterfaceAssetLibrary fails closed when one reference is unreviewed", () => {
  const sourcePath = "artifacts/reviews/shared.json";
  const library = buildInterfaceAssetLibrary({
    workflows: {
      flow_a: {
        review_groups: {
          reviewed: [{
            node_id: "shared",
            review_status: "human_approved",
            reviewed_by_human: true,
            agent_usable: true,
            agent_eligibility_reason: "human_reviewed_current_revision",
            editable_review_source_path: sourcePath,
          }],
          unreviewed: [],
        },
      },
      flow_b: {
        review_groups: {
          reviewed: [],
          unreviewed: [{
            node_id: "shared",
            review_status: "needs_human_review",
            agent_usable: false,
            editable_review_source_path: sourcePath,
          }],
        },
      },
    },
  }, []);

  assert.equal(library.reviewed.length, 0);
  assert.equal(library.unreviewed.length, 1);
  assert.equal(library.unreviewed[0].agent_usable, false);
});

test("buildInterfaceAssetLibrary keeps standalone sources unreviewed", () => {
  const library = buildInterfaceAssetLibrary({}, [{
    source_path: "artifacts/learning-runs/run/trial_result.json",
    screen_summary: "New interface",
    review_status: "unknown_legacy_state",
  }]);

  assert.equal(library.reviewed.length, 0);
  assert.equal(library.unreviewed.length, 1);
  assert.equal(library.unreviewed[0].agent_usable, false);
  assert.equal(library.unreviewed[0].workflow_memberships.length, 0);
});

test("standalone parallel projection cannot self-assert Agent usability", () => {
  const library = buildInterfaceAssetLibrary({}, [{
    source_path: "artifacts/learning-runs/run/forged-review.json",
    screen_summary: "Forged reviewed interface",
    review_status: "human_approved",
    reviewed_by_human: true,
    agent_usable: true,
    agent_eligibility_reason: "human_reviewed_current_revision",
    reviewed_revision_hash: "a".repeat(64),
    current_revision_hash: "a".repeat(64),
  }]);

  assert.equal(library.reviewed.length, 0);
  assert.equal(library.unreviewed.length, 1);
  assert.equal(library.unreviewed[0].agent_usable, false);
  assert.equal(library.unreviewed[0].agent_eligibility_reason, "untrusted_parallel_projection");
});

test("groups workflow interfaces by review status and keeps mixed workflows in both groups", () => {
  const groups = buildLearningResultsReviewGroups({
    applications: {
      "web:example.com": {
        application_identity: { name: "Example" },
        workflow_ids: ["workflow_mixed"],
      },
    },
    workflows: {
      workflow_mixed: {
        goal: "Read and open details",
        review_groups: {
          reviewed: [
            { node_id: "detail", display_name: "Detail", review_status: "human_approved" },
          ],
          unreviewed: [
            { node_id: "list", display_name: "List", review_status: "needs_human_review" },
          ],
        },
      },
    },
  });

  assert.equal(groups.reviewed.length, 1);
  assert.equal(groups.reviewed[0].workflow_id, "workflow_mixed");
  assert.deepEqual(groups.reviewed[0].interfaces.map((item) => item.node_id), ["detail"]);
  assert.equal(groups.unreviewed.length, 1);
  assert.deepEqual(groups.unreviewed[0].interfaces.map((item) => item.node_id), ["list"]);
});

test("unknown review states fail closed into the unreviewed group", () => {
  const groups = buildLearningResultsReviewGroups({
    applications: {
      app: { application_identity: { name: "App" }, workflow_ids: ["workflow_unknown"] },
    },
    workflows: {
      workflow_unknown: {
        goal: "Unknown state",
        review_groups: {
          reviewed: [],
          unreviewed: [{ node_id: "node", display_name: "Node", review_status: "legacy" }],
        },
      },
    },
  });

  assert.equal(groups.reviewed.length, 0);
  assert.equal(groups.unreviewed[0].interfaces[0].review_status, "legacy");
});

test("keeps standalone learned interfaces in an unreviewed workflow inbox", () => {
  const groups = buildLearningResultsReviewGroups({}, [
    {
      source_path: "artifacts/learning-runs/run/trial_result.json",
      screen_summary: "New interface",
      review_status: "needs_human_review",
    },
  ]);

  assert.equal(groups.unreviewed.length, 1);
  assert.equal(groups.unreviewed[0].workflow_id, "");
  assert.equal(groups.unreviewed[0].goal, "待加入流程");
  assert.equal(
    groups.unreviewed[0].interfaces[0].source_path,
    "artifacts/learning-runs/run/trial_result.json",
  );
});

test("live safe-fill preflight projection is redacted and non-authorizing", () => {
  const projection = projectLiveSafeFillPreflightReview({
    contract_version: "seek_live_safe_fill_preflight_v1",
    status: "ready_for_human_review",
    approval_state: "awaiting_explicit_approval",
    field: {
      id: "email",
      label: "Email",
      field_type: "email",
      risk_class: "ordinary_field",
      required: true,
    },
    value_evidence: {
      answer_source: "reviewed_profile",
      value_length: 31,
      value_hash: "abc123",
      value_redacted: true,
      raw_value: "must-not-leak@example.com",
    },
    target: { state_type: "easy_apply", current_step: "Contact details" },
    expected_verification: {
      mode: "post_observe_hash_and_length",
      expected_value_hash: "abc123",
      expected_value_length: 31,
      raw_value_must_not_be_recorded: true,
    },
    safety: {
      max_fields: 1,
      cover_letter_fill_allowed: false,
      continue_allowed: false,
      final_submit_allowed: false,
      artifact_is_authorization: false,
    },
    evidence: { screenshot_path: "artifacts/screenshots/contact.png", trace_path: "logs/contact.json" },
    pii_redacted: true,
  });

  assert.equal(projection.visible, true);
  assert.equal(projection.field.id, "email");
  assert.equal(projection.value_evidence.value_hash, "abc123");
  assert.equal(projection.safety.artifact_is_authorization, false);
  assert.equal(projection.interpretation.includes("not authorization"), true);
  assert.equal(JSON.stringify(projection).includes("must-not-leak@example.com"), false);
});

test("unrecognized or unsafe preflight is not reviewable", () => {
  assert.equal(projectLiveSafeFillPreflightReview({ contract_version: "other" }).visible, false);
  const projection = projectLiveSafeFillPreflightReview({
    contract_version: "seek_live_safe_fill_preflight_v1",
    status: "ready_for_human_review",
    approval_state: "awaiting_explicit_approval",
    field: { id: "email", risk_class: "ordinary_field" },
    value_evidence: { value_redacted: false, value_hash: "", value_length: 0 },
    safety: { artifact_is_authorization: false },
    pii_redacted: false,
  });
  assert.equal(projection.visible, false);
  assert.equal(projection.reason, "redaction_contract_failed");
});

function reviewFixture() {
  return {
    contract_version: "single_application_workflow_review_v1",
    workflow: {
      workflow_id: "workflow_demo",
      goal: "Open an item",
      application_identity: { name: "ExampleApp" },
      entry_node_id: "node_list",
      node_ids: ["node_list", "node_detail", "node_missing"],
      edge_ids: ["edge_open", "edge_next"],
      review_status: "needs_human_review",
    },
    nodes: [
      {
        node_id: "node_list",
        display_name: "Item list",
        surface_type: "list",
        evidence_status: "ready",
        evidence: {
          source_screenshot_path: "screens/list.png",
          numbered_overlay_path: "overlays/list-numbered.png",
          fused_overlay_path: "overlays/list-fused.png",
          human_review_overlay_path: "",
        },
        regions: [{ region_id: "list", label: "List" }],
        controls: [
          { control_id: "open_button", label: "Open item", role: "button" },
          { control_id: "filter_button", label: "Filter", role: "button" },
        ],
        action_candidates: [{ action_template_id: "open", label: "Open" }],
        page_details: { summary: { region_count: 1 } },
      },
      {
        node_id: "node_detail",
        display_name: "Item details",
        surface_type: "detail",
        evidence_status: "ready",
        evidence: {
          source_screenshot_path: "screens/detail.png",
          numbered_overlay_path: "overlays/detail-numbered.png",
          fused_overlay_path: "overlays/detail-fused.png",
          human_review_overlay_path: "overlays/detail-reviewed.png",
        },
        regions: [{ region_id: "detail", label: "Detail" }],
        action_candidates: [],
        page_details: { summary: { region_count: 1 } },
      },
      {
        node_id: "node_missing",
        display_name: "Unknown screen",
        surface_type: "unknown_surface",
        evidence_status: "screenshot_missing",
        evidence: {
          source_screenshot_path: "",
          numbered_overlay_path: "",
          fused_overlay_path: "",
          human_review_overlay_path: "",
        },
        regions: [],
        action_candidates: [],
        page_details: {},
      },
    ],
    edges: [
      {
        edge_id: "edge_open",
        source_node_id: "node_list",
        target_node_id: "node_detail",
        action_type: "open_detail",
      },
      {
        edge_id: "edge_next",
        source_node_id: "node_detail",
        target_node_id: "node_missing",
        action_type: "unknown_action",
      },
    ],
  };
}

test("removes legacy draft wording from user-facing learning labels", () => {
  assert.equal(
    userFacingLearningLabel("UI hierarchy draft: 2 structure regions"),
    "UI hierarchy: 2 structure regions",
  );
  assert.equal(
    userFacingLearningLabel("Learning draft review"),
    "Learning result review",
  );
  assert.equal(
    userFacingLearningLabel("学习草稿审核"),
    "学习结果审核",
  );
});

test("only the latest interface workflow load may update the review", () => {
  const guard = createLatestInterfaceWorkflowLoadGuard();
  const staleLoad = guard.begin();
  const latestLoad = guard.begin();

  assert.equal(guard.isCurrent(staleLoad), false);
  assert.equal(guard.isCurrent(latestLoad), true);
});

test("clicking a graph node returns only that node evidence", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());

  const list = state.current();
  assert.equal(list.node.node_id, "node_list");
  assert.equal(list.active_image_path, "overlays/list-fused.png");

  const detail = state.select("node_detail");
  assert.equal(detail.node.node_id, "node_detail");
  assert.equal(detail.active_image_path, "overlays/detail-reviewed.png");
  assert.equal(detail.node.regions[0].region_id, "detail");
  assert.equal(detail.node.action_candidates.length, 0);
  assert.equal(detail.incoming_edges[0].edge_id, "edge_open");
  assert.equal(detail.outgoing_edges[0].edge_id, "edge_next");
});

test("reviewed node evidence source can be replaced without rebuilding the graph", () => {
  const review = reviewFixture();
  review.nodes[0].editable_review_source_path = "artifacts/node-review-sources/list.json";
  review.nodes[0].source_paths = [
    "artifacts/node-review-sources/list.json",
    "logs/traces/list.json",
  ];
  const state = createInterfaceWorkflowReviewState(review);

  state.updateNode("node_list", {
    editable_review_source_path: "artifacts/learning-draft-review/list/reviewed.json",
    source_paths: [
      "artifacts/learning-draft-review/list/reviewed.json",
      "logs/traces/list.json",
    ],
    regions: [{ region_id: "reviewed_list", label: "Reviewed list" }],
  });

  const snapshot = state.snapshot();
  assert.equal(snapshot.nodes.length, 3);
  assert.equal(snapshot.edges.length, 2);
  assert.equal(
    snapshot.nodes[0].editable_review_source_path,
    "artifacts/learning-draft-review/list/reviewed.json",
  );
  assert.equal(snapshot.nodes[0].regions[0].region_id, "reviewed_list");
});

test("replacing reviewed node evidence preserves identity but revokes the old human review fact", () => {
  const review = reviewFixture();
  review.nodes[0].review_status = "human_approved";
  review.nodes[0].reviewed_by_human = true;
  review.nodes[0].editable_review_source_path = "artifacts/node-review-sources/list.json";
  review.nodes[0].source_paths = [
    "artifacts/node-review-sources/list.json",
    "logs/traces/list.json",
  ];
  review.edges[0].review_status = "human_approved";
  const state = createInterfaceWorkflowReviewState(review);

  state.select("node_detail");
  const updated = state.replaceReviewedNodeEvidenceBySource(
    "artifacts\\node-review-sources\\list.json",
    "artifacts/learning-draft-review/list/reviewed.json",
    {
      regions: [{ region_id: "reviewed_list", label: "Reviewed list" }],
    },
  );

  const snapshot = state.snapshot();
  assert.equal(updated.node.node_id, "node_list");
  assert.deepEqual(snapshot.nodes.map((node) => node.node_id), [
    "node_list",
    "node_detail",
    "node_missing",
  ]);
  assert.equal(snapshot.nodes[0].review_status, "needs_human_review");
  assert.equal(snapshot.nodes[0].reviewed_by_human, false);
  assert.deepEqual(snapshot.edges.map((edge) => edge.edge_id), ["edge_open", "edge_next"]);
  assert.equal(snapshot.edges[0].review_status, "human_approved");
  assert.deepEqual(snapshot.workflow.node_ids, ["node_list", "node_detail", "node_missing"]);
  assert.deepEqual(snapshot.workflow.edge_ids, ["edge_open", "edge_next"]);
});

test("saved workflow membership wins over a standalone source preview on reopen", () => {
  assert.deepEqual(resolveInterfaceAssetOpenTarget({
    sourcePath: "artifacts/node-review-sources/list.json",
    workflowId: "workflow_saved",
    nodeId: "node_list",
  }), {
    mode: "saved_workflow",
    workflow_id: "workflow_saved",
    node_id: "node_list",
    source_path: "artifacts/node-review-sources/list.json",
  });
  assert.deepEqual(resolveInterfaceAssetOpenTarget({
    sourcePath: "artifacts/learning/standalone.json",
  }), {
    mode: "source_preview",
    workflow_id: "",
    node_id: "",
    source_path: "artifacts/learning/standalone.json",
  });
});

test("save then reload preserves exact workflow identity projection", () => {
  const review = reviewFixture();
  review.workflow.review_status = "human_approved";
  review.nodes.forEach((node) => {
    node.review_status = "human_approved";
    node.reviewed_by_human = true;
  });
  review.edges.forEach((edge) => {
    edge.review_status = "human_approved";
  });
  const saved = createInterfaceWorkflowReviewState(review).snapshot();
  const reloaded = createInterfaceWorkflowReviewState(saved).snapshot();
  const identity = (value) => ({
    workflow_id: value.workflow.workflow_id,
    workflow_review_status: value.workflow.review_status,
    node_ids: value.nodes.map((node) => node.node_id),
    node_review_states: value.nodes.map((node) => [
      node.node_id,
      node.review_status,
      node.reviewed_by_human,
    ]),
    edge_ids: value.edges.map((edge) => edge.edge_id),
    edge_actions: value.edges.map((edge) => [
      edge.edge_id,
      edge.source_node_id,
      edge.target_node_id,
      edge.action_type,
      edge.review_status,
    ]),
  });

  assert.deepEqual(identity(reloaded), identity(saved));
});

test("removing one interface preserves unrelated identities and only removes incident edges", () => {
  const review = reviewFixture();
  review.workflow.review_status = "human_approved";
  review.nodes.forEach((node) => { node.review_status = "human_approved"; });
  review.edges.forEach((edge) => { edge.review_status = "human_approved"; });
  const state = createInterfaceWorkflowReviewState(review);

  const removed = state.removeInterfaceNode("node_missing");
  const snapshot = state.snapshot();

  assert.equal(removed.node_id, "node_missing");
  assert.deepEqual(snapshot.nodes.map((node) => node.node_id), ["node_list", "node_detail"]);
  assert.deepEqual(snapshot.edges.map((edge) => edge.edge_id), ["edge_open"]);
  assert.equal(snapshot.edges[0].action_type, "open_detail");
  assert.equal(snapshot.edges[0].review_status, "human_approved");
  assert.deepEqual(snapshot.workflow.node_ids, ["node_list", "node_detail"]);
  assert.deepEqual(snapshot.workflow.edge_ids, ["edge_open"]);
});

test("editing an approved node revokes approval until the user approves again", () => {
  const review = reviewFixture();
  review.nodes[0].review_status = "human_approved";
  review.nodes[0].reviewed_by_human = true;
  const state = createInterfaceWorkflowReviewState(review);

  state.updateNode("node_list", { display_name: "Reviewed item list" });

  assert.equal(state.snapshot().nodes[0].review_status, "needs_human_review");
  assert.equal(state.snapshot().nodes[0].reviewed_by_human, false);
  state.updateNode("node_list", { review_status: "human_approved" });
  assert.equal(state.snapshot().nodes[0].review_status, "human_approved");
  assert.equal(state.snapshot().nodes[0].reviewed_by_human, false);
});

test("only explicit confirmation records human review for the current node revision", () => {
  const review = reviewFixture();
  review.nodes[0].review_status = "human_approved";
  delete review.nodes[0].reviewed_by_human;
  const state = createInterfaceWorkflowReviewState(review);

  assert.equal(state.snapshot().nodes[0].reviewed_by_human === true, false);
  state.confirmNodeHumanReview("node_list");
  const confirmed = state.snapshot().nodes[0];
  assert.equal(confirmed.review_status, "human_approved");
  assert.equal(confirmed.reviewed_by_human, true);
  assert.equal(
    confirmed.human_review_confirmation.contract_version,
    "interface_node_human_review_confirmation_v1",
  );
  assert.equal(confirmed.human_review_confirmation.revision.node.display_name, "Item list");

  state.updateNode("node_list", {
    controls: [{ control_id: "reviewed_control", semantic_name: "Reviewed control" }],
    action_candidates: [{ action_type: "open_detail", target_control_id: "reviewed_control" }],
    verification_rules: [{ rule_id: "detail_visible" }],
    manual_revision: { source: "human_editor_v2" },
  });

  assert.equal(state.snapshot().nodes[0].review_status, "needs_human_review");
  assert.equal(state.snapshot().nodes[0].reviewed_by_human, false);
  assert.equal("human_review_confirmation" in state.snapshot().nodes[0], false);

  for (const patch of [
    { display_name: "Changed semantics" },
    { regions: [{ region_id: "changed_region" }] },
    { controls: [{ control_id: "changed_control" }] },
    { action_candidates: [{ action_type: "open_detail" }] },
    { verification_rules: [{ rule_id: "changed_rule" }] },
    { evidence: { source_screenshot_path: "artifacts/screenshots/changed.png" } },
    { page_details: { summary: "Changed evidence semantics" } },
    { source_paths: ["artifacts/changed-revision.json"] },
  ]) {
    const revisionState = createInterfaceWorkflowReviewState(reviewFixture());
    revisionState.confirmNodeHumanReview("node_list");
    revisionState.updateNode("node_list", patch);
    assert.equal(revisionState.snapshot().nodes[0].review_status, "needs_human_review");
    assert.equal(revisionState.snapshot().nodes[0].reviewed_by_human, false);
  }
});

test("human review revision excludes only durable evidence projections", () => {
  const initial = createInterfaceWorkflowReviewState(reviewFixture());
  initial.confirmNodeHumanReview("node_list");
  const confirmedRevision = initial.snapshot().nodes[0].human_review_confirmation.revision;

  const materialized = initial.snapshot();
  materialized.nodes[0].evidence = {
    source_screenshot_path: "artifacts/interface-workflow-reviews/fixture/node-evidence/node_list/source.png",
    overlay_image_path: "artifacts/interface-workflow-reviews/fixture/node-evidence/node_list/overlay.png",
    review_revision_source_screenshot_path: "artifacts/interface-workflow-reviews/fixture/source.png",
    review_revision_fused_overlay_path: "",
    review_revision_human_review_overlay_path: "",
    review_revision_numbered_overlay_path: "",
  };
  materialized.nodes[0].editable_review_source_path = "artifacts/node-review-sources/node_list.json";
  materialized.nodes[0].source_paths = [
    "artifacts/node-review-sources/node_list.json",
    "artifacts/interface-workflow-reviews/fixture/node-evidence/node_list/source.png",
  ];

  const restored = createInterfaceWorkflowReviewState(materialized);
  restored.confirmNodeHumanReview("node_list");
  const restoredRevision = restored.snapshot().nodes[0].human_review_confirmation.revision;
  assert.notDeepEqual(restoredRevision, confirmedRevision);
  assert.equal(
    restoredRevision.node.evidence.source_screenshot_path,
    "artifacts/interface-workflow-reviews/fixture/source.png",
  );
  assert.equal(
    restoredRevision.node.evidence.overlay_image_path,
    "artifacts/interface-workflow-reviews/fixture/node-evidence/node_list/overlay.png",
  );
  assert.deepEqual(restoredRevision.node.source_paths, [
    "artifacts/interface-workflow-reviews/fixture/node-evidence/node_list/source.png",
  ]);
});

test("panel save orchestration commits operation edits before binding human review", () => {
  const review = reviewFixture();
  const state = createInterfaceWorkflowReviewState(review);
  const callOrder = [];
  const originalUpdateNode = state.updateNode;
  const originalConfirm = state.confirmNodeHumanReview;
  state.updateNode = (...args) => {
    callOrder.push("node");
    return originalUpdateNode(...args);
  };
  state.confirmNodeHumanReview = (...args) => {
    callOrder.push("confirm");
    return originalConfirm(...args);
  };

  const snapshot = commitInterfaceWorkflowReviewForSave({
    state,
    nodeId: "node_list",
    nodePatch: { display_name: "Reviewed list" },
    commitOperation: () => {
      callOrder.push("operation");
      state.updateEdge("edge_open", { success_conditions: ["new detail visible"] });
    },
    humanReviewConfirmed: true,
  });

  assert.deepEqual(callOrder, ["node", "operation", "confirm"]);
  assert.equal(snapshot.nodes[0].reviewed_by_human, true);
  assert.deepEqual(
    snapshot.nodes[0].human_review_confirmation.revision.outgoing_edges[0].success_conditions,
    ["new detail visible"],
  );
});

test("editing workflow actions revokes the source node human review fact", () => {
  const review = reviewFixture();
  review.nodes[0].review_status = "human_approved";
  review.nodes[0].reviewed_by_human = true;
  const state = createInterfaceWorkflowReviewState(review);

  state.updateEdge("edge_open", {
    success_conditions: ["updated detail is visible"],
  });

  assert.equal(state.snapshot().nodes[0].review_status, "needs_human_review");
  assert.equal(state.snapshot().nodes[0].reviewed_by_human, false);

  state.confirmNodeHumanReview("node_list");
  state.addOperation("node_list", {
    operation_id: "open_missing",
    action_type: "open_detail",
    target_node_id: "node_missing",
  });
  assert.equal(state.snapshot().nodes[0].review_status, "needs_human_review");
  assert.equal(state.snapshot().nodes[0].reviewed_by_human, false);
});

test("missing evidence clears the previous image and details", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());
  state.select("node_detail");

  const missing = state.select("node_missing");

  assert.equal(missing.active_image_path, "");
  assert.equal(missing.available_layers.length, 0);
  assert.deepEqual(missing.node.page_details, {});
  assert.equal(missing.evidence_status, "screenshot_missing");
});

test("runtime report projects one auditable Agent Gate Operation Trace step", () => {
  const audit = projectInterfaceWorkflowStepAudit({
    contract_version: "navigation_reading_controller_report_v1",
    final_status: "ready_for_agent_decision",
    stop_reason: null,
    steps: [
      {
        interface_id: "node_list",
        agent_decision: {
          semantic_action: "open_detail",
          choice_id: "open_selected_item",
          reason: "The reviewed item matches the goal",
        },
        decision_source: "reviewed_interface_memory",
        gate_allowed: true,
        gate_result: { allowed: true, reason: "fresh_target_confirmed" },
        dispatch_success: true,
        action_executed: true,
        effect_verified: true,
        destination_observation_verified: true,
        actual_target_interface_id: "node_detail",
        trace_path: "logs/demo/step-1.json",
        case_outcome: "passed",
      },
    ],
  }, "node_list");

  assert.equal(audit.coverage_status, "recorded_runtime_step");
  assert.equal(audit.agent.status, "decision_recorded");
  assert.equal(audit.agent.semantic_action, "open_detail");
  assert.equal(audit.gate.status, "allowed");
  assert.equal(audit.dispatch.status, "dispatched");
  assert.equal(audit.effect.status, "verified");
  assert.equal(audit.post_observe.status, "verified");
  assert.equal(audit.post_observe.interface_id, "node_detail");
  assert.equal(audit.trace.status, "recorded");
  assert.equal(audit.trace.path, "logs/demo/step-1.json");
  assert.equal(audit.stop.status, "continuing");
});

test("gate rejection is a safe stop and never becomes a dispatched action", () => {
  const audit = projectInterfaceWorkflowStepAudit({
    final_status: "safe_stop",
    stop_reason: "gate_rejected",
    steps: [
      {
        interface_id: "node_list",
        agent_decision: { semantic_action: "open_detail" },
        gate_allowed: false,
        gate_result: { allowed: false, reason: "target_ambiguous" },
        action_executed: false,
        case_outcome: "safe_intercept",
      },
    ],
  }, "node_list");

  assert.equal(audit.gate.status, "rejected");
  assert.equal(audit.gate.reason, "target_ambiguous");
  assert.equal(audit.dispatch.status, "not_dispatched");
  assert.equal(audit.effect.status, "not_attempted");
  assert.equal(audit.stop.status, "safe_stop");
  assert.equal(audit.stop.reason, "gate_rejected");
});

test("an unvisited interface never inherits another node runtime evidence", () => {
  const audit = projectInterfaceWorkflowStepAudit({
    final_status: "ready_for_agent_decision",
    steps: [
      {
        interface_id: "node_list",
        agent_decision: { semantic_action: "open_detail" },
        gate_allowed: true,
        dispatch_success: true,
        effect_verified: true,
      },
    ],
  }, "node_missing");

  assert.equal(audit.coverage_status, "not_run");
  assert.equal(audit.agent.status, "not_recorded");
  assert.equal(audit.gate.status, "not_covered");
  assert.equal(audit.trace.status, "not_recorded");
});

test("controller report direct step fields are projected as recorded Agent evidence", () => {
  const audit = projectInterfaceWorkflowStepAudit({
    contract_version: "navigation_reading_controller_report_v1",
    final_status: "safe_stop",
    stop_reason: "gate_rejected",
    trace_path: "logs/traces/controller.json",
    steps: [
      {
        interface_id: "node_list",
        choice_id: "open_item",
        semantic_action: "open_detail",
        decision_source: "actual_model_call",
        decision_audit: { rationale: "目标与任务一致" },
        gate_allowed: false,
        dispatch_success: false,
        effect_verified: false,
        case_outcome: "safe_intercept",
      },
    ],
  }, "node_list");

  assert.equal(audit.agent.status, "decision_recorded");
  assert.equal(audit.agent.semantic_action, "open_detail");
  assert.equal(audit.agent.choice_id, "open_item");
  assert.equal(audit.agent.reason, "目标与任务一致");
  assert.equal(audit.agent.source, "actual_model_call");
  assert.equal(audit.gate.status, "rejected");
  assert.equal(audit.dispatch.status, "not_dispatched");
  assert.equal(audit.effect.status, "not_attempted");
  assert.equal(audit.trace.path, "logs/traces/controller.json");
  assert.equal(audit.stop.reason, "gate_rejected");
});

test("runtime report source path is used as Trace evidence when a step has no trace path", () => {
  const audit = projectInterfaceWorkflowStepAudit({
    final_status: "ready_for_agent_decision",
    source_report_path: "logs/smoke/multi-interface/report.json",
    steps: [
      {
        interface_id: "node_list",
        semantic_action: "read",
        gate_allowed: true,
        dispatch_success: true,
        effect_verified: true,
      },
    ],
  }, "node_list");

  assert.equal(audit.trace.status, "recorded");
  assert.equal(audit.trace.path, "logs/smoke/multi-interface/report.json");
});

test("review state exposes only the selected node step audit", () => {
  const review = reviewFixture();
  review.runtime_report = {
    final_status: "ready_for_agent_decision",
    steps: [
      {
        interface_id: "node_list",
        agent_decision: { semantic_action: "open_detail" },
        gate_allowed: true,
        dispatch_success: true,
        effect_verified: true,
      },
    ],
  };
  const state = createInterfaceWorkflowReviewState(review);

  assert.equal(state.current().step_audit.coverage_status, "recorded_runtime_step");
  assert.equal(state.select("node_missing").step_audit.coverage_status, "not_run");
});

test("layer selection is node-owned and falls back without stale images", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());

  assert.equal(state.selectLayer("source").active_image_path, "screens/list.png");
  assert.equal(state.select("node_detail").active_image_path, "overlays/detail-reviewed.png");
  assert.equal(state.selectLayer("numbered").active_image_path, "overlays/detail-numbered.png");
  assert.equal(state.select("node_list").active_image_path, "overlays/list-fused.png");
});

test("graph view is generic and contains no application-specific workflow copy", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());
  const graph = state.graph();

  assert.equal(graph.nodes.length, 3);
  assert.equal(graph.edges.length, 2);
  assert.equal(graph.nodes[0].label, "Item list");
  assert.equal(JSON.stringify(graph).toLowerCase().includes("seek"), false);
});

test("graph view preserves formal human review state for nodes and transitions", () => {
  const review = reviewFixture();
  review.nodes.forEach((node) => {
    node.review_status = "human_approved";
    node.reviewed_by_human = true;
  });
  review.edges.forEach((edge) => {
    edge.review_status = "human_approved";
  });

  const graph = createInterfaceWorkflowReviewState(review).graph();

  assert.equal(graph.nodes.every((node) => node.review_status === "human_approved"), true);
  assert.equal(graph.nodes.every((node) => node.reviewed_by_human === true), true);
  assert.equal(graph.edges.every((edge) => edge.review_status === "human_approved"), true);
});

test("creates an empty software workflow without execution authority", () => {
  const review = createEmptyInterfaceWorkflowReview({
    workflowId: "example_app_research",
    goal: "Research items",
    applicationIdentity: { kind: "desktop", display_name: "Example App" },
  });

  assert.equal(review.workflow.workflow_id, "example_app_research");
  assert.equal(review.workflow.goal, "Research items");
  assert.deepEqual(review.workflow.node_ids, []);
  assert.deepEqual(review.workflow.edge_ids, []);
  assert.equal(review.display_only, true);
  assert.equal(review.execute_binding_enabled, false);
});

test("interface focus exposes its controls and control focus is reversible", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());

  const interfaceFocus = state.focusInterface("node_list");
  assert.equal(interfaceFocus.focus.node_id, "node_list");
  assert.equal(interfaceFocus.nodes.find((node) => node.node_id === "node_list").controls.length, 2);

  const controlFocus = state.focusControl("open_button");
  assert.deepEqual(controlFocus.focus, {
    node_id: "node_list",
    control_id: "open_button",
  });
  assert.equal(state.current().selected_control.control_id, "open_button");

  const restored = state.clearFocus();
  assert.deepEqual(restored.focus, { node_id: "", control_id: "" });
});

test("single-interface preview uses an explicit evidence source and can switch back", () => {
  const workbench = createInterfaceWorkflowWorkbenchState();

  assert.deepEqual(workbench.current(), {
    evidence_mode: "workflow",
    evidence_node_id: "",
    correction_open: false,
    link_source_node_id: "",
    link_target_node_id: "",
  });

  workbench.showSourcePreview("node_detail");
  assert.equal(workbench.current().evidence_mode, "source_preview");
  assert.equal(workbench.current().evidence_node_id, "node_detail");

  workbench.showWorkflowNode("node_list");
  assert.equal(workbench.current().evidence_mode, "workflow");
  assert.equal(workbench.current().evidence_node_id, "node_list");
});

test("interface correction follows the displayed source preview instead of the workflow node", () => {
  const workflowState = createInterfaceWorkflowReviewState(reviewFixture());
  workflowState.focusInterface("node_detail");
  const sourcePreviewReview = reviewFixture();
  sourcePreviewReview.nodes = [{
    ...sourcePreviewReview.nodes[0],
    node_id: "standalone_asset_a",
    display_name: "Standalone asset A",
    editable_review_source_path: "artifacts/standalone-a/trial_result.json",
  }];
  sourcePreviewReview.edges = [];
  sourcePreviewReview.workflow.node_ids = ["standalone_asset_a"];
  sourcePreviewReview.workflow.edge_ids = [];
  const sourcePreviewState = createInterfaceWorkflowReviewState(sourcePreviewReview);
  const workbench = createInterfaceWorkflowWorkbenchState();
  workbench.showWorkflowNode("node_detail");
  workbench.showSourcePreview("standalone_asset_a");

  const target = resolveInterfaceWorkflowCorrectionTarget({
    workbench: workbench.current(),
    workflowState,
    sourcePreviewState,
  });

  assert.equal(target.authority, "source_preview");
  assert.equal(target.view.node.node_id, "standalone_asset_a");
  assert.equal(target.view.node.editable_review_source_path, "artifacts/standalone-a/trial_result.json");
  assert.notEqual(target.view.node.node_id, workflowState.current().node.node_id);
});

test("interface correction fails closed when the displayed source preview is unavailable", () => {
  const workflowState = createInterfaceWorkflowReviewState(reviewFixture());
  workflowState.focusInterface("node_detail");

  const target = resolveInterfaceWorkflowCorrectionTarget({
    workbench: { evidence_mode: "source_preview", evidence_node_id: "standalone_asset_a" },
    workflowState,
    sourcePreviewState: null,
  });

  assert.equal(target.authority, "source_preview");
  assert.equal(target.view, null);
  assert.equal(target.reason, "displayed_source_preview_unavailable");
});

test("source preview synchronizes the review editor to asset A instead of workflow node B", async () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const vm = require("node:vm");
  const panelSource = fs.readFileSync(
    path.join(__dirname, "../../app/web_panel/panel.js"),
    "utf8",
  );
  const start = panelSource.indexOf("async function previewInterfaceWorkflowSource");
  const end = panelSource.indexOf("async function selectInterfaceWorkflowAttachTarget", start);
  assert.notEqual(start, -1, "source preview loader must exist");
  assert.notEqual(end, -1, "source preview loader boundary must exist");

  const assetA = { node_id: "asset_a", display_name: "Standalone asset A" };
  const elements = {
    interfaceWorkflowSourceSelect: { value: "artifacts/asset-a/trial_result.json" },
    interfaceWorkflowSourceStatus: { textContent: "" },
    learningTrialGoal: { value: "Review asset A" },
  };
  const rendered = { editorNodeId: "", evidence: false };
  const sandbox = {
    globalThis: null,
    $: (id) => elements[id] || null,
    api: async () => ({ success: true, data: { nodes: [assetA] } }),
    clearInterfaceWorkflowCorrectionSelection: () => {},
    currentInterfaceWorkflowApplicationIdentity: () => ({ kind: "web", host: "example.test" }),
    renderInterfaceWorkflowSourcePreview: () => {},
    renderActiveInterfaceWorkflowEvidence: () => { rendered.evidence = true; },
    renderInterfaceWorkflowEditor: (view) => { rendered.editorNodeId = view?.node?.node_id || ""; },
    interfaceWorkflowWorkbenchState: { showSourcePreview: () => {} },
    InterfaceWorkflowReview: {
      createInterfaceWorkflowReviewState: () => ({ current: () => ({ node: assetA }) }),
    },
  };
  sandbox.globalThis = sandbox;
  vm.runInNewContext(`
    let interfaceWorkflowSourceReviewState = null;
    ${panelSource.slice(start, end)}
    globalThis.previewSource = previewInterfaceWorkflowSource;
  `, sandbox);

  await sandbox.previewSource();

  assert.equal(rendered.evidence, true);
  assert.equal(rendered.editorNodeId, "asset_a");
});

test("panel correction editor opens displayed asset A while workflow remains on node B", async () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const vm = require("node:vm");
  const panelSource = fs.readFileSync(
    path.join(__dirname, "../../app/web_panel/panel.js"),
    "utf8",
  );
  const start = panelSource.indexOf("function currentInterfaceWorkflowCorrectionTarget");
  const end = panelSource.indexOf("function interfaceWorkflowSourcePathsAfterReview", start);
  assert.notEqual(start, -1, "panel must resolve correction from displayed evidence");
  assert.notEqual(end, -1, "panel correction editor boundary must exist");

  const assetAView = {
    node: {
      node_id: "asset_a",
      editable_review_source_path: "artifacts/asset-a/trial_result.json",
      evidence: { source_screenshot_path: "artifacts/asset-a/source.png" },
    },
    available_layers: [{ layer: "source", path: "artifacts/asset-a/source.png" }],
  };
  const workflowBView = {
    node: {
      node_id: "workflow_b",
      editable_review_source_path: "artifacts/workflow-b/source.json",
      evidence: { source_screenshot_path: "artifacts/workflow-b/source.png" },
    },
  };
  const opened = { sourcePath: "", imagePath: "", correctionNodeId: "" };
  const sandbox = {
    console,
    globalThis: null,
    InterfaceWorkflowReview: { resolveInterfaceWorkflowCorrectionTarget },
    interfaceWorkflowWorkbenchState: {
      current: () => ({ evidence_mode: "source_preview", evidence_node_id: "asset_a" }),
    },
    interfaceWorkflowReviewState: { current: () => workflowBView },
    interfaceWorkflowSourceReviewState: { current: () => assetAView },
    learningDraftReview: { draft: { source_screenshot_path: "artifacts/asset-a/source.png" } },
    learningDraftEditorState: {},
    currentLearningDraftReviewMatchesSource: () => true,
    setLearningDraftReviewSourcePath: (value) => { opened.sourcePath = value; },
    learningDraftSourceImagePath: () => "artifacts/asset-a/source.png",
    openLearningDraftBoxEditor: (value) => { opened.imagePath = value; return true; },
    setInterfaceWorkflowCorrectionOpen: (_open, view) => { opened.correctionNodeId = view?.node?.node_id || ""; },
    setInterfaceWorkflowBoxEditorStatus: () => {},
    renderResponse: () => {},
    $: () => null,
    openImageInspector: () => {},
    closeImageInspector: () => {},
    loadLearningDraftReview: async () => null,
  };
  sandbox.globalThis = sandbox;
  vm.runInNewContext(
    `${panelSource.slice(start, end)}; globalThis.openCorrection = openCurrentInterfaceWorkflowBoxEditor;`,
    sandbox,
  );

  await sandbox.openCorrection();

  assert.equal(opened.correctionNodeId, "asset_a");
  assert.equal(opened.sourcePath, "artifacts/asset-a/trial_result.json");
  assert.equal(opened.imagePath, "artifacts/asset-a/source.png");
});

test("panel asset switch invalidates and clears the previous editor selection", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const vm = require("node:vm");
  const panelSource = fs.readFileSync(
    path.join(__dirname, "../../app/web_panel/panel.js"),
    "utf8",
  );
  const clearStart = panelSource.indexOf("function clearInterfaceWorkflowCorrectionSelection");
  const clearEnd = panelSource.indexOf("async function openInterfaceWorkflowReviewGroupNode", clearStart);
  const openEnd = panelSource.indexOf("function showInterfaceAssetPage", clearEnd);
  assert.notEqual(clearStart, -1, "editor selection reset must exist");
  assert.match(
    panelSource.slice(clearEnd, openEnd),
    /clearInterfaceWorkflowCorrectionSelection\(\)/,
    "asset click must clear the previous editor before selecting another asset",
  );

  const sandbox = { console, globalThis: null };
  sandbox.globalThis = sandbox;
  vm.runInNewContext(`
    let learningDraftReviewLoadRequestToken = 7;
    let learningDraftReviewLoadPromise = { pending: true };
    let learningDraftReviewLoadSourcePath = "artifacts/old/source.json";
    let learningDraftReview = { draft: { source_path: "artifacts/old/source.json" } };
    let learningDraftReviewBboxEdits = { regions: { old: true }, actions: {} };
    let resetValue = "not-called";
    let inspectorClosed = false;
    let correctionOpen = true;
    function resetLearningDraftEditorState(value) { resetValue = value; }
    function closeImageInspector() { inspectorClosed = true; }
    function setInterfaceWorkflowCorrectionOpen(value) { correctionOpen = value; }
    function setInterfaceWorkflowBoxEditorStatus() {}
    ${panelSource.slice(clearStart, clearEnd)}
    clearInterfaceWorkflowCorrectionSelection();
    globalThis.snapshot = {
      token: learningDraftReviewLoadRequestToken,
      promise: learningDraftReviewLoadPromise,
      sourcePath: learningDraftReviewLoadSourcePath,
      review: learningDraftReview,
      edits: learningDraftReviewBboxEdits,
      resetValue,
      inspectorClosed,
      correctionOpen,
    };
  `, sandbox);

  assert.equal(sandbox.snapshot.token, 8);
  assert.equal(sandbox.snapshot.promise, null);
  assert.equal(sandbox.snapshot.sourcePath, "");
  assert.equal(sandbox.snapshot.review, null);
  assert.equal(sandbox.snapshot.resetValue, null);
  assert.equal(sandbox.snapshot.inspectorClosed, true);
  assert.equal(sandbox.snapshot.correctionOpen, false);
  assert.deepEqual(JSON.parse(JSON.stringify(sandbox.snapshot.edits)), { regions: {}, actions: {} });
});

test("the learning draft box editor click handler does not pass the browser event as an image path", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const vm = require("node:vm");
  const panelSource = fs.readFileSync(
    path.join(__dirname, "../../app/web_panel/panel.js"),
    "utf8",
  );
  const registration = panelSource.match(
    /on\("learningDraftOpenBoxEditorBtn",\s*"click",\s*[^;]+\);/,
  )?.[0];
  assert.ok(registration, "box editor click registration must exist");
  const opened = { value: "not_called" };
  const sandbox = {
    console,
    openLearningDraftBoxEditor: (value) => { opened.value = value; },
    on: (_id, _eventName, handler) => { sandbox.handler = handler; },
  };
  vm.runInNewContext(`${registration};`, sandbox);
  sandbox.handler({ type: "click" });
  assert.equal(opened.value, undefined);
});

test("graph linking records source then target without exposing control ids", () => {
  const workbench = createInterfaceWorkflowWorkbenchState();

  workbench.startLink("node_list");
  assert.equal(workbench.current().link_source_node_id, "node_list");

  const link = workbench.chooseLinkTarget("node_detail");
  assert.deepEqual(link, {
    source_node_id: "node_list",
    target_node_id: "node_detail",
  });
});

test("control choices expose readable labels while retaining internal ids", () => {
  const choices = interfaceWorkflowControlChoices(reviewFixture().nodes[0]);

  assert.deepEqual(choices, [
    {
      control_id: "open_button",
      label: "Open item",
      role: "button",
    },
    {
      control_id: "filter_button",
      label: "Filter",
      role: "button",
    },
  ]);
});

test("invalid contracts are rejected", () => {
  assert.throws(
    () => createInterfaceWorkflowReviewState({ contract_version: "wrong" }),
    /unsupported interface workflow review contract/,
  );
});

test("node and transition edits are retained in the review snapshot", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());

  state.updateNode("node_list", {
    display_name: "Reviewed item list",
    surface_type: "collection",
    content_descriptors: [
      {
        content_id: "open_button_label",
        source_kind: "control",
        source_id: "open_button",
        content_behavior: "fixed_label",
        agent_usage: "action_target",
        read_policy: "on_interface_match",
        agent_description: "用于打开当前条目的按钮",
      },
    ],
  });
  state.updateEdge("edge_open", {
    action_type: "open_detail",
    agent_description: "点击当前条目进入详情页",
    review_status: "human_reviewed",
  });

  const current = state.current();
  const snapshot = state.snapshot();
  assert.equal(current.node.display_name, "Reviewed item list");
  assert.equal(current.node.surface_type, "collection");
  assert.equal(snapshot.edges[0].review_status, "human_reviewed");
  assert.equal(snapshot.edges[0].agent_description, "点击当前条目进入详情页");
  assert.equal(snapshot.nodes[0].content_descriptors[0].content_behavior, "fixed_label");
  assert.equal(snapshot.display_only, true);
  assert.equal(snapshot.execute_binding_enabled, false);
});

test("a learned interface can be renamed and linked from an explicit source interface", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());

  state.updateNode("node_detail", {
    display_name: "Reviewed item details",
    review_status: "human_reviewed",
  });
  const edge = state.addOperation("node_list", {
    operation_id: "open_reviewed_details",
    display_name: "Open reviewed details",
    agent_description: "Click the reviewed item card and verify the details interface.",
    action_type: "open_detail",
    target_node_id: "node_detail",
    target_control_id: "open_button",
    risk_level: "low",
  });

  const snapshot = state.snapshot();
  assert.equal(
    snapshot.nodes.find((node) => node.node_id === "node_detail").display_name,
    "Reviewed item details",
  );
  assert.equal(edge.source_node_id, "node_list");
  assert.equal(edge.target_node_id, "node_detail");
  assert.equal(edge.target_control_id, "open_button");
  assert.equal(edge.artifact_is_authorization, false);
});

test("adds a reviewed interface to a workflow without creating a link", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());
  const edgeCount = state.snapshot().edges.length;
  const added = state.addInterfaceNode({
    node_id: "node_form",
    display_name: "Application form",
    surface_type: "form",
    source_paths: ["artifacts/form/reviewed.json"],
    evidence: { fused_overlay_path: "overlays/form.png" },
    controls: [{ control_id: "field_name", label: "Name", role: "input" }],
  });

  const snapshot = state.snapshot();
  assert.equal(added.node_id, "node_form");
  assert.equal(snapshot.nodes.some((node) => node.node_id === "node_form"), true);
  assert.equal(snapshot.edges.length, edgeCount);
  assert.equal(snapshot.workflow.node_ids.includes("node_form"), true);
  assert.throws(
    () => state.addInterfaceNode({ node_id: "node_form", display_name: "Duplicate" }),
    /already exists/,
  );
});

test("unknown node and edge edits fail closed", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());

  assert.throws(() => state.updateNode("missing", {}), /unknown interface workflow node/);
  assert.throws(() => state.updateEdge("missing", {}), /unknown interface workflow edge/);
});

test("rebuilding a workflow preserves only matching human-review edits", () => {
  const previous = reviewFixture();
  previous.nodes[0].display_name = "Reviewed list";
  previous.nodes[0].surface_type = "reviewed_collection";
  previous.nodes[0].manual_revision = { note: "checked" };
  previous.nodes[0].execute_binding_enabled = true;
  previous.edges[0].action_type = "open_detail";
  previous.edges[0].review_status = "reviewed_candidate";
  previous.edges.push({
    edge_id: "edge_custom_back",
    operation_id: "back_to_list",
    source_node_id: "node_detail",
    target_node_id: "node_list",
    display_name: "Back to list",
    action_type: "back",
    risk_level: "low",
    review_status: "human_reviewed",
  });

  const next = reviewFixture();
  next.workflow.workflow_id = "temporary_rebuild_id";
  next.nodes.push({
    node_id: "node_form",
    display_name: "Application form",
    surface_type: "form",
    evidence_status: "ready",
    evidence: { source_screenshot_path: "screens/form.png" },
  });
  next.workflow.node_ids.push("node_form");

  const merged = mergeEditableWorkflowReview(next, previous);

  assert.equal(merged.nodes[0].display_name, "Reviewed list");
  assert.equal(merged.workflow.workflow_id, previous.workflow.workflow_id);
  assert.equal(merged.nodes[0].surface_type, "reviewed_collection");
  assert.deepEqual(merged.nodes[0].manual_revision, { note: "checked" });
  assert.equal(merged.edges[0].action_type, "open_detail");
  assert.equal(merged.edges[0].review_status, "reviewed_candidate");
  assert.equal(
    merged.edges.some((edge) => (
      edge.source_node_id === "node_detail"
      && edge.target_node_id === "node_list"
      && edge.display_name === "Back to list"
    )),
    true,
  );
  assert.equal(merged.nodes[0].execute_binding_enabled, false);
  assert.equal(merged.nodes[3].display_name, "Application form");
});

test("transition target is editable but remains display-only", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());

  state.updateEdge("edge_open", {
    target_node_id: "node_missing",
  });

  const snapshot = state.snapshot();
  assert.equal(snapshot.edges[0].target_node_id, "node_missing");
  assert.equal(snapshot.edges[0].display_only, true);
  assert.equal(snapshot.edges[0].artifact_is_authorization, false);
});

test("adds a routine operation and placeholder target without execution authority", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());
  const target = state.addPlaceholderNode("Quick Apply form", "form");

  const edge = state.addOperation("node_list", {
    operation_id: "open_quick_apply",
    display_name: "Open Quick Apply",
    agent_description: "Open the reviewed application entry and verify the next interface",
    action_type: "open_apply_flow",
    target_node_id: target.node_id,
    target_control_id: "quick_apply_button",
    risk_level: "medium",
    requires_user_confirmation: true,
  });

  const snapshot = state.snapshot();
  assert.equal(edge.action_type, "open_apply_flow");
  assert.equal(
    edge.agent_description,
    "Open the reviewed application entry and verify the next interface",
  );
  assert.equal(edge.target_node_id, target.node_id);
  assert.equal(snapshot.nodes.at(-1).review_status, "needs_learning");
  assert.equal(snapshot.nodes.at(-1).execute_binding_enabled, false);
  assert.equal(snapshot.workflow.node_ids.at(-1), target.node_id);
  assert.equal(snapshot.workflow.edge_ids.at(-1), edge.edge_id);
  assert.equal(snapshot.edges.at(-1).artifact_is_authorization, false);
});

test("graph view preserves the human-readable operation label", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());
  const target = state.addPlaceholderNode("Detail screen", "detail");

  state.addOperation("node_list", {
    operation_id: "open_detail",
    display_name: "Open selected item detail",
    action_type: "open_detail",
    target_node_id: target.node_id,
  });

  assert.equal(state.graph().edges.at(-1).display_name, "Open selected item detail");
});

test("removes only an operation edge and rejects forbidden operations", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());
  const target = state.addPlaceholderNode("Review screen", "review");
  const edge = state.addOperation("node_list", {
    operation_id: "continue_to_review",
    action_type: "continue_next_step",
    target_node_id: target.node_id,
  });

  const removed = state.removeOperation(edge.edge_id);

  assert.equal(removed.edge_id, edge.edge_id);
  assert.equal(state.snapshot().nodes.some((node) => node.node_id === target.node_id), true);
  assert.equal(state.snapshot().edges.some((item) => item.edge_id === edge.edge_id), false);
  assert.throws(
    () => state.addOperation("node_list", {
      operation_id: "unsafe_submit",
      action_type: "final_submit",
      target_node_id: target.node_id,
    }),
    /forbidden review action type/,
  );
});


function loadScopedLearningCaptureExports() {
  const source = require("node:fs").readFileSync(
    require("node:path").join(__dirname, "../../app/web_panel/panel.js"),
    "utf8",
  );
  const start = source.indexOf("function scopedLearningCaptureIsAbortError");
  const end = source.indexOf("const scopedLearningCaptureTestExports", start);
  assert.notEqual(start, -1, "scoped learning capture helpers must exist");
  assert.notEqual(end, -1, "scoped learning capture test exports must exist");
  const sandbox = { AbortController, DOMException, console };
  sandbox.globalThis = sandbox;
  require("node:vm").runInNewContext(
    `${source.slice(start, end)}; globalThis.scopedLearningCaptureExports = { runScopedLearningCaptureSequence, buildScopedLearningCaptureScrollPayload, scopedLearningCaptureStopFromScroll };`,
    sandbox,
  );
  return sandbox.scopedLearningCaptureExports;
}

function scopedCaptureResponse(imagePath, captureId = "capture") {
  return { success: true, data: { image_path: imagePath, capture_id: captureId, window_size: { width: 1200, height: 800 } } };
}

function verifiedScopedScroll(overrides = {}) {
  return {
    success: true,
    data: {
      result: {
        execution_path: { action_executed: true },
        scroll_effect_validation: { status: "moved", no_effect_detected: false, wrong_scope_detected: false, ...overrides },
        trace_path: "artifacts/traces/scroll.json",
      },
    },
  };
}

test("runScopedLearningCaptureSequence keeps normal capture single-shot and model-safe", async () => {
  const { runScopedLearningCaptureSequence } = loadScopedLearningCaptureExports();
  const calls = [];
  const result = await runScopedLearningCaptureSequence({
    mode: "normal",
    capture: async () => { calls.push("capture"); return scopedCaptureResponse("artifacts/a.png"); },
    scroll: async () => { calls.push("scroll"); return verifiedScopedScroll(); },
    compose: async () => { calls.push("compose"); return { success: true }; },
  });

  assert.deepEqual(calls, ["capture"]);
  assert.equal(result.model_allowed, true);
  assert.equal(result.image_path, "artifacts/a.png");
  assert.equal(result.stop_reason, "single_capture");
});

test("runScopedLearningCaptureSequence captures, verifies scroll, then composes the learning input", async () => {
  const { runScopedLearningCaptureSequence } = loadScopedLearningCaptureExports();
  const calls = [];
  const result = await runScopedLearningCaptureSequence({
    mode: "scoped_long",
    config: { roi: { x: 10, y: 20, width: 300, height: 400 }, scroll_scope: "container", target_pane: "job_detail", target_container_id: "detail", wheel_clicks: 4, max_segments: 2 },
    capture: async () => {
      calls.push("capture");
      return scopedCaptureResponse(`artifacts/${calls.length}.png`, `capture-${calls.length}`);
    },
    scroll: async (payload) => { calls.push({ scroll: payload }); return verifiedScopedScroll(); },
    compose: async (payload) => { calls.push({ compose: payload }); return { success: true, data: { composite_path: "artifacts/composite.png", manifest_path: "artifacts/manifest.json", artifact_is_authorization: false, historical_coordinates_are_priors: true } }; },
  });

  assert.equal(calls[0], "capture");
  assert.equal(calls[1].scroll.direction, "down");
  assert.equal(calls[2], "capture");
  assert.equal(calls[3].compose.segments.length, 2);
  assert.equal(result.model_allowed, true);
  assert.equal(result.image_path, "artifacts/composite.png");
  assert.equal(result.stop_reason, "max_segments");
  assert.equal(result.composite.artifact_is_authorization, false);
});

test("runScopedLearningCaptureSequence uses the capture-adjusted ROI for scroll and compose", async () => {
  const { runScopedLearningCaptureSequence } = loadScopedLearningCaptureExports();
  const requestedRoi = { x: 0, y: 74, width: 2048, height: 1046 };
  const effectiveRoi = { x: 0, y: 74, width: 2048, height: 982 };
  const scrollPayloads = [];
  let composePayload = null;
  let captureIndex = 0;

  const result = await runScopedLearningCaptureSequence({
    mode: "scoped_long",
    config: {
      roi: requestedRoi,
      scroll_scope: "page",
      target_pane: "page",
      wheel_clicks: 4,
      max_segments: 2,
    },
    capture: async () => {
      captureIndex += 1;
      return {
        success: true,
        data: {
          image_path: `artifacts/adjusted-${captureIndex}.png`,
          capture_id: `adjusted-${captureIndex}`,
          window_size: { width: 2048, height: 1056 },
          roi: { ...effectiveRoi, requested: requestedRoi },
          roi_adjusted: true,
        },
      };
    },
    scroll: async (payload) => {
      scrollPayloads.push(payload);
      return verifiedScopedScroll();
    },
    compose: async (payload) => {
      composePayload = payload;
      return {
        success: true,
        data: {
          composite_path: "artifacts/adjusted-composite.png",
          manifest_path: "artifacts/adjusted-manifest.json",
        },
      };
    },
  });

  assert.equal(result.phase, "completed");
  assert.deepEqual(JSON.parse(JSON.stringify(scrollPayloads[0].container_bbox)), effectiveRoi);
  assert.deepEqual(JSON.parse(JSON.stringify(composePayload.roi)), effectiveRoi);
  assert.deepEqual(JSON.parse(JSON.stringify(composePayload.viewport)), { width: 2048, height: 1056 });
});

test("runScopedLearningCaptureSequence safe-stops when capture geometry changes", async () => {
  const { runScopedLearningCaptureSequence } = loadScopedLearningCaptureExports();
  const rois = [
    { x: 0, y: 74, width: 2048, height: 982 },
    { x: 0, y: 74, width: 1920, height: 982 },
  ];
  let captureIndex = 0;
  let composeCalled = false;

  const result = await runScopedLearningCaptureSequence({
    mode: "scoped_long",
    config: {
      roi: { x: 0, y: 74, width: 2048, height: 1046 },
      scroll_scope: "page",
      target_pane: "page",
      wheel_clicks: 4,
      max_segments: 3,
    },
    capture: async () => {
      const roi = rois[Math.min(captureIndex, rois.length - 1)];
      captureIndex += 1;
      return {
        success: true,
        data: {
          image_path: `artifacts/geometry-${captureIndex}.png`,
          capture_id: `geometry-${captureIndex}`,
          window_size: { width: 2048, height: 1056 },
          roi,
        },
      };
    },
    scroll: async () => verifiedScopedScroll(),
    compose: async () => {
      composeCalled = true;
      return { success: true, data: {} };
    },
  });

  assert.equal(result.phase, "safe_stopped");
  assert.equal(result.stop_reason, "capture_geometry_changed");
  assert.equal(result.model_allowed, false);
  assert.equal(composeCalled, false);
});

test("runScopedLearningCaptureSequence normalizes only persisted compose stop reasons", async () => {
  const { runScopedLearningCaptureSequence } = loadScopedLearningCaptureExports();

  async function runCase({ maxSegments, capture, scroll }) {
    let composePayload = null;
    const result = await runScopedLearningCaptureSequence({
      mode: "scoped_long",
      config: {
        roi: { x: 0, y: 0, width: 30, height: 40 },
        scroll_scope: "page",
        target_pane: "page",
        wheel_clicks: 2,
        max_segments: maxSegments,
      },
      capture,
      scroll,
      compose: async (payload) => {
        composePayload = payload;
        return { success: true, data: { composite_path: "artifacts/composite.png" } };
      },
    });
    return { result, composePayload };
  }

  let maxCaptureCount = 0;
  const maxSegments = await runCase({
    maxSegments: 2,
    capture: async () => {
      maxCaptureCount += 1;
      return scopedCaptureResponse(`artifacts/max-${maxCaptureCount}.png`, `max-${maxCaptureCount}`);
    },
    scroll: async () => verifiedScopedScroll(),
  });
  assert.equal(maxSegments.result.stop_reason, "max_segments");
  assert.equal(maxSegments.composePayload.stop_reason, "max_captures");

  const duplicateSegment = await runCase({
    maxSegments: 3,
    capture: async () => scopedCaptureResponse("artifacts/repeated.png", "repeated"),
    scroll: async () => verifiedScopedScroll(),
  });
  assert.equal(duplicateSegment.result.stop_reason, "duplicate_segment");
  assert.equal(duplicateSegment.composePayload.stop_reason, "no_new_content");

  const reachedBottom = await runCase({
    maxSegments: 3,
    capture: async () => scopedCaptureResponse("artifacts/bottom.png", "bottom"),
    scroll: async () => verifiedScopedScroll({ reached_bottom: true }),
  });
  assert.equal(reachedBottom.result.stop_reason, "reached_bottom");
  assert.equal(reachedBottom.composePayload.stop_reason, "reached_bottom");
});

test("buildScopedLearningCaptureScrollPayload preserves ROI, verification, and Learn metadata", () => {
  const { buildScopedLearningCaptureScrollPayload } = loadScopedLearningCaptureExports();
  const payload = buildScopedLearningCaptureScrollPayload(
    { roi: { x: 1, y: 2, width: 30, height: 40 }, scroll_scope: "container", target_pane: "results_list", target_container_id: "results", wheel_clicks: 5 },
    { window_size: { width: 900, height: 700 } },
  );

  assert.equal(JSON.stringify(payload.container_bbox), JSON.stringify({ x: 1, y: 2, width: 30, height: 40 }));
  assert.equal(JSON.stringify(payload.coordinate_window_size), JSON.stringify({ width: 900, height: 700 }));
  assert.equal(payload.scroll_scope, "container");
  assert.equal(payload.enable_verification, true);
  assert.equal(payload.dry_run, false);
  assert.equal(JSON.stringify(payload.metadata), JSON.stringify({ agent_mode: "learn", capture_mode: "scoped_long", artifact_is_authorization: false }));
  assert.equal(JSON.stringify(payload.expected_effect), JSON.stringify({
    target_content: "changed",
    non_target_regions: "stable",
  }));
});

test("runScopedLearningCaptureSequence blocks next capture, compose, and model after unverified scroll", async () => {
  const { runScopedLearningCaptureSequence } = loadScopedLearningCaptureExports();
  for (const effect of [
    { status: "unknown" },
    { status: "moved", no_effect_detected: true },
    { status: "moved", wrong_scope_detected: true },
  ]) {
    const calls = [];
    const result = await runScopedLearningCaptureSequence({
      mode: "scoped_long",
      config: { roi: { x: 0, y: 0, width: 30, height: 40 }, scroll_scope: "page", target_pane: "page", wheel_clicks: 2, max_segments: 3 },
      capture: async () => { calls.push("capture"); return scopedCaptureResponse("artifacts/one.png"); },
      scroll: async () => { calls.push("scroll"); return verifiedScopedScroll(effect); },
      compose: async () => { calls.push("compose"); return { success: true }; },
    });
    assert.deepEqual(calls, ["capture", "scroll"]);
    assert.equal(result.model_allowed, false);
    assert.equal(result.composite, null);
    assert.equal(result.stop_reason, "no_effect_or_unverified");
  }
  const gateCalls = [];
  const gateRejected = await runScopedLearningCaptureSequence({
    mode: "scoped_long",
    config: { roi: { x: 0, y: 0, width: 30, height: 40 }, scroll_scope: "page", target_pane: "page", wheel_clicks: 2, max_segments: 3 },
    capture: async () => { gateCalls.push("capture"); return scopedCaptureResponse("artifacts/gate.png"); },
    scroll: async () => { gateCalls.push("scroll"); return { success: false, error: { code: "scroll_precondition_rejected" } }; },
    compose: async () => { gateCalls.push("compose"); return { success: true }; },
  });
  assert.deepEqual(gateCalls, ["capture", "scroll"]);
  assert.equal(gateRejected.model_allowed, false);
  assert.equal(gateRejected.stop_reason, "no_effect_or_unverified");

  for (const conflictResponse of [
    {
      success: false,
      data: { result: { execution_path: { action_executed: false }, scroll_effect_validation: { status: "unknown", can_scroll_down: false } } },
    },
    {
      success: true,
      data: { result: { execution_path: { action_executed: false }, scroll_effect_validation: { status: "unknown", reached_bottom: true } } },
    },
  ]) {
    const conflictCalls = [];
    const conflict = await runScopedLearningCaptureSequence({
      mode: "scoped_long",
      config: { roi: { x: 0, y: 0, width: 30, height: 40 }, scroll_scope: "page", target_pane: "page", wheel_clicks: 2, max_segments: 3 },
      capture: async () => { conflictCalls.push("capture"); return scopedCaptureResponse("artifacts/conflict.png"); },
      scroll: async () => { conflictCalls.push("scroll"); return conflictResponse; },
      compose: async () => { conflictCalls.push("compose"); return { success: true, data: { composite_path: "artifacts/forbidden.png" } }; },
    });
    assert.deepEqual(conflictCalls, ["capture", "scroll"]);
    assert.equal(conflict.stop_reason, "no_effect_or_unverified");
    assert.equal(conflict.model_allowed, false);
    assert.equal(conflict.composite, null);
  }
});

test("runScopedLearningCaptureSequence classifies duplicate, bottom, failure, and cancellation safely", async () => {
  const { runScopedLearningCaptureSequence } = loadScopedLearningCaptureExports();
  const base = { mode: "scoped_long", config: { roi: { x: 0, y: 0, width: 30, height: 40 }, scroll_scope: "page", target_pane: "page", wheel_clicks: 2, max_segments: 3 }, compose: async () => ({ success: true, data: { composite_path: "artifacts/composite.png" } }) };
  const duplicate = await runScopedLearningCaptureSequence({ ...base, capture: async () => scopedCaptureResponse("artifacts/one.png"), scroll: async () => verifiedScopedScroll() });
  assert.equal(duplicate.stop_reason, "duplicate_segment");
  assert.equal(duplicate.model_allowed, true);
  const bottom = await runScopedLearningCaptureSequence({ ...base, capture: async () => scopedCaptureResponse("artifacts/one.png"), scroll: async () => verifiedScopedScroll({ reached_bottom: true }) });
  assert.equal(bottom.stop_reason, "reached_bottom");
  assert.equal(bottom.model_allowed, true);
  const failed = await runScopedLearningCaptureSequence({ ...base, capture: async () => ({ success: false, message: "capture failed" }), scroll: async () => verifiedScopedScroll() });
  assert.equal(failed.stop_reason, "capture_failed");
  assert.equal(failed.model_allowed, false);
  const controller = new AbortController();
  controller.abort();
  const cancelled = await runScopedLearningCaptureSequence({ ...base, signal: controller.signal, capture: async () => scopedCaptureResponse("artifacts/one.png"), scroll: async () => verifiedScopedScroll() });
  assert.equal(cancelled.stop_reason, "cancelled");
  assert.equal(cancelled.model_allowed, false);
});


function loadScopedLearningCapturePanelHarness(overrides = {}) {
  const source = require("node:fs").readFileSync(
    require("node:path").join(__dirname, "../../app/web_panel/panel.js"),
    "utf8",
  );
  const start = source.indexOf("function scopedLearningCaptureIsAbortError");
  const end = source.indexOf("async function completeLearningInterfaceReadonlyFlow", start);
  assert.notEqual(start, -1, "scoped capture panel code must exist");
  assert.notEqual(end, -1, "learning flow code must exist");
  class Element {
    constructor(value = "") { this.value = value; this.checked = false; this.hidden = false; this.textContent = ""; this.children = []; this.src = ""; this.disabled = false; }
    replaceChildren(...children) { this.children = children; }
    removeAttribute(name) { if (name === "src") this.src = ""; }
  }
  const elements = new Map();
  const element = (id, value = "") => {
    if (!elements.has(id)) elements.set(id, new Element(value));
    return elements.get(id);
  };
  const captures = [];
  const isolatedFunctions = [
    "transitionLearningWorkflowState",
    "startLearningWorkflowStageOperation",
    "runLearningStageTaskWithHeartbeat",
    "runManagedLearningStageWorker",
  ];
  let panelSource = source.slice(start, end);
  for (const name of isolatedFunctions) {
    panelSource = panelSource.replace(`async function ${name}`, `async function isolated${name}`);
  }
  panelSource = panelSource
    .replace("function learningStageContinuation(", "function isolatedLearningStageContinuation(")
    .replace("function learningStageContinuationFinished(", "function isolatedLearningStageContinuationFinished(")
    .replace("async function finishLearningWorkflowStageOperation(", "async function isolatedFinishLearningWorkflowStageOperation(");
  const prefix = `
    let learningSourceImagePath = "";
    let currentImagePath = "";
    let lastLearningDraftObserveResponse = null;
    let lastLearningDraftObserveTracePath = "";
    let lastLearningTwoStageReportPath = "";
    let lastLearningFinalStage2ReportPath = "";
    let lastLearningFinalReviewedOverlayPath = "";
    let lastLearningFusedTrialPath = "";
    let activeScopedLearningCaptureContext = null;
    let activeLearningStageTaskContext = null;
    let activeLearningStageOperation = null;
    let currentLearningWorkflowState = null;
    let currentLearningWorkflowRunId = "";
    let currentLearningInterfaceFlowStep = "bind_capture";
    let scopedLearningCaptureState = { mode: "normal", segments: [], scrolls: [], stop_reason: "", composite: null, image_path: "" };
    let scopedLearningCaptureRecommendation = null;
    function setCurrentImage(path) { currentImagePath = path || ""; }
    function setLearningSourceImagePath(path) { learningSourceImagePath = path || ""; }
    function setLearningTrialImagePath(path) { $("learningTrialImagePath").value = path || ""; }
  `;
  const sandbox = {
    AbortController,
    DOMException,
    console,
    document: { createElement: () => new Element(), querySelectorAll: () => [] },
    $: element,
    panelFileUrl: (path) => `file://${path}`,
    clearScreenUnderstandingResidualDisplays: () => {},
    setLearningInterfaceCancelEnabled: (enabled) => { element("learningInterfaceCancelBtn").disabled = !enabled; },
    resultOf: (response = {}) => response?.data?.result || response?.data || response?.result || {},
    nestedGet: (value, path) => path.reduce((next, key) => next?.[key], value),
    firstLearningSourceImagePath: (...paths) => paths.find((path) => String(path || "").trim()) || "",
    requestTimeoutSeconds: () => 30,
    statusTextForResponse: (response = {}) => response?.message || "failed",
    t: (key) => key,
    clearLearningDraftWorkspaceForNewRun: () => {},
    newLearningWorkflowRunId: () => "run-test",
    persistLearningWorkflowRunId: () => {},
    transitionLearningWorkflowState: async () => ({ revision: 1, workflow_status: "running", stages: {} }),
    bindSelectedWindow: async () => ({ success: true }),
    startLearningWorkflowStageOperation: async () => ({ operation_id: "observe-op", stage: "screen_understanding" }),
    runLearningStageTaskWithHeartbeat: async (_operation, task) => task({ signal: new AbortController().signal, operation: _operation }),
    learningStageContinuationFinished: () => true,
    learningStageContinuation: () => ({ outcome: "completed" }),
    completeLearningInterfaceReadonlyFlow: async () => ({ success: true }),
    finishLearningWorkflowStageOperation: async () => {},
    recoverLearningWorkflowState: async () => {},
    renderResponse: () => {},
    setStatus: () => {},
    syncStageProvider: () => ({ profile_id: "observe" }),
    ensureStageModelReady: async () => true,
    metadataWithPrompt: () => ({}),
    runManagedLearningStageWorker: async (kind, payload, options = {}) => {
      captures.push({ kind, payload });
      const response = {
        success: true,
        data: {
          result: {
            image_path: payload.image_path,
            observation: {
              model_io: {
                model_name: "vision:test",
                raw_response: {
                  model_json: {
                    capture_mode: "normal",
                    model_source: "vision:test",
                  },
                },
              },
            },
          },
          continuation: { outcome: "completed" },
        },
      };
      await options.onWorkerResponse?.({ taskKind: kind, response });
      return response;
    },
    api: async () => ({ success: false }),
    ...overrides,
  };
  sandbox.globalThis = sandbox;
  require("node:vm").runInNewContext(
    `${prefix}\n${panelSource}\n; globalThis.panelHarness = {
      selectedLearningCaptureMode, syncScopedLearningCaptureControls, setScopedLearningCaptureRecommendation,
      resetScopedLearningCaptureState, clearScopedLearningCaptureForNewRun, runLearningInterfaceCaptureStrategy,
      runLearningInterfaceFlow, cancelActiveLearningInterfaceFlow,
      snapshot: () => ({ state: scopedLearningCaptureState, source: learningSourceImagePath, current: currentImagePath }),
      seed: (state, sourcePath, currentPath) => { scopedLearningCaptureState = state; learningSourceImagePath = sourcePath; currentImagePath = currentPath; },
    };`,
    sandbox,
  );
  return { harness: sandbox.panelHarness, element, captures };
}

test("runScopedLearningCaptureSequence keeps cancelled after capture, scroll, or compose resolves", async () => {
  const { runScopedLearningCaptureSequence } = loadScopedLearningCaptureExports();
  for (const cancelAt of ["capture", "scroll", "compose"]) {
    const controller = new AbortController();
    let captureCount = 0;
    const result = await runScopedLearningCaptureSequence({
      mode: cancelAt === "capture" ? "normal" : "scoped_long",
      config: { roi: { x: 0, y: 0, width: 20, height: 20 }, scroll_scope: "page", target_pane: "page", wheel_clicks: 1, max_segments: 2 },
      signal: controller.signal,
      capture: async () => {
        captureCount += 1;
        if (cancelAt === "capture") controller.abort();
        return scopedCaptureResponse(`artifacts/${captureCount}.png`, `capture-${captureCount}`);
      },
      scroll: async () => {
        if (cancelAt === "scroll") controller.abort();
        return verifiedScopedScroll();
      },
      compose: async () => {
        if (cancelAt === "compose") controller.abort();
        return { success: true, data: { composite_path: "artifacts/composite.png" } };
      },
    });
    assert.equal(result.stop_reason, "cancelled", cancelAt);
    assert.equal(result.model_allowed, false, cancelAt);
  }
});

test("runScopedLearningCaptureSequence prioritizes explicit bottom and composes accepted segments", async () => {
  const { runScopedLearningCaptureSequence } = loadScopedLearningCaptureExports();
  const calls = [];
  const result = await runScopedLearningCaptureSequence({
    mode: "scoped_long",
    config: { roi: { x: 0, y: 0, width: 20, height: 20 }, scroll_scope: "page", target_pane: "page", wheel_clicks: 1, max_segments: 3 },
    capture: async () => { calls.push("capture"); return scopedCaptureResponse("artifacts/one.png"); },
    scroll: async () => { calls.push("scroll"); return verifiedScopedScroll({ status: "unknown", can_scroll_down: false }); },
    compose: async () => { calls.push("compose"); return { success: true, data: { composite_path: "artifacts/composite.png" } }; },
  });
  assert.deepEqual(calls, ["capture", "scroll", "compose"]);
  assert.equal(result.stop_reason, "reached_bottom");
  assert.equal(result.model_allowed, true);
});

test("runScopedLearningCaptureSequence publishes capture, scroll verification, compose, and safe-stop phases", async () => {
  const { runScopedLearningCaptureSequence } = loadScopedLearningCaptureExports();
  const phases = [];
  const success = await runScopedLearningCaptureSequence({
    mode: "scoped_long",
    config: { roi: { x: 0, y: 0, width: 20, height: 20 }, scroll_scope: "page", target_pane: "page", wheel_clicks: 1, max_segments: 2 },
    capture: async () => scopedCaptureResponse(`artifacts/${phases.length}.png`, `capture-${phases.length}`),
    scroll: async () => verifiedScopedScroll(),
    compose: async () => ({ success: true, data: { composite_path: "artifacts/composite.png" } }),
    onProgress: (state) => phases.push(state.phase),
  });
  assert.equal(success.phase, "completed");
  assert.equal(phases.includes("capture"), true);
  assert.equal(phases.includes("scroll_verification"), true);
  assert.equal(phases.includes("compose"), true);
  const stopped = await runScopedLearningCaptureSequence({
    mode: "scoped_long",
    config: { roi: { x: 0, y: 0, width: 20, height: 20 }, scroll_scope: "page", target_pane: "page", wheel_clicks: 1, max_segments: 2 },
    capture: async () => scopedCaptureResponse("artifacts/stop.png"),
    scroll: async () => verifiedScopedScroll({ status: "unknown" }),
    compose: async () => ({ success: true }),
  });
  assert.equal(stopped.phase, "safe_stopped");
});

test("invalid scoped capture parameters publish a safe-stopped panel phase", async () => {
  const { harness, element } = loadScopedLearningCapturePanelHarness();
  element("learningCaptureModeScopedLong").checked = true;
  element("learningScopedCaptureConfirmed").checked = false;

  const result = await harness.runLearningInterfaceCaptureStrategy();

  assert.equal(result.stop_reason, "invalid_scoped_capture");
  assert.equal(result.phase, "safe_stopped");
  assert.equal(result.model_allowed, false);
  assert.match(element("learningScopedCaptureStatus").textContent, /safe_stopped/);
});

test("scoped capture panel behavior switches modes, preserves human choice, clears before bind failure, and sends composite to observe", async () => {
  const apiCalls = [];
  let bindCount = 0;
  const { harness, element, captures } = loadScopedLearningCapturePanelHarness({
    bindSelectedWindow: async () => ({ success: bindCount++ > 0 }),
    api: async (method, path) => {
      apiCalls.push(path);
      if (path === "/state/capture_window") {
        const count = apiCalls.filter((item) => item === path).length;
        return scopedCaptureResponse(`artifacts/segment-${count}.png`, `capture-${count}`);
      }
      if (path === "/action/scroll") return verifiedScopedScroll();
      if (path === "/panel/compose_scoped_learning_capture") return { success: true, data: { composite_path: "artifacts/composite.png", manifest_path: "artifacts/manifest.json", artifact_is_authorization: false, historical_coordinates_are_priors: true } };
      return { success: false };
    },
  });
  element("learningCaptureModeNormal").checked = true;
  element("learningCaptureModeScopedLong").checked = false;
  element("learningScopedCaptureFields").hidden = false;
  harness.syncScopedLearningCaptureControls();
  assert.equal(element("learningScopedCaptureFields").hidden, true);
  element("learningCaptureModeNormal").checked = false;
  element("learningCaptureModeScopedLong").checked = true;
  element("learningScopedCaptureConfirmed").checked = true;
  element("learningScopedCaptureRoiX").value = "0";
  element("learningScopedCaptureRoiY").value = "0";
  element("learningScopedCaptureRoiWidth").value = "20";
  element("learningScopedCaptureRoiHeight").value = "20";
  element("learningScopedCaptureWheelClicks").value = "1";
  element("learningScopedCaptureMaxSegments").value = "2";
  harness.syncScopedLearningCaptureControls();
  assert.equal(element("learningScopedCaptureFields").hidden, false);
  assert.equal(harness.selectedLearningCaptureMode(), "scoped_long");
  assert.match(element("learningCaptureRecommendation").textContent, /未评估/);

  harness.seed({ mode: "scoped_long", segments: [{ image_path: "old.png" }], composite: { composite_path: "old-composite.png" }, image_path: "old-composite.png" }, "old-composite.png", "old-composite.png");
  const failed = await harness.runLearningInterfaceFlow();
  assert.equal(failed, null);
  assert.equal(harness.snapshot().state.segments.length, 0);
  assert.equal(harness.snapshot().source, "");
  assert.equal(harness.snapshot().current, "");

  const succeeded = await harness.runLearningInterfaceFlow();
  assert.equal(succeeded.success, true, JSON.stringify(succeeded));
  assert.deepEqual(apiCalls, ["/state/capture_window", "/action/scroll", "/state/capture_window", "/panel/compose_scoped_learning_capture"]);
  const observe = captures.find((item) => item.kind === "vision_observe_screen");
  assert.equal(observe.payload.image_path, "artifacts/composite.png");
  assert.equal(observe.payload.capture_live, false);
  assert.equal(harness.selectedLearningCaptureMode(), "scoped_long");
  assert.match(element("learningCaptureRecommendation").textContent, /vision:test/);
  assert.match(element("learningCaptureRecommendation").textContent, /普通截图/);
});

test("scoped capture panel cancellation wins while capture, scroll, or compose is in flight", async () => {
  for (const targetPath of ["/state/capture_window", "/action/scroll", "/panel/compose_scoped_learning_capture"]) {
    let resolveRequest;
    const pending = new Promise((resolve) => { resolveRequest = resolve; });
    const { harness, element } = loadScopedLearningCapturePanelHarness({
      api: async (_method, path) => {
        if (path !== targetPath) {
          if (path === "/state/capture_window") return scopedCaptureResponse(`artifacts/${Math.random()}.png`, path);
          if (path === "/action/scroll") return verifiedScopedScroll();
          if (path === "/panel/compose_scoped_learning_capture") return { success: true, data: { composite_path: "artifacts/composite.png" } };
        }
        return pending;
      },
    });
    element("learningCaptureModeScopedLong").checked = true;
    element("learningScopedCaptureConfirmed").checked = true;
    element("learningScopedCaptureRoiX").value = "0";
    element("learningScopedCaptureRoiY").value = "0";
    element("learningScopedCaptureRoiWidth").value = "20";
    element("learningScopedCaptureRoiHeight").value = "20";
    element("learningScopedCaptureWheelClicks").value = "1";
    element("learningScopedCaptureMaxSegments").value = "2";
    const run = harness.runLearningInterfaceCaptureStrategy();
    await new Promise((resolve) => setImmediate(resolve));
    const cancelled = await harness.cancelActiveLearningInterfaceFlow();
    assert.equal(cancelled.cancelled, true, targetPath);
    if (targetPath === "/state/capture_window") resolveRequest(scopedCaptureResponse("artifacts/cancelled.png"));
    else if (targetPath === "/action/scroll") resolveRequest(verifiedScopedScroll());
    else resolveRequest({ success: true, data: { composite_path: "artifacts/cancelled-composite.png" } });
    const result = await run;
    assert.equal(result.stop_reason, "cancelled", targetPath);
    assert.equal(result.model_allowed, false, targetPath);
  }
});
