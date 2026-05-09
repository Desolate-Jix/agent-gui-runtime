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

- `artifacts/`
  - screenshots
  - verification diff images
  - vision region image bundles
- `logs/`
  - structured JSON traces
  - action/state memory JSON
  - replay cases
  - transition records

### Tests

- `tests/`
  - pytest coverage for extracted logic and route-level behavior

### Project memory and takeover docs

- `README.md`
  - concise overview, setup, endpoints, roadmap
- `PROJECT_STRUCTURE.md`
  - detailed repository map, file ownership, and persistence/config locations
- `PROJECT_CONTEXT.md`
  - Codex-native replacement for OpenClaw project context
- `RULES.md`
  - working rules and migration constraints
- `KNOWLEDGE_BASE.md`
  - recovered implementation knowledge
- `ACCURACY_EVALUATION_STANDARD.md`
  - stage-by-stage completion rubric, accuracy thresholds, and optimization workflow
- `RUNTIME_STATE_GRAPH.md`
  - English design/reference doc for runtime state graph growth and reuse
- `RUNTIME_STATE_GRAPH.zh-CN.md`
  - Chinese version of the runtime state graph reference
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
  - `POST /vision/page_structure`
  - `POST /vision/layer_trace`
  - `POST /vision/render_review_overlay`
  - responsibility:
    - OCR a bound-window ROI through the OCR adapter
    - run provider-based vision analysis through the `app/vision/` abstraction
    - normalize learned regions
    - fuse semantic regions with OCR text boxes into `page_structure_v1`
    - expose a test/debug trace that shows every layer result and schema validation
    - redraw region/OCR boxes on the original screenshot for human review
    - optionally feed the local provider a light pixel-grid reference overlay for bbox-accuracy experiments
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
  - writes purpose- and ROI-labeled screenshots to `artifacts/screenshots/`

- `app/core/ocr_service.py`
  - lazy OCR adapter
  - RapidOCR first, PaddleOCR fallback
  - converts raw OCR output into `modules.ocr` contracts

- `app/core/input_controller.py`
  - low-level mouse movement and click dispatch through `SendInput`

- `app/core/verifier.py`
  - before/after capture
  - OpenCV diff-based verification
  - writes diff artifacts to `artifacts/verification/`

- `app/core/runtime_artifacts.py`
  - shared naming and storage helpers for screenshots, verification images, and JSON traces

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
  - route payloads may include `execution_path` and `trace_path` inside `result`

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
  - local OpenAI-compatible multimodal provider for Qwen3-VL-style backends
  - falls back to stub behavior only when no endpoint is configured
  - rescales large screenshots for inference, retries with a compact prompt after truncated JSON, remaps coordinates back to original pixels, and can optionally render a light grid/tick reference image for inference
- `api_provider.py`
  - API provider stub
- `normalizer.py`
  - normalizes provider output into a stable schema
- `schemas.py`
  - dataclasses for provider I/O
- `prompting.py`
  - model-facing prompt contract for `vision_regions_v1`
- `grid_overlay.py`
  - draws light review/inference grids with pixel tick labels and denser minor guide lines for bbox experiments
- `region_standard.py`
  - deterministic coordinate normalization and region match-key helpers
- `artifacts.py`
  - writes full annotated screenshots, per-region crops, per-region annotated crops, and `regions.json`
- `layer_trace.py`
  - validates and summarizes each stage of the vision/OCR/fusion pipeline for test visibility
- `review_overlay.py`
  - renders human-review overlays from saved `layer_trace` JSON files
  - supports red region boxes plus blue OCR boxes on the original screenshot
  - can draw either raw provider regions or another trace layer for comparison
- `ocr_region_refiner.py`
  - experimental OCR-assisted box correction that shifts semantic regions toward matching OCR text without editing OCR output

Current status:

- structure exists
- `/vision/analyze` can call into it
- the local provider can invoke a configured local multimodal endpoint and normalize model JSON
- local provider traces preserve per-attempt metadata such as scaled inference size, compact retry mode, coordinate remap evidence, and optional grid-reference artifact paths
- optional OCR-assisted refinement can add a second `vision_regions_refined_v1` layer for trace comparison without overwriting the raw provider layer
- the API provider remains a stub implementation
- learned region artifacts are persisted locally under `artifacts/vision-regions/`

### Page structure fusion layer

- `app/page_structure/`
  - deterministic fusion layer that consumes normalized `vision_regions_v1` plus `OCRResult`
  - outputs `page_structure_v1`
  - does not call an LLM; it keeps click, verification, fallback, and memory decisions transparent

