# Observe Operation Service Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the `vision_observe_screen` Learn Worker dependency on `app.api.*` by introducing a neutral Operation observation service and a separate Learn enrichment task without changing public API, Trace, or safety behavior.

**Architecture:** A neutral Operation service produces the base read-only observation. A Learn application task enriches that result with screen-map, read-only PathGraph, deep-review, and visual-asset data. FastAPI and Learn Worker remain thin adapters over the same task contract.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, multiprocessing `spawn`, pytest.

## Global Constraints

- Keep all local model processes stopped for offline implementation and tests.
- Do not modify Locate, recognition plan, Execute, Gate, final-submit, click, fill, scroll, or action authorization.
- Preserve `/vision/observe_screen`, public request fields, OpenAPI model names, response JSON, Trace operation names, screenshot identity, and write policy.
- `app.operation.observe.*` must not import `app.api.*` or `app.learn.*`.
- `app.learn.workflow_tasks.observe` must not import `app.api.*`.
- A degraded observation must remain explicitly degraded; do not convert model failure into a normal model result.
- Workflow and PathGraph output remains read-only and non-authorizing.
- Use UTF-8 and make one independently verified checkpoint at a time.

---

### Task 1: Freeze Observe Behavior

**Files:**
- Modify: `tests/test_vision_observe_locate.py`
- Modify: `tests/test_learning_workflow_stage_worker.py`
- Modify: `tests/test_learning_workflow_task_boundaries.py`

**Interfaces:**
- Consumes: `app.api.vision.observe_screen`
- Consumes: `app.learn.workflow_worker.execute_learning_stage_worker_task`
- Produces: characterization coverage for API shape, Worker shape, Trace, screenshot override, degraded result, and deep enrichment

- [ ] **Step 1: Add a saved-screenshot API characterization test**

Call `observe_screen` with `capture_live=False`, a temporary image, patched screen reading, and patched Trace writer. Assert:

```python
assert payload["success"] is True
assert payload["message"] == "Screen observation completed"
assert payload["data"]["result"]["contract_version"] == "screen_observation_v1"
assert payload["data"]["result"]["live_capture"] is None
assert payload["data"]["result"]["execution_path"]["action_executed"] is False
assert payload["data"]["result"]["trace_path"] == expected_trace_path
```

- [ ] **Step 2: Add degraded-path characterization**

Patch screen reading to return `success=False`, patch OCR/UIA evidence, and assert the result remains explicitly degraded with the same `screen_map`, `operation_context`, `timings`, and Trace fields.

- [ ] **Step 3: Add deep-mode characterization**

Patch deep review and visual-asset generation. Assert `path_graph_deep_review`, `path_graph_delta`, `element_memory_init_plan`, `visual_asset_learning`, and `learned_interface_map` retain their current locations.

- [ ] **Step 4: Run narrow characterization tests**

Run:

```powershell
$env:AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=':memory:'
uv run pytest tests/test_vision_observe_locate.py -k "observe_screen" -q
uv run pytest tests/test_learning_workflow_stage_worker.py -k "vision_observe_screen" -q
```

Expected: PASS before production edits.

---

### Task 2: Add Neutral Observe Contracts

**Files:**
- Create: `app/operation/observe/__init__.py`
- Create: `app/operation/observe/contracts.py`
- Create: `tests/test_observe_operation_contracts.py`

**Interfaces:**
- Produces: `ObserveScreenTaskInput`
- Produces: `ObserveScreenTaskFailure`
- Produces: `ObserveScreenTaskResult`

- [ ] **Step 1: Write contract tests**

Assert:

```python
task = ObserveScreenTaskInput.model_validate(api_request.model_dump())
assert task.capture_live is False
assert task.image_path == screenshot_path
assert task.learn_depth == "deep"
assert task.write_policy.path_graph is True
assert task.write_policy.element_memory is True
```

