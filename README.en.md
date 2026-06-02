# agent-gui-runtime

[Chinese](README.md) | English

A local Windows-only GUI automation runtime for AI agents.

`agent-gui-runtime` is not a full agent. It is an execution layer that exposes stable local HTTP APIs so an upper-layer agent can discover applications, bind windows, capture screenshots, run OCR and vision recognition, build click plans, execute gated clicks, and verify results.

Core path:

```text
Agent -> local HTTP API -> GUI runtime -> bound Windows window
```

## Setup And Startup

### 1. Requirements

- Windows 10 / Windows 11
- Python 3.11
- `uv`
- Local vision models are optional. Without a model you can still open the test panel and exercise basic APIs.

### 2. Install Dependencies

```powershell
uv sync
```

`FastAPI` and `uvicorn[standard]` are declared in `pyproject.toml`, so `uv sync` installs them automatically. You do not need a separate `pip install fastapi`.

Optional verification:

```powershell
uv run python -c "import fastapi, uvicorn; print('FastAPI runtime deps ok')"
```

### 3. One-Click Test Panel Startup

Double-click from the repository root:

```text
start_test_panel.bat
```

It no longer depends on a PowerShell launcher, because some antivirus tools quarantine `.ps1` launchers. The batch file:

- checks `http://127.0.0.1:8000/health`
- starts the FastAPI runtime in a minimized `cmd` window when needed
- opens the browser test panel at `http://127.0.0.1:8000/panel`
- appends runtime logs to `logs\test-panel-runtime.log`


```text
```

Command-line startup:

```bat
start_test_panel.bat
```

Startup-path check only:

```powershell
```

### 4. Manual Runtime Startup

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open API docs:

```text
http://127.0.0.1:8000/docs
```

Open the test panel manually:

```powershell
```

### 5. Local Vision Models

The recommended path is through the test panel:

1. Open the `Screen understanding` or `Precise localization` stage.
2. Select a model profile.
3. Click `Start local vision model`.
4. Click `Test model /v1/models`.

When a model has just started, `/v1/models` may briefly return `Loading model`. The test panel reports that state as model loading instead of service failure. During that warm-up window, runtime vision requests wait for the model to become available before continuing.

Model profiles live in:

```text
configs/model_profiles/
```

Model server scripts live in:

```text
scripts/model_servers/
```

Current profiles include:

- `configs/model_profiles/qwen3_6_iq4_xs.json`
- `configs/model_profiles/qwen3_vl_8b_q4_k_m.json`

Manual llama.cpp vision-model startup:

```powershell
.\scripts\model_servers\start_llama_vision_server.ps1
```

Stop local vision models:

```powershell
.\scripts\model_servers\stop_local_vision_server.ps1
```

Use another GGUF model:

```powershell
.\scripts\model_servers\start_llama_vision_server.ps1 `
  -ModelPath .\models\some-model.gguf `
  -MmprojPath .\models\some-mmproj.gguf
```

## Test Panel

The browser test panel is now the recommended debugging entry point:

```text
http://127.0.0.1:8000/panel
```


The browser panel follows the agent workflow:

1. Runtime preparation
2. App discovery
3. Open / bind
4. Screen understanding
5. Precise localization
6. Gated execution

Main capabilities:

- `GET /health` runtime health
- `GET /runtime/models` model status
- `POST /runtime/prepare` runtime preparation
- `POST /runtime/models/start` / `POST /runtime/models/stop` model start and stop
- Chinese/English UI switching
- observe / locate model profile dropdowns
- model start/stop script display
- model service `/v1/models` status test
- `GET /apps` app discovery
- `POST /apps/open` open app
- `GET /session/windows` list visible windows
- `POST /session/bind_window` bind window
- open-window dropdown selection with process/title binding fields
- `POST /state/capture_window` screenshot capture and preview
- Drag or choose a local image and upload it as a saved screenshot test input
- `POST /vision/observe_screen` screen understanding
- `POST /vision/locate_target` precise localization
- Automatic candidate bbox / point fill for operator review
- `POST /action/execute_recognition_plan` dry-run click gate
- `POST /action/execute_confirmed_point` operator-reviewed coordinate dry-run / real click
- `POST /action/type_text` controlled text input
- Recognition overlay rendering
- Observe / locate additional prompt rules
- Screenshot, uploaded image, overlay image, and candidate-box preview
- Raw JSON responses for each stage


