const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildInterfaceWorkflowTopology,
  layoutInterfaceWorkflowTopology,
  fitInterfaceWorkflowLayout,
  interfaceWorkflowEdgeGeometry,
  interfaceWorkflowEdgeLabelPose,
  interfaceWorkflowEdgeLabelLayout,
  createInterfaceWorkflowSimulation,
  interfaceWorkflowHoverProjection,
  hitTestInterfaceWorkflowNode,
  resolveInterfaceWorkflowTargetEvidence,
  interfaceWorkflowNodePresentation,
  interfaceWorkflowNodeDiameter,
} = require("../../app/web_panel/interface_workflow_graph.js");

function branchingGraph() {
  return {
    workflow: { entry_node_id: "home" },
    nodes: [
      {
        node_id: "home",
        label: "Home",
        surface_type: "job_search_results",
        evidence_status: "ready",
        review_status: "human_reviewed",
        evidence: {
          fused_overlay_path: "artifacts/review-overlays/home.png",
        },
        selected: true,
        controls: [
          { control_id: "detail_button", label: "Details", role: "button" },
          { control_id: "filter_button", label: "Filters", role: "button" },
        ],
      },
      { node_id: "detail", label: "Detail" },
      { node_id: "filters", label: "Filters" },
    ],
    edges: [
      {
        edge_id: "open_detail",
        source_node_id: "home",
        target_node_id: "detail",
        display_name: "Open detail",
        action_type: "open_detail",
        target_control_id: "detail_button",
      },
      {
        edge_id: "open_filters",
        source_node_id: "home",
        target_node_id: "filters",
        display_name: "Open filters",
        action_type: "open_detail",
        target_control_id: "filter_button",
      },
    ],
  };
}

function cyclicGraph() {
  return {
    workflow: { entry_node_id: "home" },
    nodes: [
      { node_id: "home", label: "Home" },
      { node_id: "detail", label: "Detail" },
    ],
    edges: [
      {
        edge_id: "open_detail",
        source_node_id: "home",
        target_node_id: "detail",
        display_name: "Open detail",
      },
      {
        edge_id: "back_home",
        source_node_id: "detail",
        target_node_id: "home",
        display_name: "Back",
      },
      {
        edge_id: "refresh_home",
        source_node_id: "home",
        target_node_id: "home",
        display_name: "Refresh",
      },
    ],
  };
}

test("projects operations as direct labelled links between interface nodes", () => {
  const topology = buildInterfaceWorkflowTopology(branchingGraph());

  assert.deepEqual(
    topology.nodes.map((node) => node.ref_id),
    ["home", "detail", "filters"],
  );
  assert.equal(topology.nodes.every((node) => node.kind === "interface"), true);
  assert.deepEqual(
    topology.links.map((link) => ({
      source_id: link.source_id,
      target_id: link.target_id,
      label: link.label,
      action_type: link.action_type,
    })),
    [
      {
        source_id: "interface::home",
        target_id: "interface::detail",
        label: "Open detail",
        action_type: "open_detail",
      },
      {
        source_id: "interface::home",
        target_id: "interface::filters",
        label: "Open filters",
        action_type: "open_detail",
      },
    ],
  );
  assert.equal(topology.entry_node_id, "home");
});

test("projects interface review metadata for readable graph cards", () => {
  const topology = buildInterfaceWorkflowTopology(branchingGraph());
  const home = topology.nodes.find((node) => node.id === "interface::home");

  assert.equal(home.surface_type, "job_search_results");
  assert.equal(home.evidence_status, "ready");
  assert.equal(home.review_status, "human_reviewed");
  assert.equal(home.control_count, 2);
  assert.equal(home.outgoing_count, 2);
  assert.equal(home.evidence_path, "artifacts/review-overlays/home.png");
});

test("builds concise interface node copy without child-node presentation", () => {
  const topology = buildInterfaceWorkflowTopology(branchingGraph());
  const home = topology.nodes.find((node) => node.id === "interface::home");

  assert.deepEqual(interfaceWorkflowNodePresentation(home), {
    title: "Home",
    subtitle: "job_search_results",
    meta: "2 个控件 · 2 条路径",
    status: "已审核",
    status_tone: "reviewed",
  });
});

test("focused interface keeps the complete software workflow visible", () => {
  const graph = branchingGraph();
  graph.edges.push({
    edge_id: "back_home",
    source_node_id: "detail",
    target_node_id: "home",
    display_name: "Back",
    action_type: "navigate_back",
  });
  graph.focus = { node_id: "detail", control_id: "" };

  const topology = buildInterfaceWorkflowTopology(graph);

  assert.deepEqual(
    topology.nodes.map((node) => node.ref_id),
    ["home", "detail", "filters"],
  );
  assert.deepEqual(
    topology.links.map((link) => link.ref_id),
    ["open_detail", "open_filters", "back_home"],
  );
  assert.equal(topology.entry_node_id, "detail");
});