Also assert `app.operation.observe.contracts` source contains no `app.api` or `fastapi` import.

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
uv run pytest tests/test_observe_operation_contracts.py -q
```

Expected: FAIL because the contracts do not exist.

- [ ] **Step 3: Implement the contracts**

Mirror the validated fields of `VisionObserveScreenRequestModel` in a transport-neutral Pydantic model. Return task outcomes as `completed`, `safe_stopped`, or `failed` with a payload and optional structured failure.

- [ ] **Step 4: Run the contract tests**

Expected: PASS.

---

### Task 3: Extract Base Observation Service

**Files:**
- Create: `app/operation/observe/service.py`
- Create: `app/operation/observe/image_source.py`
- Create: `app/operation/observe/degraded.py`
- Modify: `app/api/vision.py`
- Create: `tests/test_observe_operation_service.py`

**Interfaces:**
- Consumes: `ObserveScreenTaskInput`
- Produces: `run_base_observation(task: ObserveScreenTaskInput) -> ObserveScreenTaskResult`

- [ ] **Step 1: Add tests for image source and capture identity**

Cover saved image, live bound-window capture, missing image, visually unready capture, viewport size, and immutable `capture_id`.

- [ ] **Step 2: Add tests for normal and degraded base observation**

Inject screen-reading, OCR, UIA, runtime-context, and timing dependencies. Assert normal and degraded results preserve source identity and explicitly distinguish model failure.

- [ ] **Step 3: Run the new tests and confirm RED**

Run:

```powershell
uv run pytest tests/test_observe_operation_service.py -q
```

- [ ] **Step 4: Move the smallest coherent base helpers**

Move image-source resolution, readiness checks, provider-mode selection, image-size handling, and degraded observation assembly. Do not leave wrappers in `app.operation` that import `app.api.vision`.

- [ ] **Step 5: Make the API route call the base service**

Keep the existing API route and response mapping in place. At this checkpoint, Learn enrichment may still be called by the API adapter, but the base observation must be API-independent.

- [ ] **Step 6: Run service and Observe route tests**

Run:

```powershell
uv run pytest tests/test_observe_operation_service.py tests/test_vision_observe_locate.py -k "observe_screen" -q
```

Expected: PASS.

---

### Task 4: Extract Learn Screen-Map And PathGraph Enrichment

**Files:**
- Create: `app/learn/observe_enrichment/__init__.py`
- Create: `app/learn/observe_enrichment/screen_map_builder.py`
- Create: `app/learn/observe_enrichment/path_graph.py`
- Modify: `app/api/vision.py`
- Modify: `tests/test_observe_learned_path_graph.py`
- Create: `tests/test_observe_enrichment.py`

**Interfaces:**
- Consumes: base observation payload plus `ObserveScreenTaskInput`
- Produces: `enrich_observation_screen_map(...) -> dict[str, Any]`

- [ ] **Step 1: Freeze representative screen-map output**

Use deterministic OCR/UIA/model fixtures and assert sections, candidates, risk classes, candidate IDs, state hints, and non-authorizing execution fields.

- [ ] **Step 2: Run the new tests and confirm RED**

- [ ] **Step 3: Move screen-map and learned-PathGraph helpers**

Move only the transitive helper closure required by screen-map and learned-PathGraph enrichment. Preserve candidate deduplication, SEEK form scoping, section assignment, card grouping, and risk vocabulary.

- [ ] **Step 4: Remove migrated API helper copies**

Before deletion, run static references and focused tests. Keep compatibility exports only where a real caller remains.

- [ ] **Step 5: Run enrichment and route tests**

Run:

```powershell
uv run pytest tests/test_observe_enrichment.py tests/test_observe_learned_path_graph.py tests/test_vision_observe_locate.py -k "observe_screen or learned_path_graph" -q
```

Expected: PASS.

---

### Task 5: Extract Deep Review And Visual Assets

**Files:**
- Create: `app/learn/observe_enrichment/deep_review.py`
- Create: `app/learn/observe_enrichment/visual_assets.py`
- Modify: `app/api/vision.py`
- Modify: `tests/test_vision_observe_locate.py`
- Create: `tests/test_observe_deep_enrichment.py`

**Interfaces:**
- Produces: `apply_deep_review(...)`
- Produces: `apply_visual_asset_learning(...)`

- [ ] **Step 1: Add deep-review failure and success tests**

Assert model output parsing, schema normalization, delta fields, ElementMemory initialization, and safe failure reporting.

- [ ] **Step 2: Add visual-asset tests**

Assert missing source image is skipped explicitly, crop failures are structured, learned interface map summary is preserved, and artifacts remain non-authorizing.

- [ ] **Step 3: Move the helper closures**

Do not change prompt text, model configuration, crop policy, path-graph policy, or output fields.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
uv run pytest tests/test_observe_deep_enrichment.py tests/test_visual_asset_recall.py tests/test_vision_observe_locate.py -k "observe_screen or visual_asset" -q
```

