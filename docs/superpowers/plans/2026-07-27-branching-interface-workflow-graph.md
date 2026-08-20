# Branching Interface Workflow Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three-column review workbench's linear interface list with an interactive branching graph that renders `interface -> operation -> target interface` relationships and keeps graph selection synchronized with evidence and operation editing.

**Architecture:** Add a small browser/Node-compatible topology module that projects the existing `single_application_workflow_review_v1` `nodes + edges` into interface and operation view nodes, computes a deterministic layered diffusion layout, and performs hit testing. `panel.js` owns only DOM/canvas lifecycle and maps graph clicks back to the existing review state, so there is no second persisted graph model.

**Tech Stack:** Vanilla JavaScript, Canvas 2D, existing HTML/CSS panel, Node built-in test runner, pytest/FastAPI panel tests.

## Global Constraints

- Reuse `single_application_workflow_review_v1`; do not create a second persisted graph contract.
- Interface view nodes come from `review.nodes`; operation view nodes are projections of `review.edges`.
- Render `interface -> operation -> target interface`, including one-to-many branches, shared targets, cycles, self-loops, and independent `needs_learning` targets.
- Clicking an interface selects its evidence; clicking an operation selects its source interface and that exact edge in the operation editor.
- The graph is display/review only: no runtime click coordinates, Execute authorization, live click, fill, or submit.
- Every edge must retain a valid `target_node_id`; unknown destinations use explicit placeholder interface nodes.
- Preserve UTF-8 Chinese text and the current unrelated dirty worktree.

---

### Task 1: Pure Topology Projection And Layout

**Files:**
- Create: `app/web_panel/interface_workflow_graph.js`
- Create: `tests/js/interface_workflow_graph.test.cjs`

**Interfaces:**
- Consumes: `{ workflow, nodes, edges }` returned by `InterfaceWorkflowReviewState.graph()`.
- Produces:
  - `buildInterfaceWorkflowTopology(graph): { entry_node_id, nodes, links }`
  - `layoutInterfaceWorkflowTopology(topology, viewport): { nodes, links, bounds }`
  - `hitTestInterfaceWorkflowNode(layout, point): LayoutNode | null`
- Interface topology node IDs use `interface::<node_id>`.
- Operation topology node IDs use `operation::<edge_id>`.

- [ ] **Step 1: Write failing projection tests**

```javascript
test("projects one interface with multiple operations into separate branches", () => {
  const topology = buildInterfaceWorkflowTopology({
    workflow: { entry_node_id: "home" },
    nodes: [
      { node_id: "home", label: "Home" },
      { node_id: "detail", label: "Detail" },
      { node_id: "filters", label: "Filters" },
    ],
    edges: [
      { edge_id: "open_detail", source_node_id: "home", target_node_id: "detail", display_name: "Open detail" },
      { edge_id: "open_filters", source_node_id: "home", target_node_id: "filters", display_name: "Open filters" },
    ],
  });

  assert.deepEqual(
    topology.nodes.filter((node) => node.kind === "operation").map((node) => node.ref_id),
    ["open_detail", "open_filters"],
  );
  assert.equal(topology.links.length, 4);
});
```

```javascript
test("reuses a shared target interface instead of duplicating it", () => {
  const topology = buildInterfaceWorkflowTopology(sharedTargetFixture());
  assert.equal(
    topology.nodes.filter((node) => node.kind === "interface" && node.ref_id === "detail").length,
    1,
  );
});
```

- [ ] **Step 2: Run projection tests and verify RED**

Run:

```powershell
node --test tests\js\interface_workflow_graph.test.cjs
```

Expected: FAIL because `interface_workflow_graph.js` and its exports do not exist.

- [ ] **Step 3: Implement the topology projection**

Implement a UMD-style module compatible with both browser globals and `module.exports`:

```javascript
(function attachInterfaceWorkflowGraph(globalScope) {
  "use strict";

  function buildInterfaceWorkflowTopology(graph = {}) {
    const interfaceNodes = (graph.nodes || []).map((node) => ({
      id: `interface::${node.node_id}`,
      kind: "interface",
      ref_id: node.node_id,
      label: node.label || node.node_id,
      surface_type: node.surface_type || "unknown_surface",
      evidence_status: node.evidence_status || "unknown",
      selected: node.selected === true,
    }));
    const operationNodes = (graph.edges || []).map((edge) => ({
      id: `operation::${edge.edge_id}`,
      kind: "operation",
      ref_id: edge.edge_id,
      source_node_id: edge.source_node_id,
      target_node_id: edge.target_node_id,
      label: edge.display_name || edge.action_type || edge.edge_id,
      action_type: edge.action_type || "unknown_action",
      review_status: edge.review_status || "needs_human_review",
    }));
    const links = (graph.edges || []).flatMap((edge) => [
      {
        id: `source::${edge.edge_id}`,
        source_id: `interface::${edge.source_node_id}`,
        target_id: `operation::${edge.edge_id}`,
        kind: "source_operation",
      },
      {
        id: `target::${edge.edge_id}`,
        source_id: `operation::${edge.edge_id}`,
        target_id: `interface::${edge.target_node_id}`,
        kind: "operation_target",
      },
    ]);
    return {
      entry_node_id: String(graph.workflow?.entry_node_id || ""),
      nodes: [...interfaceNodes, ...operationNodes],
      links,
    };
  }
}
```

