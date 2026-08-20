# Learning Recognition Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the front half of Learn Mode recognition into a parser/classifier/ROI-grounding/validator pipeline while preserving Execute Mode and the existing Learning Draft Review -> PathGraph candidate pipeline.

**Architecture:** The new path writes intermediate artifacts (`learn_observe_bundle_v1`, `screen_inventory_v2`, `learn_candidate_classification_v1`, `learning_grounding_validation_v1`) and then emits the existing `learning_template_draft_v1`. Parser providers are pluggable and never authorize clicks. Grounding output is only accepted after deterministic validation, then reviewed by the existing display-only draft tools.

**Tech Stack:** Python/FastAPI backend, existing `app.api.vision`, `app.learn.*`, `app.web_panel`, pytest, JSON artifacts under `artifacts/learning-recognition/`, model profiles under `configs/model_profiles/`.

---

## Files And Responsibilities

- Modify `app/learn/__init__.py`: export new learning recognition contracts after implementation.
- Create `app/learn/recognition/contracts.py`: typed helpers and schema builders for observe bundles, inventory items, classification reports, ROI crops, grounding reports, and validation reports.
- Create `app/learn/recognition/parsers.py`: parser provider interface plus wrappers for existing OCR/UIA/vision evidence; later OmniParser adapter plugs in here.
- Create `app/learn/recognition/classifier.py`: deterministic non-actionable/actionable/form-field/danger-zone classification.
- Create `app/learn/recognition/roi.py`: ROI expansion, crop metadata, coordinate transform restore/replay.
- Create `app/learn/recognition/validator.py`: hard validation for point/bbox/evidence/danger-zone/freshness.
- Create `app/learn/recognition/pipeline.py`: orchestrates parser -> classifier -> ROI -> grounding adapter -> validation -> `learning_template_draft_v1`.
- Modify `app/api/panel.py`: add read-only experiment endpoint for learning recognition trial, without Execute binding.
- Modify `app/web_panel/panel.js`: add a small Learning Recognition experiment entry, leaving draft review/pathgraph candidate UI intact.
- Create `scripts/run_learn_recognition_benchmark.py`: fixed manifest runner with layered metrics.
- Create `artifacts/benchmarks/learn_recognition_golden_manifest_v1.json`: first 20-30 cases.
- Create `tests/test_learn_recognition_*.py`: focused tests per layer.
- Update `LEARNING_MODE_PLAN.zh-CN.md`, `CURRENT_STATE.md`, `NEXT_STEPS.md`, `README.md`: document new architecture and current checkpoint.

## Task 1: Contracts And Non-Executable Boundaries

**Files:**
- Create: `app/learn/recognition/contracts.py`
- Modify: `app/learn/__init__.py`
- Test: `tests/test_learn_recognition_contracts.py`

- [x] **Step 1: Write failing contract tests**

Add tests that assert:

```python
def test_inventory_item_defaults_to_non_click_authorization():
    item = build_inventory_item(
        item_id="text_1",
        label="Latest News",
        item_type="readable",
        bbox={"x": 10, "y": 10, "w": 100, "h": 20},
        source_evidence=["ocr"],
        evidence_level="ocr_text_only",
    )
    assert item["contract_version"] == "screen_inventory_item_v2"
    assert item["click_candidate"] is False
    assert item["artifact_is_authorization"] is False


def test_learning_draft_safety_flags_are_non_executable():
    draft = build_learning_template_draft_from_validated_items(
        state_guess="homepage",
        summary="home screen",
        valid_items=[],
        evidence_refs={"screen_inventory_path": "artifacts/x.json"},
    )
    assert draft["contract_version"] == "learning_template_draft_v1"
    assert draft["safety"]["artifact_is_authorization"] is False
    assert draft["safety"]["execute_binding_enabled"] is False
    assert draft["safety"]["final_submit_forbidden"] is True
```

- [x] **Step 2: Verify tests fail**

Run:

```powershell
uv run pytest tests\test_learn_recognition_contracts.py -q
```

Expected: fail because `app.learn.recognition.contracts` does not exist.

- [x] **Step 3: Implement minimal contract builders**

Implement builders with explicit UTF-8 JSON-safe dictionaries and no side effects. Do not add model calls.

