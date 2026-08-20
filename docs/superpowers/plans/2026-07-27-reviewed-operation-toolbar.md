# Reviewed Operation Toolbar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compact human-review toolbar that defines routine Agent operations and interface transitions, then validates a saved operation through a no-click dry-run.

**Architecture:** Extend the existing `single_application_workflow_review_v1` edge contract instead of creating a second workflow model. The browser editor owns operation creation and transition selection; the backend enforces allowed action types and hard-blocks submit/send/confirm/payment/delete. Dry-run reuses `/action/execute_recognition_plan` with a live capture and `dry_run=true`, while the reviewed workflow remains display-only and non-authorizing.

**Tech Stack:** FastAPI, Pydantic, Python JSON artifacts, vanilla JavaScript state modules, HTML/CSS, Node test runner, pytest.

## Global Constraints

- The toolbar never exposes a live Execute command.
- `final_submit`, `submit`, `send`, `confirm`, `payment`, and `delete` are rejected by the backend validator.
- Reviewed coordinates never authorize a click.
- Dry-run requires current window evidence and always sends `dry_run=true`.
- The existing dirty worktree must be preserved; only files named in this plan are modified.
- Chinese text is read and written as UTF-8.

---

### Task 1: Enforce the reviewed operation contract

**Files:**
- Modify: `app/learn/interface_workflow_review.py`
- Test: `tests/test_interface_workflow_review.py`

**Interfaces:**
- Consumes: `save_interface_workflow_review_candidate(review, project_root, out_dir)`
- Produces: `ALLOWED_REVIEW_ACTION_TYPES`, `FORBIDDEN_REVIEW_ACTION_TYPES`, validated edge fields `operation_id`, `action_type`, `target_control_id`, `risk_level`, `requires_user_confirmation`, `preconditions`, `success_conditions`, `failure_conditions`

- [ ] **Step 1: Write failing tests for allowed and forbidden operation types**

```python
def test_save_workflow_review_accepts_routine_agent_operation(tmp_path: Path) -> None:
    review = build_interface_workflow_review(...)
    review["edges"][0].update({
        "operation_id": "open_job_detail",
        "action_type": "open_detail",
        "target_control_id": "job_card_1",
        "risk_level": "low",
        "requires_user_confirmation": False,
    })
    result = save_interface_workflow_review_candidate(review, project_root=tmp_path)
    saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert saved["edges"][0]["action_type"] == "open_detail"
    assert saved["execute_binding_enabled"] is False


@pytest.mark.parametrize("action_type", ["final_submit", "submit", "send", "confirm", "payment", "delete"])
def test_save_workflow_review_rejects_forbidden_operation(action_type: str, tmp_path: Path) -> None:
    review = build_interface_workflow_review(...)
    review["edges"][0]["action_type"] = action_type
    with pytest.raises(ValueError, match="forbidden review action type"):
        save_interface_workflow_review_candidate(review, project_root=tmp_path)
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `uv run pytest tests/test_interface_workflow_review.py -q`

Expected: the forbidden action test fails because the current validator accepts arbitrary `action_type`.

- [ ] **Step 3: Add strict operation normalization and validation**

```python
ALLOWED_REVIEW_ACTION_TYPES = {
    "read",
    "open_detail",
    "open_apply_flow",
    "fill_field",
    "select_option",
    "scroll",
    "back",
    "close_modal",
    "wait",
    "continue_next_step",
    "unknown_action",
}
FORBIDDEN_REVIEW_ACTION_TYPES = {
    "final_submit",
    "submit",
    "send",
    "confirm",
    "payment",
    "delete",
}


def _validate_review_operation(edge: dict[str, Any]) -> None:
    action_type = str(edge.get("action_type") or "unknown_action").strip().lower()
    if action_type in FORBIDDEN_REVIEW_ACTION_TYPES:
        raise ValueError(f"forbidden review action type: {action_type}")
    if action_type not in ALLOWED_REVIEW_ACTION_TYPES:
        raise ValueError(f"unsupported review action type: {action_type}")
    edge["action_type"] = action_type
    edge["risk_level"] = str(edge.get("risk_level") or "low").strip().lower()
    if edge["risk_level"] not in {"low", "medium", "high"}:
        raise ValueError("workflow edge risk_level must be low, medium, or high")
    edge["requires_user_confirmation"] = bool(
        edge.get("requires_user_confirmation") or edge["risk_level"] == "high"
    )