Key files:

- `schemas.py`
  - dataclasses for `PageStructure`, `PageElement`, `PageText`, `PageLink`, `VerificationHints`, and `InteractionPolicy`
- `fusion.py`
  - rule-based binding between Qwen semantic regions and OCR text boxes
  - first supported element roles: `button`, `input`, `tab`, `menu_item`
  - maps semantic `nav`/`menu`/`link` roles to `menu_item`
  - applies rule-based interaction learning to separate trusted test actions from ad-like candidates

Runtime input:

- `VisionAnalyzeResponse`
  - normalized Qwen/local-provider output
  - supplies semantic roles, descriptions, destinations, region bbox, and region match keys
- `OCRResult`
  - RapidOCR/PaddleOCR text boxes
  - supplies text, OCR confidence, and precise text bbox for click grounding

Runtime output:

- `contract_version`
  - always `page_structure_v1`
  - lets action/memory code distinguish fused page structure from raw `vision_regions_v1`
- `image_size`
  - screenshot dimensions used by both providers
  - keeps downstream coordinate interpretation explicit
- `screen_summary`
  - Qwen-level page summary
  - useful for state naming and human debugging
- `state_guess`
  - best semantic page/state guess
  - weak hint only; local state matching should still verify
- `regions`
  - normalized semantic regions copied from `vision_regions_v1`
  - preserves Qwen's page layout interpretation for learning and debugging
- `elements`
  - executable UI candidates produced by fusion
  - first layer intended for future action selection
- `texts`
  - raw OCR text boxes normalized into page-structure coordinates
  - kept separate because OCR evidence is not the same thing as an executable element
- `links`
  - evidence relationships between regions, texts, and elements
  - explains why a text box was bound to a semantic region or left unbound
- `learning_summary`
  - page-level rule output for safe elements, blocked elements, and ad-like candidates
  - first profile: `rule_based_interaction_learning_v1`
- `raw_ocr`
  - complete OCR result as returned by `modules.ocr`
  - supports replay and failure analysis
- `raw_vision_regions`
  - complete normalized semantic region list
  - supports replay and future memory rebuilding

`PageElement` fields:

- `element_id`
  - deterministic-ish element identifier built from role, label, and source region
  - stable enough for debug traces but not the long-term memory key
- `label`
  - display name selected from OCR text first, semantic label second
  - should be short enough for action logs
- `role`
  - normalized UI role: currently `button`, `input`, `tab`, or `menu_item`
  - describes what the element is
- `interaction_type`
  - intended operation, separate from role
  - first mappings: `button/tab/menu_item -> click`, `input -> focus`
- `description`
  - semantic explanation from Qwen
  - describes visible meaning and likely outcome
- `text`
  - merged OCR text bound to the element
  - empty or semantic-only when OCR did not bind
- `bbox`
  - execution bbox chosen by fusion
  - OCR text bbox when available, semantic bbox otherwise
- `semantic_bbox`
  - original Qwen region bbox
  - retained because semantic area and OCR text box often differ
- `click_point`
  - concrete point selected for interaction
  - OCR center for text-bound elements, semantic bbox center for semantic-only elements
- `click_strategy`
  - why the point was selected
  - first values: `ocr_text_center`, `ocr_text_center_focus`, `semantic_bbox_center`
- `possible_destinations`
  - likely destination pages/panels from Qwen
  - weak planning hint, not a verified transition
- `verification_hints`
  - expected post-action evidence
  - first mappings:
    - `button/menu_item`: `state_change`, `new_region`, `content_change`, scope `page`
    - `tab`: `selection_change`, `content_change`, scope `local`
    - `input`: `focus_change`, `caret_visible`, scope `local`
- `interaction_policy`
  - rule-based click policy
  - current fields:
    - `allowed`
    - `zone_type`
    - `priority`
    - `ad_risk`
    - `reasons`
  - first zone types:
    - `test_module`
    - `nav_control`
    - `general_action`
    - `ad_candidate`
- `fusion_confidence`
  - combined confidence from text match, geometry, OCR score, role support, and Qwen confidence
  - used to prefer high-evidence elements
- `coordinate_confidence`
  - coarse coordinate reliability: `high`, `medium`, or `low`
  - high means OCR text binding is strong; semantic-only coordinates stay medium/low
- `memory_key`
  - stable learning key: `role:*|label:*|text:*|layout:*`
  - intended for storing successful click strategy, validation outcomes, and layout-specific reliability
- `sources`
  - evidence producers, for example `qwen3_vl` and `rapidocr_onnxruntime`