Expected: PASS.

---

### Task 6: Add Shared Observe Application Task

**Files:**
- Create: `app/learn/workflow_tasks/observe.py`
- Modify: `app/learn/workflow_task_result_adapter.py`
- Modify: `app/api/vision.py`
- Create: `tests/test_observe_workflow_task.py`

**Interfaces:**
- Produces: `run_observe_task(task: ObserveScreenTaskInput, *, project_root: Path) -> ObserveScreenTaskResult`
- Produces: `observe_result_to_legacy_response(result) -> APIResponse-compatible payload`

- [ ] **Step 1: Add task outcome tests**

Cover completed, degraded-but-completed, safe-stopped, failed, Trace failure, and deep enrichment failure without starting a model.

- [ ] **Step 2: Implement task orchestration**

Call base observation, screen-map enrichment, optional deep review, optional visual assets, Trace creation, and typed failure mapping in the same order as the frozen route.

- [ ] **Step 3: Convert the API route to a thin adapter**

The route validates the public request, builds `ObserveScreenTaskInput`, calls the task, and maps the result to the exact legacy `APIResponse`.

- [ ] **Step 4: Run task and route tests**

Run:

```powershell
uv run pytest tests/test_observe_workflow_task.py tests/test_vision_observe_locate.py -k "observe_screen" -q
```

Expected: PASS.

---

### Task 7: Remove Worker API Dependency For Observe

**Files:**
- Modify: `app/learn/workflow_worker.py`
- Modify: `tests/test_learning_workflow_stage_worker.py`
- Modify: `tests/test_learning_workflow_task_boundaries.py`

**Interfaces:**
- Consumes: `ObserveScreenTaskInput`
- Consumes: `run_observe_task`
- Produces: legacy-compatible serialized worker response

- [ ] **Step 1: Add a clean-subprocess boundary test**

Execute only `vision_observe_screen` with task doubles and assert:

```python
assert not any(name == "app.api" or name.startswith("app.api.") for name in sys.modules)
```

- [ ] **Step 2: Run the test and confirm RED**

Expected: FAIL because the Worker currently imports `app.api.models.request` and `app.api.vision`.

- [ ] **Step 3: Switch the Worker branch**

Validate `ObserveScreenTaskInput`, call `run_observe_task`, and serialize through the compatibility adapter. Do not add an import fallback to the old API route.

- [ ] **Step 4: Run Worker and boundary tests**

Run:

```powershell
$env:AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=':memory:'
uv run pytest tests/test_learning_workflow_stage_worker.py -k "vision_observe_screen" -q
uv run pytest tests/test_learning_workflow_task_boundaries.py -q
```

Expected: PASS and no `app.api` loaded by this branch.

---

### Task 8: Compatibility Audit And Documentation

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`
- Modify: `PROJECT_SUMMARY.md`

**Interfaces:**
- Produces: verified architecture status and an explicit Locate follow-up boundary

- [ ] **Step 1: Audit remaining API coupling**

Run:

```powershell
rg -n "from app\\.api\\.vision|from app\\.api\\.models\\.request" app/learn app/operation
```

Expected: no Observe Worker dependency; Locate and calibration sequence remain explicitly listed as future work.

- [ ] **Step 2: Run syntax and focused tests**

Run:

```powershell
uv run python -m py_compile app\operation\observe\contracts.py app\operation\observe\service.py app\learn\workflow_tasks\observe.py app\learn\workflow_worker.py app\api\vision.py
$env:AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=':memory:'
uv run pytest tests/test_observe_operation_contracts.py tests/test_observe_operation_service.py tests/test_observe_enrichment.py tests/test_observe_deep_enrichment.py tests/test_observe_workflow_task.py tests/test_learning_workflow_task_boundaries.py -q
```

- [ ] **Step 3: Run the complete test suite**

Run:

```powershell
$env:AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=':memory:'
uv run pytest tests -q
```

- [ ] **Step 4: Check Panel health and model shutdown**

Verify `http://127.0.0.1:8765/health`, confirm no local model process and no listeners on model ports, then run `git diff --check`.

- [ ] **Step 5: Update documentation**

State exactly which boundary is verified. Do not claim recognition accuracy, model reliability, Execute success, live safe fill, live submit, or E2E stability.