```

Call `_validate_review_operation(edge)` from `_validate_workflow_structure`.

- [ ] **Step 4: Run the focused tests**

Run: `uv run pytest tests/test_interface_workflow_review.py -q`

Expected: all interface workflow review tests pass.

---

### Task 2: Add operation and placeholder-transition state APIs

**Files:**
- Modify: `app/web_panel/learning_workflow_review.js`
- Test: `tests/js/learning_workflow_review.test.cjs`
- Test: `tests/test_learning_draft_editor_js.py`

**Interfaces:**
- Consumes: `createInterfaceWorkflowReviewState(inputReview)`
- Produces: `addOperation(sourceNodeId, operation)`, `updateOperation(edgeId, patch)`, `removeOperation(edgeId)`, `addPlaceholderNode(displayName, surfaceType)`

- [ ] **Step 1: Write failing Node tests**

```javascript
test("adds an allowed operation and placeholder target", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());
  const target = state.addPlaceholderNode("Quick Apply form", "form");
  const edge = state.addOperation("state_a", {
    operation_id: "open_quick_apply",
    display_name: "Open Quick Apply",
    action_type: "open_apply_flow",
    target_node_id: target.node_id,
  });
  assert.equal(edge.action_type, "open_apply_flow");
  assert.equal(state.current().outgoing_edges.length, 2);
  assert.equal(state.snapshot().nodes.at(-1).review_status, "needs_learning");
});

test("rejects forbidden operations before save", () => {
  const state = createInterfaceWorkflowReviewState(reviewFixture());
  assert.throws(
    () => state.addOperation("state_a", { action_type: "final_submit", target_node_id: "state_b" }),
    /forbidden review action type/,
  );
});
```

- [ ] **Step 2: Run the Node tests and confirm they fail**

Run: `node --test tests/js/learning_workflow_review.test.cjs`

Expected: `addOperation` and `addPlaceholderNode` are missing.

- [ ] **Step 3: Implement state operations with stable IDs**

```javascript
const ALLOWED_ACTION_TYPES = new Set([
  "read", "open_detail", "open_apply_flow", "fill_field", "select_option",
  "scroll", "back", "close_modal", "wait", "continue_next_step",
]);
const FORBIDDEN_ACTION_TYPES = new Set([
  "final_submit", "submit", "send", "confirm", "payment", "delete",
]);
```

Generate IDs from a normalized caller-provided `operation_id` plus an incrementing collision suffix. Every created node and edge must set:

```javascript
{
  display_only: true,
  artifact_is_authorization: false,
  execute_binding_enabled: false,
}
```

Removing an operation deletes only the matching edge and updates `workflow.edge_ids`; placeholder nodes remain.

- [ ] **Step 4: Run the Node and Python wrapper tests**

Run: `node --test tests/js/learning_workflow_review.test.cjs`

Run: `uv run pytest tests/test_learning_draft_editor_js.py -q`

Expected: both pass.

---

### Task 3: Build the operation toolbar and transition editor

**Files:**
- Modify: `app/web_panel/index.html`
- Modify: `app/web_panel/panel.css`
- Modify: `app/web_panel/panel.js`
- Test: `tests/test_web_panel_route.py`

**Interfaces:**
- Consumes: `interfaceWorkflowReviewState`, `renderInterfaceWorkflowReviewSelection()`
- Produces: `commitInterfaceWorkflowOperationEditor()`, `addInterfaceWorkflowOperation()`, `removeInterfaceWorkflowOperation()`, `createInterfaceWorkflowPlaceholderNode()`

- [ ] **Step 1: Add failing panel contract assertions**

```python
def test_panel_contains_reviewed_operation_toolbar() -> None:
    html = PANEL_INDEX.read_text(encoding="utf-8")
    panel_js = PANEL_JS.read_text(encoding="utf-8")
    for element_id in [
        "interfaceWorkflowOperationList",
        "interfaceWorkflowOperationType",
        "interfaceWorkflowOperationLabel",
        "interfaceWorkflowOperationTargetControl",
        "interfaceWorkflowOperationTargetNode",
        "interfaceWorkflowOperationAddBtn",
        "interfaceWorkflowOperationDeleteBtn",
        "interfaceWorkflowOperationDryRunBtn",
        "interfaceWorkflowOperationStatus",
    ]:
        assert f'id="{element_id}"' in html
    assert "addInterfaceWorkflowOperation" in panel_js
    assert "removeInterfaceWorkflowOperation" in panel_js