- `source_region_ids`
  - semantic regions used to create the element
  - supports replay/debug tracing
- `source_text_ids`
  - OCR text boxes bound to the element
  - supports click fallback and multi-line text reconstruction
- `evidence`
  - binding scores and source match keys
  - explains how fusion chose this element and click point

### Vision layer trace

- endpoint: `POST /vision/layer_trace`
- contract: `vision_layer_trace_v1`
- purpose:
  - test and debug the full vision stack one layer at a time
  - show actual returned payloads, not just pass/fail status
  - make webpage screenshot testing inspectable before action execution consumes the result

Top-level trace fields:

- `contract_version`
  - always `vision_layer_trace_v1`
  - identifies this as a debug/test trace, not an action-ready page model
- `image_path`
  - image file used for the trace
  - lets later replay use the exact same screenshot
- `final_ok`
  - true only when every emitted layer has `ok = true`
  - false means at least one layer failed schema validation or runtime execution
- `layers`
  - ordered list of layer records
  - each layer contains `layer`, `ok`, `summary`, `validation`, and `result`

Layer record fields:

- `layer`
  - stable layer name
  - current values:
    - `input_image`
    - `vision_provider_raw`
    - `vision_regions_v1`
    - `ocr_result`
    - `page_structure_v1`
- `ok`
  - boolean result of that layer's validation
  - intended for quick inspection and automated smoke checks
- `summary`
  - compact human-readable counters and key values
  - examples: `region_count`, `match_count`, `element_count`, OCR `texts`
- `validation`
  - machine-readable schema check result
  - contains:
    - `ok`: true when this layer met required field checks
    - `missing_fields`: missing top-level fields
    - `item_errors`: missing fields inside list items such as regions/elements/OCR matches
    - `warnings`: non-fatal concerns such as no OCR matches or no returned regions
    - `errors`: runtime exceptions for that layer
- `result`
  - full layer payload
  - this is the field to inspect when checking whether a model or fusion step returned the expected format

Layer meanings:

- `input_image`
  - verifies the image exists and records its size
  - required result fields: `image_path`, `image_exists`, `image_size`
- `vision_provider_raw`
  - raw provider response before route-level normalization
  - useful for seeing what Qwen/local provider actually returned
  - required result fields: `provider`, `contract_version`, `image_size`, `screen_summary`, `state_guess`, `regions`, `targets`, `observers`, `notes`
- `vision_regions_v1`
  - normalized semantic layer consumed by fusion
  - validates every region has `region_id`, `label`, `role`, `bbox`, `diagonal`, `normalized_diagonal`, `description`, `ocr_text`, `text_lines`, `possible_destinations`, `confidence`, `layout_key`, `content_key`, and `match_key`
- `ocr_result`
  - local OCR layer
  - validates `image_path`, `matches`, and `metadata`
  - validates each match has `text`, `score`, and `bbox`
- `page_structure_v1`
  - final fused structure
  - validates top-level `regions`, `elements`, `texts`, `links`, `learning_summary`, `raw_ocr`, and `raw_vision_regions`
  - validates each element has execution fields including `interaction_type`, `interaction_policy`, `verification_hints`, `memory_key`, `click_point`, `click_strategy`, `fusion_confidence`, and `coordinate_confidence`

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
- choose provider mode for `/vision/page_structure`
- define fallback mode
- set provider-specific endpoint/model values

Current shape:

- `vision.mode`
- `vision.fallback_mode`
- `vision.timeout_seconds`
- `vision.local.*`
- `vision.api.*`

Current reality:

- local and API provider entries exist
- local defaults target `Qwen3VL-8B-Instruct-Q4_K_M.gguf` through `http://127.0.0.1:1234/v1/chat/completions`
- full-page stability is now improved in provider code through inference scaling plus compact retry fallback
- local deployment assets are stored under ignored `models/` and `tools/` directories
- API provider remains a stub unless replaced with a real endpoint

### Other config folders

Current status:

- no additional config subdirectories are present in the repo right now
- older ROI/scene/template config ideas are not part of the active mainline runtime path

## logs/

Important runtime persistence paths:

- `artifacts/screenshots/`
  - named screenshots
  - filenames include window identity, purpose, and ROI position

- `artifacts/verification/`
  - verification diff images

- `artifacts/vision-regions/`
  - annotated screenshots, crops, and `regions.json` manifests

- `artifacts/review-overlays/`
  - human-review overlay images rendered from saved traces

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

- `logs/traces/actions/`
  - structured action traces with request, execution path, attempts, and verification evidence

