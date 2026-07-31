# Learning Worker Service Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the Learn Worker dependency on Panel API routes by introducing typed Learn task contracts, application services, and explicit Panel/Worker adapters without changing public API or safety behavior.

**Architecture:** Panel request models remain public API contracts. Panel and Worker convert payloads into neutral Learn task inputs and call the same application services. Services return typed task results; a compatibility adapter preserves the current API/Worker response JSON while the worker lifecycle envelope remains unchanged.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, multiprocessing `spawn`, pytest.

## Global Constraints

- Keep all local model processes stopped during offline implementation and tests.
- Do not modify Execute Mode, Gate, final-submit detection, click, type, scroll, or action authorization.
- Preserve all Panel routes, request fields, OpenAPI schemas, response JSON, Trace operations, worker envelopes, adoption receipts, and digest checks.
- Learn task services must not import `app.api.*`.
- Workflow and PathGraph assets remain non-authoritative and read-only.
- Use UTF-8 for every source, test, prompt, Trace, and document.
- Make one checkpoint-sized change at a time and run the narrowest relevant test before continuing.

---

### Task 1: Freeze Model Review Route And Worker Behavior

**Files:**
- Modify: `tests/test_learning_workflow_stage_worker.py`
- Modify: `tests/test_learning_draft_review.py`
- Create: `tests/test_learning_workflow_task_boundaries.py`

**Interfaces:**
- Consumes: `app.api.panel.run_learning_model_review_repair_endpoint`
- Consumes: `app.learn.workflow_worker.execute_learning_stage_worker_task`
- Produces: characterization fixtures for the current success, safe-stop, failure, Trace, and safety-counter behavior

- [ ] **Step 1: Add a Panel route characterization test**

Create a temporary report, screenshot, and overlay. Monkeypatch `run_panel_learning_model_review_repair` and `write_trace`, call the route with `PanelRunLearningModelReviewRepairRequest`, and assert the complete `APIResponse.model_dump(mode="json")`:

```python
def test_model_review_route_preserves_legacy_response_and_safety(monkeypatch):
    monkeypatch.setattr(
        panel_api,
        "run_panel_learning_model_review_repair",
        lambda **_kwargs: {
            "status": "safe_stop",
            "calibration_permission": False,
            "integrity_gate": {"status": "failed"},
            "final_stage2_report_path": "artifacts/final.json",
            "final_numbering_revision": 3,
        },
    )
    monkeypatch.setattr(panel_api, "write_trace", lambda **_kwargs: "logs/traces/review.json")

    response = panel_api.run_learning_model_review_repair_endpoint(
        panel_api.PanelRunLearningModelReviewRepairRequest(
            two_stage_report_path="artifacts/input.json",
            screenshot_path="artifacts/input.png",
            composite_overlay_path="artifacts/overlay.png",
        )
    )

    payload = response.model_dump(mode="json")
    assert payload["success"] is True
    assert payload["message"] == "Learning model review and repair stopped safely"
    assert payload["data"]["real_clicks"] == 0
    assert payload["data"]["live_fills"] == 0
    assert payload["data"]["live_submits"] == 0
    assert payload["data"]["trace_path"] == "logs/traces/review.json"
    assert payload["error"] is None
```

- [ ] **Step 2: Run the characterization test**

Run:

```powershell
uv run pytest tests/test_learning_draft_review.py -k "model_review_route_preserves_legacy_response_and_safety" -q
```

Expected: PASS against the current implementation. This freezes behavior; it is not the RED test.

- [ ] **Step 3: Add the first failing boundary test**

```python
def test_model_review_application_service_exists_without_api_dependency():
    module = importlib.import_module("app.learn.workflow_tasks.model_review")
    source = inspect.getsource(module)
    assert "app.api" not in source
    assert callable(module.run_model_review_task)
```

- [ ] **Step 4: Run the boundary test and verify RED**

Run:

```powershell
uv run pytest tests/test_learning_workflow_task_boundaries.py::test_model_review_application_service_exists_without_api_dependency -q
```