Filter links whose source or target interface does not exist rather than inventing a node; backend validation remains authoritative.

- [ ] **Step 4: Run projection tests and verify GREEN**

Run:

```powershell
node --test tests\js\interface_workflow_graph.test.cjs
```

Expected: projection tests PASS.

- [ ] **Step 5: Write failing layout and hit-test tests**

Cover:

```javascript
test("places interface and operation nodes in alternating outward layers", () => {
  const layout = layoutInterfaceWorkflowTopology(
    buildInterfaceWorkflowTopology(branchingFixture()),
    { width: 720, height: 520 },
  );
  const home = layout.nodes.find((node) => node.id === "interface::home");
  const detailAction = layout.nodes.find((node) => node.id === "operation::open_detail");
  const detail = layout.nodes.find((node) => node.id === "interface::detail");
  assert.ok(home.x < detailAction.x);
  assert.ok(detailAction.x < detail.x);
});
```

```javascript
test("keeps cycles and self-loops finite and hit-testable", () => {
  const layout = layoutInterfaceWorkflowTopology(
    buildInterfaceWorkflowTopology(cyclicFixture()),
    { width: 720, height: 520 },
  );
  assert.equal(layout.nodes.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y)), true);
  const target = layout.nodes[0];
  assert.equal(hitTestInterfaceWorkflowNode(layout, { x: target.x, y: target.y }).id, target.id);
});
```

- [ ] **Step 6: Run layout tests and verify RED**

Run:

```powershell
node --test tests\js\interface_workflow_graph.test.cjs
```

Expected: FAIL because layout and hit testing are not implemented.

- [ ] **Step 7: Implement deterministic diffusion layout and hit testing**

Use breadth-first graph distance from `interface::<entry_node_id>`:

- interface layers are even indexes;
- operation layers are odd indexes;
- already visited nodes are not relayered by cycles;
- disconnected interface nodes are appended after reachable layers;
- nodes within each layer are vertically distributed;
- self-loop links remain links between the interface and its operation node, then back to the same interface;
- node dimensions are stable by kind.

Return layout nodes with:

```javascript
{
  id,
  kind,
  ref_id,
  x,
  y,
  width,
  height,
  label,
  source_node_id,
  target_node_id,
}
```

Hit testing must use the node rectangle and return the topmost matching node.

- [ ] **Step 8: Run all topology tests**

Run:

```powershell
node --test tests\js\interface_workflow_graph.test.cjs
```

Expected: all tests PASS.

- [ ] **Step 9: Commit Task 1**

```powershell
git add app\web_panel\interface_workflow_graph.js tests\js\interface_workflow_graph.test.cjs
git commit -m "feat: add interface workflow topology layout"
```

---

### Task 2: Canvas Surface And Static Panel Contract

**Files:**
- Modify: `app/web_panel/index.html`
- Modify: `app/web_panel/panel.css`
- Modify: `tests/test_web_panel_route.py`

**Interfaces:**
- Consumes: browser global `InterfaceWorkflowGraph`.
- Produces DOM IDs:
  - `interfaceWorkflowGraphCanvas`
  - `interfaceWorkflowGraphEmpty`
  - `interfaceWorkflowGraphZoomOut`
  - `interfaceWorkflowGraphZoomIn`
  - `interfaceWorkflowGraphReset`

- [ ] **Step 1: Replace the old static assertions with failing canvas assertions**

Update `test_web_panel_route.py` to require:

```python
assert 'src="/static/interface_workflow_graph.js"' in html
assert 'id="interfaceWorkflowGraphCanvas"' in html
assert 'id="interfaceWorkflowGraphZoomOut"' in html
assert 'id="interfaceWorkflowGraphZoomIn"' in html
assert 'id="interfaceWorkflowGraphReset"' in html
assert "下一界面尚未加入" not in panel_js
```

Also require that the graph panel subtitle describes branching:

```python
assert "界面、操作与跳转关系" in html
```

- [ ] **Step 2: Run the focused route test and verify RED**

Run:

```powershell
uv run pytest tests\test_web_panel_route.py -q
```

Expected: FAIL because the canvas and graph script are absent and the linear renderer remains.