```

- [ ] **Step 2: Run the focused panel test and confirm it fails**

Run: `uv run pytest tests/test_web_panel_route.py -q`

Expected: missing toolbar IDs.

- [ ] **Step 3: Add the compact toolbar markup**

Use an operation list, action-type menu, label, target-control input, target-node menu, optional placeholder-node input, confirmation checkbox, and four commands: add, update, delete, dry-run. Do not add a live Execute button.

- [ ] **Step 4: Bind toolbar state to the selected interface**

When a graph node changes:

1. refresh the operation list from `current().outgoing_edges`;
2. select the first operation without overwriting its values;
3. render the target-node choices from the current graph;
4. update the PathGraph preview immediately after add, update, or delete;
5. mark the workflow review as unsaved.

- [ ] **Step 5: Add restrained responsive CSS**

The operation toolbar stays inside the right inspector. At desktop width it uses two compact columns; below 1280 px it becomes one column. Buttons use stable heights and do not resize the evidence canvas.

- [ ] **Step 6: Run panel contract tests**

Run: `uv run pytest tests/test_web_panel_route.py -q`

Expected: all panel route tests pass.

---

### Task 4: Add no-click dry-run validation

**Files:**
- Modify: `app/web_panel/panel.js`
- Test: `tests/test_web_panel_route.py`
- Test: `tests/test_reviewed_interface_memory_execution.py`

**Interfaces:**
- Consumes: current reviewed edge, bound window, `/action/execute_recognition_plan`
- Produces: `dryRunInterfaceWorkflowOperation()`

- [ ] **Step 1: Add failing tests for the request contract**

```python
def test_reviewed_operation_dry_run_never_requests_execution() -> None:
    panel_js = PANEL_JS.read_text(encoding="utf-8")
    start = panel_js.index("async function dryRunInterfaceWorkflowOperation")
    end = panel_js.index("\n}", start) + 2
    body = panel_js[start:end]
    assert '"/action/execute_recognition_plan"' in body
    assert "capture_live: true" in body
    assert "dry_run: true" in body
    assert "action_executed=false" in body
    assert "dry_run: false" not in body
```

Add an action API regression test showing `ExecuteRecognitionPlanRequest(dry_run=True)` returns an execution path with `action_executed=False`.

- [ ] **Step 2: Run the tests and confirm the new panel test fails**

Run: `uv run pytest tests/test_web_panel_route.py tests/test_reviewed_interface_memory_execution.py -q`

- [ ] **Step 3: Implement dry-run**

Build this request only after the current review has been saved:

```javascript
const payload = {
  goal: operation.display_name || operation.action_type,
  app_name: currentInterfaceWorkflowApplicationIdentity().process_name,
  state_hint: currentNode.surface_type || "",
  capture_live: true,
  dry_run: true,
  provider_mode: "local_grounding",
  top_k: 3,
  enable_post_click_verification: false,
  max_execution_attempts: 1,
  metadata: {
    reviewed_workflow_operation: {
      edge_id: operation.edge_id,
      operation_id: operation.operation_id,
      action_type: operation.action_type,
      target_region_id: operation.target_region_id || "",
      target_control_id: operation.target_control_id || "",
    },
  },
};
```

Reject forbidden action types locally before sending. Show `ready_for_operator_review`, `safe_stop`, or `invalid`, plus trace path and `action_executed=false`. Never call the non-dry-run helper.

- [ ] **Step 4: Run the focused tests**

Run: `uv run pytest tests/test_web_panel_route.py tests/test_reviewed_interface_memory_execution.py -q`

Expected: all pass.

---

### Task 5: Verify the full reviewed-operation slice and synchronize docs

**Files:**
- Modify: `README.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Consumes: completed Tasks 1-4
- Produces: verified panel behavior and current limitations

- [ ] **Step 1: Run syntax and focused test verification**

Run:

```powershell
uv run python -m py_compile app\learn\interface_workflow_review.py app\api\panel.py
node --test tests\js\learning_workflow_review.test.cjs
uv run pytest tests\test_interface_workflow_review.py tests\test_learning_draft_editor_js.py tests\test_web_panel_route.py tests\test_reviewed_interface_memory_execution.py -q
```

- [ ] **Step 2: Start or reuse the local panel**

Run: `python scripts\start_test_panel.py`

Expected: the project panel is available at `http://127.0.0.1:8765/panel`.

- [ ] **Step 3: Run a browser smoke**

Verify:

1. load a historical single-application workflow;
2. select an interface node;
3. add `open_detail`;
4. select an existing target or create a `needs_learning` placeholder;
5. save and verify the graph remains updated;
6. run dry-run with a bound test window;
7. confirm the result displays `action_executed=false`;
8. confirm no real click occurs.

- [ ] **Step 4: Update documentation**

Document that the operation toolbar is review-only, dry-run requires a bound current window, dangerous actions are rejected, and reviewed transitions are not Runtime PathGraph authorization.

- [ ] **Step 5: Run `git diff --check`**

Run: `git diff --check`

Expected: no whitespace errors in changed files.
