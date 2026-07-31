# Connected-Papers-Style Workflow Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic animated workflow graph with Connected Papers-style hover exploration on top of the current Learn Mode Canvas graph.

**Architecture:** Keep the existing workflow schema and Canvas renderer. Add a pure deterministic force simulation and adjacency projection to `interface_workflow_graph.js`, then connect animation and hover presentation in `panel.js` without changing selection or execution behavior.

**Tech Stack:** Browser Canvas 2D, requestAnimationFrame, Node.js built-in test runner, vanilla JavaScript.

## Global Constraints

- The same graph data must settle to the same node positions.
- Animation must be bounded and stop automatically.
- Hover is presentation-only and must not mutate review or workflow state.
- Existing click focus, pan, zoom, and reset behavior must remain compatible.
- No Agent, Operation, Gate, Trace, Execute, or final-submit behavior may change.
- No new runtime dependency is introduced.

---

### Task 1: Deterministic Force Layout Core

**Files:**
- Modify: `tests/js/interface_workflow_graph.test.cjs`
- Modify: `app/web_panel/interface_workflow_graph.js`

**Interfaces:**
- Produces: `createInterfaceWorkflowSimulation(topology, viewport, options)`
- Produces: simulation object with `layout`, `step(iterations)`, `isSettled()`, and `runToCompletion(maxIterations)`

- [ ] **Step 1: Write failing deterministic simulation tests**

Add tests that create the same branching graph twice, run both simulations to completion, and assert equal rounded coordinates, finite bounds, non-overlapping nodes, and a centred entry node.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
node --test tests/js/interface_workflow_graph.test.cjs
```

Expected: failure because `createInterfaceWorkflowSimulation` is not exported.

- [ ] **Step 3: Implement the bounded deterministic simulation**

Use sorted topology order, the existing radial layout as deterministic initial positions, center/link/repulsion/collision forces, a fixed entry node, velocity decay, and a settled threshold.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```powershell
node --test tests/js/interface_workflow_graph.test.cjs
```

Expected: all graph tests pass.

### Task 2: Adjacency Hover Projection

**Files:**
- Modify: `tests/js/interface_workflow_graph.test.cjs`
- Modify: `app/web_panel/interface_workflow_graph.js`

**Interfaces:**
- Produces: `interfaceWorkflowHoverProjection(layout, nodeId)`
- Returns: `{ hovered_node_id, highlighted_node_ids, highlighted_link_ids, dimmed_node_ids, dimmed_link_ids }`

- [ ] **Step 1: Write failing one-hop adjacency tests**

Add a graph with a branch and an unrelated node. Assert that hovering the entry highlights only the entry, its direct neighbours, and their links while dimming the unrelated node.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
node --test tests/js/interface_workflow_graph.test.cjs
```

Expected: failure because `interfaceWorkflowHoverProjection` is not exported.

- [ ] **Step 3: Implement immutable hover projection**

Build sets from layout links without modifying layout nodes, links, selection, or source graph data.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```powershell
node --test tests/js/interface_workflow_graph.test.cjs
```

Expected: all graph tests pass.

### Task 3: Canvas Animation And Hover UI

**Files:**
- Modify: `app/web_panel/panel.js`
- Modify: `app/web_panel/index.html`
- Modify: `app/web_panel/panel.css`
- Test: `tests/test_web_panel_route.py`

**Interfaces:**
- Consumes: `createInterfaceWorkflowSimulation`
- Consumes: `interfaceWorkflowHoverProjection`
- Produces: bounded requestAnimationFrame loop and hover tooltip

- [ ] **Step 1: Add route assertions for tooltip markup and cache-busted assets**

Update `tests/test_web_panel_route.py` to require the workflow graph tooltip element and the current static asset version.

- [ ] **Step 2: Run the focused route test and verify RED**

Run:

```powershell
uv run pytest tests/test_web_panel_route.py -q
```

Expected: failure because the tooltip element is absent.

- [ ] **Step 3: Implement animation and hover rendering**

Create simulation on topology signature changes, request animation frames until settled, hit-test pointer movement when not dragging, set the Canvas cursor, render highlighted/dimmed nodes and links, and position the tooltip beside the hovered node.

- [ ] **Step 4: Verify syntax and focused tests**

Run:

```powershell
node --check app/web_panel/interface_workflow_graph.js
node --check app/web_panel/panel.js
node --test tests/js/interface_workflow_graph.test.cjs
uv run pytest tests/test_web_panel_route.py -q
```

Expected: all checks pass.

### Task 4: Documentation And Browser Smoke

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_SUMMARY.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Documents: deterministic force layout, hover exploration, and presentation-only safety boundary

- [ ] **Step 1: Synchronize affected documentation**

Describe the graph as a review and navigation surface, not execution authorization. Record the deterministic layout and hover interaction.

- [ ] **Step 2: Run the complete affected checks**

Run:

```powershell
node --test tests/js/*.test.cjs
uv run pytest tests/test_web_panel_route.py -q
```

Expected: all checks pass.

- [ ] **Step 3: Exercise the local panel**

Open the Learn Mode panel, load a multi-interface workflow, verify the graph animates briefly, hover highlights one-hop neighbours and shows the tooltip, drag and zoom remain functional, and click focus still loads the selected interface.

- [ ] **Step 4: Inspect final diff**

Run:

```powershell
git diff --stat
git diff -- app/web_panel/interface_workflow_graph.js app/web_panel/panel.js app/web_panel/index.html app/web_panel/panel.css tests/js/interface_workflow_graph.test.cjs tests/test_web_panel_route.py
```

Expected: only graph presentation, tests, and synchronized documentation changed.