- [ ] **Step 3: Add script, canvas markup, and compact graph controls**

Load `interface_workflow_graph.js` before `panel.js`.

Replace the contents of `interfaceWorkflowGraph` with:

```html
<div class="interface-workflow-graph-toolbar" aria-label="路径图视图控制">
  <button id="interfaceWorkflowGraphZoomOut" type="button" title="缩小">−</button>
  <button id="interfaceWorkflowGraphZoomIn" type="button" title="放大">+</button>
  <button id="interfaceWorkflowGraphReset" type="button">重置</button>
</div>
<div class="interface-workflow-graph-stage">
  <canvas id="interfaceWorkflowGraphCanvas" aria-label="界面操作路径图"></canvas>
  <p class="trace-idle" id="interfaceWorkflowGraphEmpty">加载学习草稿后显示界面、操作与跳转关系。</p>
</div>
```

- [ ] **Step 4: Replace list CSS with responsive canvas CSS**

Remove `.interface-workflow-path-entry`, `.interface-workflow-path-step`, `.interface-workflow-path-edge`, and `.interface-workflow-path-target`.

Add stable dimensions:

```css
.interface-workflow-graph-stage {
  position: relative;
  min-height: 520px;
  overflow: hidden;
  background: #f8fafc;
}

#interfaceWorkflowGraphCanvas {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 520px;
  cursor: grab;
}

.interface-workflow-node-workspace {
  grid-template-columns: minmax(300px, 0.8fr) minmax(420px, 1.45fr) minmax(320px, 0.9fr);
}
```

At the existing narrow breakpoint, keep one-column stacking.

- [ ] **Step 5: Run focused route tests and verify GREEN**

Run:

```powershell
uv run pytest tests\test_web_panel_route.py -q
```

Expected: PASS for new static contract.

- [ ] **Step 6: Commit Task 2**

```powershell
git add app\web_panel\index.html app\web_panel\panel.css tests\test_web_panel_route.py
git commit -m "feat: add branching workflow graph canvas"
```

---

### Task 3: Canvas Rendering And Review Selection Integration

**Files:**
- Modify: `app/web_panel/panel.js`
- Modify: `tests/test_web_panel_route.py`
- Modify: `tests/js/interface_workflow_graph.test.cjs`

**Interfaces:**
- Consumes:
  - `InterfaceWorkflowGraph.buildInterfaceWorkflowTopology(graph)`
  - `InterfaceWorkflowGraph.layoutInterfaceWorkflowTopology(topology, viewport)`
  - `InterfaceWorkflowGraph.hitTestInterfaceWorkflowNode(layout, point)`
- Produces:
  - `renderInterfaceWorkflowGraph(graph): void`
  - `selectInterfaceWorkflowGraphNode(layoutNode): void`
  - canvas pan/zoom/reset lifecycle.

- [ ] **Step 1: Add failing panel integration assertions**

Require `renderInterfaceWorkflowReviewSelection` to call `renderInterfaceWorkflowGraph(graph)` and forbid the old string-built path:

```python
render_body = panel_js[render_start:render_end]
assert "renderInterfaceWorkflowGraph(graph)" in render_body
assert "interface-workflow-path-step" not in render_body
assert "下一界面尚未加入" not in render_body
```

Require operation selection to synchronize the exact edge:

```python
assert "interfaceWorkflowSelectedOperationId = layoutNode.ref_id" in panel_js
assert "interfaceWorkflowReviewState.select(layoutNode.source_node_id)" in panel_js
```

- [ ] **Step 2: Run focused route tests and verify RED**

Run:

```powershell
uv run pytest tests\test_web_panel_route.py -q
```

Expected: FAIL because the linear renderer is still present.

- [ ] **Step 3: Implement graph rendering state**

Add panel-local view state:

```javascript
let interfaceWorkflowGraphLayout = null;
let interfaceWorkflowGraphZoom = 1;
let interfaceWorkflowGraphPan = { x: 0, y: 0 };
let interfaceWorkflowGraphDrag = null;
```

`renderInterfaceWorkflowGraph(graph)` must:

1. build topology;
2. compute a layout using the canvas CSS size;
3. account for device pixel ratio;
4. clear stale canvas state when no nodes exist;
5. draw curved directional links first;
6. draw animated directional dots on links using one shared `requestAnimationFrame` loop;
7. draw interface nodes as larger rectangles;
8. draw operation nodes as smaller command nodes;
9. distinguish `needs_learning`, selected, review-needed, and rejected states;
10. never display runtime click coordinates.

- [ ] **Step 4: Implement click selection**

For an interface node:

```javascript
interfaceWorkflowSelectedOperationId = "";
interfaceWorkflowReviewState.select(layoutNode.ref_id);
renderInterfaceWorkflowReviewSelection();
```

For an operation node:

