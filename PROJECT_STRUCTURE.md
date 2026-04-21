# PROJECT_STRUCTURE

## Purpose

This file is the concrete repository map for day-to-day development.

Use it when you need to answer:

- where a feature lives
- where a config file is loaded
- where runtime artifacts are written
- which entrypoint to call for a given capability

`README.md` should stay concise. This file can be more explicit.

## Root Layout

### Runtime code

- `app/`
  - FastAPI runtime, Windows integration, persistence, schemas, and API routes

### Pure logic

- `modules/`
  - testable logic extracted from runtime shells
  - no FastAPI-specific code
  - no Windows handle management

### Config

- `configs/`
  - runtime configuration files
  - currently most relevant file: `configs/vision.json`

### Evidence and persistence

- `logs/`
  - screenshots
  - diff images
  - action/state memory JSON
  - replay cases
  - transition records

### Tests

- `tests/`
  - pytest coverage for extracted logic and route-level behavior

### Project memory and takeover docs

- `README.md`
  - concise overview, setup, endpoints, roadmap
- `PROJECT_SUMMARY.md`
  - what the project is and current direction
- `ARCHITECTURE.md`
  - runtime layers and execution paths
- `CURRENT_STATE.md`
  - verified status, risks, current branch reality
- `NEXT_STEPS.md`
  - short prioritized roadmap
- `PROJECT_CONTEXT.md`
  - Codex-native replacement for OpenClaw project context
- `RULES.md`
  - working rules and migration constraints
- `KNOWLEDGE_BASE.md`
  - recovered implementation knowledge
- `AGENTS.md`
  - repository-level working instructions for the coding agent

## app/

### Entry

- `app/main.py`
  - FastAPI application entrypoint
  - registers routers
  - configures runtime logging

### API routes

- `app/api/session.py`
  - `GET /session/windows`
  - `POST /session/bind_window`
  - responsibility: list visible windows and bind the runtime to one target window

- `app/api/state.py`
  - `GET /state`
  - `POST /state/capture_window`
  - responsibility: expose current bound-window state and screenshot capture

- `app/api/vision.py`
  - `POST /vision/ocr_region`
  - `POST /vision/analyze`
  - responsibility:
    - OCR a bound-window ROI through the OCR adapter
    - run provider-based vision analysis through the `app/vision/` abstraction
    - normalize learned regions
    - persist annotated screenshots and per-region crops for later page-structure building

- `app/api/action.py`
  - `POST /action/click_text`
  - `POST /action/click_mouse_tester_left_region`
  - responsibility:
    - OCR-driven text click
    - MouseTester-specific region click with validation and persistence

### Runtime services

- `app/core/window_manager.py`
  - visible-window enumeration
  - target window matching
  - foreground focus and bound-window refresh

- `app/core/screenshot.py`
  - capture the bound window or ROI with `mss`
  - writes `capture-*.png` files to `logs/`

- `app/core/ocr_service.py`
  - lazy OCR adapter
  - RapidOCR first, PaddleOCR fallback
  - converts raw OCR output into `modules.ocr` contracts

- `app/core/input_controller.py`
  - low-level mouse movement and click dispatch through `SendInput`

- `app/core/verifier.py`
  - before/after capture
  - OpenCV diff-based verification
  - writes `verify-*.png` diff artifacts to `logs/`

- `app/core/action_registry.py`
  - JSON persistence for:
    - app states
    - action targets
    - validator profiles

- `app/core/transition_memory.py`
  - persists transition records to `logs/app-transitions/`

- `app/core/replay_case_store.py`
  - persists replay cases to `logs/replay-cases/`

### Action orchestration

- `app/actions/known_action_runner.py`
  - wraps execution with evidence capture
  - writes replay and transition artifacts

### Request/response models

- `app/models/request.py`
  - API request payloads
  - actual current models in use:
    - `BindWindowRequest`
    - `CaptureWindowRequest`
    - `OCRRegionRequest`
    - `ClickTextRequest`
    - `VisionAnalyzeRequestModel`

- `app/models/response.py`
  - common API envelope and response payload models

### Persisted schemas

- `app/schemas/state.py`
  - `AppState`

- `app/schemas/action_target.py`
  - `ActionTarget`

- `app/schemas/validator_profile.py`
  - `ValidatorProfile`

- `app/schemas/replay_case.py`
  - `ReplayCase`

- `app/schemas/transition.py`
  - `TransitionRecord`

### Vision provider layer

- `app/vision/`
  - provider abstraction for `/vision/analyze`

Key files:

- `factory.py`
  - loads provider config and constructs provider instances
- `local_provider.py`
  - local provider stub
- `api_provider.py`
  - API provider stub
- `normalizer.py`
  - normalizes provider output into a stable schema
- `schemas.py`
  - dataclasses for provider I/O
- `prompting.py`
  - model-facing prompt contract for `vision_regions_v1`
- `region_standard.py`
  - deterministic coordinate normalization and region match-key helpers
- `artifacts.py`
  - writes full annotated screenshots, per-region crops, per-region annotated crops, and `regions.json`

Current status:

- structure exists
- `/vision/analyze` can call into it
- providers are still stub implementations
- learned region artifacts are persisted locally under `logs/vision-regions/`
- the next intended layer is a page-structure builder that summarizes learned regions for the agent

### Vision execution protocol

- `app/vision_protocol/`
  - parser and executor-adapter for structured vision outputs
  - not yet the primary runtime path

## modules/

### `modules/ocr/`

- `contracts.py`
  - OCR bounding box and OCR result data types
- `matching.py`
  - text normalization
  - match ranking
  - bbox center calculation

Used by:

- `app/core/ocr_service.py`
- `app/api/action.py`

### `modules/click/`

- `geometry.py`
  - translate window-relative points to screen coordinates

Used by:

- `app/core/input_controller.py`

### `modules/region/`

- `geometry.py`
  - window rect normalization
  - MouseTester panel location
  - zone point generation
  - normalized point persistence helpers

Used by:

- `app/api/action.py`

### `modules/validation/`

- `counter.py`
  - numeric counter extraction and comparison helpers

Used by:

- `app/api/action.py`

## configs/

### `configs/vision.json`

Current purpose:

- choose provider mode for `/vision/analyze`
- define fallback mode
- set provider-specific endpoint/model placeholders

Current shape:

- `vision.mode`
- `vision.fallback_mode`
- `vision.timeout_seconds`
- `vision.local.*`
- `vision.api.*`

Current reality:

- local and API provider entries exist
- both are still stubs unless replaced with real endpoints

### Other config folders

- `configs/rois/`
- `configs/scenes/`
- `configs/templates/`

Current status:

- retained from older design direction
- not part of the active mainline runtime path right now

## logs/

Important runtime persistence paths:

- `logs/app-states/`
  - `AppState` JSON files

- `logs/app-actions/`
  - `ActionTarget` JSON files

- `logs/app-actions/validators/`
  - `ValidatorProfile` JSON files

- `logs/app-transitions/`
  - transition records

- `logs/replay-cases/`
  - replay/debug evidence bundles

- `logs/region-click-cache/`
  - learned normalized click point memory

- `logs/region-click-cases/`
  - per-run region click cases

Also written here:

- `app.log`
- `capture-*.png`
- `verify-*.png`

## tests/

Current test coverage:

- `test_action_registry.py`
  - registry persistence

- `test_click_geometry.py`
  - coordinate translation

- `test_click_text_route.py`
  - route-level `click_text` behavior
  - ROI offset handling
  - retry fallback behavior

- `test_ocr_matching.py`
  - OCR text matching and bbox center logic

- `test_region_geometry.py`
  - region point generation

- `test_validation_counter.py`
  - counter extraction and verification logic

## How Features Map To Files

### Window binding

- route: `app/api/session.py`
- core logic: `app/core/window_manager.py`

### Screenshot capture

- route: `app/api/state.py`
- core logic: `app/core/screenshot.py`

### OCR region

- route: `app/api/vision.py`
- OCR runtime: `app/core/ocr_service.py`
- OCR contracts/matching: `modules/ocr/`

### click_text

- route: `app/api/action.py`
- OCR runtime: `app/core/ocr_service.py`
- text matching: `modules/ocr/matching.py`
- click dispatch: `app/core/input_controller.py`
- verification: `app/core/verifier.py`

### MouseTester region click

- route: `app/api/action.py`
- region geometry: `modules/region/geometry.py`
- click dispatch: `app/core/input_controller.py`
- validation: `app/core/verifier.py` and `modules/validation/counter.py`
- persistence: `app/core/action_registry.py`, `app/actions/known_action_runner.py`

### vision analyze

- route: `app/api/vision.py`
- provider loading: `app/vision/factory.py`
- provider impls: `app/vision/local_provider.py`, `app/vision/api_provider.py`
- learned region artifacts: `app/vision/artifacts.py`
- protocol handling: `app/vision_protocol/`

### planned page structure

- source inputs:
  - normalized `vision_regions_v1`
  - saved region artifacts
  - historical `match_key` reuse
- intended output:
  - `page_id`
  - `page_name`
  - `screen_summary`
  - `sections[]`
  - `elements[]`
  - `destination_page_id`
  - `expected_result`
  - `priority`
  - `recommended_action_id`

This layer is not yet implemented in code, but it is now the intended agent-facing structure.

## Active Vs Legacy

### Active mainline

- `session`
- `state`
- `vision/ocr_region`
- `vision/analyze`
- `action/click_text`
- `action/click_mouse_tester_left_region`

### Legacy or partially retained structures

- old template/scene config folders
- old request models for template/wait flows in `app/models/request.py`
- `app/vision/` provider abstraction is active structurally but still stubbed behaviorally

## Recommended Documentation Split

Keep this split:

- `README.md`
  - concise overview
  - setup
  - active endpoints
  - short structure tree
  - link to this file

- `PROJECT_STRUCTURE.md`
  - detailed folder-by-folder map
  - file ownership by feature
  - config and persistence locations

This keeps `README.md` useful for first entry while preserving a real handoff document for development.