- `logs/traces/vision/`
  - structured vision traces with request, execution path, returned contracts, and local-provider attempt metadata

Also written here:

- `app.log`

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

- `test_page_structure_fusion.py`
  - deterministic fusion of semantic regions and OCR text boxes
  - element fields such as `interaction_type`, `interaction_policy`, `verification_hints`, `memory_key`, and click strategy
  - rule-based blocking of ad-like action candidates

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

### vision page structure

- route: `app/api/vision.py`
- endpoint: `POST /vision/page_structure`
- provider loading: `app/vision/factory.py`
- semantic input: `app/vision/local_provider.py` or `app/vision/api_provider.py`
- OCR input: `app/core/ocr_service.py`
- fusion logic: `app/page_structure/fusion.py`
- output schema: `app/page_structure/schemas.py`

Execution sequence:

1. validate `image_path`
2. run configured vision provider and normalize its output into `vision_regions_v1`
3. run OCR on the same image path
4. bind OCR text boxes to supported semantic regions with deterministic scoring
5. emit `page_structure_v1`

Fusion scoring uses:

- text similarity between OCR text and semantic label/ocr_text/text_lines
- geometry proximity between OCR bbox and semantic bbox
- supported-role score
- OCR confidence
- Qwen semantic confidence

The first version intentionally does not make action decisions. It prepares executable element evidence for the future action layer.

### vision layer trace

- route: `app/api/vision.py`
- endpoint: `POST /vision/layer_trace`
- trace helpers: `app/vision/layer_trace.py`
- use when:
  - validating a new webpage screenshot
  - checking whether Qwen returned required `vision_regions_v1` fields
  - checking whether OCR found the expected visible text
  - checking whether fusion produced usable `page_structure_v1` elements

Execution sequence:

1. validate image existence and size
2. call the configured vision provider and expose raw provider output
3. normalize provider output to `vision_regions_v1`
4. run OCR and expose raw OCR matches
5. optionally build `vision_regions_refined_v1` by shifting semantic boxes toward matching OCR text
6. build `page_structure_v1`

Useful request metadata:

- `grid_overlay = true`
  - use a light `100px` pixel grid on the inference image
- `grid_overlay = 120`
  - use a light `120px` pixel grid
- `grid_overlay = {"enabled": true, "spacing": 100}`
  - explicit object form for experiment toggling

When grid mode is enabled, the saved provider attempt metadata includes the rendered grid-reference image path for later human review.

Useful request metadata:

- `ocr_region_refine = true`
  - enable the default OCR-anchor correction pass
- `ocr_region_refine = {"enabled": true, "min_text_score": 0.58, "padding": 16}`
  - explicit experiment settings

When OCR refinement is enabled, the raw model layer is preserved and an additional `vision_regions_refined_v1` layer is written into `/vision/layer_trace` for review overlays.
6. validate every layer and return the full trace

When the local provider is active, the `vision_provider_raw` layer also shows whether large-image scaling or compact retry logic was needed to produce stable JSON.

This endpoint is for inspection and test reporting. It should not be the final action-selection API because it intentionally returns verbose raw evidence.

### Recommended recognition strategy

For better grounding accuracy, the project should evolve toward:

1. `parse`
   - analyze one screenshot into semantic regions, OCR text, and executable page elements
   - current building blocks:
     - `vision_provider_raw`
     - `vision_regions_v1`
     - `ocr_result`
     - `page_structure_v1`
2. `candidate`
   - build a ranked list of only the plausible targets for the current user goal
   - candidate scoring should combine:
     - task-text similarity
     - region role support
     - trusted-zone vs ad-candidate signals
     - current page-state hints
3. `narrow search`
   - crop the top candidate ROIs and rerun local grounding on each smaller image
   - this should be the main answer to full-screen bbox drift and cross-card confusion
4. `verify`
   - add both pre-click and post-click checks
   - pre-click:
     - reject when top-1 is not clearly ahead of top-2
     - reject when the refined point falls into a blocked or ambiguous zone
   - post-click:
     - require evidence such as content change, focus change, URL change, or state transition

This means the intended long-term click path is:

`full screenshot -> parse -> candidate ranking -> local ROI re-grounding -> verification -> action memory`

The key design principle is to avoid asking one model response to produce a trustworthy final click point directly from the full page.

### Recognition MVP design

The next MVP should implement the staged recognition path as a real runtime flow, not just a documentation idea.

MVP goal:

- choose one intended target from a full screenshot with better accuracy than direct full-page coordinate generation
- keep every stage inspectable with artifacts and traces
- support rejection and retry instead of forcing a click on weak evidence

