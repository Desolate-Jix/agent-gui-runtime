# Single-Application Workflow Review MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a generic single-application workflow review surface where each PathGraph node owns its boxed screenshot, page details, editable structure, transitions, and review status.

**Architecture:** Add a display-only workflow-review contract separate from the existing learning-stage state machine. A backend projector assembles interface nodes and transitions from existing learning draft evidence without inventing missing data; the panel renders a shared graph/evidence/editor workspace and atomically switches node-owned evidence. Reviewed edits remain draft-only until explicit publication through the existing reviewed-memory boundary.

**Tech Stack:** Python 3.11, FastAPI, vanilla JavaScript, HTML/CSS, pytest, Node test runner.

## Global Constraints

- First release is single application and single target window.
- SEEK is a test case only and must not define the contract or UI copy.
- Missing node evidence must clear the previous node display and show an explicit unavailable state.
- Long-term memory must not store reusable click coordinates.
- Manual edits may strengthen safety but may not disable hard Gate protections.
- Saving produces a review draft; only explicit publication affects reviewed Agent Memory.
- No final submit, send, delete, confirm, or payment action is authorized by this feature.

---

### Task 1: Workflow Review Contract And Projector

**Files:**
- Create: `app/learn/interface_workflow_review.py`
- Test: `tests/test_interface_workflow_review.py`

**Interfaces:**
- Consumes: existing learning-draft review payloads containing draft, screenshot, overlay, page details, and action candidates.
- Produces: `build_interface_workflow_review(*, goal: str, application_identity: dict, draft_sources: list[dict]) -> dict`.

- [ ] **Step 1: Write failing contract tests**

Cover:

```python
def test_builds_generic_nodes_and_edges_without_seek_fields() -> None: ...
def test_reuses_state_signature_for_duplicate_interface() -> None: ...
def test_missing_overlay_is_explicit_and_does_not_borrow_previous_node() -> None: ...
def test_runtime_click_coordinates_are_not_persisted() -> None: ...
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
uv run pytest tests/test_interface_workflow_review.py -q
```

Expected: import or assertion failures.

- [ ] **Step 3: Implement the contract**

Return:

```python
{
    "contract_version": "single_application_workflow_review_v1",
    "display_only": True,
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "workflow": {
        "workflow_id": "...",
        "goal": "...",
        "application_identity": {...},
        "entry_node_id": "...",
        "node_ids": [...],
        "edge_ids": [...],
        "review_status": "needs_human_review",
    },
    "nodes": [...],
    "edges": [...],
    "invalid_sources": [...],
}
```

Each node owns its own screenshot, overlays, page details, hierarchy, regions, controls, action candidates, blockers, and source path. Reject path traversal and remove runtime click points from the review projection.

- [ ] **Step 4: Rerun tests**

Run:

```powershell
uv run pytest tests/test_interface_workflow_review.py -q
```

Expected: all pass.

### Task 2: Panel API For Workflow Review

**Files:**
- Modify: `app/api/panel.py`
- Modify: `app/api/models/request.py`
- Test: `tests/test_web_panel_route.py`

**Interfaces:**
- Consumes: `build_interface_workflow_review`.
- Produces: `POST /panel/load_interface_workflow_review`.

- [ ] **Step 1: Write failing route tests**

Assert:

- valid source list returns the review contract;
- missing source is reported in `invalid_sources`;
- source paths must remain under the project root;
- response remains display-only and non-authorizing.

- [ ] **Step 2: Run the focused tests**

```powershell
uv run pytest tests/test_web_panel_route.py -k "interface_workflow_review" -q
```

- [ ] **Step 3: Implement the request and route**

Request fields:

```python
class PanelLoadInterfaceWorkflowReviewRequest(BaseModel):
    goal: str = ""
    application_identity: dict[str, Any] = Field(default_factory=dict)
    draft_source_paths: list[str] = Field(default_factory=list)
```

The route loads each existing review source through the established draft-review loader, then calls the projector.

- [ ] **Step 4: Rerun focused tests**

Expected: all pass.

### Task 3: Shared PathGraph And Node Evidence Workspace

**Files:**
- Create: `app/web_panel/learning_workflow_review.js`
- Modify: `app/web_panel/index.html`
- Modify: `app/web_panel/panel.css`
- Modify: `app/web_panel/panel.js`
- Create: `tests/js/learning_workflow_review.test.cjs`
- Modify: `tests/test_web_panel_route.py`

**Interfaces:**
- Consumes: `single_application_workflow_review_v1`.
- Produces:
  - `renderInterfaceWorkflowReview(review)`
  - `selectInterfaceWorkflowNode(nodeId)`
  - `clearInterfaceWorkflowNodeEvidence(reason)`

- [ ] **Step 1: Write failing JavaScript tests**

Cover:

```javascript
test("clicking a graph node renders only that node evidence", () => {});
test("missing evidence clears the previous image and details", () => {});
test("duplicate selection does not reload stale draft data", () => {});
test("graph labels are generic and contain no SEEK-specific copy", () => {});
```

- [ ] **Step 2: Run tests and verify failure**

```powershell
node --test tests/js/learning_workflow_review.test.cjs
```

- [ ] **Step 3: Implement the shared renderer**

The primary learning review page order is:

1. learning goal and application;
2. interface PathGraph;
3. selected node evidence viewer;
4. selected node structure/action inspector;
5. review actions.