Expected: FAIL with `ModuleNotFoundError: app.learn.workflow_tasks`.

- [ ] **Step 5: Record the checkpoint diff**

Run:

```powershell
git diff --stat
```

Expected: only the three test files differ for this checkpoint.

### Task 2: Add Neutral Model Review Contracts

**Files:**
- Create: `app/learn/workflow_contracts.py`
- Create: `tests/test_learning_workflow_contracts.py`

**Interfaces:**
- Produces: `LearningTaskFailure`, `LearningTaskResult`, and `ModelReviewTaskInput`
- `ModelReviewTaskInput.model_validate(payload)` is used by Panel and Worker adapters

- [ ] **Step 1: Write failing contract tests**

```python
def test_model_review_task_input_preserves_validation_contract():
    value = ModelReviewTaskInput.model_validate(
        {
            "two_stage_report_path": "artifacts/report.json",
            "screenshot_path": "artifacts/screen.png",
            "composite_overlay_path": "artifacts/overlay.png",
        }
    )
    assert value.model_profile_id == "learn_mode_qwen3_vl_8b"
    assert value.timeout_seconds == 240


def test_learning_task_result_is_transport_neutral():
    fields = set(LearningTaskResult.model_fields)
    assert fields == {"outcome", "payload", "failure"}
    assert "status_code" not in fields
    assert "message" not in fields
    assert "error" not in fields
```

- [ ] **Step 2: Run contract tests and verify RED**

Run:

```powershell
uv run pytest tests/test_learning_workflow_contracts.py -q
```

Expected: FAIL because `app.learn.workflow_contracts` does not exist.

- [ ] **Step 3: Implement the minimal contracts**

```python
from typing import Any, Literal

from pydantic import BaseModel, Field


class LearningTaskFailure(BaseModel):
    code: str = Field(min_length=1)
    details: str


class LearningTaskResult(BaseModel):
    outcome: Literal["completed", "safe_stopped", "failed"]
    payload: dict[str, Any] = Field(default_factory=dict)
    failure: LearningTaskFailure | None = None


class ModelReviewTaskInput(BaseModel):
    two_stage_report_path: str = Field(min_length=1)
    screenshot_path: str = Field(min_length=1)
    composite_overlay_path: str = Field(min_length=1)
    model_profile_id: str = "learn_mode_qwen3_vl_8b"
    timeout_seconds: int = Field(default=240, ge=30, le=900)
```

- [ ] **Step 4: Run contract tests and verify GREEN**

Run:

```powershell
uv run pytest tests/test_learning_workflow_contracts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the isolated contract checkpoint**

```powershell
git add app/learn/workflow_contracts.py tests/test_learning_workflow_contracts.py
git commit -m "refactor: add neutral learning task contracts"
```

### Task 3: Extract Model Review Application Service

**Files:**
- Create: `app/learn/workflow_tasks/__init__.py`
- Create: `app/learn/workflow_tasks/model_review.py`
- Create: `app/learn/workflow_task_result_adapter.py`
- Modify: `app/api/panel.py`
- Modify: `app/learn/workflow_worker.py`
- Modify: `tests/test_learning_workflow_task_boundaries.py`
- Modify: `tests/test_learning_workflow_stage_worker.py`
- Modify: `tests/test_learning_draft_review.py`

**Interfaces:**
- Produces: `run_model_review_task(task_input, *, project_root, review_runner, trace_writer) -> LearningTaskResult`
- Produces: `model_review_result_to_legacy_response(result) -> dict[str, Any]`
- Panel and Worker both consume the same task service and adapter

- [ ] **Step 1: Write a failing service behavior test**

```python
def test_run_model_review_task_returns_safe_stopped_result(tmp_path):
    result = run_model_review_task(
        ModelReviewTaskInput(
            two_stage_report_path="input.json",
            screenshot_path="screen.png",
            composite_overlay_path="overlay.png",
        ),
        project_root=tmp_path,
        review_runner=lambda **_kwargs: {
            "status": "safe_stop",
            "calibration_permission": False,
        },
        trace_writer=lambda **_kwargs: "logs/traces/review.json",
    )

    assert result.outcome == "safe_stopped"
    assert result.payload["real_clicks"] == 0
    assert result.payload["live_fills"] == 0
    assert result.payload["live_submits"] == 0
    assert result.payload["trace_path"] == "logs/traces/review.json"