Long model-backed requests run in worker threads, so the panel remains responsive during screen understanding, precise localization, and dry-run execution. These requests use the panel `Timeout seconds` value from `configs/vision.json`; the local default is `600` seconds because the large grounding model can legitimately run for several minutes.

Screen understanding and precise localization keep separate prompt defaults:

- Screen understanding is a fast discovery stage. It asks the smaller model for a compact screen summary and actionable-control shortlist. It does not ask the model to repeat OCR boxes or detailed grounding evidence.
- Screen understanding now asks `state_guess` to be a concise localization hint for the next stage. `POST /vision/observe_screen` exposes it as `suggested_state_hint`, and the panel auto-fills that value into the precise-localization State hint field.
- Precise localization is a single-target grounding stage. It handles only the chosen goal, distinguishes visual-only icons from text-bearing controls, and asks for OCR anchor relations, edge constraints, center constraints, size constraints, negative constraints, and a final bbox reason.

For visual-only icons, a strong large-model bbox can be returned as `located_bbox` / `located_point` for review. It does not automatically become an executable click point and does not drift to nearby OCR text.

## Model Management

Model configuration is registry-based:

```text
configs/model_profiles/*.json
```

A profile describes:

- `profile_id`
- `label`
- `role`
- `provider_mode`
- `input_format`
- `model_name`
- `endpoint`
- `model_path`
- `mmproj_path`
- `server_path`
- `start_script`
- `stop_script`
- `port`
- `context_size`
- `gpu_layers`
- `image_min_tokens`
- `supports_ocr_anchors`
- `best_for`
- `limitations`

The active runtime selection is written to:

```text
configs/vision.json
```

The runtime currently uses two local vision roles:

- `vision.local_understanding`: smaller model for fast screen understanding and candidate indexing.
- `vision.local_grounding`: larger model for precise target localization.

The test panel model dropdowns read only from `configs/model_profiles/`, which avoids duplicate model definitions from multiple sources.

## Agent Workflow

Upper-layer agents should use the API-first workflow. They should not directly click raw visual-model coordinates.

Recommended sequence:

```text
GET  /apps
POST /runtime/prepare            optional, checks/starts local vision models
POST /apps/open                 optional
GET  /session/windows
POST /session/bind_window
POST /state/capture_window      optional; APIs can also capture live
POST /vision/observe_screen
POST /vision/locate_target
POST /action/execute_recognition_plan  dry_run=true
POST /action/execute_recognition_plan  dry_run=false with approved_plan_id
```

Key rules:

- First use screen understanding to get a compact candidate list, then precisely locate the chosen target.
- `observe_screen.suggested_state_hint` is the default suggestion for the next `locate_target.state_hint`. The panel auto-fills it, and an agent can still override it.
- The upper-layer agent should preserve the user's original instruction for trace review, but send normalized English `goal`, `state_hint`, and negative constraints to the vision model. Example: `Click the first organic Google search result title` with `main organic search results list below Google navigation tabs`.
- OCR anchors participate in visual localization by default. The runtime keeps full OCR evidence for traces and validation, but precise localization sends a bounded projection to the model.
- `observe_screen` is for screen summary and candidate discovery, not click proof.
- `locate_target` returns a no-click localization result.
- `located_bbox` / `located_point` are model-suggested review coordinates. Only `selected_click_point` means the local pre-click gate approved an executable point.
- Autonomous agents should execute real clicks only through `execute_recognition_plan`.
- The test panel's `execute_confirmed_point` endpoint is only for an operator-reviewed coordinate click after a human has inspected the candidate box.
- Execution must pass `pre_click_decision_v1`.
- A successful dry-run returns `approved_plan_id`. Reuse that ID for the real click so the runtime validates the same window and approved point, then clicks without running the large vision model a second time.
- `learning_mode="instruction"` is the minimal instruction-learning mode: after a successful real click and verification, the runtime writes `learned_instruction_v1`. A later call with `learned_instruction_id` reuses the click point only after validating the same goal, window handle, window size, and point bounds, and still runs post-click verification.
- Instruction-learning assets are not ordinary screenshot-cache files. Each learned instruction is permanently stored under `artifacts/local-learning/instructions/{id}/` with `learned_instruction.json`, the source window screenshot, pre-action screenshot, post-action screenshot, diff image, and target crop. The desktop response path graph renders this learning-asset bundle as an artifact node.
- Agent-facing runtime, app, vision, and recognition-execution paths now include `timings` with `total_ms` and `steps[]` so agents can see whether time was spent in model startup, screenshot capture, OCR anchor preparation, vision inference, ranking, the pre-click gate, click dispatch, or post-click verification.