The evidence viewer exposes `原图`, `编号图`, `融合图`, and `人工修订` tabs. The inspector exposes summary, hierarchy, actions, transitions, blockers, memory status, and execution verification. Trace opens in a node-scoped drawer.

- [ ] **Step 4: Demote debug-only controls**

Move raw paths, JSON, benchmark, fixture, scaffold, paused-task handoff, and model controls into the existing advanced diagnostics disclosure. Do not remove their IDs or event handlers.

- [ ] **Step 5: Run JavaScript and route tests**

```powershell
node --test tests/js/learning_workflow_review.test.cjs
node --test tests/js/learning_draft_editor.test.cjs
uv run pytest tests/test_web_panel_route.py -k "learning_interface_flow or interface_workflow_review" -q
node --check app/web_panel/learning_workflow_review.js
node --check app/web_panel/panel.js
```

### Task 4: Node, Structure, And Transition Review Draft Editing

**Files:**
- Create: `app/learn/interface_workflow_revision.py`
- Modify: `app/api/panel.py`
- Modify: `app/web_panel/learning_workflow_review.js`
- Modify: `app/web_panel/learning_draft_editor.js`
- Test: `tests/test_interface_workflow_revision.py`
- Modify: `tests/js/learning_workflow_review.test.cjs`
- Modify: `tests/js/learning_draft_editor.test.cjs`

**Interfaces:**
- Consumes: workflow review contract plus a revision patch and expected revision.
- Produces:
  - `apply_interface_workflow_revision(review, patch, expected_revision) -> dict`
  - `POST /panel/save_interface_workflow_review_draft`

- [ ] **Step 1: Write failing revision tests**

Cover node rename/delete/merge, bbox add/delete/move/resize, parent assignment, semantic type, action binding, edge reconnect, verification conditions, undo/redo, and revision conflicts.

- [ ] **Step 2: Run tests and verify failure**

```powershell
uv run pytest tests/test_interface_workflow_revision.py -q
node --test tests/js/learning_workflow_review.test.cjs
```

- [ ] **Step 3: Implement minimal revision storage**

Persist a new review-draft version with:

- original source references;
- revision number;
- structured diff;
- manual-edit audit;
- `published=false`;
- `artifact_is_authorization=false`;
- no click points.

- [ ] **Step 4: Connect the editor**

After save, rerender graph, image, hierarchy, page details, and transitions from the returned revision before closing the editor. A failed refresh leaves the editor open with an actionable error.

- [ ] **Step 5: Rerun tests**

Expected: all pass.

### Task 5: Explicit Publication And Execute Verification Boundary

**Files:**
- Modify: `app/agent/reviewed_interface_memory.py`
- Modify: `app/api/memory.py`
- Modify: `app/api/action.py`
- Modify: `app/web_panel/learning_workflow_review.js`
- Test: `tests/test_reviewed_interface_memory.py`
- Test: `tests/test_reviewed_interface_memory_execution.py`
- Modify: `tests/js/learning_workflow_review.test.cjs`

**Interfaces:**
- Consumes: a fully reviewed workflow revision.
- Produces:
  - published reviewed workflow memory version;
  - one-step execute preview using fresh capture and recognition.

- [ ] **Step 1: Write failing publication and execution tests**

Assert:

- unpublished edits never change active memory;
- explicit publication creates a new version;
- publish rejects unresolved or unsafe nodes;
- execution ignores stored click coordinates;
- execution recaptures, regrounds, passes Gate, and verifies one edge;
- dangerous actions remain blocked.

- [ ] **Step 2: Run focused tests**

```powershell
uv run pytest tests/test_reviewed_interface_memory.py tests/test_reviewed_interface_memory_execution.py -q
```

- [ ] **Step 3: Implement publication and preview**

Reuse the reviewed-memory registry and gated recognition-plan execution. Do not introduce a second execution path.

- [ ] **Step 4: Rerun focused tests**

Expected: all pass.

### Task 6: Browser Verification And Documentation

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Consumes: completed review MVP.
- Produces: verified panel UX and synchronized project documentation.

- [ ] **Step 1: Run regression tests**

```powershell
node --test tests/js/learning_workflow_review.test.cjs
node --test tests/js/learning_draft_editor.test.cjs
uv run pytest tests/test_interface_workflow_review.py tests/test_interface_workflow_revision.py tests/test_web_panel_route.py -q
uv run pytest tests/test_reviewed_interface_memory.py tests/test_reviewed_interface_memory_execution.py -q
```

- [ ] **Step 2: Verify the panel visually**

Using the local panel:

- load at least two generic interface nodes;
- click each node and confirm its own overlay and details appear;
- select a node with missing evidence and confirm the previous node clears;
- edit a box and relation, save, and confirm immediate refresh;
- confirm raw diagnostics remain folded;
- confirm no target application click occurs.

- [ ] **Step 3: Synchronize documentation**

Document:

- generic single-application scope;
- review-draft versus published-memory boundary;
- shared developer/user components;
- current limitations;
- no-submit and fresh-grounding safety rules.

- [ ] **Step 4: Run final verification**

```powershell
uv run python -m py_compile app/learn/interface_workflow_review.py app/learn/interface_workflow_revision.py app/api/panel.py
git diff --check
```

Expected: no errors.