```

- [ ] **Step 2: Run the service test and verify RED**

Run:

```powershell
uv run pytest tests/test_learning_workflow_task_boundaries.py -k "run_model_review_task_returns_safe_stopped_result" -q
```

Expected: FAIL because `run_model_review_task` is not implemented.

- [ ] **Step 3: Implement the model review service**

The service must:

1. Resolve all three paths under `project_root`.
2. Call the injected `review_runner`.
3. Set `real_clicks`, `live_fills`, and `live_submits` to zero.
4. Write the same Trace operation and summary fields.
5. Return `completed` when calibration is permitted, `safe_stopped` otherwise.
6. Convert exceptions to `LearningTaskFailure(code="learning_model_review_repair_failed", details=str(exc))`.

- [ ] **Step 4: Implement the compatibility adapter**

```python
def model_review_result_to_legacy_response(
    result: LearningTaskResult,
) -> dict[str, Any]:
    if result.failure is not None:
        return {
            "success": False,
            "message": "Learning model review and repair failed",
            "data": result.payload,
            "error": result.failure.model_dump(mode="json"),
        }
    return {
        "success": True,
        "message": (
            "Learning model review and repair ready for calibration"
            if result.outcome == "completed"
            else "Learning model review and repair stopped safely"
        ),
        "data": result.payload,
        "error": None,
    }
```

- [ ] **Step 5: Convert the Panel route into an adapter**

Keep `PanelRunLearningModelReviewRepairRequest` and the route decorator unchanged. Convert `request.model_dump()` to `ModelReviewTaskInput`, call the service, convert with `model_review_result_to_legacy_response`, then return `APIResponse.model_validate(...)`.

- [ ] **Step 6: Convert only the Worker model-review branch**

Replace the dynamic import of `app.api.panel` for `panel_learning_model_review_repair` with imports from:

```python
app.learn.workflow_contracts
app.learn.workflow_tasks.model_review
app.learn.workflow_task_result_adapter
```

Do not change recognition or two-stage branches yet.

- [ ] **Step 7: Run focused tests**

Run:

```powershell
uv run pytest tests/test_learning_workflow_task_boundaries.py tests/test_learning_workflow_stage_worker.py -q
uv run pytest tests/test_learning_draft_review.py -k "model_review" -q
uv run python -m py_compile app/learn/workflow_contracts.py app/learn/workflow_task_result_adapter.py app/learn/workflow_tasks/model_review.py app/learn/workflow_worker.py app/api/panel.py
```

Expected: PASS.

- [ ] **Step 8: Verify model processes remain stopped**

Run the repository model-process check and assert zero known model processes and zero listeners on ports `1234,1244,1245,1246,1247,1248`.

- [ ] **Step 9: Commit the model-review checkpoint**

```powershell
git add app/learn/workflow_contracts.py app/learn/workflow_task_result_adapter.py app/learn/workflow_tasks app/learn/workflow_worker.py app/api/panel.py tests/test_learning_workflow_task_boundaries.py tests/test_learning_workflow_stage_worker.py tests/test_learning_draft_review.py
git commit -m "refactor: isolate learning model review task"
```

### Task 4: Extract Recognition Task

**Files:**
- Create: `app/learn/workflow_tasks/recognition.py`
- Modify: `app/learn/workflow_contracts.py`
- Modify: `app/learn/workflow_task_result_adapter.py`
- Modify: `app/api/panel.py`
- Modify: `app/learn/workflow_worker.py`
- Modify: `tests/test_learning_workflow_task_boundaries.py`
- Modify: `tests/test_learning_workflow_stage_worker.py`
- Modify: `tests/test_learning_draft_review.py`

**Interfaces:**
- Produces: `RecognitionTaskInput`
- Produces: `run_recognition_task(...) -> LearningTaskResult`
- Produces: `recognition_result_to_legacy_response(...) -> dict[str, Any]`

- [ ] **Step 1: Add a failing dual-entry recognition test**

Use one fixed `observation_evidence` payload and injected deterministic grounding adapter. Assert Panel and Worker compatibility responses have identical `success`, `message`, `data`, and `error`.

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
uv run pytest tests/test_learning_workflow_task_boundaries.py -k "recognition_dual_entry" -q
```