Full agent workflow:

```text
AGENT_API_WORKFLOW.md
```

Chinese field-by-field API reference:

```text
API_FIELD_REFERENCE.zh-CN.md
```

## Text-Card Localization Safety

Text-bearing clickable targets have a conservative review path. Their proposed bbox and point come from matched OCR text rather than a drifting visual card boundary, and this is not an autonomous click approval. If the larger semantic bbox contains unreferenced OCR text outside the selected target text cluster, fusion records `unreferenced_text_contamination` and keeps the candidate in confirmation-required `precise_text_target` mode.


## Main Endpoints

Apps and windows:

- `GET /apps`
- `POST /runtime/prepare`
- `GET /runtime/models`
- `POST /runtime/models/start`
- `POST /runtime/models/stop`
- `POST /apps/open`
- `GET /session/windows`
- `POST /session/bind_window`
- `GET /state`
- `POST /state/capture_window`

Vision:

- `POST /vision/analyze`
- `POST /vision/page_structure`
- `POST /vision/screen_reading`
- `POST /vision/observe_screen`
- `POST /vision/locate_target`
- `POST /vision/recognition_plan`
- `POST /vision/render_recognition_plan_overlay`

Actions:

- `POST /action/execute_recognition_plan`
- `POST /action/execute_confirmed_point`
- `POST /action/type_text`
- `POST /action/click_text`
- `POST /action/click_mouse_tester_left_region`

## Recognition Pipeline

Current main path:

```text
screenshot
-> OCR anchors
-> vision_regions_v1 + OCR
-> page_structure_v1
-> screen_reading_v1
-> candidate_rank_v1
-> narrow_search_v1
-> pre_click_decision_v1
-> gated action
```

Important points:

- OCR text boxes are used as spatial anchors for vision grounding.
- `click_target` sends a `relation_matrix_compact` text-coordinate and inclusion/exclusion policy matrix by default, selecting anchors within a prompt budget instead of injecting a verbose full-page structure.
- Icon/text relations are carried as grounding evidence.
- Small-icon localization prioritizes OCR anchor context.
- Candidate click points must pass local ranking, narrow search, and the pre-click gate.
- Overlays are available for human review.

## Project Structure

```text
app/
  api/                FastAPI routes
  core/               window, screenshot, OCR, input, verifier
  vision/             local/API vision providers and prompting
  page_structure/     page structure and screen reading logic
  models/             request/response schemas
configs/
  app_catalog.json
  settings_panel.json
  vision.json
  model_profiles/     model registry
scripts/
  model_servers/      model server start/stop scripts
tests/
artifacts/
logs/
```

Detailed structure:

```text
PROJECT_STRUCTURE.md
```

## Current State

Implemented:

- Local FastAPI runtime
- Windows window discovery and binding
- Screenshot and ROI screenshot capture
- OCR anchors
- Local/API vision provider abstraction
- `observe_screen` screen-understanding endpoint
- `locate_target` precise-localization endpoint
- No-click recognition plan
- Pre-click decision gate
- Gated click execution
- Recognition overlays
- MouseTester real-click baseline
- Desktop test panel
- Model registry and unified model-server script directory

