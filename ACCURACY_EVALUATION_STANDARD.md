# ACCURACY_EVALUATION_STANDARD

## Purpose

This document defines a practical evaluation standard for checking:

- whether each runtime stage is actually complete
- whether that stage is accurate enough to trust
- where the current bottleneck is when end-to-end execution is wrong
- how to improve accuracy with evidence instead of guesswork

It is designed for the current runtime in this repo, not for a generic agent system.

The main evaluation chain is:

`session -> capture -> OCR -> vision_regions_v1 -> page_structure_v1 -> screen_reading_v1 -> action -> verification -> memory`

The preferred recognition-improvement strategy on top of that chain is:

`parse -> candidate -> narrow search -> verify`

---

## Core Principle

Do not mark a stage as "done" only because:

- the route exists
- the code imports
- one manual demo happened to work
- the JSON shape looks plausible

A stage is only considered complete when all four are true:

1. it returns the expected contract
2. it is accurate on a defined sample set
3. it is repeatable across multiple runs
4. it leaves enough evidence to debug failures

---

## Evaluation Levels

Use the same five completion levels for every stage.

### L0 - Not usable

- missing route, broken import, or cannot run

### L1 - Runnable

- route/module runs
- contract exists
- no accuracy evidence yet

### L2 - Functionally correct

- expected JSON fields are present
- happy-path behavior works on curated samples
- weak or incomplete accuracy evidence

### L3 - Measured and repeatable

- stage has a sample set
- metrics are recorded
- repeated runs are stable enough for local use

### L4 - Operationally reliable

- stage meets pass thresholds
- failure modes are known
- artifacts and traces are sufficient for debugging

### L5 - Production-trustworthy

- stage remains stable across software/layout variation
- false positives are controlled
- downstream stages do not need frequent manual correction

For the current repo, a realistic short-term target is:

- critical path stages at least `L3`
- action and verification stages at least `L4`

---

## Shared Metrics

Every stage should be judged with these four metric families.

### 1. Contract correctness

Measure:

- required fields present
- field types correct
- no silent fallback to invalid empty values unless explicitly allowed

Suggested metric:

- `contract_pass_rate = passed_contract_checks / total_runs`

Target:

- minimum acceptable: `>= 0.98`
- target: `1.00`

### 2. Accuracy

Measure the stage against a labeled expectation.

Examples:

- OCR text exact match
- semantic role correct
- click lands in the intended control
- verifier correctly distinguishes success from failure

### 3. Repeatability

Measure:

- same input, same output class
- low variance across 5 to 10 repeated runs

---

## Recommended Recognition Architecture

This repo should treat high-accuracy targeting as a staged recognition problem, not a single-coordinate prediction problem.

The recommended architecture is:

### 1. Parse

Goal:

- convert one screenshot into structured page evidence

Typical outputs:

- semantic regions
- OCR text boxes
- executable elements
- trusted zones vs blocked zones

Current repo mapping:

- `vision_provider_raw`
- `vision_regions_v1`
- `ocr_result`
- `page_structure_v1`
- `screen_reading_v1`

Primary evaluation question:

- did the runtime correctly represent what is on screen

### 2. Candidate

Goal:

- reduce many parsed elements down to a small ranked set that could satisfy the current intent

Typical ranking signals:

- task text similarity
- element role support
- interaction-policy trust
- screen-reading provider evidence such as UIA accessible names and UIA/icon matches
- ad risk
- page-state compatibility

Expected behavior:

- the correct target should usually appear in top-3
- blocked or ad-like elements should be demoted or excluded

Primary evaluation question:

- is the intended target preserved in the candidate set

### 3. Narrow Search

Goal:

- rerun grounding on smaller cropped ROIs instead of trusting the full-screen box

Typical operations:

- crop top candidate region
- rerun OCR and/or local vision grounding on that crop
- choose a refined bbox or click point inside the local crop

Why this matters:

- most full-screen errors are caused by cross-card drift, whitespace drift, and ad interference
- smaller local crops usually improve coordinate stability

Primary evaluation question:

- after local refinement, does the point land on the intended control