- [x] **Step 4: Verify tests pass**

Run:

```powershell
uv run pytest tests\test_learn_recognition_contracts.py -q
uv run python -m py_compile app\learn\recognition\contracts.py app\learn\__init__.py
```

## Task 2: Parser Provider Interface And Existing Evidence Adapter

**Files:**
- Create: `app/learn/recognition/parsers.py`
- Test: `tests/test_learn_recognition_parsers.py`

- [x] **Step 1: Write failing parser tests**

Test that OCR-only ordinary text becomes inventory but not click authorization, and UIA invokable controls retain evidence:

```python
def test_ocr_parser_outputs_readable_non_click_items():
    bundle = {"sources": {"ocr": {"texts": [{"id": "t1", "text": "Latest News", "bbox": {"x": 1, "y": 2, "w": 80, "h": 20}}]}}}
    items = parse_existing_evidence_to_inventory(bundle)
    assert items[0]["item_type"] == "readable"
    assert items[0]["click_candidate"] is False
    assert items[0]["evidence_level"] == "ocr_text_only"


def test_uia_parser_preserves_invokable_evidence_without_authorizing_click():
    bundle = {"sources": {"uia": {"controls": [{"id": "u1", "name": "Search", "control_type": "Button", "bbox": {"x": 1, "y": 2, "w": 80, "h": 30}, "patterns": ["Invoke"]}]}}}
    items = parse_existing_evidence_to_inventory(bundle)
    assert items[0]["item_type"] == "actionable"
    assert items[0]["interactable_evidence"]["uia_invokable"] is True
    assert items[0]["click_candidate"] is False
```

- [x] **Step 2: Verify tests fail**

Run:

```powershell
uv run pytest tests\test_learn_recognition_parsers.py -q
```

- [x] **Step 3: Implement parser adapter**

Build only deterministic adapters for existing evidence. Keep OmniParser as a future provider entry in config, not a hard dependency.

- [x] **Step 4: Verify parser tests pass**

Run:

```powershell
uv run pytest tests\test_learn_recognition_parsers.py -q
```

## Task 3: Non-Actionable Classifier

**Files:**
- Create: `app/learn/recognition/classifier.py`
- Test: `tests/test_learn_recognition_classifier.py`

- [x] **Step 1: Write failing classifier tests**

Cases:

```python
def test_rejects_code_block_and_readonly_card():
    report = classify_inventory_items([
        {"item_id": "code", "label": ">>> print('Hello')", "item_type": "readable", "role": "text", "source_evidence": ["ocr"], "evidence_level": "ocr_text_only"},
        {"item_id": "card", "label": "Looking for work", "item_type": "readable", "role": "card", "source_evidence": ["vision"], "evidence_level": "semantic_region_only"},
    ])
    assert {x["item_id"] for x in report["rejected_non_actionable"]} == {"code", "card"}
    assert report["accepted_for_grounding"] == []


def test_accepts_multi_source_button_for_grounding():
    report = classify_inventory_items([
        {"item_id": "search", "label": "Search", "item_type": "actionable", "role": "button", "source_evidence": ["ocr", "uia"], "interactable_evidence": {"uia_invokable": True}, "evidence_level": "multi_source_grounded"}
    ])
    assert report["accepted_for_grounding"][0]["item_id"] == "search"
```

- [x] **Step 2: Verify tests fail**

Run:

```powershell
uv run pytest tests\test_learn_recognition_classifier.py -q
```

- [x] **Step 3: Implement classifier rules**

Make classifier conservative: semantic-only and OCR-only items require stronger evidence before grounding.

- [x] **Step 4: Verify classifier tests pass**

Run:

```powershell
uv run pytest tests\test_learn_recognition_classifier.py -q
```

## Task 4: ROI Crop And Coordinate Transform

**Files:**
- Create: `app/learn/recognition/roi.py`
- Test: `tests/test_learn_recognition_roi.py`

- [x] **Step 1: Write failing ROI tests**

Test ROI expansion, clamping, and local-to-screen replay:

```python
def test_roi_transform_replays_local_point_to_screen_point():
    roi = build_roi_crop_metadata(
        source_image_size={"width": 1000, "height": 800},
        candidate_bbox={"x": 400, "y": 300, "w": 100, "h": 40},
        crop_size={"width": 300, "height": 120},
        expand_scale=2.0,
    )
    point = restore_local_point_to_screen(roi["coordinate_transform"], {"x": 150, "y": 60})
    assert roi["coordinate_transform"]["roi_bbox"] == {"x": 350, "y": 280, "w": 200, "h": 80}
    assert point == {"x": 450, "y": 320}
```

- [x] **Step 2: Verify tests fail**

Run:

```powershell
uv run pytest tests\test_learn_recognition_roi.py -q
```

- [x] **Step 3: Implement ROI helpers**

No model calls yet. Save transform data in a replayable format.

- [x] **Step 4: Verify ROI tests pass**

Run:

```powershell
uv run pytest tests\test_learn_recognition_roi.py -q
```

## Task 5: Grounding Validator

**Files:**
- Create: `app/learn/recognition/validator.py`
- Test: `tests/test_learn_recognition_validator.py`

- [x] **Step 1: Write failing validator tests**

Cases:

```python
def test_rejects_point_outside_bbox():
    result = validate_grounding_candidate(
        item={"item_id": "search", "item_type": "actionable", "bbox": {"x": 10, "y": 10, "w": 100, "h": 30}},
        grounding={"screen_point": {"x": 200, "y": 20}, "screen_bbox": {"x": 10, "y": 10, "w": 100, "h": 30}},
        evidence={"screenshot_freshness": True, "coordinate_transform_replay": True},
    )
    assert result["status"] == "rejected"
    assert result["failure_category"] == "point_outside_bbox"


def test_danger_zone_never_becomes_valid_action():
    result = validate_grounding_candidate(
        item={"item_id": "submit", "item_type": "danger_zone", "label": "Submit application", "bbox": {"x": 1, "y": 1, "w": 120, "h": 40}},
        grounding={"screen_point": {"x": 50, "y": 20}, "screen_bbox": {"x": 1, "y": 1, "w": 120, "h": 40}},
        evidence={"screenshot_freshness": True, "coordinate_transform_replay": True},
    )
    assert result["status"] == "rejected"
    assert result["failure_category"] == "danger_zone"
```

- [x] **Step 2: Verify tests fail**

Run:

```powershell
uv run pytest tests\test_learn_recognition_validator.py -q
```

- [x] **Step 3: Implement validator**

Keep final-submit/danger handling stricter than ordinary action validation.

- [x] **Step 4: Verify validator tests pass**

Run:

```powershell
uv run pytest tests\test_learn_recognition_validator.py -q
```

## Task 6: Pipeline To Existing Draft Review

**Files:**
- Create: `app/learn/recognition/pipeline.py`
- Test: `tests/test_learn_recognition_pipeline.py`

- [x] **Step 1: Write failing pipeline test**

Use fixture evidence with one button and one rejected text block. Assert output is `learning_template_draft_v1`, display-only, and accepted by `load_learning_draft_review()`.

- [x] **Step 2: Verify test fails**

Run:

```powershell
uv run pytest tests\test_learn_recognition_pipeline.py -q
```

- [x] **Step 3: Implement the smallest pipeline**

Use a fake grounding adapter in tests. Real models are not required for this task.

- [x] **Step 4: Verify pipeline and review compatibility**

Run:

```powershell
uv run pytest tests\test_learn_recognition_pipeline.py tests\test_learning_draft_review.py -q
uv run python -m py_compile app\learn\recognition\pipeline.py app\learn\draft_review.py app\learn\pathgraph_candidate.py
```

## Task 7: Benchmark Harness

**Files:**
- Create: `scripts/run_learn_recognition_benchmark.py`
- Create: `artifacts/benchmarks/learn_recognition_golden_manifest_v1.json`
- Test: `tests/test_learn_recognition_benchmark_runner.py`

- [x] **Step 1: Write failing benchmark tests**

Assert invalid fixtures are excluded, attempted denominators are correct, and layered metrics do not output a total success rate.

- [x] **Step 2: Verify tests fail**

Run:

```powershell
uv run pytest tests\test_learn_recognition_benchmark_runner.py -q
```

- [x] **Step 3: Implement runner**

Output report fields:

```json
{
  "parse_inventory": {"passed": 0, "attempted": 0, "rate": "not_covered"},
  "actionable_classification": {"passed": 0, "attempted": 0, "rate": "not_covered"},
  "non_actionable_rejection": {"passed": 0, "attempted": 0, "rate": "not_covered"},
  "grounding_point": {"passed": 0, "attempted": 0, "rate": "not_covered"},
  "coordinate_transform": {"passed": 0, "attempted": 0, "rate": "not_covered"},
  "pathgraph_candidate_validation": {"passed": 0, "attempted": 0, "rate": "not_covered"}
}
```

- [x] **Step 4: Verify runner**

Run:

```powershell
uv run pytest tests\test_learn_recognition_benchmark_runner.py -q
uv run python scripts\run_learn_recognition_benchmark.py `
  --manifest artifacts\benchmarks\learn_recognition_golden_manifest_v1.json `
  --out logs\benchmarks\learn_recognition_initial `
  --json
```

## Task 8: Model Experiment Registry Under 12B

**Files:**
- Create: `configs/model_profiles/learn_mode_qwen3_vl_8b.json`
- Create: `configs/model_profiles/learn_mode_uground_2b.json`
- Create: `configs/model_profiles/learn_mode_uground_7b.json`
- Create: `configs/model_profiles/learn_mode_gui_actor_3b.json`
- Create: `configs/model_profiles/learn_mode_gui_actor_7b.json`
- Create: `configs/model_profiles/learn_mode_showui_2b.json`
- Create: `configs/model_profiles/learn_mode_omniparser_v2.json`
- Test: `tests/test_learn_recognition_model_profiles.py`

- [x] **Step 1: Write failing profile tests**

Assert every learn-mode profile has `mode_scope=learn_only`, `max_parameters_b <= 12`, and never equals the Execute Mode profile id.

- [x] **Step 2: Verify tests fail**

Run:

```powershell
uv run pytest tests\test_learn_recognition_model_profiles.py -q
```

- [x] **Step 3: Add profile metadata only**

Do not download in this task. Add URLs/model ids as metadata and a `download_status=not_downloaded`.

- [x] **Step 4: Verify profile tests pass**

Run:

```powershell
uv run pytest tests\test_learn_recognition_model_profiles.py -q
```

## Task 9: Panel Experiment Entry

**Files:**
- Modify: `app/api/panel.py`
- Modify: `app/web_panel/panel.js`
- Test: `tests/test_web_panel_route.py`, `tests/test_learning_draft_review.py`

- [ ] **Step 1: Write tests for read-only endpoint**

Endpoint must return artifact paths and safety flags, never Execute binding.

- [ ] **Step 2: Implement endpoint and panel button**

Add only one experiment entry: `运行新识别实验`. Keep existing Learning Draft Review loading.

- [ ] **Step 3: Verify panel checks**

Run:

```powershell
uv run pytest tests\test_web_panel_route.py tests\test_learning_draft_review.py -q
node --check app\web_panel\panel.js
```

## Task 10: Documentation Sync

**Files:**
- Modify: `LEARNING_MODE_PLAN.zh-CN.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`
- Modify: `README.md`
- Create: `docs/LEARN_RECOGNITION_PARSER_AND_GROUNDING.zh-CN.md`

- [x] **Step 1: Update docs with new Learn Recognition boundary**

Document that old Learn Deep coordinate overlay is diagnostic/compatibility, not the primary future recognition path.

Added `docs/LEARN_RECOGNITION_PARSER_AND_GROUNDING.zh-CN.md` to make the parser/provider boundary, candidate-model roles, and two-stage ROI grounding flow explicit. README, CURRENT_STATE, and NEXT_STEPS now link to that boundary.

- [x] **Step 2: Verify docs and syntax**

Run:

```powershell
uv run python -m py_compile app\learn\recognition\contracts.py app\learn\recognition\parsers.py app\learn\recognition\classifier.py app\learn\recognition\roi.py app\learn\recognition\validator.py app\learn\recognition\pipeline.py
```

## Checkpoint Stop Condition

Stop after Task 1-3 are green if implementation risk grows. That checkpoint proves the old messy target generation can be replaced by explicit inventory and non-actionable rejection without touching Execute Mode.