```javascript
interfaceWorkflowReviewState.select(layoutNode.source_node_id);
interfaceWorkflowSelectedOperationId = layoutNode.ref_id;
renderInterfaceWorkflowReviewSelection();
```

The operation editor must therefore select the exact clicked edge, while evidence remains owned by the source interface.

- [ ] **Step 5: Implement pan, zoom, reset, and resize**

- Pointer drag pans only the graph canvas.
- Wheel zoom clamps to `0.55..2.2`.
- `−` and `+` use the same clamp.
- Reset restores zoom `1` and pan `{x: 0, y: 0}`.
- `ResizeObserver` recomputes the layout without changing selected review data.
- Event binding is idempotent and does not duplicate listeners after rerender.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
node --test tests\js\interface_workflow_graph.test.cjs
uv run pytest tests\test_web_panel_route.py -q
```

Expected: all focused tests PASS.

- [ ] **Step 7: Run workflow review regressions**

Run:

```powershell
node --test tests\js\learning_workflow_review.test.cjs
uv run pytest tests\test_interface_workflow_review.py -q
```

Expected: existing review state, placeholder target, forbidden action, and save safety tests PASS.

- [ ] **Step 8: Commit Task 3**

```powershell
git add app\web_panel\panel.js tests\test_web_panel_route.py tests\js\interface_workflow_graph.test.cjs
git commit -m "feat: render branching interface workflow graph"
```

---

### Task 4: Evidence Highlight, Visual Verification, And Documentation

**Files:**
- Modify: `app/web_panel/panel.js`
- Modify: `app/web_panel/panel.css`
- Modify: `tests/test_web_panel_route.py`
- Modify: `README.md`
- Modify: `CURRENT_STATE.md`

**Interfaces:**
- Consumes selected operation `target_control_id` / `target_region_id` and the source interface's controls/regions.
- Produces a best-evidence target highlight over the displayed source image or an explicit “target evidence unavailable” status.

- [ ] **Step 1: Add failing target-highlight contract assertions**

Require:

```python
assert 'id="interfaceWorkflowEvidenceTargetHighlight"' in html
assert "resolveInterfaceWorkflowOperationTargetBbox" in panel_js
assert "target evidence unavailable" in panel_js
```

- [ ] **Step 2: Run focused route test and verify RED**

Run:

```powershell
uv run pytest tests\test_web_panel_route.py -q
```

Expected: FAIL because operation target highlighting is not implemented.

- [ ] **Step 3: Implement evidence target resolution**

`resolveInterfaceWorkflowOperationTargetBbox(node, operation)` must:

- match `target_control_id` against node controls first;
- match `target_region_id` against node regions second;
- accept `{x,y,width,height}` and `{x,y,w,h}`;
- require a valid source viewport before calculating percentages;
- return `null` instead of guessing when evidence is incomplete.

Render a positioned highlight only when the selected operation has a valid target bbox. Otherwise show `target evidence unavailable` without borrowing another node's bbox.

- [ ] **Step 4: Run focused automated tests**

Run:

```powershell
uv run pytest tests\test_web_panel_route.py -q
node --test tests\js\interface_workflow_graph.test.cjs tests\js\learning_workflow_review.test.cjs
uv run pytest tests\test_interface_workflow_review.py -q
```

Expected: all focused tests PASS.

- [ ] **Step 5: Run local panel visual verification**

Use the existing local panel only because the user's current test surface is already open there. Verify at 1280px and 1920px:

- one interface fans out to multiple operation nodes;
- shared target appears once;
- click interface changes the evidence image;
- click operation selects the exact operation editor item;
- graph pan, zoom, and reset work;
- no linear “下一界面尚未加入” list remains;
- no overlap between path, evidence, and inspector columns;
- no live click, fill, or submit occurs.

Capture one screenshot of the graph and record its absolute path in the work log.

- [ ] **Step 6: Update documentation**

Update README and CURRENT_STATE with:

- the three-column graph now renders branching `interface -> operation -> interface` topology;
- interface clicks switch evidence;
- operation clicks edit that edge;
- graph remains display-only and requires fresh grounding plus Gate in Execute mode.

- [ ] **Step 7: Run final verification**

Run:

```powershell
node --test tests\js\interface_workflow_graph.test.cjs tests\js\learning_workflow_review.test.cjs
uv run pytest tests\test_interface_workflow_review.py tests\test_web_panel_route.py -q
uv run python -m py_compile app\learn\interface_workflow_review.py app\api\panel.py
```

Expected: all commands exit `0`.

- [ ] **Step 8: Commit Task 4**

```powershell
git add app\web_panel\panel.js app\web_panel\panel.css tests\test_web_panel_route.py README.md CURRENT_STATE.md
git commit -m "docs: record branching workflow review graph"
```
