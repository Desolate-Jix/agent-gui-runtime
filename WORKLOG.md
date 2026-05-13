# WORKLOG

## 2026-05-13 Execute Unicode Goal Regression

### Summary

This session kept the MouseTester execution path on the existing gated recognition-plan mainline:

- confirmed `execute_recognition_plan` forwards a real Unicode goal (`点击此处测试`) into the internal recognition request unchanged
- identified the earlier `??????` goal as a PowerShell/script invocation encoding problem before the request object was built, not a candidate ranker, pre-click gate, or `screen_reading_v1` issue
- added a regression test that passes the goal as Python Unicode escapes and asserts the internal recognition request and returned recognition plan keep the same Unicode value
- reran live MouseTester `execute_recognition_plan` with a Unicode-safe invocation
- archived the successful run as a golden baseline with copied traces, execute response, before/after screenshots, diff image, validation summary, and manual regression checklist
- added the golden action trace to the MouseTester trace-evaluation manifest

### Validation completed

- `uv run pytest tests/test_execute_recognition_plan_route.py -q`
  - `7 passed`
- `uv run pytest -q`
  - `77 passed`
- `uv run python scripts/evaluate_mousetester_traces.py --cases configs/mousetester_eval_cases.json`
  - `5/5` cases passed
- Live MouseTester execute:
  - internal recognition trace goal: `点击此处测试`
  - recognition trace: `logs/traces/vision/20260513-182111-330997__recognition-plan__mousetesterweb.json`
  - action trace: `logs/traces/actions/20260513-182115-605129__execute-recognition-plan__mousetesterweb.json`
  - golden baseline: `artifacts/golden-traces/mousetester-live-execute-20260513-182111-unicode-goal/`
  - selected click point: `{x: 1434, y: 433}`
  - pre-click decision: allowed
  - actual click: executed
  - post-click verification: passed through screenshot diff, cursor/focus evidence, and MouseTester target-area semantic OCR evidence
  - semantic evidence: target-area OCR changed from `点击此处测试` to `超时/单击`

## 2026-05-13 Recognition Rank Correction

### Summary

This session pulled `screen_reading_v1` back into the main recognition path:

- `POST /vision/recognition_plan` now builds `screen_reading_v1` during planning
- `CandidateRankRequest` now accepts optional `screen_reading` evidence
- `candidate_rank_v1` now uses UIA accessible names as goal-text evidence
- `ScoreBreakdown` now includes `screen_reading_score`
- UIA matches, UIA Invoke patterns, and Microsoft Fluent icon catalog matches add bounded ranking evidence and explicit reasons
- blocked/ad-like interaction policy still rejects candidates even when screen-reading evidence matches the goal

### Validation completed

- `python -m py_compile app\recognition\schemas.py app\recognition\candidate_ranker.py app\api\vision.py`
- `uv run pytest tests/test_candidate_ranker.py tests/test_vision_route.py -q`
  - `16 passed`
- `uv run pytest -q`
  - `76 passed`

## 2026-05-13

### Summary

This session ran the live Edge/MouseTester Windows UIA smoke and fixed the first real provider robustness issue:

- opened and bound `MouseTester.cn` in Microsoft Edge
- confirmed the Windows UIA provider can scan the bound Edge window after the fix
- found that pywinauto UIA pattern descriptors can raise `NoPatternInterfaceError` during `hasattr` probing
- changed UIA pattern detection to use safe attribute probing so one unsupported pattern does not fail the whole scan
- added `app/evaluation/uia_smoke_eval.py` for scoring saved UIA smoke traces
- added `scripts/record_uia_smoke.py` to bind a target window, save `uia_smoke_trace_v1`, and write a UIA smoke evaluation report
- kept the existing `screen_reading_v1` response shape unchanged

### Validation completed

- Live UIA smoke against MouseTester.cn in Microsoft Edge:
  - scan status: `ok`
  - latest recorded controls returned: `249`
  - buttons returned: `26`
  - useful controls included `返回`, `刷新`, address edit `https://www.mousetester.cn`, `RootWebArea`, `点击此处测试`, and reset controls
  - trace: `logs/traces/evaluation/20260513-162852-157632__uia-smoke__mousetester.json`
  - report: `logs/evaluations/uia-smoke-eval-20260513-162852.json`
- `uv run python scripts\record_uia_smoke.py --process-name msedge.exe --title MouseTester --max-controls 250 --min-controls 50 --min-buttons 5`
  - `1/1` UIA smoke cases passed
- `python -m py_compile app\screen_reading\uia_provider.py`
- `python -m py_compile app\evaluation\uia_smoke_eval.py scripts\record_uia_smoke.py`
- `uv run pytest tests/test_uia_smoke_eval.py tests/test_screen_reading.py -q`
  - `4 passed`
