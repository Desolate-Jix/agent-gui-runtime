const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildInterfaceWorkflowTopology,
  layoutInterfaceWorkflowTopology,
  hitTestInterfaceWorkflowNode,
} = require("../../app/web_panel/interface_workflow_graph.js");

function branchingGraph() {
  return {
    workflow: { entry_node_id: "home" },
    nodes: [
      { node_id: "home", label: "Home", selected: true },
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
      },
      {
        edge_id: "open_filters",
        source_node_id: "home",
        target_node_id: "filters",
        display_name: "Open filters",
        action_type: "open_detail",
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

test("projects one interface with multiple operations into separate branches", () => {
  const topology = buildInterfaceWorkflowTopology(branchingGraph());

  assert.deepEqual(
    topology.nodes.filter((node) => node.kind === "operation").map((node) => node.ref_id),
    ["open_detail", "open_filters"],
  );
  assert.equal(topology.links.length, 4);
  assert.equal(topology.entry_node_id, "home");
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
  assert.equal(topology.nodes.some((node) => node.id === "operation::dangling"), false);
  assert.equal(topology.links.some((link) => link.id.includes("dangling")), false);
});

test("places interface and operation nodes in alternating outward layers", () => {
  const layout = layoutInterfaceWorkflowTopology(
    buildInterfaceWorkflowTopology(branchingGraph()),
    { width: 720, height: 520 },
  );
  const home = layout.nodes.find((node) => node.id === "interface::home");
  const detailAction = layout.nodes.find((node) => node.id === "operation::open_detail");
  const detail = layout.nodes.find((node) => node.id === "interface::detail");

  assert.ok(home.x < detailAction.x);
  assert.ok(detailAction.x < detail.x);
  assert.equal(layout.nodes.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y)), true);
});

test("keeps cycles and self-loops finite and hit-testable", () => {
  const layout = layoutInterfaceWorkflowTopology(
    buildInterfaceWorkflowTopology(cyclicGraph()),
    { width: 720, height: 520 },
  );
  const target = layout.nodes.find((node) => node.id === "operation::refresh_home");

  assert.equal(layout.nodes.length, 5);
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