### 4. Verify

Goal:

- prevent low-confidence clicks and confirm that the chosen action actually worked

Pre-click verification:

- top-1 clearly ahead of top-2
- refined point inside trusted region
- candidate not marked as ad-like or blocked

Post-click verification:

- OCR change
- content change
- state transition
- URL or focus change

Primary evaluation question:

- did the system both avoid risky clicks and correctly confirm successful ones

---

## Stage-Specific Accuracy Checks For The Recommended Flow

Use these checks when implementing the staged strategy.

### Parse checks

- semantic region recall on labeled screenshots
- OCR recall for actionable text
- element contract pass rate

### Candidate checks

- `top_1_hit_rate`
- `top_3_hit_rate`
- `screen_reading_rank_contribution_rate`
- ad-candidate exclusion rate
- false-candidate promotion rate

Current candidate contract:

- `CandidateRankRequest`
- `CandidateRankResult`
- `RecognitionCandidate`
- `ScoreBreakdown`
- contract version: `candidate_rank_v1`
- no-click route: `POST /vision/recognition_plan`
- planning response version: `recognition_plan_v1`

Minimum evidence per candidate:

- final score
- score breakdown
- `screen_reading_score` when `screen_reading_v1` evidence is available
- eligibility
- reasons
- source element id
- original element bbox
- optional OCR-derived `refined_bbox` only when it is tighter than the original bbox
- whether `refined_bbox` came from goal-matching OCR text or all bound source text
- bbox refinement reason

### Narrow search checks

- local bbox IoU against labeled ROI
- click-point-inside-target rate
- cross-card drift rate

Current narrow-search contract:

- `LocalGroundingRequest`
- `LocalGroundingResult`
- `LocalGroundingCandidateResult`
- contract version: `narrow_search_v1`
- current baseline: crop top candidates using `refined_bbox` when available, run local OCR, map matched local OCR text center back to full-image coordinates

Minimum evidence per grounded candidate:

- crop path
- crop bbox in full-image coordinates
- matched local OCR text
- local OCR bbox
- refined full-image click point
- fallback reason when no match is found

### Verify checks

- true-success acceptance rate
- false-success rejection rate
- retry-trigger precision

Current pre-click decision contract:

- `PreClickDecisionResult`
- `PreClickCandidateDecision`
- contract version: `pre_click_decision_v1`

Minimum pre-click evidence:

- selected candidate id
- selected click point
- allow/reject boolean
- per-candidate reasons
- top-1 margin status
- candidate-goal text match status
- local OCR text match status
- refined-point-in-candidate-bbox status, using `refined_bbox` when present

Human review evidence:

- `POST /vision/render_recognition_plan_overlay`
- output image under `artifacts/review-overlays/`
- should show original candidate boxes, OCR-refined candidate boxes, decision state, local OCR matches, and refined click points

---

## Practical Guidance For This Repo

Short-term priority should be:

1. keep improving `parse`
2. add a real `candidate` ranking layer
3. add local ROI `narrow search`
4. strengthen `verify`

Do not rely on:

- one full-screen model call producing the final click point
- heavy post-hoc coordinate patching without a candidate model
- success claims that are not backed by verification evidence

Suggested metric:

- `repeatability_rate = consistent_runs / repeated_runs`

Target:

- minimum acceptable: `>= 0.90`
- target: `>= 0.95`

### 4. Traceability

Measure whether a failure leaves enough evidence to diagnose.

Evidence examples:

- screenshot path
- OCR result
- vision raw output
- layer trace
- click coordinates
- before/after images
- diff image
- replay case

Suggested metric:

- `traceability_rate = failures_with_debug_evidence / total_failures`

Target:

- minimum acceptable: `>= 0.95`

---

## Dataset Standard

Do not evaluate accuracy on a single screenshot.

For each target app/page, build a labeled sample set with at least:

- 10 screenshots for smoke evaluation
- 30 screenshots for meaningful tuning
- 50+ screenshots before trusting layout variation

Each sample should record:

- `sample_id`
- app name
- page/state name
- screenshot path
- window size or bucket
- expected visible texts
- expected actionable elements
- expected click target
- expected post-action result

Recommended split:

- 70% tuning set
- 30% holdout validation set

Do not tune thresholds only on the same screenshots used for final scoring.

---

## Stage-By-Stage Standard

## 1. Session Binding

Scope:

- `GET /session/windows`
- `POST /session/bind_window`

Goal:

- bind the intended target window and only that window

Completion checks:

- candidates list is returned
- chosen window metadata is correct
- bound handle stays stable unless the real target changes

Metrics:

- `window_discovery_recall`
  - expected target appears in candidate list
- `bind_success_rate`
  - correct target bound / bind attempts
- `wrong_bind_rate`
  - wrong target bound / bind attempts

Target thresholds:

- `window_discovery_recall >= 0.98`
- `bind_success_rate >= 0.95`
- `wrong_bind_rate <= 0.02`

Pass evidence:

- candidate list snapshot
- returned handle/title/process
- 5 repeated binds on the same target

Common failure meaning:

- target missing from candidates: enumeration problem
- wrong bind with similar titles: matching strategy too loose

## 2. Screenshot Capture

Scope:

- `POST /state/capture_window`
- internal screenshot path used by OCR, vision, and verifier

Goal:

- capture the correct window region with correct dimensions and ROI mapping

Completion checks:

- screenshot exists
- image dimensions match expected window or ROI
- ROI clipping is correct near edges
- repeated captures are visually consistent when UI is unchanged

Metrics:

- `capture_success_rate`
- `roi_coordinate_accuracy`
  - manually inspect whether saved crop corresponds to requested ROI
- `stable_capture_rate`
  - unchanged UI produces near-identical captures

Target thresholds:

- `capture_success_rate >= 0.99`
- `roi_coordinate_accuracy >= 0.98`
- `stable_capture_rate >= 0.95`

Pass evidence:

- saved screenshot files
- ROI metadata
- 10 repeated captures on a static target

Common failure meaning:

- shifted crop: ROI translation bug
- partial black area: capture backend timing or window visibility issue

## 3. OCR Region

Scope:

- `POST /vision/ocr_region`
- `app/core/ocr_service.py`

Goal:

- recover visible text and usable text boxes from the intended image region

Completion checks:

- OCR result contains expected texts
- bounding boxes are close enough for click grounding
- low-confidence noise does not overwhelm real text

Metrics:

- `text_recall = expected_texts_found / expected_texts`
- `text_precision = correct_texts_found / all_returned_texts_used_for_matching`
- `bbox_clickability_rate`
  - text bbox center lands inside the intended control
- `ocr_noise_rate`
  - obvious false text detections / total detections

Target thresholds:

- `text_recall >= 0.92`
- `text_precision >= 0.95`
- `bbox_clickability_rate >= 0.95`
- `ocr_noise_rate <= 0.10`

Scoring note:

- for action-critical labels such as buttons, use exact or normalized match
- track Chinese/English variants separately if the UI language changes

Pass evidence:

- OCR JSON
- annotated screenshot with OCR boxes
- list of missed texts and false texts

Common failure meaning:

- text found but click fails: OCR text okay, bbox grounding not okay
- many partial fragments: OCR engine or ROI too broad

## 4. Vision Regions

Scope:

- `POST /vision/analyze`
- `vision_regions_v1`

Goal:

- turn a screenshot into semantically useful regions with stable geometry and role hints

Completion checks:

- contract fields present
- important controls appear as semantic regions
- role and destination hints are useful, not random
- region geometry is close enough for later fusion

Metrics:

- `region_contract_pass_rate`
- `important_region_recall`
  - expected actionable controls represented by at least one region
- `role_accuracy`
  - expected role matches predicted role or allowed alias
- `region_iou_rate`
  - percentage of key regions with IoU above threshold against labeled semantic box

Recommended IoU thresholds:

- `>= 0.50` acceptable for semantic region recall
- `>= 0.70` good for stable downstream fusion

Target thresholds:

- `region_contract_pass_rate = 1.00`
- `important_region_recall >= 0.90`
- `role_accuracy >= 0.85`
- `region_iou_rate >= 0.80` at IoU `0.50`

Pass evidence:

- normalized provider JSON
- saved region artifacts under `logs/vision-regions/`
- optional `POST /vision/layer_trace` result

Common failure meaning:

- correct text but missing semantic region: vision model weakness
- semantic region present but wrong role: prompt/schema alignment issue

## 5. Page Structure Fusion

Scope:

- `POST /vision/page_structure`
- `page_structure_v1`

Goal:

- fuse semantic regions and OCR boxes into executable elements

Completion checks:

- expected controls become `elements[]`
- element labels are correct
- click point is usable
- unsupported regions do not create misleading actionable elements
- far repeated OCR fragments are not bound to the same element unless local geometry supports the binding
- short ambiguous OCR text does not override semantic-only coordinates when it is far from the semantic region

Metrics:

- `element_recall`
  - expected actionable elements produced / expected actionable elements
- `element_precision`
  - correct actionable elements / produced actionable elements
- `click_point_hit_rate`
  - selected click point lands within intended live control
- `memory_key_stability`
  - same control across repeated runs keeps the same memory key

Target thresholds:

- `element_recall >= 0.90`
- `element_precision >= 0.90`
- `click_point_hit_rate >= 0.95`
- `memory_key_stability >= 0.95`

Pass evidence:

- `page_structure_v1` JSON
- `elements`, `texts`, `links`
- layer trace comparison against OCR and semantic source

Common failure meaning:

- OCR and vision both good, element bad: fusion scoring or role filter problem
- element exists but point misses: bbox selection strategy problem
- element bbox spans unrelated text: OCR binding cluster or short-text guard problem

## 6. Screen Reading

Scope:

- `POST /vision/screen_reading`
- `screen_reading_v1`
- `app/screen_reading/builder.py`
- `app/screen_reading/uia_provider.py`
- `app/screen_reading/icon_library.py`

Goal:

- expose a READ-facing UI layer that describes text, modules, executable elements, visual-only/icon candidates, provider slots, and learning hooks without executing actions

Completion checks:

- OCR-backed page elements appear in `ui.elements`
- visual-only or icon-like candidates appear in `ui.icon_candidates`
- visual-only/icon candidates are not marked as safe execution targets without stronger grounding
- provider slots are present for UIA, browser accessibility, Microsoft Fluent icon catalog, and learned UI memory
- UIA scan status and control count appear in `source_layers.windows_uia`
- UIA matches appear on supported bound-window controls when overlap/name evidence is available
- Microsoft Fluent catalog matches appear for supported contextual icon candidates
- uncertainties explicitly describe missing catalog or grounding evidence

Metrics:

- `screen_reading_contract_pass_rate`
- `ui_element_recall`
  - expected UI elements represented / expected UI elements
- `icon_candidate_recall`
  - expected no-text icons represented / expected no-text icons
- `icon_catalog_match_rate`
  - expected Microsoft Fluent matches found / expected supported icon candidates
- `uia_control_match_rate`
  - expected UIA controls merged / expected supported bound-window controls
- `uia_smoke_pass_rate`
  - UIA smoke cases with expected status, control counts, button counts, and required control-name substrings passing / UIA smoke cases
- `unsafe_icon_block_rate`
  - visual-only icon candidates kept out of safe action candidates / visual-only icon candidates
- `module_grouping_accuracy`

Target thresholds for the current phase:

- `screen_reading_contract_pass_rate = 1.00`
- `ui_element_recall >= 0.90`
- `icon_candidate_recall >= 0.80`
- `icon_catalog_match_rate >= 0.80` for supported common browser/UI icons
- `uia_control_match_rate >= 0.80` for supported bound-window controls
- `uia_smoke_pass_rate = 1.00` for the current MouseTester/Edge smoke case
- `unsafe_icon_block_rate = 1.00`

Pass evidence:

- `screen_reading_v1` JSON
- `ui.elements`, `ui.icon_candidates`, `ui.provider_slots`, `source_layers.windows_uia`, `execution_relevance`, and `uncertainties`
- route trace under `logs/traces/vision/`
- UIA smoke trace under `logs/traces/evaluation/` and report from `scripts/record_uia_smoke.py`
- targeted route/unit tests

Common failure meaning:

- OCR/page structure good but missing UI element: READ builder mapping issue
- icon visible but absent from `icon_candidates`: visual-region role/label mapping issue
- icon candidate present but expected Microsoft Fluent match absent: catalog alias/context mapping issue
- UIA control present but not merged into expected element: bbox overlap/name matching issue
- visual-only icon marked safe: grounding safety policy issue

## 7. Action Execution

Scope:

- `POST /action/execute_recognition_plan`
- `POST /action/click_text`
- `POST /action/click_mouse_tester_left_region`
- `input_controller`

Goal:

- dispatch the intended GUI action on the intended target

Completion checks:

- selected coordinate is correct
- recognition-plan execution is gated by `pre_click_decision_v1.allowed`
- saved screenshots are not used for live execution unless explicitly overridden
- click is physically sent
- retry/fallback behaves as designed
- wrong control is not clicked more often than tolerated

Metrics:

- `action_dispatch_success_rate`
  - action call completed without runtime error
- `intended_target_hit_rate`
  - click landed on intended target
- `fallback_recovery_rate`
  - initial miss but retry succeeds
- `wrong_target_activation_rate`
  - wrong control activated / total actions

Target thresholds:

- `action_dispatch_success_rate >= 0.99`
- `intended_target_hit_rate >= 0.93`
- `fallback_recovery_rate >= 0.60`
- `wrong_target_activation_rate <= 0.03`

Pass evidence:

- recognition plan trace and overlay
- returned click coordinates
- attempts list
- retry reason and retry count for every repeated execution attempt
- before and after screenshots
- semantic post-click verification for MouseTester targets
- trace-evaluation report from `scripts/evaluate_mousetester_traces.py`
- replay case if applicable

Common failure meaning:

- click sent but no effect: verification or target point issue
- wrong click with correct OCR: coordinate translation issue

## 8. Verification

Scope:

- `app/core/verifier.py`
- validator behavior used by click paths

Goal:

- correctly decide whether the action really changed the UI as intended

Completion checks:

- true success is marked success
- true failure is marked failure
- static UI noise does not create false positives

Metrics:

- `verification_precision`
  - predicted success that was truly success / predicted success
- `verification_recall`
  - true success correctly recognized / true success
- `false_positive_rate`
  - predicted success on true failure
- `false_negative_rate`
  - predicted failure on true success

Target thresholds:

- `verification_precision >= 0.95`
- `verification_recall >= 0.90`
- `false_positive_rate <= 0.03`
- `false_negative_rate <= 0.08`

Important rule:

- false positives are more dangerous than false negatives
- when tuning thresholds, prefer reducing false positives first

Pass evidence:

- before image
- after image
- diff image
- verification basis fields

Common failure meaning:

- precision low: visual diff threshold too loose
- recall low: wait time or ROI too narrow

## 9. State Memory And Persistence

Scope:

- action/state registry
- transition memory
- replay cases
- region click cache

Goal:

- record successful behavior without corrupting future runs

Completion checks:

- expected JSON artifacts are written
- files are reloadable
- reused memory improves or at least does not degrade success rate

Metrics:

- `artifact_write_success_rate`
- `artifact_reload_success_rate`
- `memory_reuse_gain`
  - success rate with memory minus success rate without memory
- `memory_corruption_rate`
  - invalid or misleading stored artifacts / total stored artifacts

Target thresholds:

- `artifact_write_success_rate = 1.00`
- `artifact_reload_success_rate = 1.00`
- `memory_reuse_gain >= 0.00`
- `memory_corruption_rate <= 0.02`

Pass evidence:

- files under `logs/app-states/`, `logs/app-actions/`, `logs/app-transitions/`, `logs/replay-cases/`, `logs/region-click-cache/`
- before/after comparison with cache enabled and disabled

Common failure meaning:

- memory exists but success drops: match key or reuse policy too aggressive

