const test = require("node:test");
const assert = require("node:assert/strict");

const {
  createEmptyInterfaceWorkflowReview,
  createLatestInterfaceWorkflowLoadGuard,
  createInterfaceWorkflowWorkbenchState,
  createInterfaceWorkflowReviewState,
  interfaceWorkflowControlChoices,
  mergeEditableWorkflowReview,
  userFacingLearningLabel,
} = require("../../app/web_panel/learning_workflow_review.js");

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

test("missing evidence clears the previous image and details", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());
  state.select("node_detail");

  const missing = state.select("node_missing");

  assert.equal(missing.active_image_path, "");
  assert.equal(missing.available_layers.length, 0);
  assert.deepEqual(missing.node.page_details, {});
  assert.equal(missing.evidence_status, "screenshot_missing");
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