MVP non-goals:

- end-to-end autonomous browsing across many unseen layouts
- training a new grounding model
- replacing OCR with a purely visual solution
- solving every desktop and browser UI in V1

#### MVP pipeline

1. `parse`
   - input:
     - screenshot path
     - task text
     - optional app/state hint
   - output:
     - semantic regions
     - OCR result
     - `page_structure_v1` elements
   - current repo base:
     - `vision/layer_trace`
     - `vision/page_structure`

2. `candidate`
   - input:
     - parsed elements
     - user goal such as "click start detection"
   - output:
     - ranked candidate list with scores and reasons
   - minimum scoring signals:
     - text similarity to goal
     - supported role
     - `interaction_policy.allowed`
     - ad-candidate penalty
     - current page-state compatibility

3. `narrow_search`
   - input:
     - top-k candidates from the candidate stage
   - output:
     - local refined bbox or click point for each candidate
   - expected operations:
     - crop candidate ROI
     - rerun OCR and/or local vision analysis on crop
     - compute refined click point

4. `verify`
   - input:
     - chosen candidate and refined click point
   - output:
     - allow / reject / retry decision
   - pre-click checks:
     - top-1 clearly ahead of top-2
     - refined point remains inside trusted candidate area
     - candidate is not blocked
   - post-click checks:
     - OCR change
     - local content change
     - URL, focus, or state transition

#### MVP module plan

- `parse`
  - keep using:
    - `app/api/vision.py`
    - `app/vision/`
    - `app/page_structure/`
- `candidate`
  - add new module:
    - `app/recognition/candidate_ranker.py`
  - responsibility:
    - rank parsed elements for one task
  - current contract:
    - request: `CandidateRankRequest(goal, page_structure, top_k=5, state_hint=None)`
    - response: `CandidateRankResult`
    - response version: `candidate_rank_v1`
    - candidate id: stable `candidate_<element_id>` form
    - ranking evidence: `ScoreBreakdown`
  - current scoring signals:
    - goal text similarity
    - supported interaction role
    - interaction policy priority and zone type
    - fusion and coordinate confidence
    - optional state hint similarity
    - ad and blocked-policy penalties
- `narrow_search`
  - add new module:
    - `app/recognition/local_grounding.py`
  - responsibility:
    - crop and rerun local analysis on candidate ROIs
- `verify`
  - first reuse:
    - `app/core/verifier.py`
  - then add task-specific decision logic:
    - `app/recognition/decision.py`
- orchestration
  - add one thin coordinator:
    - `app/recognition/pipeline.py`

#### Suggested MVP endpoint shape

The cleanest first endpoint is one new debug-first route:

- `POST /vision/recognition_plan`

Request:

- `image_path`
- `task`
- `goal`
- optional `state_hint`
- optional `top_k`

Response should include:

- `parse_result`
- `candidate_result`
- `narrow_search_result`
- `verification_plan`
- `recommended_target`
- `trace_path`

This route should not click yet.
It should exist to prove that the staged selection logic is working before action dispatch is attached.

#### Suggested first execution endpoint after planning works

- `POST /action/click_candidate`

Request:

- `image_path`
- `goal`
- optional `candidate_id`
- optional `top_k`
- optional `enable_validation`

Response:

- selected candidate
- refined click point
- pre-click reasoning
- post-click verification result
- artifacts and trace paths

#### MVP acceptance criteria

For one controlled page family such as MouseTester:

- parse stage returns stable `page_structure_v1`
- correct target appears in `top-3` candidates on the labeled sample set
- narrow search improves click-point stability relative to full-page grounding
- verifier rejects obvious ad or wrong-card clicks
- all stages write enough trace evidence for human review

#### MVP implementation order

1. implement `candidate` ranking without any clicking
   - status: first local contract and unit tests exist under `app/recognition/`
2. implement local ROI `narrow_search`
3. connect pre-click `verify`
4. expose a no-click planning route
5. attach action execution only after the planning path is measured

This keeps the MVP small, inspectable, and reversible.

## Active Vs Legacy

### Active mainline

- `session`
- `state`
- `vision/ocr_region`
- `vision/analyze`
- `vision/page_structure`
- `vision/layer_trace`
- `vision/render_review_overlay`
- `action/click_text`
- `action/click_mouse_tester_left_region`

### Legacy or partially retained structures

- old template/scene config folders
- old request models for template/wait flows in `app/models/request.py`
- `app/vision/` provider abstraction is active; local provider supports OpenAI-compatible multimodal endpoints, API provider is still stubbed

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