Expected: FAIL because `RecognitionTaskInput` and `run_recognition_task` do not exist.

- [ ] **Step 3: Add `RecognitionTaskInput`**

It must preserve:

```python
app_name: str = "unknown_app"
state_hint: str = ""
summary: str = ""
observation_evidence: dict[str, Any] = Field(default_factory=dict)
crop_size: dict[str, Any] = Field(default_factory=dict)
two_stage_report_path: str | None = None
```

- [ ] **Step 4: Move recognition orchestration and exclusive helpers**

Move only helpers whose callers are limited to the recognition route/task. For Panel helpers still shared by unrelated routes, introduce explicit callable dependencies instead of importing Panel.

- [ ] **Step 5: Convert Panel and Worker adapters**

Keep the route decorator and public request class unchanged. Remove only the recognition branch dynamic import from Worker.

- [ ] **Step 6: Run focused regression**

Run:

```powershell
uv run pytest tests/test_learning_workflow_task_boundaries.py tests/test_learning_workflow_stage_worker.py -q
uv run pytest tests/test_learning_draft_review.py -k "recognition" -q
uv run python -m py_compile app/learn/workflow_tasks/recognition.py app/learn/workflow_worker.py app/api/panel.py
```

Expected: PASS with all read-only and safety assertions unchanged.

- [ ] **Step 7: Commit the recognition checkpoint**

```powershell
git add app/learn/workflow_contracts.py app/learn/workflow_task_result_adapter.py app/learn/workflow_tasks/recognition.py app/learn/workflow_worker.py app/api/panel.py tests/test_learning_workflow_task_boundaries.py tests/test_learning_workflow_stage_worker.py tests/test_learning_draft_review.py
git commit -m "refactor: isolate learning recognition task"
```

### Task 5: Extract Two-Stage Understanding Task

**Files:**
- Create: `app/learn/workflow_tasks/two_stage.py`
- Modify: `app/learn/workflow_contracts.py`
- Modify: `app/learn/workflow_task_result_adapter.py`
- Modify: `app/api/panel.py`
- Modify: `app/learn/workflow_worker.py`
- Modify: `tests/test_learning_workflow_task_boundaries.py`
- Modify: `tests/test_learning_workflow_stage_worker.py`
- Modify: `tests/test_deterministic_root_partition.py`
- Modify: `tests/test_learn_recognition_pipeline.py`

**Interfaces:**
- Produces: `TwoStageTaskInput`
- Produces: `run_two_stage_task(...) -> LearningTaskResult`
- Produces: `two_stage_result_to_legacy_response(...) -> dict[str, Any]`

- [ ] **Step 1: Add a failing dual-entry two-stage test**