test("focused control does not hide interfaces or paths", () => {
  const graph = branchingGraph();
  graph.focus = { node_id: "home", control_id: "detail_button" };

  const topology = buildInterfaceWorkflowTopology(graph);

  assert.equal(topology.nodes.every((node) => node.kind === "interface"), true);
  assert.deepEqual(
    topology.links.map((link) => link.ref_id),
    ["open_detail", "open_filters"],
  );
  assert.equal(topology.nodes.some((node) => node.id === "interface::detail"), true);
  assert.equal(topology.nodes.some((node) => node.id === "interface::filters"), true);
});

test("sizes interface nodes by evidence and graph importance within readable bounds", () => {
  const topology = buildInterfaceWorkflowTopology(branchingGraph());
  const home = topology.nodes.find((node) => node.ref_id === "home");
  const detail = topology.nodes.find((node) => node.ref_id === "detail");

  assert.ok(interfaceWorkflowNodeDiameter(home) > interfaceWorkflowNodeDiameter(detail));
  assert.ok(interfaceWorkflowNodeDiameter(home) <= 132);
  assert.ok(interfaceWorkflowNodeDiameter(detail) >= 74);
});

test("keeps high-content interface nodes visually distinct instead of saturating at one size", () => {
  const medium = interfaceWorkflowNodeDiameter({
    control_count: 60,
    outgoing_count: 1,
    incoming_count: 0,
  });
  const dense = interfaceWorkflowNodeDiameter({
    control_count: 100,
    outgoing_count: 1,
    incoming_count: 0,
  });

  assert.ok(dense > medium);
});

test("reuses a shared target interface instead of duplicating it", () => {
  const graph = branchingGraph();
  graph.edges[1].target_node_id = "detail";

  const topology = buildInterfaceWorkflowTopology(graph);

  assert.equal(
    topology.nodes.filter((node) => node.kind === "interface" && node.ref_id === "detail").length,
    1,
  );
  assert.equal(
    topology.links.filter((link) => link.target_id === "interface::detail").length,
    2,
  );
});

test("drops dangling links without inventing missing interface nodes", () => {
  const graph = branchingGraph();
  graph.edges.push({
    edge_id: "dangling",
    source_node_id: "home",
    target_node_id: "missing",
    display_name: "Broken",
  });

  const topology = buildInterfaceWorkflowTopology(graph);

  assert.equal(topology.nodes.some((node) => node.id === "interface::missing"), false);
  assert.equal(topology.links.some((link) => link.id.includes("dangling")), false);
});

test("places the selected interface in the centre and neighbours on a radial ring", () => {
  const layout = layoutInterfaceWorkflowTopology(
    buildInterfaceWorkflowTopology(branchingGraph()),
    { width: 720, height: 520 },
  );
  const home = layout.nodes.find((node) => node.id === "interface::home");
  const detail = layout.nodes.find((node) => node.id === "interface::detail");
  const filters = layout.nodes.find((node) => node.id === "interface::filters");

  assert.deepEqual({ x: home.x, y: home.y }, { x: 360, y: 260 });
  assert.ok(Math.hypot(detail.x - home.x, detail.y - home.y) >= 150);
  assert.ok(Math.hypot(filters.x - home.x, filters.y - home.y) >= 150);
  assert.notDeepEqual({ x: detail.x, y: detail.y }, { x: filters.x, y: filters.y });
  assert.ok(home.width > detail.width);
  assert.equal(home.width, home.height);
  assert.equal(layout.nodes.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y)), true);
});

test("settles the same workflow into the same deterministic force layout", () => {
  const topology = buildInterfaceWorkflowTopology(branchingGraph());
  const first = createInterfaceWorkflowSimulation(topology, { width: 720, height: 520 });
  const second = createInterfaceWorkflowSimulation(topology, { width: 720, height: 520 });

  first.runToCompletion(360);
  second.runToCompletion(360);

  const firstPositions = first.layout.nodes.map((node) => ({
    id: node.id,
    x: Number(node.x.toFixed(3)),
    y: Number(node.y.toFixed(3)),
  }));
  const secondPositions = second.layout.nodes.map((node) => ({
    id: node.id,
    x: Number(node.x.toFixed(3)),
    y: Number(node.y.toFixed(3)),
  }));
  const entry = first.layout.nodes.find((node) => node.id === "interface::home");

  assert.deepEqual(firstPositions, secondPositions);
  assert.deepEqual(
    { x: Number(entry.x.toFixed(3)), y: Number(entry.y.toFixed(3)) },
    { x: 360, y: 260 },
  );
  assert.equal(first.layout.nodes.every((node) => (
    Number.isFinite(node.x)
    && Number.isFinite(node.y)
    && Number.isFinite(node.vx)
    && Number.isFinite(node.vy)
  )), true);
  assert.equal(first.isSettled(), true);
});