- `uv run pytest tests/test_screen_reading.py tests/test_vision_route.py -q`
  - `10 passed`
- `uv run pytest -q`
  - `74 passed`

### Remaining follow-up

- Add browser accessibility evidence for web content controls.
- Add icon shape/template matching so Fluent catalog matches are backed by visual evidence, not only label/context.
- Expand the MouseTester evaluation set across more states and negative cases.

## 2026-05-11

### Summary

This session connected the first Microsoft icon-library and Windows UIA slices into `screen_reading_v1`:

- added a local Microsoft Fluent System Icons catalog matcher in `app/screen_reading/icon_library.py`
- added a Windows UIA provider in `app/screen_reading/uia_provider.py`
- wired `build_screen_reading` so `ui.icon_candidates[*].icon_library_match` can contain Fluent ids such as `arrow_left_24_regular`
- wired `build_screen_reading` so UIA evidence can appear in `ui.elements[*].provider_matches.uia` and `ui.icon_candidates[*].uia_match`
- changed the `icon_library` provider slot from reserved to connected for the Fluent catalog matcher
- changed the `uia` provider slot from reserved to connected, with scan status reported separately
- kept visual-only icon candidates blocked from safe execution; catalog matching is evidence, not action permission
- updated route metadata with `icon_library_provider_connected`, `uia_provider_connected`, and `uia_scan_status`
- updated project docs to reflect connected UIA/catalog matching and the remaining browser/shape-verification gap

### Validation completed

- `python -m py_compile app\screen_reading\icon_library.py app\screen_reading\uia_provider.py app\screen_reading\builder.py app\api\vision.py`
- `uv run pytest tests/test_screen_reading.py tests/test_vision_route.py -q`
  - `9 passed`
- `uv run pytest -q`
  - `71 passed`

### Remaining follow-up

- Run a live bound-window UIA smoke against Edge/MouseTester and inspect returned controls.
- Add browser accessibility evidence for web content controls.
- Add icon shape/template matching so Fluent catalog matches are backed by visual evidence, not only label/context.

## 2026-05-10

### Summary

This session attached the first controlled execution bridge on top of the staged recognition plan:

- added `POST /action/execute_recognition_plan`
- added `execute_recognition_plan_v1` result payloads
- defaulted execution to live bound-window captures
- blocked saved-image execution unless dry-run or explicit override is used
- required `pre_click_decision_v1.allowed == true` before any click is sent
- clicked only `pre_click_decision_v1.selected_click_point`
- captured generic post-click evidence through the existing verifier
- attempted to render a recognition-plan overlay for accepted plans
- added MouseTester-specific semantic post-click verification using target-area OCR before/after evidence
- added bounded retry policy for retry-safe post-click verification failures
- added initial trace-based MouseTester evaluation set and CLI report generator
- added `POST /vision/screen_reading` with `screen_reading_v1`
- split the READ-facing UI layer out from page structure, including OCR-backed elements, visual-only/icon candidates, module grouping, reserved provider slots, and learned-UI hooks

### Validation completed

- Targeted screen-reading tests passed:
  - `9 passed`
- Targeted route tests passed:
  - `6 passed`
- Full test suite passed:
  - `71 passed`
- Trace evaluation passed:
  - `4/4` cases
  - top-1, pre-click, action execution, and semantic verification pass rates: `1.0`
  - report: `logs/evaluations/mousetester-trace-eval-20260510-175234.json`
- Local Qwen3-VL server started on `http://127.0.0.1:1234/v1/chat/completions`.
- Live MouseTester dry-run succeeded:
  - goal `点击此处测试`
  - recommended target `点击此处测试`
  - selected point `{x: 1434, y: 493}`
  - `pre_click_decision.allowed == true`
  - no click executed
- Live MouseTester click smoke succeeded:
  - clicked `{x: 1434, y: 493}`
  - generic post-click verification passed through screenshot diff and cursor/focus evidence
  - MouseTester semantic verification passed; target-area OCR changed from `点击此处测试` to `超时/单击`
  - action trace: `logs/traces/actions/20260510-163204-630600__execute-recognition-plan__mousetesterweb.json`
  - recognition trace: `logs/traces/vision/20260510-163203-384944__recognition-plan__mousetesterweb.json`
  - overlay: `artifacts/review-overlays/20260510-163203-384944-recognition-plan-mousetesterweb__recognition-plan-overlay__20260510-163233-420701.png`

### Remaining follow-up

- Expand the MouseTester evaluation set with more states and negative cases.

## 2026-05-09

### Summary

This session turned the recognition-design work into a verified no-click MouseTester recognition MVP:

- `POST /vision/recognition_plan` now runs parse -> candidate ranking -> local grounding -> pre-click decision
- `POST /vision/render_recognition_plan_overlay` produces review images for recognition plans
- candidate ranking can add a goal-specific OCR `refined_bbox`
- local grounding crops refined candidate ROIs and maps matched OCR text centers back to full-screen coordinates
- pre-click decision now rejects goal-mismatched candidates even if local OCR matches the candidate itself