## 10. End-To-End Task Accuracy

Scope:

- complete task flow on a live bound target

Goal:

- finish the intended user-visible operation without human correction

Task examples:

- bind a window and click a visible named control
- detect page structure and activate a chosen element
- perform MouseTester left-region action and confirm the counter changed

Metrics:

- `task_success_rate`
- `steps_per_success`
- `human_intervention_rate`
- `mean_time_to_success`

Target thresholds:

- `task_success_rate >= 0.85` for early live testing
- `task_success_rate >= 0.93` before trusting routine use
- `human_intervention_rate <= 0.10`

Pass evidence:

- full request/response log
- screenshots
- verification output
- replay artifacts

---

## Required Scorecard

Use one scorecard row per stage.

Suggested columns:

- `stage`
- `level`
- `sample_count`
- `contract_pass_rate`
- `accuracy_metric_1`
- `accuracy_metric_2`
- `repeatability_rate`
- `traceability_rate`
- `current_blocker`
- `next_fix`

Example:

| stage | level | sample_count | key metrics | blocker | next fix |
|---|---:|---:|---|---|---|
| session_bind | L3 | 20 | bind_success=0.95, wrong_bind=0.00 | similar window titles | tighten title match |
| capture | L4 | 30 | capture_success=1.00, roi_accuracy=0.97 | edge ROI clipping | clamp and retest |
| ocr_region | L3 | 30 | recall=0.90, precision=0.97 | small text missed | reduce ROI and compare OCR backend |
| page_structure | L2 | 15 | element_recall=0.80, click_hit=0.87 | fusion misses tabs | adjust role mapping |

---

## Failure Classification Standard

Every failed run should be tagged into exactly one primary bucket first.

Primary buckets:

- `bind_failure`
- `capture_failure`
- `ocr_failure`
- `vision_failure`
- `fusion_failure`
- `action_failure`
- `verification_failure`
- `memory_failure`
- `unknown`

Then optionally add one secondary cause:

- `contract_missing_field`
- `wrong_target`
- `bbox_shift`
- `false_positive`
- `false_negative`
- `timeout`
- `noisy_ui`
- `layout_variation`
- `language_variation`

This prevents all bad runs from being lazily grouped into "accuracy issue".

---

## Optimization Loop

Use this order when improving accuracy.

1. fix contract failures first
2. fix highest-frequency upstream failure first
3. prefer recall improvements in OCR and region discovery
4. prefer precision improvements in verification and final click selection
5. rerun only the smallest affected benchmark first
6. rerun end-to-end after the stage score improves

Reason:

- upstream misses destroy downstream accuracy
- downstream false positives are more dangerous than upstream uncertainty

---

## Recommended Practical Workflow

For each target app/page:

1. collect 10 to 30 screenshots
2. label expected texts and expected controls
3. run `POST /vision/layer_trace` on the screenshot set
4. score OCR, regions, and page structure separately
5. run live action tests only after page structure click-point accuracy is acceptable
6. score verification precision and recall on true success and true failure cases
7. enable memory reuse only after the non-memory baseline is stable

---

## Current Repo-Specific Minimum Acceptance Gate

Before trusting a new target workflow in this repo, require at least:

- `session binding` at `L3`
- `capture` at `L4`
- `ocr_region` at `L3`
- `vision_regions_v1` at `L3`
- `page_structure_v1` at `L3`
- `screen_reading_v1` at `L2`
- `action execution` at `L3`
- `verification` at `L4`
- `memory reuse` at `L2`
- `end-to-end task accuracy >= 0.85`

If verification is below `L4`, do not claim the workflow is reliable even if clicks sometimes appear to work.

---

## What To Check First When Accuracy Drops

If the end result is wrong, inspect in this order:

1. was the correct window bound
2. was the correct image captured
3. did OCR see the needed text
4. did `vision_regions_v1` contain the intended control
5. did `page_structure_v1` create the right element and click point
6. did the action click the intended coordinate
7. did verification classify the outcome correctly
8. did stored memory push the runtime toward a stale target

This order matches the real dependency chain of the repo.