test("force layout keeps interface nodes separated after settling", () => {
  const topology = buildInterfaceWorkflowTopology(branchingGraph());
  const simulation = createInterfaceWorkflowSimulation(topology, { width: 720, height: 520 });

  simulation.runToCompletion(360);

  for (let leftIndex = 0; leftIndex < simulation.layout.nodes.length; leftIndex += 1) {
    for (
      let rightIndex = leftIndex + 1;
      rightIndex < simulation.layout.nodes.length;
      rightIndex += 1
    ) {
      const left = simulation.layout.nodes[leftIndex];
      const right = simulation.layout.nodes[rightIndex];
      assert.ok(
        Math.hypot(left.x - right.x, left.y - right.y) >= 100,
        `${left.id} overlaps ${right.id}`,
      );
    }
  }
});

test("hover projection highlights only the hovered interface and one-hop neighbours", () => {
  const graph = branchingGraph();
  graph.nodes.push({ node_id: "orphan", label: "Orphan" });
  const layout = layoutInterfaceWorkflowTopology(
    buildInterfaceWorkflowTopology(graph),
    { width: 720, height: 520 },
  );

  const projection = interfaceWorkflowHoverProjection(layout, "interface::detail");

  assert.deepEqual(
    projection.highlighted_node_ids.sort(),
    ["interface::detail", "interface::home"],
  );
  assert.deepEqual(projection.highlighted_link_ids, ["transition::open_detail"]);
  assert.deepEqual(
    projection.dimmed_node_ids.sort(),
    ["interface::filters", "interface::orphan"],
  );
  assert.deepEqual(projection.dimmed_link_ids, ["transition::open_filters"]);
});

test("hover projection does not mutate workflow layout state", () => {
  const layout = layoutInterfaceWorkflowTopology(
    buildInterfaceWorkflowTopology(branchingGraph()),
    { width: 720, height: 520 },
  );
  const before = JSON.stringify(layout);

  interfaceWorkflowHoverProjection(layout, "interface::home");

  assert.equal(JSON.stringify(layout), before);
});

test("keeps cycles and self-loops finite and hit-testable", () => {
  const layout = layoutInterfaceWorkflowTopology(
    buildInterfaceWorkflowTopology(cyclicGraph()),
    { width: 720, height: 520 },
  );
  const target = layout.nodes.find((node) => node.id === "interface::home");

  assert.equal(layout.nodes.length, 2);
  assert.equal(layout.links.length, 3);
  assert.equal(layout.nodes.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y)), true);
  assert.equal(
    hitTestInterfaceWorkflowNode(layout, { x: target.x, y: target.y }).id,
    target.id,
  );
});

test("appends disconnected interfaces without overlapping reachable nodes", () => {
  const graph = branchingGraph();
  graph.nodes.push({ node_id: "orphan", label: "Orphan" });

  const layout = layoutInterfaceWorkflowTopology(
    buildInterfaceWorkflowTopology(graph),
    { width: 720, height: 520 },
  );
  const orphan = layout.nodes.find((node) => node.id === "interface::orphan");
  const occupied = layout.nodes.filter((node) => node.id !== orphan.id);

  assert.equal(
    occupied.some((node) => (
      Math.abs(node.x - orphan.x) < (node.width + orphan.width) / 2
      && Math.abs(node.y - orphan.y) < (node.height + orphan.height) / 2
    )),
    false,
  );
});

test("fits radial graph bounds into the viewport without losing its centre", () => {
  const transform = fitInterfaceWorkflowLayout(
    { x: -120, y: -80, width: 960, height: 720 },
    { width: 720, height: 520 },
    24,
  );

  assert.ok(transform.zoom > 0 && transform.zoom <= 1);
  assert.ok(Number.isFinite(transform.pan.x));
  assert.ok(Number.isFinite(transform.pan.y));
  assert.equal(
    Math.round((-120 + 960 / 2) * transform.zoom + transform.pan.x),
    360,
  );
  assert.equal(
    Math.round((-80 + 720 / 2) * transform.zoom + transform.pan.y),
    260,
  );
});