### Accuracy fixes

- Page-structure fusion now rejects far ambiguous OCR bindings, especially short repeated text fragments.
- Additional bound OCR text is clustered around the best local OCR anchor instead of unioning distant same-label fragments.
- Candidate bbox refinement prefers OCR text that matches the current goal before falling back to all bound source text.
- Pre-click verification now requires candidate-goal text similarity, not only local OCR text match.

### Latest real evidence

- Goal: `点击此处测试`
- Trace: `logs/traces/vision/20260509-191124-406879__recognition-plan__mousetesterweb.json`
- Overlay: `artifacts/review-overlays/20260509-191124-406879-recognition-plan-mousetesterweb__recognition-plan-overlay__20260509-191124-668878.png`
- Result: top candidate was the double-click test card, `refined_bbox` narrowed to the target text line, local OCR matched `点击此处测试`, and pre-click verification allowed the action.
- Actual click: not executed.

### Validation completed

- Full test suite passed:
  - `61 passed in 0.76s`
- Real route smoke passed:
  - `POST /vision/recognition_plan`
  - `POST /vision/render_recognition_plan_overlay`

### Remaining follow-up

- Attach a controlled execution endpoint only after `pre_click_decision_v1` allows the candidate.
- Add post-click verification and retry policy before broadening beyond MouseTester.
- Build a small screenshot evaluation set for candidate accuracy and click-point hit rate.

## 2026-04-21

### Summary

This session turned the recent vision/learning work from a draft contract into a partially verified runtime slice:

- OCR is now usable again through a RapidOCR-first adapter with PaddleOCR fallback
- screenshot understanding now has a code-defined `vision_regions_v1` contract
- normalized region results now persist local learning artifacts:
  - full annotated screenshot
  - per-region crops
  - per-region annotated crops
  - `regions.json` manifest
- the next agent-facing abstraction was clarified and documented as `page_structure_v1`

### What changed

#### OCR runtime

- replaced the single-backend OCR assumption with a fallback chain in `app/core/ocr_service.py`
- added support for both:
  - Paddle-style OCR rows: `[polygon, [text, score]]`
  - RapidOCR rows: `[polygon, text, score]`
- fixed a parsing bug where OCR result parsing could collapse to only the first row
- added `rapidocr-onnxruntime` to project dependencies

#### Vision region contract

- added region-level schema fields in `app/vision/schemas.py`
- added deterministic region normalization helpers in `app/vision/region_standard.py`
- added model-facing output instructions in `app/vision/prompting.py`
- updated `app/vision/normalizer.py` so provider output can be normalized into:
  - image size
  - diagonal coordinates
  - normalized coordinates
  - `layout_key`
  - `content_key`
  - `match_key`

#### Local learning artifacts

- added `app/vision/artifacts.py`
- `/vision/analyze` now saves local evidence bundles under `logs/vision-regions/`
- each bundle contains:
  - one full annotated image
  - one crop per region
  - one annotated crop per region
  - one `regions.json` manifest

#### Architecture/documentation direction

- documented the intended next abstraction as `page_structure_v1`
- clarified the desired flow:

`screenshot -> vision_regions_v1 -> local learning artifacts -> page_structure_v1 -> agent decision`

### Validation completed

#### OCR validation

Real OCR run succeeded against:

- `logs/capture-20260413-163327-800177.png`

Observed result:

- engine used: `rapidocr_onnxruntime`
- recognized match count: `17`
- recognized texts included:
  - `https://mousetester.net/zh`
  - `MouseTester`
  - `功能特点`
  - `使用说明`
  - `常见问题`

#### Region artifact validation

A real artifact bundle was written to:

- `logs/vision-regions/20260421-201148-876757-capture-20260413-163327-800177/`

Bundle contents verified:

- full annotated screenshot
- `hero_primary_cta` crop + annotated crop
- `site_top_nav` crop + annotated crop
- `regions.json`

#### Test validation

Full test suite passed during this session:

- `24 passed in 1.43s`

Additional targeted test coverage was added for:

- OCR fallback and RapidOCR parsing
- region normalization and prompt contract
- region artifact writing
- `/vision/analyze` artifact metadata wiring

### Key decisions captured

- the agent should not consume raw OCR or raw region geometry as its primary decision input
- learned `regions` are the evidence layer
- `page_structure_v1` should be the agent-facing decision layer
- artifact persistence is required so local learning can bind saved image evidence to `match_key`

### Remaining follow-up

- implement a real `page_structure_v1` builder on top of normalized regions
- connect a real vision model backend to emit `vision_regions_v1`
- decide how learned `match_key` values map into higher-level page or section identity