Use a fixed inline observe result with a temporary source image. Assert Panel and Worker produce the same compatibility response and preserve Stage1 gate, Stage2 strategy, fusion status, overlay path, and safety fields.

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
uv run pytest tests/test_learning_workflow_task_boundaries.py -k "two_stage_dual_entry" -q
```

Expected: FAIL because `TwoStageTaskInput` and `run_two_stage_task` do not exist.

- [ ] **Step 3: Add `TwoStageTaskInput`**

It must preserve:

```python
app_name: str = "unknown_app"
state_hint: str = ""
trace_path: str | None = None
source_image_path: str | None = None
observe_result: dict[str, Any] = Field(default_factory=dict)
require_stage1_gate: bool = True
stage2_region_strategy: Literal["partitioned", "global_no_partition"] = "partitioned"
```

- [ ] **Step 4: Move orchestration and two-stage-only helpers**

Move observe normalization, source-image override, layout graph construction, surface-rule loading, fusion status, review-box summary, artifact save, and Trace mapping into the application service or explicit neutral collaborators.

- [ ] **Step 5: Convert Panel and Worker adapters**

Remove the final Panel dynamic import from Worker. Keep public route and request schema unchanged.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
uv run pytest tests/test_learning_workflow_task_boundaries.py tests/test_learning_workflow_stage_worker.py -q
uv run pytest tests/test_deterministic_root_partition.py tests/test_learn_recognition_pipeline.py -q
uv run python -m py_compile app/learn/workflow_tasks/two_stage.py app/learn/workflow_worker.py app/api/panel.py
```

Expected: PASS.

- [ ] **Step 7: Commit the two-stage checkpoint**

```powershell
git add app/learn/workflow_contracts.py app/learn/workflow_task_result_adapter.py app/learn/workflow_tasks/two_stage.py app/learn/workflow_worker.py app/api/panel.py tests/test_learning_workflow_task_boundaries.py tests/test_learning_workflow_stage_worker.py tests/test_deterministic_root_partition.py tests/test_learn_recognition_pipeline.py
git commit -m "refactor: isolate learning two-stage task"
```

### Task 6: Close The Dependency Boundary

**Files:**
- Modify: `tests/test_learning_workflow_task_boundaries.py`
- Modify: `PROJECT_SUMMARY.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`
- Review: `README.md`

**Interfaces:**
- Verifies: no direct, dynamic, string-based, or transitive Learn task dependency on `app.api.*`
- Documents: final Panel adapter, Learn service, and Worker lifecycle boundaries

- [ ] **Step 1: Add static boundary tests**

Parse imports and string constants under:

```text
app/learn/workflow_worker.py
app/learn/workflow_contracts.py
app/learn/workflow_task_result_adapter.py
app/learn/workflow_tasks/
```

Fail on:

```text
from app.api
import app.api
importlib.import_module("app.api...")
"app.api.panel"
```

- [ ] **Step 2: Add clean-process runtime test**

Spawn a Python process that imports the worker and executes a deterministic non-model task path. Assert the reported module list does not contain `app.api.panel`.

- [ ] **Step 3: Run boundary tests**

Run:

```powershell
uv run pytest tests/test_learning_workflow_task_boundaries.py -q
```

Expected: PASS.

- [ ] **Step 4: Run complete verification**

Run:

```powershell
uv run pytest tests/test_learning_workflow_stage_worker.py -q
uv run pytest tests -q
uv run python -m py_compile app/api/panel.py app/learn/workflow_worker.py app/learn/workflow_contracts.py app/learn/workflow_task_result_adapter.py app/learn/workflow_tasks/model_review.py app/learn/workflow_tasks/recognition.py app/learn/workflow_tasks/two_stage.py
```

Then check:

- Panel `/health` returns `status=ok`.
- Known model process count is zero.
- Known model listener count is zero.
- `git diff --stat` contains only planned files.

- [ ] **Step 5: Update architecture and state documents**

Document:

- Panel as HTTP adapter;
- Learn tasks as application services;
- Worker as process lifecycle owner;
- neutral task contracts;
- unchanged safety boundary and no-click behavior;
- completed tests and remaining cleanup candidates.

- [ ] **Step 6: Commit the boundary closure**

```powershell
git add tests/test_learning_workflow_task_boundaries.py PROJECT_SUMMARY.md ARCHITECTURE.md CURRENT_STATE.md NEXT_STEPS.md README.md
git commit -m "docs: record learning worker service boundary"
```