test("connects radial links at the facing edges of circular interface nodes", () => {
  const vertical = interfaceWorkflowEdgeGeometry(
    { x: 100, y: 100, width: 96, height: 96 },
    { x: 100, y: 300, width: 96, height: 96 },
  );
  const horizontal = interfaceWorkflowEdgeGeometry(
    { x: 100, y: 100, width: 96, height: 96 },
    { x: 300, y: 100, width: 96, height: 96 },
  );

  assert.deepEqual(vertical.start, { x: 100, y: 148 });
  assert.deepEqual(vertical.end, { x: 100, y: 252 });
  assert.deepEqual(horizontal.start, { x: 148, y: 100 });
  assert.deepEqual(horizontal.end, { x: 252, y: 100 });
});

test("places edge labels above and parallel to the arrow path", () => {
  const pose = interfaceWorkflowEdgeLabelPose(
    { x: 100, y: 100, width: 96, height: 96 },
    { x: 300, y: 100, width: 96, height: 96 },
  );

  assert.equal(pose.angle, 0);
  assert.equal(pose.x, 200);
  assert.ok(pose.y < 100);
});

test("keeps reverse edge labels readable instead of upside down", () => {
  const pose = interfaceWorkflowEdgeLabelPose(
    { x: 300, y: 100, width: 96, height: 96 },
    { x: 100, y: 100, width: 96, height: 96 },
  );

  assert.ok(pose.angle >= -Math.PI / 2);
  assert.ok(pose.angle <= Math.PI / 2);
  assert.ok(pose.y < 100);
});

test("sizes edge labels to the clear span between circular nodes", () => {
  const longLink = interfaceWorkflowEdgeLabelLayout(
    { x: 100, y: 100, width: 96, height: 96 },
    { x: 400, y: 100, width: 96, height: 96 },
  );
  const mediumLink = interfaceWorkflowEdgeLabelLayout(
    { x: 100, y: 100, width: 96, height: 96 },
    { x: 250, y: 100, width: 96, height: 96 },
  );

  assert.equal(longLink.visible, true);
  assert.equal(longLink.max_width, 112);
  assert.equal(longLink.font_size, 8);
  assert.equal(mediumLink.visible, true);
  assert.ok(mediumLink.max_width < longLink.max_width);
  assert.ok(mediumLink.font_size < longLink.font_size);
});

test("hides an edge label when circular nodes leave no readable clear span", () => {
  const layout = interfaceWorkflowEdgeLabelLayout(
    { x: 100, y: 100, width: 96, height: 96 },
    { x: 220, y: 100, width: 96, height: 96 },
  );

  assert.equal(layout.visible, false);
  assert.ok(layout.max_width < 24);
});

test("resolves an operation target control into screenshot-relative evidence", () => {
  const node = {
    evidence: {
      viewport_size: { width: 1200, height: 800 },
    },
    controls: [
      {
        control_id: "open_detail_button",
        bbox: { x: 900, y: 620, w: 180, h: 60 },
      },
    ],
  };
  const operation = {
    edge_id: "edge_open",
    target_control_id: "open_detail_button",
  };

  const evidence = resolveInterfaceWorkflowTargetEvidence(node, operation);

  assert.deepEqual(evidence.bbox, { x: 900, y: 620, width: 180, height: 60 });
  assert.deepEqual(evidence.viewport, { width: 1200, height: 800 });
  assert.deepEqual(evidence.normalized, {
    left: 0.75,
    top: 0.775,
    width: 0.15,
    height: 0.075,
  });
});

test("refuses to invent target evidence when bbox or viewport is missing", () => {
  assert.equal(
    resolveInterfaceWorkflowTargetEvidence(
      { controls: [{ control_id: "button_1", bbox: { x: 10, y: 20, w: 30, h: 40 } }] },
      { target_control_id: "button_1" },
    ),
    null,
  );
  assert.equal(
    resolveInterfaceWorkflowTargetEvidence(
      { evidence: { viewport_size: { width: 100, height: 100 } }, controls: [] },
      { target_control_id: "missing_button" },
    ),
    null,
  );
});

test("uses the loaded screenshot dimensions as a verified viewport override", () => {
  const evidence = resolveInterfaceWorkflowTargetEvidence(
    {
      regions: [
        {
          region_id: "filter_button",
          bbox: [900, 620, 180, 60],
        },
      ],
    },
    {
      target_region_id: "filter_button",
    },
    {
      width: 1200,
      height: 800,
    },
  );

  assert.deepEqual(evidence.viewport, { width: 1200, height: 800 });
  assert.equal(evidence.normalized.left, 0.75);
});