Current boundaries:

- This is not yet a production-grade general desktop agent.
- More pages, negative cases, window sizes, DPI settings, and browser zoom states still need testing.
- Successful-run learning write-back is not yet a mainline capability.

## Verification

Latest browser-panel migration checks:

```powershell
node --check app\web_panel\panel.js
uv run pytest tests\test_web_panel_route.py tests\test_runtime_route.py -q
uv run pytest -q
```

Current result:

```text
targeted panel/runtime route tests: 10 passed
full suite: 141 passed
```

Useful targeted check:

```powershell
```

For broader regression coverage:

```powershell
uv run pytest -q
```

## Important Documents

- `README.md`: Chinese README
- `AGENT_API_WORKFLOW.md`: standard API workflow for agents
- `API_FIELD_REFERENCE.zh-CN.md`: Chinese field-level API reference
- `PROJECT_STRUCTURE.md`: file structure, config, and artifact locations
- `PROJECT_SUMMARY.md`: project summary
- `CURRENT_STATE.md`: current implementation state
- `NEXT_STEPS.md`: next planned work
- `ACCURACY_EVALUATION_STANDARD.md`: accuracy evaluation standard
- `RUNTIME_STATE_GRAPH.md` / `RUNTIME_STATE_GRAPH.zh-CN.md`: runtime state graph design

## Development Rules

This repository requires code and documentation to stay in sync. When behavior, API shape, architecture, configuration, progress, or limitations change, update the relevant docs in the same work session.

When implementing code, follow:

```text
skills/code-implementation-loop/SKILL.md
```

Smallest useful loop:

1. Make the smallest meaningful change.
2. Run the narrowest relevant verification.
3. Inspect the result.
4. Fix failures.
5. Rerun until the path is verified or a real blocker remains.

## Maintenance Notes

- Windows only
- Local-only HTTP API
- Prefer one session / one bound window
- Do not click directly from raw model bboxes
- All real clicks should go through the gated action API
- Keep historical experiment details in dedicated docs instead of growing the README indefinitely

## Browser Panel Status (2026-06-02)

`/panel` is the only retained local test-panel entry. The old Tkinter desktop panel code, launcher, tests, and `tkinterdnd2` dependency have been removed. `start_test_panel.bat` starts the FastAPI runtime when needed and opens `http://127.0.0.1:8000/panel`.

The browser panel now uses segmented language buttons, a trace-grouped top flow strip, stage-specific layouts, a Trace page backed by `/panel/inspect_trace` `flow_stages`, and a Models page backed by `POST /panel/model_test` for direct prompt/image calls to configured vision models.

Latest verification: `node --check app\web_panel\panel.js`; `python -m py_compile app\main.py app\api\panel.py`; `uv run pytest tests\test_web_panel_route.py tests\test_runtime_route.py -q` -> `11 passed`; `uv run pytest -q` -> `136 passed`; a temporary uvicorn smoke returned 200 for `/panel` and `/panel/assets/panel.js`.

### 2026-06-02 Trace UTF-8 compatibility update

The browser panel now serves `/panel` as `text/html; charset=utf-8`; trace JSON inspection reads files with `utf-8-sig` so UTF-8 files with BOM are accepted. `/panel/inspect_trace` supports current recognition/screen-reading traces plus older overlay traces and `vision_layer_trace_v1` layer traces by returning stage-oriented `flow_stages` with raw per-stage JSON for the Trace Flow UI.

Latest verification after this update: `node --check app\web_panel\panel.js`; `python -m py_compile app\api\panel.py`; `uv run pytest tests\test_web_panel_route.py -q` -> `9 passed`; `uv run pytest -q` -> `138 passed`; uvicorn smoke returned `/panel` 200 with `text/html; charset=utf-8` and no remaining visible mojibake in Trace controls.
