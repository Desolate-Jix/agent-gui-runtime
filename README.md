# agent-gui-runtime

## 2026-07-12 Stage2 multi-row header and partial-card reconciliation

Stage1 structure division remains unchanged. The shared Stage2 path now treats a confirmed top/header region as potentially multi-row: direct-control search uses the full confirmed region, controls are clustered by horizontal y-band before hit-area normalization, and each row receives its own display-only `topbar_control_strip`. This prevents lower header rows from being clipped by the former 96px search band. In the Python fixture, the header now contains 3 rows and all 22 review controls have height at least 39px instead of several 1px fragments.

Bottom-edge partial cards now merge text fragments that share one visual card and infer a peer card slot from the observed card width when the second card is only partially visible. The Python fixture changes from 4 narrow fragments to 2 review-only cards: `Success Stories + More` and `Use Python for... + More`, both covering the visible 72px card strip. The latest same-source three-image report is `logs/benchmarks/learning_structure_triad_stage2_partition_fix_final_20260712/learning_structure_triad_report.json`; Apple Music, Python, and Windows Settings all pass their fixed fixture checks. This is offline parser/OCR/heuristic review evidence only, not model accuracy, Execute readiness, or Runtime PathGraph promotion.

Main-content semantic ownership is now explicit: when repeated metadata/title rows form a `list_group`, the same OCR items cannot also remain inside inferred `stage2_primary_text_tile_card_parent_grouping` boxes. Only conflicting inferred text tiles are removed; explicit media cards and settings tiles remain unchanged. The latest regression report is `logs/benchmarks/learning_structure_triad_list_precedence_fix_20260712/learning_structure_triad_report.json`.

## 2026-07-11 Learning structure three-image self-audit

Learning Mode structure review now requires three artifacts from the same source screenshot: the original image, the Stage1 bar-only overlay, and the final fused overlay. `scripts/run_learning_structure_triad_benchmark.py` validates the screenshot checksum and all three paths, writes one three-column contact sheet per case, and excludes stale or incomplete evidence as invalid. The fixed manifest is `artifacts/benchmarks/learning_structure_triad_manifest_v1.json`; the latest report is `logs/benchmarks/learning_structure_triad_stage2_partition_fix_final_20260712/learning_structure_triad_report.json`. Its explicit workflow is same-source evidence validation, structure scoring, golden-element scoring, then mandatory manual three-image review.

The current self-review checks both coarse structure bars and 28 independently annotated elements. The aggregate report records `28 / 28 / 1.0`, rather than requiring a manually assembled percentage. Boundary errors are normalized against each expected region's own width and height, not the full screenshot. A shallow full-screen inventory can use a reliable OCR-aligned repeated horizontal control row to recover the header/main boundary; without that evidence it retains the rough boundary. The corrected web-portal fixture moves the boundary from `y=321` to `y=212`, keeping the full Hero in main content. The largest observed center-offset ratio is `0.0669`; the largest structure-boundary error is now `0.0093`. Generic reconciliation also protects a substantiated unlabeled left rail, prevents an oversized row container from swallowing one media card, groups repeated heading/body text columns into complete parent modules, and normalizes parallel list parents from a complete sibling column. Codex reviewed each same-source original / Stage1 / final contact sheet. This remains fixture-review evidence only, not model accuracy, general website reliability, Execute readiness, or Runtime PathGraph promotion.

Root fixes in this checkpoint are generic: OCR edge text marked as `geometry_hint_only` no longer creates a sidebar; a shallow top-only observation cannot silently pass as a full-screen main region; and the panel now prefers `compiled_overlay_path` so the displayed completion image is the actual final fusion rather than an earlier overlay. No application names, application-specific text, or fixed production coordinates were added.

## 2026-07-11 Windows Settings free-exploration review

The first valid non-protected free-exploration trace after the source-fixture repair is Windows Settings, not a protected AppleMusic / QQ / Python.org replay. It was replayed through the guarded no-click path and then through the panel chain:

- Source inventory: `logs\benchmarks\learning_free_exploration_source_inventory_after_source_fixture_repair_20260711.json`
- Free replay report: `logs\benchmarks\learning_free_exploration_windows_settings_after_source_fixture_repair_20260711\learning_free_exploration_from_trace_20260711-124910.json`
- Panel-chain report: `logs\benchmarks\learning_free_exploration_windows_settings_panel_chain_20260711\learning_free_exploration_panel_chain_report.json`
- Visual contact sheet: `logs\benchmarks\learning_free_exploration_windows_settings_panel_chain_20260711\learning_interface_chain_contact_sheet.png`

Self-review: this sample is only `replay_ready_for_visual_review`. Stage1 finds the coarse window structure and Stage2 has numbered/fused review boxes, but the visual contact sheet still misses many settings tiles as clear card-level boxes. It is not demo-ready, not model accuracy evidence, not Execute readiness, and not Runtime PathGraph promotion.

Anti-pollution check: `logs\benchmarks\learning_protected_after_windows_settings_panel_chain_review_20260711.json` passes AppleMusic / QQ / Python.org with `attempted=3`, `passed=3`, and `baseline_comparison.mismatch_count=0`.

## 2026-07-11 Python fixture repair and protected three-interface archive

The protected Learning Interface chain smoke no longer depends on the stale Python.org `locate-target` screenshot that disappeared from `artifacts/screenshots`. The root fix was not to fall back to an annotated overlay. Instead, the Stage1 replay input reader now accepts current parser artifacts where `screen_inventory` is a list and where the source screenshot / image size live under `observe_bundle`. This lets the Python.org stress sample use the existing matched fixture `artifacts/learning-runs/new_site_python_org_20260702/python_org_home.png` with its matching parser output, avoiding coordinate-space drift.

Latest no-click chain smoke: `logs\benchmarks\learning_interface_chain_smoke_source_fixture_repair_20260711\learning_interface_chain_smoke_report.json`. AppleMusic and QQ are `review_only_chain_ready`; Python.org is explicitly `stress_only_needs_review` with missing deep review boxes and must not be used as a demo-ready success sample. Visual report: `logs\benchmarks\learning_interface_demo_visual_source_fixture_repair_20260711\learning_interface_demo_visual_report.json`. Archive node: `logs\benchmarks\learning_demo_visual_archive_source_fixture_repair_20260711.json`.

Safety boundary: no live clicks, fills, submits, Execute binding, Runtime PathGraph promotion, model accuracy claim, or 5.5/old-model success claim.

## 2026-07-11 Learning review-box status contract

`POST /panel/run_learning_recognition_trial` now returns a `learn_all_targets` status block for display-only learning drafts. When an attached two-stage report has numbered items or fused review boxes but no executable calibrated targets, the API reports `status=review_boxes_ready`, `target_count=0`, and the real `review_box_count`. This prevents the panel from inheriting a previous Learn Deep `no_targets` status after the fused screenshot / page-detail draft already exists.

Boundary: review boxes remain learning-draft display evidence only. They are not executable targets, not click authorization, not Runtime PathGraph promotion, and not model accuracy evidence.

Evidence: `tests/test_learning_draft_review.py::test_panel_learning_recognition_trial_uses_two_stage_numbered_items_when_calibration_has_no_targets` now asserts the response status contract. Protected review check `logs\benchmarks\learning_protected_after_review_box_status_contract_20260711.json` passes AppleMusic / QQ / Python.org with `mismatch_count=0`. Full chain smoke is currently blocked by a missing legacy Python.org source screenshot fixture at `artifacts\screenshots\welcome-to-python-org-microsoft-edge__locate-target__python-org__full-window__20260703-173956-578036.png`; this fixture problem was not hidden with a fallback.

## 2026-07-11 Free-exploration panel self-observation guard

The first apparent non-protected free-exploration candidate was rechecked visually and rejected. Although the trace name was `openclaw-console-free-exploration`, the screenshot showed the local Learning panel at `127.0.0.1:8000/panel?stage=learn_replay&learn_view=draft` with a previously loaded Python.org learning draft. That is not a clean fourth-interface sample.

`scripts/report_learning_free_exploration_sources.py` now classifies this as `panel_self_observation_trace` when the trace text or screen map contains panel replay / learning-draft markers such as `127.0.0.1:8000/panel`, `stage=learn_replay`, `learn_view=draft`, `学习草稿`, `草稿路径图`, or `PathGraph`. Such traces are forbidden for free exploration, do not become candidates, and are blocked by `scripts/prepare_learning_free_exploration_preflight.py`.

Evidence: `logs\benchmarks\learning_free_exploration_source_inventory_panel_self_guard_20260711.json` now has `candidate_count=0`, `panel_self_observation_trace=1`, and `intake_gate.status=blocked_until_real_observe_capture`. `logs\benchmarks\learning_free_exploration_preflight_openclaw_panel_self_guard_20260711.json` blocks the OpenClaw trace with `classification=panel_self_observation_trace`. Protected anti-pollution check `logs\benchmarks\learning_protected_after_panel_self_observation_intake_guard_20260711.json` passes with `mismatch_count=0`.

Boundary: free exploration still needs a fresh, real, non-protected `/vision/observe_screen` trace from a target app or website window, not the local panel observing its own replay. No live click, fill, submit, Execute binding, or Runtime PathGraph promotion occurred.

## 2026-07-11 Browser chrome container boundary fix

Historical Python.org screenshots were re-reviewed against the current trace reports. The old clean-looking Python overlays were display/fusion artifacts, and earlier 5.5/model draft coordinates were not trustworthy: one saved draft reported `image_size=768x417` while emitting points beyond that width. The current failure was traced to the shared Stage1 path instead: large UIA containers such as `window`, `pane`, and `document` with labels like `Python.org` were treated as browser chrome evidence, expanding `browser_chrome` into the page header and causing `structure_region_overlap`.

`app/learn/recognition/two_stage.py` now rejects large top-surface containers as browser-chrome top items, calibrates browser chrome only from actual chrome-top evidence, and clamps `browser_chrome` against the page top/header boundary so adjacent bars may touch but not overlap. Regression: `tests/test_learn_recognition_pipeline.py::test_two_stage_browser_chrome_ignores_large_python_org_surface_containers`.

Evidence: Python.org real trace replay `logs\benchmarks\learning_twostage_python_browser_chrome_container_fix_with_overlay_20260711\learn_two_stage_replay_report_20260711-114623.json` now has `stage1_gate_status=passed`, `stage2_numbering_skipped=false`, and a rendered overlay at `artifacts\review-overlays\welcome-to-python-org-microsoft-edge__locate-target__python-org__full-window__20260703-173956-578036__two-stage-understanding__20260711-114623-108517.png`. Three-surface chain smoke `logs\benchmarks\learning_interface_chain_smoke_browser_chrome_container_fix_20260711\learning_interface_chain_smoke_report.json` keeps AppleMusic and QQ as `review_only_chain_ready`, Python.org as `stress_only_needs_review`, with no live clicks/fills/submits and no Runtime PathGraph promotion. Visual report: `logs\benchmarks\learning_interface_demo_visual_browser_chrome_container_fix_20260711\learning_interface_demo_visual_report.json`.

## 2026-07-11 Learning Interface fused-overlay attachment fix

Historical Python.org v92/v97 screenshots were rechecked. The clean-looking Python overlays are fusion/display artifacts: Qwen/VLM output in the historical trace was sparse, and the dense boxes came from OCR/UIA/layout heuristics plus display suppression. They are protected visual-regression references, not evidence that the old 5.5 coordinate/model path was accurate.

Historical model-evidence audit: `uv run python scripts\audit_learning_historical_model_evidence.py --out logs\benchmarks\learning_historical_model_evidence_audit_20260711.json --json` classifies the Python.org v92 visual audit, v97 visual audit, honest fullscreen summary, current replay, and actual parser inventory. The saved report has `attempted=5`, `display_review_only_cases=5`, `model_grounding_evidence_cases=0`, and `model_accuracy_claim_allowed=false`; even the actual parser inventory is only `model_semantic_inventory_only` because it has no recorded model grounding attempts.

Real-flow Stage1 root-cause fix: the Stage1 inventory builder now reads the real `/vision/observe_screen` `screen_inventory` buckets (`available_actions`, `page_elements`, and `cards`) instead of relying only on `screen_map` / OCR fragments. The Stage1 localization path also merges same-family, near-identical structure regions before the gate, recording `merged_same_family_regions` so duplicate `browser_chrome/top_bar` or `main_content/primary_area` zones do not masquerade as sibling overlap failures. AppleMusic replay report `logs\benchmarks\learning_twostage_stage1_dedupe_fix_v3_applemusic_20260711\learn_two_stage_replay_report_20260711-103508.json` now reports `stage1_gate_status=passed`, `stage2_numbering_skipped=false`, `stage2_region_count=3`, and `numbered_item_count=67`. The protected three-interface chain smoke `logs\benchmarks\learning_interface_chain_smoke_stage1_inventory_dedupe_v3_20260711\learning_interface_chain_smoke_report.json` still has AppleMusic / QQ as `review_only_chain_ready`, Python.org as `stress_only_needs_review`, and `runtime_pathgraph_ready_count=0`; the protected comparison node `logs\benchmarks\learning_protected_after_stage1_inventory_dedupe_v3_20260711.json` passes with `mismatch_count=0`. Visual self-review contact sheet: `logs\benchmarks\learning_interface_demo_visual_stage1_inventory_dedupe_v3_20260711\learning_interface_demo_visual_contact_sheet.png`. This is still display/review evidence only, not model accuracy, not Execute authorization, and not Runtime PathGraph promotion.

Pre-exploration readiness gate: `uv run python scripts\check_learning_exploration_readiness.py --baseline logs\benchmarks\learning_protected_after_structure_quality_archive_fields_20260711.json --checkpoint-id exploration_readiness_20260711 --out logs\benchmarks\learning_exploration_readiness_20260711.json --json` now runs the protected-set comparison, historical model-evidence audit, and structure-quality gate. The current report has `ready_for_new_interface_exploration=true`, `protected_set_passed=true`, `baseline_comparison_passed=true`, and `historical_model_evidence_boundary_passed=true`. This only means exploration is safe to start; it is not recognition quality, model accuracy, Execute authorization, or Runtime PathGraph promotion.

The same readiness report now separates protected readiness from replay readiness. Latest report: `logs\benchmarks\learning_exploration_readiness_after_free_intake_integration_20260711.json` has `ready_for_new_interface_exploration=true` but `ready_for_free_exploration_replay=false`, because `free_exploration_intake_allowed=false` and there is no usable non-protected observe trace yet. This prevents treating a healthy protected baseline as proof that a fourth-interface replay source already exists.

Structure-quality gate: `uv run python scripts\check_learning_structure_quality.py --out logs\benchmarks\learning_structure_quality_three_surface_20260711.json --json` checks the current AppleMusic / QQ / Python.org two-stage reports for Stage1 coverage, Stage2 numbered items, fused review boxes, boundary-contract failures, and Runtime PathGraph promotion risk. Latest result: AppleMusic and QQ are only `display_review_candidate`; Python.org is `stress_only_needs_review` because it still has non-parent sibling overlap. `scripts\check_learning_exploration_readiness.py` now embeds this gate and records `runtime_pathgraph_promotion_blocked=true`, so historical clean Python screenshots cannot be reinterpreted as old 5.5/model accuracy or execution readiness.

Stage1 partition coverage is now a near-full-screen contract, not a loose visual heuristic. `scripts\check_learning_structure_quality.py` requires `stage1_partition_near_full_coverage` at ratio `>=0.98`, so empty visible lanes must still belong to a structure bar/region before Stage2 numbering is trusted. Latest report: `logs\benchmarks\learning_structure_quality_stage1_near_full_partition_20260711.json`. The protected comparison node `logs\benchmarks\learning_protected_after_stage1_near_full_partition_gate_20260711.json` passes with AppleMusic / QQ still display-review candidates and Python.org still a stress sample; the old baseline skips the new optional threshold field only because that legacy archive did not record it.

`scripts\check_learning_exploration_readiness.py` now defaults to the near-full partition checkpoint `logs\benchmarks\learning_protected_after_stage1_near_full_partition_gate_verify_20260711.json` and exposes the Stage1 partition threshold in its summary. Latest readiness report: `logs\benchmarks\learning_exploration_readiness_stage1_near_full_partition_20260711.json` has `structure_stage1_near_full_partition_required_ratio=0.98`, `structure_stage1_near_full_partition_passed=3`, and `structure_stage1_near_full_partition_attempted=3`. New-interface exploration remains protected-ready, but free replay is still blocked until a real non-protected observe trace with inventory exists.

Free exploration now has a guarded trace runner: `scripts\run_learning_free_exploration_from_trace.py`. It first classifies the requested observe trace, blocks protected AppleMusic / QQ / Python.org traces, screenshot-only traces, model-test traces, and stale-image traces, then runs protected-set comparison before and after any two-stage replay. The source inventory `next_action` now points to this guarded runner instead of direct `run_learn_two_stage_replay.py`. Latest blocked smoke: `logs\benchmarks\learning_free_exploration_from_trace_blocked_protected_20260711\learning_free_exploration_from_trace_20260711-091200.json` correctly rejects an AppleMusic trace as `protected_baseline_trace` with no replay report and no live click/fill/submit.

Protected archive nodes now carry the same structure-quality fields. `logs\benchmarks\learning_protected_after_structure_quality_archive_fields_20260711.json` is the stronger three-interface checkpoint: AppleMusic / QQ stay `display_review_candidate`, Python.org stays `stress_only_needs_review`, and future comparisons will fail if those structure-quality statuses or counts drift. The checker remains compatible with older archives, but new strategy work should use this structure-aware checkpoint as the baseline.

Screenshot-only free exploration after the gate: OpenClaw Console, NVIDIA overlay, and Codex/ChatGPT screenshots were run through `scripts\run_learn_screenshot_exploration.py`; summary is `logs\benchmarks\learning_free_exploration_screenshot_only_batch_20260711.json` and visual contact sheet is `artifacts\review-overlays\free_exploration_screenshot_only_contact_sheet_20260711.png`. All three are `no_review_boxes` / `not_demo_ready` (`numbered=0`, `fused=0`), so screenshot-only exploration is only a boundary probe. The post-run readiness check `logs\benchmarks\learning_exploration_readiness_after_screenshot_only_20260711.json` still passes, proving the protected baseline was not polluted.

Free-exploration source inventory: `uv run python scripts\report_learning_free_exploration_sources.py --out logs\benchmarks\learning_free_exploration_source_inventory_20260711.json --json` scans recent vision traces and classifies only non-protected traces with an existing screenshot plus observe inventory as usable. Current scan: `scanned_trace_count=500`, `candidate_count=0`, with `model_test_trace=174`, `protected_baseline_trace=61`, and `missing_or_stale_image=265`. The post-inventory readiness check `logs\benchmarks\learning_exploration_readiness_after_source_inventory_20260711.json` still passes. Next exploration must capture a real non-protected window through `/vision/observe_screen`; old model-test/pytest/screenshot-only artifacts are not demo evidence.

Free-exploration intake gate: `scripts\report_learning_free_exploration_sources.py` now emits `intake_gate`. The latest gate report is `logs\benchmarks\learning_free_exploration_source_inventory_intake_gate_20260711.json`: `candidate_count=0`, `intake_gate.allowed=false`, `status=blocked_until_real_observe_capture`, and blockers include `no_usable_non_protected_observe_trace`, `missing_or_stale_image_not_allowed`, and `protected_baseline_must_not_be_used_for_free_exploration`. This is intentional: free exploration cannot start from screenshot-only, panel model-test, stale pytest temp images, or AppleMusic / QQ / Python protected traces.

The real Learning Interface flow now carries the active two-stage report into the second `/panel/run_learning_recognition_trial` pass through `two_stage_report_path`. The backend attaches that report's `fusion_status` into `learning_draft.page_details.pipeline_audit.precise_understanding_fusion_status`, so `load_learning_draft_review` can render `compiled_overlay_path` / `full_screen_understanding_overlay_path` instead of falling back to the raw screenshot. If Stage1 blocks Stage2, the flow still loads the display-only review overlay and marks it as no-Execute evidence; it no longer stops before the review panel can show what happened.

The recognition-trial endpoint now also consumes the attached two-stage report's Stage2 numbered items as read-only draft inventory. This fixes the real-panel dataflow where the overlay/numbered screenshot existed, but Learn Deep calibration returned `target_count=0`, leaving the learning draft, page details, and read-only PathGraph preview empty. Stage2 numbered items are imported only as `review_only` / `display_only` regions; they are not calibrated click targets, grounding validation, Execute authorization, or Runtime PathGraph promotion evidence. AppleMusic smoke evidence: `artifacts\learning-runs\panel_20260711-092413-363_apple_music\trial_result.json` produced `screen_inventory_count=31`, `two_stage_review_region_count=31`, `accepted_for_grounding_count=0`, and `grounding_validation_count=0`.

Protected chain smoke after the Stage2 inventory fix: `uv run python scripts\run_learning_interface_chain_smoke.py --regression-root logs\benchmarks\learn_three_surface_regression_20260710_v5 --out logs\benchmarks\learning_interface_chain_smoke_after_stage2_inventory_fix_v2_20260711 --json` generated `logs\benchmarks\learning_interface_chain_smoke_after_stage2_inventory_fix_v2_20260711\learning_interface_chain_smoke_report.json` and contact sheet `logs\benchmarks\learning_interface_chain_smoke_after_stage2_inventory_fix_v2_20260711\learning_interface_chain_contact_sheet.png`. AppleMusic / QQ / Python.org all completed the display-only chain; draft trial `two_stage_review_region_count` is `31 / 94 / 124`, page-detail region count is `32 / 32 / 32`, and read-only PathGraph preview is ready for all three. AppleMusic and QQ are `review_only_chain_ready`; Python.org remains `stress_only_needs_review`.

Anti-pollution check after that run: `logs\benchmarks\learning_protected_after_stage2_inventory_fix_20260711.json` passes against `logs\benchmarks\learning_protected_after_structure_quality_archive_fields_20260711.json` with `mismatch_count=0`. This remains a protected display/review checkpoint, not model accuracy, point-grounding proof, Execute authorization, or Runtime PathGraph readiness.

Demo visual audit: `scripts\render_learning_interface_demo_visual_report.py` renders screenshot-backed page-detail previews, screenshot-backed read-only PathGraph previews, and a separate read-only PathGraph structure diagram from a chain-smoke report. Latest output is `logs\benchmarks\learning_interface_demo_visual_pathgraph_structure_v4_20260711\learning_interface_demo_visual_report.json` with contact sheet `logs\benchmarks\learning_interface_demo_visual_pathgraph_structure_v4_20260711\learning_interface_demo_visual_contact_sheet.png`. AppleMusic and QQ are `display_review_ready`; Python.org is `stress_sample_display_review` and is not counted as display-ready. All visuals remain `display_only`, `execute_binding_enabled=false`, and `runtime_pathgraph_promotion=false`.

Demo visual archive node: `scripts\archive_learning_demo_visual_checkpoint.py` now binds the v4 visual report to the protected-set comparison in one reviewable checkpoint. Current archive: `logs\benchmarks\learning_demo_visual_archive_v4_20260711.json`, `status=pass`, `display_review_ready_count=2`, `stress_sample_display_review_count=1`, `runtime_pathgraph_ready_count=0`, `protected_baseline_status=pass`, and `protected_baseline_mismatch_count=0`. Follow-up readiness report `logs\benchmarks\learning_exploration_readiness_after_demo_visual_archive_v4_20260711.json` keeps `ready_for_new_interface_exploration=true` but `ready_for_free_exploration_replay=false` until a real non-protected observe trace with inventory is captured.

Free-exploration preflight: `scripts\prepare_learning_free_exploration_preflight.py` is the fixed no-click gate before trying a fourth interface. It runs the protected readiness checks and then validates a supplied observe trace. Current report without a trace is `logs\benchmarks\learning_free_exploration_preflight_current_20260711.json`: `ready_for_new_interface_exploration=true`, `ready_for_free_exploration_replay=false`, and blocker `usable_non_protected_observe_trace_required`. The required next input is a real non-protected `/vision/observe_screen` trace with an existing screenshot and OCR/UIA inventory; protected AppleMusic / QQ / Python traces, screenshot-only images, model-test traces, and stale temp images remain forbidden.

Real-flow dataflow fix: later learning-draft evidence now keeps the original observe result's `screen_map`, screen size, summary, and source screenshot even after the current `lastResponse` changes to a two-stage or draft response. The panel also sends explicit `source_image_path` into `/panel/run_learning_two_stage_understanding`. This prevents the current run from degrading into screenshot-only / stale-overlay evidence while the saved observe trace still has the richer OCR/UIA/screen-map data.

Latest protected review check: `logs\benchmarks\learning_protected_after_historical_evidence_audit_20260711.json` passed AppleMusic / QQ / Python.org as display/review baselines and matched the archived comparison node. This remains not model accuracy, not point-grounding proof, not Execute authorization, and not Runtime PathGraph promotion.

AppleMusic real-trace endpoint smoke after the fix: `logs\traces\vision\20260710-032439-862225__learn-mode-fast-observe__applemusic.json` replayed through `/panel/run_learning_two_stage_understanding` with explicit `source_image_path` produced `stage1_regions=3`, `stage2_items=31`, `fusion_boxes=44`, saved report `artifacts\learning-runs\panel_20260711-054241-964_applemusic_panel_dataflow_smoke\trial_result.json`, and overlay `artifacts\review-overlays\apple-music__observe-screen__applemusic__full-window__20260710-032407-416762__two-stage-understanding__20260711-054241-912250.png`.

Learn Deep review-box status fix: `/vision/locate_target` now distinguishes executable targets from learning-mode read-only review boxes. If no executable target survives but non-actionable or review-only boxes are rendered, `location_status` is `learn_review_boxes_ready` instead of `not_located`; the response also records `review_box_count` and `review_only_overlay_ready` in `path_map_review.summary` and `execution_path`. `statusTextForResponse()` maps that status to `review_boxes_ready`, so the panel no longer reports a useful review overlay as `no_targets`. This does not authorize clicks or promote Runtime PathGraph.

Learning calibration evidence clarification: the panel now exposes whether Learn Deep model/VISTA validation actually ran. Recent AppleMusic `locate-target` traces showed `learn_locate_model_review.enabled=false` and `vista_validation_enabled=false`; those runs can still provide review boxes and overlays, but they are not proof of precise 4B/VISTA calibration. `learningDeepCalibrationEvidenceSummary()` now reports `modelValidationStatus` and `vistaValidationStatus`, and learning-draft observation evidence keeps the coordinate review trace/overlay even when `target_count=0`, with `coordinate_calibration_status=review_overlay_only_model_validation_not_run`.

Learning Interface calibration wiring fix: the unified `Learn current interface` flow now calls the Learn Deep dry-run calibration step before the fused draft trial. The calibration request is forced to `agent_mode=learn`, `learn_depth=deep`, `metadata.learn_all_targets=true`, and uses `lastLearningDraftObserveTracePath` from the current learning screenshot before falling back to the generic observe trace. This repairs the real-flow bug where the UI jumped from two-stage numbering to fusion/page details without running the precise calibration chain, or reused a stale generic trace and reported `no_targets`. It still performs no live click, fill, submit, Execute authorization, or Runtime PathGraph promotion.

Offline AppleMusic chain smoke after this wiring fix: `logs\benchmarks\learning_interface_deep_calibration_chain_smoke_20260711.json` replays saved observe trace `logs\traces\vision\20260710-032439-862225__learn-mode-fast-observe__applemusic.json` through `/panel/run_learning_two_stage_understanding`, `/vision/locate_target` Learn Deep dry-run, `/panel/run_learning_recognition_trial`, `/panel/create_page_detail_candidate`, and `/panel/create_learning_demo_scaffold`. The chain returns success with `deep_calibration.location_status=learn_review_boxes_ready`, `review_box_count=44`, `target_count=0`, draft `regions=32`, page-detail `region_count=32`, and read-only scaffold preview `page_detail_readonly_preview_ready`. The generated overlays are review-only evidence and still require visual self-review; this is not demo-quality proof or Runtime PathGraph readiness.

Three-interface chain smoke now carries the Python.org boundary into the real report. `logs\benchmarks\learning_interface_chain_smoke_three_surface_stress_guard_20260711\learning_interface_chain_smoke_report.json` exercises AppleMusic, QQ, and Python.org through the same backend chain and generates `learning_interface_chain_contact_sheet.png` for visual self-review. AppleMusic and QQ are counted as `review_only_chain_ready`; Python.org is forced to `stress_only_needs_review` with `python_org_stress_sample`, even though its endpoint chain succeeds. This prevents the cleaner historical Python overlays from being counted as a successful model/5.5 recognition baseline. The report still has `runtime_pathgraph_ready_count=0`, no live clicks/fills/submits, and no Execute binding.

Current panel demo sources: `/panel/learning_draft_sources` pins the current three-interface scaffold checkpoint first: AppleMusic, QQ, then Python.org. `logs\benchmarks\learning_panel_demo_load_check_20260711.json` confirms all three load through `/panel/load_learning_draft_review` with source screenshot, fused overlay, page-detail layout, and read-only PathGraph preview present. This is a display/loading check only, not model accuracy, Execute authorization, or Runtime PathGraph readiness.

Panel source-list latency fix: `/panel/learning_draft_sources` now defaults to the current three-interface demo set only, with `include_recent=false`, so old v103/v104/v105 sources do not appear on the demo first screen and the endpoint does not cold-scan historical artifacts. Historical/recent sources remain available through `include_recent=true`. Latest HTTP check: `logs\benchmarks\panel_learning_draft_sources_latency_20260711.json` records default `source_count=3`, `default_current_three_only=true`, and explicit recent scanning as a separate path. This is a panel usability/dataflow fix only; it does not change recognition quality or authorize execution.

Three-interface visual self-review: `artifacts\review-overlays\learning_three_interface_panel_load_contact_sheet_20260711.png` verifies the panel-load path uses fused overlays rather than raw screenshots for AppleMusic / QQ / Python.org. `artifacts\review-overlays\learning_three_interface_page_detail_contact_sheet_20260711.png` verifies page-detail previews render for all three. The self-review report `logs\benchmarks\learning_three_interface_page_detail_visual_check_20260711.json` marks AppleMusic as the best current demo candidate, QQ as a complex protected-layout stress sample, and Python.org as `needs_quality_work_before_demo`. This remains display/review evidence only.

Three-interface archive node: `logs\benchmarks\learning_three_interface_visual_archive_node_20260711.json` consolidates the current panel-load overlay sheet, page-detail sheet, protected-set comparison, source-list latency check, and Learn Deep review-box status smoke into one checkpoint before free exploration. Its status is `pass`, with AppleMusic / QQ / Python.org preserved as display-review baselines. The follow-up readiness gate `logs\benchmarks\learning_exploration_readiness_after_three_interface_archive_20260711.json` reports `ready_for_new_interface_exploration=true`; exploration is allowed only under the same no-click/no-fill/no-submit and anti-pollution constraints.

Checkpoint archive node: `logs\benchmarks\learning_protected_after_structure_quality_archive_fields_20260711.json` records the three protected cases, their overlay/source paths, region/action counts, structure-quality fields, safety boundary, and the anti-pollution command that must be run before exploring a new interface. Use `--checkpoint-id` on `scripts\check_learning_protected_set_review.py` whenever a new protected baseline is created. Use `--baseline <archive report>` to compare the current protected set against a previous node; any case/count/path/structure drift exits nonzero and must be reviewed before testing another interface.

First free-exploration smoke: `logs\benchmarks\learn_explore_chatgpt_prompt_20260711_v2\learn_screenshot_exploration_report_20260711-051905.json` ran a non-protected ChatGPT/Codex screenshot through the screenshot-only path. It was safe but not demo-ready: `exploration_status=no_review_boxes`, `demo_readiness=not_demo_ready`, `numbered=0`, `fused=0`. This confirms screenshot-only exploration is a boundary probe, not a replacement for a real observe trace with OCR/UIA inventory. Protected-set comparison before and after the exploration passed with `mismatch_count=0`.

## 2026-07-10 Learning Interface source-image / overlay separation

The Learning Interface now keeps the captured source screenshot separate from display-only review overlays. Two-stage overlays under `artifacts/review-overlays` are rendered in the Learning Draft screenshot panel, but they are no longer promoted through `setCurrentImage()` into the next learning input path. `learningSourceImagePath` is the source-of-truth for the next recognition trial and Learn Deep dry-run, while fused overlays remain review-only evidence.

Three-surface regression follow-up: `scripts\run_learn_two_stage_replay.py` now records `observe_bundle`, `source_image_status`, `overlay_status`, and `model_grounding_evidence` in replay reports. This makes stale screenshot evidence explicit and prevents recommendation-only model names from being mistaken for actual model-grounding proof.

Current three-surface regression output: `logs\benchmarks\learn_three_surface_regression_20260710_v5`.

- AppleMusic: source image available, overlay available, `stage1_gate=passed`, `stage2_numbering_skipped=false`, `numbered=31`, `fused=44`, page detail `regions=37`, `sections=3`, read-only PathGraph preview ready. `model_grounding_evidence.status=not_valid_for_model_grounding_evidence` because no structure region records an actual model-grounding attempt.
- QQ: source image available, overlay available, `stage1_gate=passed`, `stage2_numbering_skipped=false`, `numbered=94`, `fused=109`, page detail `regions=95`, `sections=6`, read-only PathGraph preview ready. Visual self-review keeps QQ as review-only because message bubble/card hierarchy is still fragmented. `model_grounding_evidence.status=not_valid_for_model_grounding_evidence`.
- Python.org: source image is supplied through explicit `--source-image` override, overlay available, `stage1_gate=passed`, `stage2_numbering_skipped=false`, `numbered=124`, `fused=148`, page detail `regions=37`, `sections=4`, read-only PathGraph preview ready. This is a valid current visual regression sample, but not a model-grounding pass: `model_grounding_evidence.status=not_valid_for_model_grounding_evidence`, `model_grounding_attempted_count=0`, and `model_call_plan_is_recommendation_only=true`.

Historical Python clarification: older v92/v97 Python.org overlays looked cleaner mostly because heuristic cleanup and display suppression hid some noisy boxes. They remain useful protected-set visual-regression references, but they must not be described as 5.5 model accuracy, point-grounding success, or Runtime PathGraph readiness unless a future report records actual per-region model grounding attempts with coordinate evidence.

Protected review-set check: run `uv run python scripts\check_learning_protected_set_review.py --out logs\benchmarks\learning_protected_set_review_latest.json --json` before and after Learning Mode recognition/layout changes. It verifies the current AppleMusic / QQ / Python.org scaffold sources load with review overlays, page details, and read-only PathGraph region/action refs, while explicitly keeping the result as display/review evidence rather than model accuracy or Runtime PathGraph promotion. Latest report: `logs\benchmarks\learning_protected_set_review_latest.json`; archived checkpoint: `logs\benchmarks\learning_protected_set_checkpoint_20260711_display_review.json`. New-interface exploration must rerun this protected check before and after strategy changes.

Stage1 gate was also adjusted for small lower-edge system-border slack. The adjacent-partition invariant still requires `main_content` to cover the visible lane, but a tiny bottom remainder such as the AppleMusic 28px window/system edge is recorded as `main_content_lower_edge_within_system_border_tolerance` instead of blocking Stage2 before numbering.

Follow-up root-cause fix: the two-stage endpoint now persists `learn_all_targets.review_boxes` into the saved `trial_result.json`, not only into the immediate API response. This repairs the real panel flow where Stage1/Stage2 could succeed, but the saved artifact and subsequent draft evidence still looked like `no_targets`.

Page-detail source fix: the Learning Interface now remembers the current two-stage report path for the active run and uses it as the preferred source when creating the display-only page-detail candidate. The second draft trial still loads the flattened learning draft for review, but page details and the read-only PathGraph preview are generated from the richer two-stage structure/fusion report instead of losing section/parent information.

Current-run source priority fix: page-detail generation now prefers `lastLearningTwoStageReportPath` before older `learningPathGraphCandidatePath` / `learningDetailObserveCandidatePath` fields. This prevents an old PathGraph/detail-observe candidate from overriding the current screenshot's two-stage evidence after a new learning run.

Real-flow preservation fix: the second draft-generation pass after Stage1/Stage2 now preserves `lastLearningTwoStageReportPath` while still clearing stale draft artifacts. Previously `runLearningDraftTrial()` cleared that path unconditionally, so page-detail and read-only PathGraph generation could fall back to the flattened draft or an older candidate even though the backend had saved fused review boxes.

Panel API chain regression: `logs\benchmarks\learn_panel_api_chain_regression_20260710_v2\panel_api_chain_summary.json` reruns the real panel endpoint chain for AppleMusic, QQ, and Python.org: `run_learning_two_stage_understanding` -> `create_page_detail_candidate` -> `create_learning_demo_scaffold`. AppleMusic produced `44` review boxes / `37` page-detail regions / `3` sections; QQ produced `109` review boxes / `95` regions / `6` sections; Python.org produced `148` review boxes / `37` regions / `4` sections. Python.org uses an explicit `source_image_path` override because the historical observe trace references a missing screenshot. The override is recorded in the saved report and is not a silent fallback or model-grounding proof.

Status wording fix: the panel status chip no longer labels two-stage review-only output as `no_targets` merely because it has zero executable targets. `blocked_before_stage2_numbering` is shown as `stage1_blocked`; successful two-stage review boxes are shown as `review_boxes_ready`. This keeps learning-mode display evidence separate from Execute-target readiness.

Verification:

- `node --check app\web_panel\panel.js`: passed.
- `uv run pytest tests/test_run_learn_two_stage_replay.py -q`: 7 passed.
- `uv run python -m py_compile scripts\run_learn_two_stage_replay.py`: passed.
- `uv run pytest tests/test_learn_stage1_region_selection_audit.py -q`: 5 passed.
- `uv run pytest tests/test_web_panel_route.py::test_learning_interface_keeps_display_overlay_out_of_source_image_path tests/test_web_panel_route.py::test_panel_api_response_result_helper_preserves_two_stage_gate_data -q`: 2 passed.
- `uv run pytest tests/test_web_panel_route.py::test_panel_status_text_does_not_label_two_stage_review_boxes_as_no_targets tests/test_web_panel_route.py::test_panel_api_response_result_helper_preserves_two_stage_gate_data -q`: 2 passed.
- `uv run pytest tests/test_web_panel_route.py::test_panel_two_stage_endpoint_returns_review_boxes_for_real_learning_flow -q`: passed.
- `uv run pytest tests/test_web_panel_route.py::test_learning_interface_flow_has_unified_progress_and_simple_review_surface -q`: passed for the two-stage page-detail source preference.
- `uv run pytest tests/test_web_panel_route.py::test_panel_status_text_does_not_label_two_stage_review_boxes_as_no_targets tests/test_web_panel_route.py::test_learning_interface_flow_has_unified_progress_and_simple_review_surface tests/test_web_panel_route.py::test_panel_two_stage_endpoint_returns_review_boxes_for_real_learning_flow -q`: 3 passed.
- `uv run pytest tests/test_web_panel_route.py::test_learning_draft_panel_renders_open_detail_transition_hints -q`: passed for current two-stage report priority over stale candidate paths.
- Three-surface v5 replay generated current overlays and page-detail / read-only PathGraph previews under `logs\benchmarks\learn_three_surface_regression_20260710_v5`. All three reports explicitly mark `model_grounding_evidence.status=not_valid_for_model_grounding_evidence`, so these screenshots are display regression evidence, not model accuracy, 5.5 accuracy, or complete VISTA/4B grounding evidence.
- Direct AppleMusic source comparison: flattened draft page detail was `source_shape=learning_template_draft_v1`, `sections=2`; rebuilding from `artifacts\learning-runs\panel_20260710-032446-473_applemusic\trial_result.json` produces `source_shape=learn_two_stage_screen_understanding_v1`, `regions=37`, `sections=3`, and read-only PathGraph preview `page_detail_readonly_preview_ready`.
- AppleMusic failed-run replay through `/panel/run_learning_two_stage_understanding` using raw source `artifacts\screenshots\apple-music__observe-screen__applemusic__full-window__20260710-025330-992572.png`: `stage1_gate=passed`, `stage2_numbering_skipped=false`, generated overlay `artifacts\review-overlays\apple-music__observe-screen__applemusic__full-window__20260710-025330-992572__two-stage-understanding__20260710-030357-565581.png`.
- Real panel service was restarted so port `8000` serves the new backend contract. Live smoke on raw source `artifacts\screenshots\apple-music__observe-screen__applemusic__full-window__20260710-030736-913719.png` generated `artifacts\learning-runs\panel_20260710-031524-222_applemusic\trial_result.json` with `stage1_gate=passed`, `stage2_numbering_skipped=false`, and persisted `learn_all_targets.review_box_count=33`. The next `/panel/run_learning_recognition_trial` generated `artifacts\learning-runs\panel_20260710-031553-941_applemusic\trial_result.json` with `screen_inventory_count=25` and `learning_draft.regions=25`.

Boundary: display/review-only dataflow and gate fix. No live click, fill, submit, Execute authorization, Runtime PathGraph promotion, or recognition-accuracy claim.

## 2026-07-10 Learning Interface v92-style Stage2 default restored

The Learning Interface panel now defaults back to the v92-style `stage2_region_strategy=partitioned` path. This preserves the protected AppleMusic strategy: complete Stage1 structure bars, direct numbering for top/sidebar bars, primary/main-content card grouping, and parent-child display demotion so child evidence does not visually compete with card/group parents.

`global_no_partition` remains available as a backend diagnostic strategy, but it is not the normal panel path because the comparison run surfaced more items while fragmenting main media-card grouping.

Partition stability guard: Stage1.5 partitions are candidates, not unconditional truth. Only contained `main_content` subregions are eligible to replace Stage2 input regions. Top/sidebar/bottom structure bars cannot be replaced by Stage1.5 partitions, and rejected partitions are recorded in `stage1_5_partition.stage2_selection`.

Stage1 tiling fix: horizontal bars now preserve the full visual bar bbox instead of shrinking to the non-sidebar lane. Sidebars are partitioned below the top bar, and main content expands to the remaining visible lane including empty space before Stage2 numbering. This keeps top-bar buttons from being excluded by sibling-sidebar partitioning while still enforcing non-overlapping sibling structure regions.

PathGraph/page-detail preview geometry fix: the read-only PathGraph page detail preview now renders spatial boxes at the same scaled bbox size as the recognition/page-detail source. The panel no longer forces minimum `6-8%` preview widths/heights or CSS pixel minimums for these boxes, so small top/sidebar controls stay small instead of being inflated into large cards.

Verification:

- `uv run pytest tests/test_web_panel_route.py::test_learning_interface_flow_has_unified_progress_and_simple_review_surface -q`: passed.
- `node --check app\web_panel\panel.js`: passed.
- `uv run python -m py_compile app\api\panel.py app\learn\recognition\two_stage.py`: passed.
- `uv run pytest tests/test_learn_recognition_pipeline.py::test_stage1_5_stage2_selection_only_accepts_contained_main_content_subregions tests/test_learn_recognition_pipeline.py::test_stage2_input_ignores_unstable_stage1_5_partition_for_structure_bars tests/test_learn_recognition_pipeline.py::test_two_stage_global_no_partition_numbers_items_on_full_screen_canvas -q`: passed.
- `uv run pytest tests/test_learn_recognition_pipeline.py::test_stage1_topbar_preserves_full_width_and_sidebars_start_below_it tests/test_learn_stage1_region_selection_audit.py -q`: passed.
- `node --check app\web_panel\panel.js` and `uv run pytest tests/test_web_panel_route.py::test_learning_draft_panel_renders_open_detail_transition_hints -q`: passed for the no-inflated-preview geometry guard.
- AppleMusic observe trace replay through `/panel/run_learning_two_stage_understanding`: `stage2_region_strategy=partitioned`, input regions `3`, left/top bars use direct numbering, primary area uses `primary_region_homogeneous_grouping_with_visual_card_segmenter`.
- Served panel asset probe on `127.0.0.1:8000` reports `served_panel_js=partitioned`.

Boundary: display/review-only behavior. No live click, fill, submit, Execute authorization, Runtime PathGraph promotion, or recognition-accuracy claim.

## 2026-07-09 Learning Draft preview resize fix

The Learning Draft PathGraph preview no longer stays trapped in a quarter-width area. `learningDraftPathGraphPanel` now spans the full learning-draft workspace width, and the PathGraph map / interface-detail columns have a draggable splitter with a reset button. The split ratio is saved in local storage and can also be adjusted by keyboard on the splitter.

Verification:

- `node --check app\web_panel\panel.js`: passed.
- `uv run pytest tests\test_web_panel_route.py::test_learning_interface_flow_has_unified_progress_and_simple_review_surface -q`: passed.
- Live panel asset probe on `127.0.0.1:8000` confirms the served HTML/CSS/JS include `learningDraftPathResizer`, `learningDraftPathLayoutResetBtn`, `bindLearningDraftPathResize`, and the full-width CSS.

Boundary: this is a panel layout/display usability fix only. It does not change learning recognition, Execute, model calls, live clicks, fills, submits, or Runtime PathGraph promotion.

## 2026-07-09 Real Learning Interface two-stage flow wiring

The Learning Interface button now runs the Stage1 region gate + two-stage numbering path in the real panel flow instead of only in offline replay. After `/vision/observe_screen`, the panel calls `POST /panel/run_learning_two_stage_understanding`, requires the Stage1 adjacent-partition gate to pass, forwards the fused `review_boxes` / `compiled_overlay_path` into `POST /panel/run_learning_recognition_trial`, and then builds the display-only page details / PathGraph draft from that fused evidence.

Evidence from a real endpoint smoke using the AppleMusic observe trace `logs\traces\vision\20260709-223115-875267__learn-mode-fast-observe__applemusic.json`:

- Stage1 gate: `passed`
- Stage2 skipped: `false`
- Review boxes forwarded: `42`
- Overlay generated by the real panel endpoint: `artifacts\review-overlays\apple-music__observe-screen__applemusic__full-window__20260709-223051-047459__two-stage-understanding__20260709-232354-668517.png`
- Saved report: `artifacts\learning-runs\panel_20260709-232354-720_applemusic\trial_result.json`

Verification:

- `uv run pytest tests\test_web_panel_route.py::test_learning_interface_flow_has_unified_progress_and_simple_review_surface tests\test_web_panel_route.py::test_panel_two_stage_endpoint_returns_review_boxes_for_real_learning_flow tests\test_web_panel_route.py::test_web_panel_serves_static_assets -q`: 3 passed.
- `uv run python -m py_compile app\api\panel.py`: passed.
- `node --check app\web_panel\panel.js`: passed.
- Panel server restarted on port `8000`; `/panel/assets/panel.js` now includes `/panel/run_learning_two_stage_understanding`.

Boundary: this wires the existing rules into the actual display-only learning flow. It does not claim recognition accuracy, demo-quality page details, Execute readiness, Runtime PathGraph promotion, live clicks, fills, submits, or E2E stability.

## 2026-07-09 Page-detail/scaffold overlay display fix

The panel screenshot still showed raw screenshots after completing Learning Interface because `learn_page_detail_candidate_v1` and `learn_mode_demo_scaffold_v1` sources lost their overlay paths when synthesized into a review draft. `app\learn\draft_review.py` now copies `compiled_overlay_path` and `full_screen_understanding_overlay_path` from page-detail candidates into `draft.page_details.precise_understanding_fusion_status` and `draft.page_details.screen`, so `screen_understanding_preview.compiled_overlay_path` is available for both direct page-detail and scaffold loads.

Regression: `tests\test_learning_draft_review.py::test_direct_page_detail_and_scaffold_sources_load_as_review_only` now asserts both direct page-detail and scaffold review loads expose overlay paths.

Verification:

- `uv run pytest tests\test_learning_draft_review.py::test_direct_page_detail_and_scaffold_sources_load_as_review_only -q`: passed.
- `uv run python -m py_compile app\learn\draft_review.py`: passed.
- Real artifact probe for `artifacts\learning-runs\panel_20260709-224454-531_applemusic\learn_page_detail_candidate.json` and `learn_mode_demo_scaffold.json` returns non-empty `screen_understanding_preview.compiled_overlay_path`.
- Panel server restarted on port 8000 after the backend fix.

Boundary: this is a display/dataflow fix only; it does not claim recognition quality, Execute readiness, Runtime PathGraph promotion, live clicks, fills, submits, or E2E stability.


## 2026-07-09 Stage1 adjacent partition rule

User-added invariant: Stage1 structure bars must form adjacent page partitions before Stage2 item numbering. Empty visible space belongs to a structure region; Stage1 must not shrink `main_content` to only the visible card/text cluster. Content boxes can be children of a bar, but cannot redefine the bar bbox.

Implemented in `app\learn\recognition\stage1_audit.py`:

- `main_content` must be adjacent to the left boundary / left sidebar.
- `main_content` must start at the top-bar bottom boundary.
- `main_content` must cover the right empty visible area until the right boundary / right sidebar.
- `main_content` must cover the lower empty visible area until the bottom boundary / bottom bar.
- Failure categories include `main_content_not_adjacent_to_left_boundary`, `main_content_not_adjacent_to_top_boundary`, `main_content_does_not_cover_right_empty_area`, and `main_content_does_not_cover_lower_empty_area`.

Verification:

- `uv run pytest tests\test_learn_stage1_region_selection_audit.py tests\test_web_panel_route.py::test_learning_interface_flow_has_unified_progress_and_simple_review_surface tests\test_learn_page_detail_candidate.py::test_page_detail_candidate_preserves_panel_trial_overlay_and_screenshot -q`: 6 passed.
- `uv run python -m py_compile app\learn\recognition\stage1_audit.py app\api\panel.py scripts\build_learn_page_detail_candidate.py`: passed.
- `node --check app\web_panel\panel.js`: passed.

AppleMusic `223051` Stage1 gate replay with the new rule produces adjacent regions: left nav `x=0,w=92`, top bar `x=92,y=0,w=1062,h=90`, primary area `x=92,y=90,w=1062,h=911`. Overlay: `artifacts\review-overlays\apple-music__observe-screen__applemusic__full-window__20260709-223051-047459__two-stage-understanding__20260709-224339-991446.png`.

Runtime note: the real panel did not show boxes because the running uvicorn process was still serving old code. The panel server was restarted on port `8000`; replaying the real `223131` request now saves `coordinate_overlay_path` into `trial_result.json` and `learn_page_detail_candidate.json`. Evidence: `artifacts\learning-runs\panel_20260709-224454-531_applemusic\trial_result.json` and `artifacts\learning-runs\panel_20260709-224454-531_applemusic\learn_page_detail_candidate.json`.

Boundary: this is a Stage1 gating/dataflow fix, not recognition accuracy, not demo-quality, not Runtime PathGraph readiness, and not Execute authorization.


## Learn Mode completion overlay/dataflow patch (2026-07-09)

Follow-up to the no-target completion checkpoint: the Learning Interface now reruns the learning draft after Learn Deep calibration even when `targets=0`, so `review_boxes` and the calibration overlay feed the final page-detail/scaffold artifacts instead of falling back to the first coarse trial. The screenshot panel also prefers generated overlay paths (`compiled_overlay_path` / `full_screen_understanding_overlay_path`) before raw screenshots.

AppleMusic offline replay from the latest Learn Deep trace now produces `trial_screen_inventory=39`, `trial_draft_regions=32`, `trial_review_box_count=40`, `page_region_count=32`, `page_section_count=2`, and a scaffold with `page_detail_readonly_pathgraph_preview_region_count=32`. Evidence: `artifacts\learning-runs\panel_20260709-222255-345_applemusic\trial_result.json`, `artifacts\learning-runs\panel_20260709-222255-345_applemusic\learn_page_detail_candidate.json`, `artifacts\learning-runs\panel_20260709-222255-345_applemusic\learn_page_detail_candidate_preview.png`, and `artifacts\review-overlays\state-ffea69272db08b1d-learn-targets__learn-target-coordinates__20260709-221039-477732.png`.

This fixes stale/no-box rendering after completion and preserves the calibration evidence in page-detail output. The page-detail layout still needs quality refinement and remains review/display-only: no models were started for the replay, no live click/fill/submit occurred, no Execute authorization or Runtime PathGraph promotion is implied, and no recognition accuracy or E2E stability claim is made.


## Learn Mode panel flow completion checkpoint (2026-07-09)

Latest checkpoint: the Learning Interface flow no longer stops when Learn Deep calibration returns `no actionable targets`. The panel now treats `targets=0` as a safe display-only branch: it keeps the calibration overlay visible, then continues to generate a `learn_page_detail_candidate_v1` and a `learn_mode_demo_scaffold_v1` so the Learning Draft page can show screenshot boxes, template-like page details, and a read-only PathGraph preview.

Verification against the latest failing AppleMusic panel run:

- source trial: `artifacts\learning-runs\panel_20260709-213518-851_applemusic\trial_result.json`
- page detail candidate: `logs\benchmarks\learn_panel_flow_completion_fix_applemusic_page_detail\learn_page_detail_candidate.json`
- preview: `logs\benchmarks\learn_panel_flow_completion_fix_applemusic_page_detail\learn_page_detail_candidate_preview.png` (`16` regions / `2` sections)
- scaffold: `logs\benchmarks\learn_panel_flow_completion_fix_applemusic_scaffold\learn_mode_demo_scaffold.json`, with `page_detail_readonly_pathgraph_preview_status=page_detail_readonly_preview_ready`, `page_detail_pathgraph_shared_section_count=2`, and `failure_count=0`.

GPT visual audit is saved at `artifacts\chatgpt_reports\stage2_panel_flow_completion_fix_audit_result.json`: reviewer verdict `CONDITIONAL PASS for panel-flow fix only`. GPT agrees `targets=0` should mean no Execute candidate, not no visual evidence, and that display-only page-detail/scaffold generation may continue. GPT also flags the current AppleMusic page-detail preview as not demo-quality yet: section naming is generic, the right-detail panel is unnatural for AppleMusic, and main media-card structure is incomplete.

This is still review/display-only. It does not start models, click, fill, submit, authorize Execute, promote Runtime PathGraph, or prove recognition accuracy / E2E stability. The full `tests\test_web_panel_route.py` run still has two unrelated SEEK fixture failures because `artifacts\screenshots\jobs-in-all-new-zealand-seek-3-microsoft-edge__capture__full-window__20260702-235058-876442.png` is missing.

## Learn Mode footer connector checkpoint (2026-07-09)

Latest checkpoint: v105 adds a low-emphasis display-only connector for detached semantic list footers. v104 kept Python.org `>>More` semantically attached while preventing it from stretching the list-group bbox; v105 makes that detached relationship visible in the page-detail preview without changing Execute, Gate, model prompts, or Runtime PathGraph behavior.

Protected-set evidence:

- Python.org: `logs\benchmarks\learn_two_stage_python_v105_footer_connector\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_python_v105_footer_connector\learn_page_detail_candidate_preview.png`, scaffold `logs\benchmarks\learn_two_stage_python_v105_readonly_pathgraph_scaffold\learn_mode_demo_scaffold.json`. The preview reports `footer_connector_count=1`.
- AppleMusic: `logs\benchmarks\learn_two_stage_applemusic_v105_footer_connector\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_applemusic_v105_footer_connector\learn_page_detail_candidate_preview.png`, scaffold `logs\benchmarks\learn_two_stage_applemusic_v105_readonly_pathgraph_scaffold\learn_mode_demo_scaffold.json`. The preview reports `footer_connector_count=0`.
- QQ: `logs\benchmarks\learn_two_stage_qq_v105_footer_connector\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_qq_v105_footer_connector\learn_page_detail_candidate_preview.png`, scaffold `logs\benchmarks\learn_two_stage_qq_v105_readonly_pathgraph_scaffold\learn_mode_demo_scaffold.json`. The preview reports `footer_connector_count=0`.

The Learning Draft source picker now pins these three v105 demo scaffolds first. GPT visual audit is saved at `artifacts\chatgpt_reports\stage2_v105_footer_connector_audit_result.json`: overall `CONDITIONAL PASS`; Python.org `CONDITIONAL PASS` because the connector clarifies `>>More` without re-bloating the right list-group bbox; AppleMusic `PASS`; QQ `CONDITIONAL PASS` with no obvious connector pollution.

This is still review/display-only. It does not start models, click, fill, submit, authorize Execute, promote Runtime PathGraph, or prove recognition accuracy / E2E stability.

## Learn Mode footer bbox tightening checkpoint (2026-07-09)

Latest checkpoint: v104 tightens v103's display-only list-footer behavior. A footer can still attach semantically as `list_group_footer`, but if it is horizontally detached from the row column, it no longer stretches the visible list-group parent frame. The builder records `footer_bbox_policy=semantic_attachment_no_bbox_expand` and `bbox_expanded=false`.

Protected-set evidence:

- Python.org: `logs\benchmarks\learn_two_stage_python_v104_footer_bbox_tightening\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_python_v104_footer_bbox_tightening\learn_page_detail_candidate_preview.png`, scaffold `logs\benchmarks\learn_two_stage_python_v104_readonly_pathgraph_scaffold\learn_mode_demo_scaffold.json`. The right event list group tightened from v103 `w=539/h=312` to v104 `w=310/h=198`; `>>More` remains semantically attached but review-only.
- AppleMusic: `logs\benchmarks\learn_two_stage_applemusic_v104_footer_bbox_tightening\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_applemusic_v104_footer_bbox_tightening\learn_page_detail_candidate_preview.png`, scaffold `logs\benchmarks\learn_two_stage_applemusic_v104_readonly_pathgraph_scaffold\learn_mode_demo_scaffold.json`.
- QQ: `logs\benchmarks\learn_two_stage_qq_v104_footer_bbox_tightening\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_qq_v104_footer_bbox_tightening\learn_page_detail_candidate_preview.png`, scaffold `logs\benchmarks\learn_two_stage_qq_v104_readonly_pathgraph_scaffold\learn_mode_demo_scaffold.json`.

The Learning Draft source picker now pins these three v104 demo scaffolds first. GPT visual audit is saved at `artifacts\chatgpt_reports\stage2_v104_footer_bbox_tightening_audit_result.json`: overall `CONDITIONAL PASS`; Python.org `CONDITIONAL PASS`; AppleMusic `PASS`; QQ no obvious footer/list pollution.

This is still review/display-only. It does not start models, click, fill, submit, authorize Execute, promote Runtime PathGraph, or prove recognition accuracy / E2E stability.

## Learn Mode list-footer parentage checkpoint (2026-07-09)

Latest checkpoint: v103 adds a display-only list-footer association layer to the Learning Mode page-detail path. Compact footer/link-like regions such as `More / See all / View all / 更多` can attach to the nearest same-section `list_group` when they sit just below that group. Attached regions are marked `parent_display_group_role=list_group_footer`, and display groups record `footer_region_numbers` / `footer_region_ids`.

Protected-set evidence:

- Python.org: `logs\benchmarks\learn_two_stage_python_v103_list_footer_parentage\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_python_v103_list_footer_parentage\learn_page_detail_candidate_preview.png`, scaffold `logs\benchmarks\learn_two_stage_python_v103_readonly_pathgraph_scaffold\learn_mode_demo_scaffold.json`. The `>>More` region is now attached to the right event list group.
- AppleMusic: `logs\benchmarks\learn_two_stage_applemusic_v103_list_footer_parentage\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_applemusic_v103_list_footer_parentage\learn_page_detail_candidate_preview.png`, scaffold `logs\benchmarks\learn_two_stage_applemusic_v103_readonly_pathgraph_scaffold\learn_mode_demo_scaffold.json`.
- QQ: `logs\benchmarks\learn_two_stage_qq_v103_list_footer_parentage\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_qq_v103_list_footer_parentage\learn_page_detail_candidate_preview.png`, scaffold `logs\benchmarks\learn_two_stage_qq_v103_readonly_pathgraph_scaffold\learn_mode_demo_scaffold.json`.

The Learning Draft source picker now pins these three v103 demo scaffolds first, so the latest review artifacts can be loaded directly in the panel. GPT visual audit is saved at `artifacts\chatgpt_reports\stage2_v103_list_footer_parentage_audit_result.json`: overall `CONDITIONAL PASS`; Python.org `CONDITIONAL PASS`; AppleMusic `PASS`; QQ `CONDITIONAL PASS`.

This is still review/display-only. It does not start models, click, fill, submit, authorize Execute, promote Runtime PathGraph, or prove recognition accuracy / E2E stability.

## Learn Mode read-only PathGraph scaffold checkpoint (2026-07-09)

Latest checkpoint: v102 connects existing `learn_page_detail_candidate_v1` artifacts to a display-only PathGraph preview. `scripts\build_learn_demo_scaffold.py` now synthesizes `page_detail_readonly_pathgraph_preview_v1` for direct page-detail sources, carries `layout.display_groups` into the preview, and reports shared section/group correspondence. `app\web_panel\panel.js` renders this read-only preview separately from model-only preview, so loading a page-detail scaffold can show the template-like interface detail and a matching non-executable PathGraph preview.

Protected-set scaffold evidence:

- Python.org: `logs\benchmarks\learn_two_stage_python_v102_readonly_pathgraph_scaffold\learn_mode_demo_scaffold.json` (`42` regions / `4` sections / `2` display groups / `4` shared sections / `2` shared groups).
- AppleMusic: `logs\benchmarks\learn_two_stage_applemusic_v102_readonly_pathgraph_scaffold\learn_mode_demo_scaffold.json` (`46` regions / `3` sections / `0` display groups / `3` shared sections).
- QQ: `logs\benchmarks\learn_two_stage_qq_v102_readonly_pathgraph_scaffold\learn_mode_demo_scaffold.json` (`91` regions / `6` sections / `0` display groups / `6` shared sections).

GPT visual audit is saved at `artifacts\chatgpt_reports\stage2_v102_readonly_pathgraph_scaffold_audit_result.json` and was DOM-verified with the v102 token plus 3 image attachments. Reviewer verdict: overall `CONDITIONAL PASS`; AppleMusic remains acceptable, Python.org list/hero/header details and QQ notice/member/message hierarchy remain review-only. GPT allows the wording `display-only page-detail / readonly PathGraph preview scaffold connected`.

This is still review/display-only. It does not start models, click, fill, submit, authorize Execute, promote Runtime PathGraph, or prove recognition accuracy / E2E stability.

## Learn Mode page-detail list-group checkpoint (2026-07-09)

Latest checkpoint: v101 adds display-only list-group parent frames to the Learning Mode page-detail path. `scripts\build_learn_page_detail_candidate.py` now emits `layout.display_groups` when same-parent `list_row` regions align into list columns. The preview renderer and panel mini-map draw those groups as blue parent frames, so Python.org `Latest News` / `Upcoming Events` rows have a clearer section/list-row relationship without changing Execute, Gate, model prompts, or Runtime PathGraph promotion.

Protected-set preview evidence:

- Python.org: `logs\benchmarks\learn_two_stage_python_v101_page_detail_list_groups\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_python_v101_page_detail_list_groups\learn_page_detail_candidate_preview.png` (`42` regions / `4` sections / `2` list groups).
- AppleMusic: `logs\benchmarks\learn_two_stage_applemusic_v101_page_detail_list_groups\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_applemusic_v101_page_detail_list_groups\learn_page_detail_candidate_preview.png` (`46` regions / `3` sections).
- QQ: `logs\benchmarks\learn_two_stage_qq_v101_page_detail_list_groups\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_qq_v101_page_detail_list_groups\learn_page_detail_candidate_preview.png` (`91` regions / `6` sections).

GPT visual audit is saved at `artifacts\chatgpt_reports\stage2_v101_page_detail_list_groups_audit_result.json` and was DOM-verified with 3 images. Reviewer verdict: overall `CONDITIONAL PASS`; AppleMusic `PASS`; Python.org `CONDITIONAL PASS`; QQ `CONDITIONAL PASS`. GPT agrees v101 can be a staged regression result for display-only `page_details` / read-only PathGraph preview, while keeping Python topbar/Hero text and QQ notice/member/message hierarchy review-only. No accuracy, E2E success, Execute authorization, Runtime PathGraph executable, live fill, live click, or live submit claim is made.

The v101 page-detail candidates were also wrapped into review-only demo scaffolds under `logs\benchmarks\learn_two_stage_python_v101_demo_scaffold`, `logs\benchmarks\learn_two_stage_applemusic_v101_demo_scaffold`, and `logs\benchmarks\learn_two_stage_qq_v101_demo_scaffold`. A TestClient probe against `/panel/learning_draft_sources` finds all six v101 sources (`recent_learning_page_detail` and `recent_learning_demo_scaffold`) with Execute disabled and not authorization artifacts.

## Learn Mode page-detail overlap cleanup checkpoint (2026-07-09)

Latest checkpoint: v99 adds a display-only sibling-panel overlap cleanup in `scripts\build_learn_page_detail_candidate.py`. The rule applies before page-detail sections are rendered: when same-section Hero sibling panels have no containment relationship but overlap as peers, the later/right panel is clipped away from the left panel and records `evidence.page_detail_collision_resolution.status=clipped_sibling_overlap`. This fixes the Python.org page-detail preview case where `hero_code_panel` and `hero_text_panel` were still visually pressing into each other. It does not alter Execute, Gate, live clicking, model prompts, or Runtime PathGraph promotion.

Protected-set preview evidence:

- Python.org: `logs\benchmarks\learn_two_stage_python_v99_page_detail_overlap_cleanup\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_python_v99_page_detail_overlap_cleanup\learn_page_detail_candidate_preview.png` (`42` regions / `4` sections).
- AppleMusic: `logs\benchmarks\learn_two_stage_applemusic_v99_page_detail_overlap_cleanup\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_applemusic_v99_page_detail_overlap_cleanup\learn_page_detail_candidate_preview.png` (`46` regions / `3` sections).
- QQ: `logs\benchmarks\learn_two_stage_qq_v99_page_detail_overlap_cleanup\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_qq_v99_page_detail_overlap_cleanup\learn_page_detail_candidate_preview.png` (`91` regions / `6` sections).

GPT visual audit is saved at `artifacts\chatgpt_reports\stage2_v99_page_detail_overlap_audit_result.json` and was DOM-verified with 3 images. Reviewer verdict: overall `CONDITIONAL PASS`; Python.org `CONDITIONAL PASS` with Hero sibling overlap basically resolved, AppleMusic `PASS`, QQ `CONDITIONAL PASS`. GPT allows continuing into display-only `page_details` / read-only PathGraph preview integration with review-only labels. Remaining generic work: clarify list/section parents, keep background/review-only frames visually low-weight, and preserve protected-set reruns. No accuracy, E2E success, Execute authorization, Runtime PathGraph executable, live fill, live click, or live submit claim is made.

The v99 page-detail candidates were also wrapped into review-only demo scaffolds under `logs\benchmarks\learn_two_stage_python_v99_demo_scaffold`, `logs\benchmarks\learn_two_stage_applemusic_v99_demo_scaffold`, and `logs\benchmarks\learn_two_stage_qq_v99_demo_scaffold`. A TestClient probe against `/panel/learning_draft_sources` finds all six v99 sources (`recent_learning_page_detail` and `recent_learning_demo_scaffold`) with `learning_demo_scaffold_page_detail_ready=true`, `execute_binding_enabled=false`, and `artifact_is_authorization=false`.

## Learn Mode page-detail scaffold checkpoint (2026-07-09)

Latest checkpoint: v98 page-detail candidates now use the v97 fused review boxes as the source of truth, so detail-only/model-text artifacts stay out of the visible page-detail region list while trusted visual cards and section parents remain. The generated page-detail preview keeps section positions aligned with the same bar/region buckets used by the learning overlay. Evidence:

- AppleMusic page detail: `logs\benchmarks\learn_two_stage_applemusic_v98_page_detail_sections\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_applemusic_v98_page_detail_sections\learn_page_detail_candidate_preview.png`, scaffold `logs\benchmarks\learn_two_stage_applemusic_v98_demo_scaffold\learn_mode_demo_scaffold.json` (`46` regions / `3` sections).
- QQ page detail: `logs\benchmarks\learn_two_stage_qq_v98_page_detail_sections\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_qq_v98_page_detail_sections\learn_page_detail_candidate_preview.png`, scaffold `logs\benchmarks\learn_two_stage_qq_v98_demo_scaffold\learn_mode_demo_scaffold.json` (`91` regions / `6` sections).
- Python.org page detail: `logs\benchmarks\learn_two_stage_python_v98_page_detail_sections\learn_page_detail_candidate.json`, preview `logs\benchmarks\learn_two_stage_python_v98_page_detail_sections\learn_page_detail_candidate_preview.png`, scaffold `logs\benchmarks\learn_two_stage_python_v98_demo_scaffold\learn_mode_demo_scaffold.json` (`42` regions / `4` sections).

GPT visual audit is saved at `artifacts\chatgpt_reports\stage2_v98_page_detail_sections_gpt_audit_result.json`: AppleMusic `PASS`, QQ `CONDITIONAL PASS`, Python.org `CONDITIONAL PASS`. The follow-up page-detail/path-preview audit is saved at `artifacts\chatgpt_reports\stage2_v98_page_detail_preview_gpt_audit_result.json` and was DOM-verified with 3 images: AppleMusic `PASS`, QQ `CONDITIONAL PASS`, Python.org `CONDITIONAL PASS`; GPT allows continuing into panel `page_details` / read-only PathGraph preview only as display-only/review-only evidence. `scripts\build_learn_demo_scaffold.py` can now directly load an existing `learn_page_detail_candidate_v1` as a review-only source; the non-applicable precise/current-evidence steps are reported as skipped rather than failures, and `display_readiness.pathgraph_detail_can_show_page_detail=true`. This is still display/review-only: no model start, no live click/fill/submit, no Execute authorization, no Runtime PathGraph promotion, and no recognition-accuracy or E2E claim.

The panel source picker now includes recent `logs\benchmarks\**\learn_page_detail_candidate.json` and `logs\benchmarks\**\learn_mode_demo_scaffold.json` entries as review-only history sources. Direct page-detail/scaffold sources synthesize a minimal display-only draft so the Learning Draft panel can load their screenshot/detail/path preview metadata without requiring a raw model trial file. The picker displays `source_category=recent_learning_page_detail` / `source_category=recent_learning_demo_scaffold` plus `[Page detail]` / `[Demo scaffold]` badges so these review sources are not confused with raw learning drafts. The current API probe finds all six v98 AppleMusic / QQ / Python.org page-detail and scaffold sources with `page_detail_ready=true`, `execute_binding_enabled=false`, and `artifact_is_authorization=false`.

## Learn Mode recognition checkpoint (2026-07-09)

Latest checkpoint: v97 display-hierarchy cleanup reduces Python.org full-screen overlay clutter while preserving the AppleMusic and QQ protected interfaces. The generic rule is source-aware: ungrouped review regions and model-labeled text cards (`news_card` / `recommendation_item` from `structure_region_item`) remain available in review/page-details but no longer draw large competing boxes on the main screenshot; visual media cards from `visual_card_segmenter` still render as primary card boxes. Evidence:

- AppleMusic: `logs\benchmarks\learn_two_stage_applemusic_v97_text_card_group_cleanup\learn_two_stage_replay_report_20260709-174301.json`, overlay `artifacts\review-overlays\apple-music__observe-screen__applemusic__full-window__20260706-200734-125573__two-stage-understanding__20260709-174301-100397.png`, `39` numbered / `55` fused.
- QQ: `logs\benchmarks\learn_two_stage_qq_v97_text_card_group_cleanup\learn_two_stage_replay_report_20260709-174301.json`, overlay `artifacts\review-overlays\qq__observe-screen__qq__full-window__20260706-185700-021296__two-stage-understanding__20260709-174301-038397.png`, `89` numbered / `105` fused; the far-right member list still reaches lower members such as Ad astra / ADaChi / Aeon / Airhead.
- Python.org: `logs\benchmarks\learn_two_stage_python_v97_text_card_group_cleanup\learn_two_stage_replay_report_20260709-174242.json`, overlay `artifacts\review-overlays\welcome-to-python-org-microsoft-edge__observe-screen__python-org__full-window__20260703-173928-663164__two-stage-understanding__20260709-174242-410618.png`, `131` numbered / `153` fused.

GPT visual audit was delivered through `scripts\send_chatgpt_visual_audit.py --flow-preset codex_split_20260708` and DOM-verified with 3 images. The saved reviewer report is `artifacts\chatgpt_reports\stage2_v97_text_card_group_cleanup_gpt_audit_result.json`: AppleMusic `PASS`, QQ `CONDITIONAL PASS`, Python.org `CONDITIONAL PASS`. Reviewer accepts Python.org content overlap as good enough to continue into display-only page_details review, but not as fully clean. This remains display/review-only evidence: not Execute authorization, not Runtime PathGraph promotion, not a recognition-accuracy claim, and not E2E success.

## Learn Mode recognition checkpoint (2026-07-07)

Latest checkpoint: the Learning Draft review chain now carries template-like page details and read-only PathGraph preview correspondence together. `scripts\build_learn_demo_scaffold.py` embeds `page_detail_candidate`, records `page_detail_pathgraph_correspondence`, and synthesizes missing section bboxes from section child regions so the panel can render page-detail sections and PathGraph preview sections in matching positions. `app\learn\draft_review.py` can also recover the page-detail candidate from an external scaffold output directory. Smoke evidence is under `logs\benchmarks\pathgraph_correspondence_smoke`: `learn_mode_demo_scaffold.json` reports `correspondence_status=layout_correspondence_available`, 4 shared sections, `failure_count=0`, and display-only safety (`live_clicks=0`, `live_fills=0`, `live_submits=0`, `execute_binding_enabled=false`). GPT visual audit is saved at `artifacts\chatgpt_reports\page_detail_pathgraph_correspondence_gpt_audit_result.json` and marks the correspondence scaffold / AppleMusic evidence / PathGraph preview correspondence as `CONDITIONAL PASS`; the reviewer warning is that shared section ids are understandable but must not be described as exact geometry equivalence. This is review/display scaffolding only: it is not Execute authorization, not Runtime PathGraph promotion, not an accuracy claim, and not E2E success.

Latest checkpoint: v92 parent-child display hierarchy and page-detail candidate wiring hides group child evidence from the main overlay while keeping it available for review/page-details. Protected-set replay evidence is under `logs\benchmarks\learn_two_stage_applemusic_v92_hero_child_evidence_display`, `logs\benchmarks\learn_two_stage_qq_v92_hero_child_evidence_display`, and `logs\benchmarks\learn_two_stage_python_v92_hero_child_evidence_display`. GPT visual audit is saved at `artifacts\chatgpt_reports\stage2_v92_parent_child_display_gpt_audit_result.json`: AppleMusic `PASS`, QQ `CONDITIONAL PASS`, Python.org `CONDITIONAL PASS`. This remains display-only learning evidence: it is not Execute authorization, not Runtime PathGraph promotion, not an accuracy claim, and not E2E success. QQ right-sidebar/message hierarchy and Python.org dense hero/list/card sections still need review-marked refinement before promotion.

Latest checkpoint: v89 member-list / partial-card cleanup keeps AppleMusic unchanged at `39` numbered / `55` fused, expands QQ right-sidebar `member_list_region_1` from 16 to 22 member item ids, and reduces Python.org duplicate bottom partial-card overlays from 7 to 1 (`suppressed_duplicate_partial_card_count=6`). Evidence is under `logs\benchmarks\learn_two_stage_*_v89_member_partial_cleanup`. GPT visual audit is saved at `artifacts\chatgpt_reports\stage2_v89_member_partial_cleanup_gpt_audit_result.json`: AppleMusic `PASS`, QQ `CONDITIONAL PASS`, Python.org `CONDITIONAL PASS`. This remains display-only review evidence; Python.org still needs dense hero/content display refinement plus page-detail / read-only PathGraph correspondence checks.

The ChatGPT visual-review paste path is scripted for the local Codex split layout. Use `scripts\send_chatgpt_visual_audit.py --flow-preset codex_split_20260708` instead of manually mixing bridge focus and clipboard paste. It defaults to `--dry-run`; the preset fixes the GPT composer point, attachment remove slots, and calibrated send point, then runs the same sequence every time: framework click GPT composer, paste text without hidden retargeting, framework click GPT composer before each image paste, and optionally click send. The preset preflights the bound Codex window size, forces image refocus, and reports `focus_contract.strict_composer_focus=true` / `prompt_hidden_click_before_typing=false` in JSON. It now also writes `planned_action_sequence` in dry-run and `actual_action_sequence` in real runs so each reviewer attempt can prove the order stayed text-first, image-paste-after-composer-click, send-last. A real send-click run reports `send_click_attempted=true` but keeps `sent=false` until a separate ChatGPT DOM/visible-thread check proves the latest user message contains the expected prompt token and image count. Pass `--out <path>` to save the fixed-flow JSON evidence. Custom one-off sends can still pass `--send-point`, but the normal reviewer flow should use the preset and immediately verify delivery before saving any GPT review result. The v98 dry-run evidence for three page-detail previews is `logs\benchmarks\stage2_v98_fixed_flow_dry_run.json`; it is only a send-plan check, not a GPT review result. The v83 reviewer report is saved at `artifacts\chatgpt_reports\stage1_5_v83_gpt_audit_result_external_edge.json`: AppleMusic Stage1 is now `PASS` after a generic media/card/grid right-edge preservation rule stopped cutting visible cards, QQ Stage1.5 remains `PASS` after sibling clamping keeps the right sidebar separate, and Python.org remains `CONDITIONAL PASS` with `content_column` as the only valid next numbering target. This remains display-only review evidence, not Execute authorization, not Runtime PathGraph promotion, and not a recognition-accuracy claim.

Fixed visual-audit command shape:

```powershell
uv run python scripts\send_chatgpt_visual_audit.py `
  --prompt-file logs\benchmarks\stage2_v92_parent_child_display_gpt_audit_prompt.txt `
  --image artifacts\review-overlays\apple-music__observe-screen__applemusic__full-window__20260706-200734-125573__two-stage-understanding__20260708-204617-630226.png `
  --image artifacts\review-overlays\qq__observe-screen__qq__full-window__20260706-185700-021296__two-stage-understanding__20260708-204617-604226.png `
  --image artifacts\review-overlays\welcome-to-python-org-microsoft-edge__observe-screen__python-org__full-window__20260703-173928-663164__two-stage-understanding__20260708-204550-365190.png `
  --expected-images 3 `
  --flow-preset codex_split_20260708 `
  --no-dry-run `
  --send `
  --out logs\benchmarks\stage2_v92_parent_child_display_gpt_audit_fixed_flow_real_send.json `
  --json
```

The v79 Stage1.5 replay keeps the protected-set rule: every learning-recognition strategy change must rerun Python.org, AppleMusic, and QQ together, not AppleMusic alone. Latest protected-set evidence: Python.org `logs\benchmarks\learn_stage1_only_python_v79`, AppleMusic `logs\benchmarks\learn_stage1_only_applemusic_v79`, and QQ `logs\benchmarks\learn_stage1_only_qq_v79`. QQ now constrains a horizontally overreaching `bottom_composer` to the active `message_thread` channel and records `stage1_5_boundary_review.status=composer_bbox_constrained_to_message_channel` with the previous raw bbox retained for review. AppleMusic remains `not_needed_stage1_geometry_ready`; Python.org keeps the conditional Stage1.5 `content_column` path. GPT v79 visual audit, saved at `artifacts\chatgpt_reports\stage1_5_v79_gpt_audit_result_external_edge.json`, marks Python.org `CONDITIONAL PASS`, AppleMusic `PASS`, and QQ `CONDITIONAL PASS`; QQ's remaining issue is vertical/blank-space overreach in `bottom_composer`, and Python.org must not number the whole broad primary directly. `run_learn_stage1_region_localization.py --json` continues to report `stage1_5_overlay_path`, `stage1_5_status`, and `stage1_5_subregion_count`. This remains display-only learning evidence, not Execute authorization, not Runtime PathGraph promotion, and not a recognition-accuracy claim.

The v72 Stage1-only replay adds `stage1_granularity_review` to keep reviewer semantics honest after the v71 visual split. `region_selection_audit=passed` now only means the large structure boxes are geometrically legal; it no longer implies a full Stage1 reviewer pass. Latest evidence: Python.org keeps the same v71 boxes but is reported as `stage1_geometry_passed_needs_granularity_review` with `browser_primary_scope_ambiguous_full_page_vs_content_column`; Apple Music remains `stage1_geometry_ready`; QQ is reported as `stage1_geometry_passed_needs_granularity_review` with `primary_contains_multiple_work_panes`, meaning conversation list / chat thread / composer should move to Stage1.5 before per-item numbering. Reports are under `logs\benchmarks\learn_stage1_only_python_v72`, `logs\benchmarks\learn_stage1_only_applemusic_v72`, and `logs\benchmarks\learn_stage1_only_qq_v72`. Regression protection now means rerunning the full protected interface set, currently Python.org / Apple Music / QQ, not only Apple Music. The GPT image-review route was repaired by using the browser bridge only for coordinates/status and the runtime framework for real clicking plus `CF_DIB` image paste; the reviewer confirmed Python.org `CONDITIONAL PASS`, Apple Music `PASS`, and QQ `CONDITIONAL PASS` in `artifacts\chatgpt_reports\stage1_v72_gpt_audit_result.json`. This remains display-only evidence and not Execute authorization, Runtime PathGraph promotion, or a recognition-accuracy claim.

The v71 Stage1-only replay adds a generic browser-page partition rule before any Stage2 numbering: web surfaces now keep `browser_chrome`, `webpage_header/site_nav`, `primary_area`, and right-edge `floating_controls/scroll` review ownership separate. Header/search/nav controls no longer seed the primary content top, and browser pages without an explicit right sidebar get a display-only right-edge review strip rather than leaving floating controls unowned. Evidence: Python.org Stage1 moved from GPT `FAIL` to `CONDITIONAL PASS` with `floating_controls`; Apple Music stayed clean and GPT marked it `PASS`; QQ stayed `CONDITIONAL PASS`. Reports are under `logs\benchmarks\learn_stage1_only_python_v71`, `logs\benchmarks\learn_stage1_only_applemusic_v71`, and `logs\benchmarks\learn_stage1_only_qq_v71`. This is still Stage1 display-only evidence, not Execute authorization, not a Runtime PathGraph, and not a recognition-accuracy claim.

The v48 replay adds a Stage1-before-Stage2 gate for new interface tests. `stage1_audit` now flags structure-region overlap, and `build_two_stage_screen_understanding(..., require_stage1_gate=True)` skips Stage2 item numbering when whole-region localization is not structurally valid. `scripts\run_learn_two_stage_replay.py --require-stage1-gate` is now the required entry for a new website/app recognition test: first bind/capture, localize and calibrate whole bars/regions, review the Stage1 overlay, and only then allow concrete button/card/text numbering. Apple Music passes this gate and still produces `39` numbered items / `55` fused boxes in `logs\benchmarks\learn_two_stage_applemusic_stage1_gate_v48`; GPT reviewer marks the v47 topbar boundary clamp `CONDITIONAL PASS` for display-only learning draft evidence. This is not Execute authorization, not a Runtime PathGraph, and not a recognition-accuracy claim.

The v45 replay adds a generic display-only list-row parent rule for web content: repeated `date/short metadata + same-row title text` patterns in primary content now synthesize `list_row` groups, cluster into `list_group`, and can be bound by existing `section_parent` groups. Latest evidence: `logs\benchmarks\learn_two_stage_applemusic_list_row_v45` and `logs\benchmarks\learn_two_stage_python_org_list_row_v45`. Apple Music kept the prior `39` numbered items / `55` fused boxes and local visual review did not show the protected media-card sections disappearing. GPT reviewer marks v45 `CONDITIONAL PASS` only for display-only learning-draft debug presentation: Python.org `Latest News` / `Upcoming Events` rows are clearer, but blue parent-frame clutter increased, hero/code/text/CTA remains fragmented, the four info cards still have messy internals, right floating buttons are missing, and an isolated left-side button candidate remains suspicious.

The v43 replay fixes the latest browser-page separation display path for Python.org without regressing the Apple Music baseline. The overlay now draws localized/calibrated structure regions instead of rough Stage 1 boxes, reclaims top-left browser chrome fragments that were being promoted into a false full-height `left_nav`, and suppresses browser-chrome child controls from the main orange learning-candidate overlay while keeping the blue `Browser chrome` audit region. Latest evidence: `logs\benchmarks\learn_two_stage_applemusic_chrome_overlay_suppressed_v43` and `logs\benchmarks\learn_two_stage_python_org_chrome_overlay_suppressed_v43`. GPT reviewer marks v43 `CONDITIONAL PASS` only for display-only learning-draft debug presentation: browser chrome pollution and false `left_nav` are substantially improved, but hero text, card internals, list rows, nav hit-areas, floating buttons, and main-content parent hierarchy remain too fragmented for Runtime PathGraph or Execute.

The v35 replay adds a generic guard for the v34 topbar semantic parent: pure text navigation bars (`text_action` / `nav_text_action` / text links) no longer create `topbar_semantic_group` status parents. This fixes the Python.org failure where ordinary website navigation text was wrapped into broad status groups across the browser/page header, while preserving Apple Music's icon/control-based now-playing parent. Latest evidence: `logs\benchmarks\learn_two_stage_applemusic_topbar_semantic_v35_nav_guard` and `logs\benchmarks\learn_two_stage_python_org_topbar_semantic_v35_nav_guard`. GPT reviewer marks the Python.org v35 change as a local improvement with no obvious regression, but the overall Python.org overlay remains `FAIL`: browser chrome still pollutes page structure, site nav items are still text-sized rather than full hit-areas, hero/card/list content is fragmented, right floating buttons are unclear, and no executable PathGraph or accuracy claim is implied.

The v34 replay adds a display-only `topbar_semantic_group` for sparse center top/header controls that visually belong to one now-playing/status parent. The rule is generic, review-only, and does not change child hit-areas or authorize Execute. Latest evidence: `logs\benchmarks\learn_two_stage_applemusic_topbar_semantic_v34` and `logs\benchmarks\learn_two_stage_qq_topbar_semantic_v34`. The ChatGPT review channel was repaired by writing the exact PNG into the in-app browser clipboard and verifying the uploaded image dimensions before sending; GPT reviewer now marks the Apple Music v34 overlay `CONDITIONAL PASS` only for display-only / review-only learning-draft presentation. It explicitly remains not a Runtime PathGraph, not click authorization, not live fill/submit evidence, and not a recognition-accuracy claim. Remaining reviewer issues: topbar labels clutter the header, `2.6 / 2.7` still lack clear internal now-playing structure, window button hit-areas remain tight, `1.1 / 1.2` left-nav boxes are questionable, the left-bottom account/avatar area lacks clear ownership, and `3.12 card_parent_incomplete` must stay `needs_review`.

The v19 two-stage recognition replay adds display-only `topbar_control_cluster` groups under the existing top/header strip using generic horizontal-gap evidence. Latest evidence: `logs\benchmarks\learn_two_stage_applemusic_topbar_clusters_v19` and `logs\benchmarks\learn_two_stage_qq_topbar_clusters_v19`. GPT reviewer marks Apple Music as `CONDITIONAL PASS` for display-only page-details drafting only, while QQ remains `FAIL` due to message parent, right-sidebar boundary, and bottom input parent issues. This is not Execute authorization, Runtime PathGraph promotion, live click/fill/submit evidence, or a recognition-accuracy claim.

The v20c replay adds display-only text-bubble parent expansion and a multi-timestamp guard for QQ-like chat messages. Latest evidence: `logs\benchmarks\learn_two_stage_applemusic_message_bubble_parent_v20c` and `logs\benchmarks\learn_two_stage_qq_message_bubble_parent_v20c`. GPT reviewer says the v20b cross-message merge is basically resolved and Apple Music did not regress, but QQ remains `FAIL`: short `timestamp + sender` messages can still be orphaned, image messages need cleaner outer parents, right-sidebar boundary review remains messy, and the bottom input parent is still missing. This remains debug/display-only evidence only.

The v21 replay adds a generic top/header direct-region hit-area normalizer so learned topbar controls do not remain tiny glyph/OCR fragments. Latest evidence: `logs\benchmarks\learn_two_stage_applemusic_topbar_hit_area_v21` and `logs\benchmarks\learn_two_stage_qq_topbar_hit_area_v21`. GPT reviewer marks this specific topbar hit-area checkpoint `CONDITIONAL PASS`: Apple Music topbar controls are visibly larger and the main card/section hierarchy did not regress; QQ did not gain an obvious regression from the rule. Overall learning mode is still not demo-ready, QQ remains `FAIL`, and the next generic priority is message outer-parent completeness for short/chat/image messages. No live click/fill/submit, Execute authorization, Runtime PathGraph promotion, or recognition-accuracy claim is implied.

The v23 replay adds a display-only image-message outer-parent rule for chat surfaces: when an `image_message` only has a core image/sticker bbox, the parent `message_item` can expand into a conservative review slot with `bbox_policy=message_item_image_background_expanded_needs_review`. Latest evidence: `logs\benchmarks\learn_two_stage_applemusic_image_message_parent_v23` and `logs\benchmarks\learn_two_stage_qq_image_message_parent_v23`. GPT reviewer marks this narrow checkpoint `CONDITIONAL PASS`: QQ's green image message now has a safer outer `message_item` and Apple Music did not visibly regress, but QQ remains overall `FAIL`; ordinary text-bubble background coverage, timestamp/sender ownership, right-sidebar boundaries, and bottom input parents still need work.


The v25c replay adds a display-only message-card content invariant for chat surfaces: text rows fully inside the leading continuous content band of a `message_card` become `message_card_content` instead of being expanded as ordinary `message_bubble`; later rows after a vertical break remain normal message candidates. Latest evidence: `logs\benchmarks\learn_two_stage_applemusic_message_card_content_v25c` and `logs\benchmarks\learn_two_stage_qq_message_card_content_v25c`. GPT reviewer marks only this narrow checkpoint `CONDITIONAL PASS`: QQ `3.25 / 3.28 / 3.31` are now reasonable `message_card_content`, QQ `3.35` remains a normal `message_bubble`, and Apple Music did not visibly regress. Overall learning mode still remains `FAIL` / debug-display only: message-card internal hierarchy, image-message outer `message_item`, bottom input parent, right-sidebar boundary, and topbar label clutter still need work.

The v26b replay tightens the same card hierarchy invariant: primary media-card row grouping now rejects chat semantic items (`message_card`, `message_card_content`, `message_bubble`, `image_message`) so a chat card does not also appear as a `media_card_group`. Latest evidence: `logs\benchmarks\learn_two_stage_applemusic_message_card_hierarchy_v26b` and `logs\benchmarks\learn_two_stage_qq_message_card_hierarchy_v26b`. GPT reviewer marks this narrow checkpoint `PASS`: QQ `3.23 message_card` no longer shows an erroneous internal `media_card_group`, QQ `3.25 / 3.28 / 3.31` remain `message_card_content`, QQ `3.35` remains `message_bubble`, and Apple Music's normal `media_card_group`, `section_parent`, and `partial_visible_card` overlays did not regress. Overall learning mode still remains `FAIL` / display-only debug evidence.

The v27 replay widens the display-only `image_message` parent review slot so an image-only message reserves a fuller left avatar/spacing column instead of hugging the image core. Latest evidence: `logs\benchmarks\learn_two_stage_applemusic_image_message_slot_v27` and `logs\benchmarks\learn_two_stage_qq_image_message_slot_v27`. GPT reviewer marks this narrow checkpoint `CONDITIONAL PASS`: QQ's green image message parent is more reasonable and does not cross into the conversation list or later messages, while Apple Music did not visibly regress. It is still a conservative `needs_review` display box, not a stable complete `message_item`, and not a PathGraph or Execute signal.

The v28 replay adds a machine-readable evidence-layer invariant for chat messages: every `message_item` member records `semantic_parent_group_id`, and timestamp/sender/avatar/level-like context children also record `message_context_role`. Latest evidence: `logs\benchmarks\learn_two_stage_applemusic_message_context_roles_v28` and `logs\benchmarks\learn_two_stage_qq_message_context_roles_v28`. GPT reviewer marks only this evidence-layer checkpoint `PASS`: QQ `3.34 timestamp` and `3.35 message_bubble` now share `message_item_3`, and the other timestamp/sender pairs have parent/context evidence. The overlay itself still does not make those relationships visually clear, so overall recognition remains `FAIL` / display-only debug evidence.

The v31 replay adds a stronger display-only context callout layer: timestamp/sender context children are drawn last with high-contrast cyan labels and links back to their parent `message_item`. Latest local evidence: `logs\benchmarks\learn_two_stage_applemusic_context_overlay_v31`, `logs\benchmarks\learn_two_stage_qq_context_overlay_v31`, and zoom crop `artifacts\review-overlays\qq_context_overlay_v31_message_area_zoom.png`. Codex local visual review confirms the relationship labels are visible in the generated images, while GPT web review could not reliably see the attached v31 images and continued reporting old-looking QQ overlays; therefore this is not accepted as a reviewer-passed checkpoint yet. Overall recognition remains display-only debug evidence.


[中文](README.md) | [English](README.en.md)


## Final demo readiness package (2026-07-02)



The current stage is a **benchmark-driven Windows GUI Agent Runtime / SEEK no-submit MVP scaffold**, not a production job-application bot. The final demo package is summarized in:



```text

FINAL_DEMO_READINESS_PACKAGE.md

```



Use the fixed SEEK rerun command:



```powershell

uv run python scripts\run_seek_mvp_benchmark.py `

  --manifest artifacts\benchmarks\seek_mvp_golden_manifest_v1.json `

  --out logs\benchmarks\seek_mvp_final_scaffold `

  --no-submit `

  --json

```



Latest evidence paths:



- SEEK benchmark: `logs\benchmarks\seek_mvp_final_scaffold\seek_mvp_benchmark_report.json`

- model-learning final validation: `logs\benchmarks\model_learning_feedback_loop_final\feedback_report.json`

- controlled live no-submit smoke: `logs\smoke\seek_live_no_submit_checkpoint6\checkpoint6_live_smoke_summary.json`



Current boundaries:



- SEEK manifest has 40 offline scaffold cases.

- live safe fill remains `not_covered`.

- live submit was not run in this final scaffold.

- CP6 live smoke produced a safe results-page observation/card-extraction trace only; it did not cover job detail, Apply entry, external ATS, or login blocker.

- model-learning selected config remains baseline; no prompt/config improvement is accepted for model ability.

- `draft_reference_alignment_score` / `template_similarity_score` must not be interpreted as model accuracy, click success, gate success, or SEEK E2E success.



## Learning Mode unified interface workflow scaffold (2026-07-06)



The Learning Draft subview now has a demo-first `学习当前界面 / Learn current interface` entry. It shows one progress sequence for bind/screenshot, full-screen understanding, numbered map, page details, precise calibration, fusion, read-only PathGraph draft, and completion. Internally this currently wraps the existing safe capture and learning-draft trial path; it does not call Execute, click, fill, submit, bind a Runtime PathGraph, or promote a template.



The replay surface is simplified into history drafts, screenshot/numbered-map preview, read-only PathGraph preview, interface detail, and a small manual-edit form. Existing advanced artifact/debug tools are still available, but live under a default-collapsed `Advanced diagnostics` disclosure.



The Learning Mode sidebar now stays focused on the learning workflow: `学习界面`, `模板展示`, `Trace 审计`, and `路径图安全验证`. The `打开/绑定` and `截图` preparation controls are embedded at the top of `学习界面`, where they reuse the same open/bind/capture APIs before running the draft-learning flow. `学习界面` opens the Learning Draft subview; `模板展示` opens the reviewed-template display.



Latest trace diagnosis fixed a Learning Draft dataflow bug: `runLearningDraftTrial()` now builds its request payload from the latest `/vision/observe_screen` response before clearing the panel display, so `screen_map` / `screen_inventory` evidence is not lost. Observe-only candidates are preserved as `candidate_only` / `requires_human_review` display regions in the read-only PathGraph preview and page details; they still produce no `action_templates`, no Execute binding, and no click authorization until a later calibration/Gate path validates them.



The Learning Interface progress bar is now evidence-gated. A successful draft trial no longer marks numbered map, precise calibration, fusion, or PathGraph draft as complete unless the trace contains the matching evidence. If the first pass only has `screen_map` evidence, the flow now continues into Learn Deep by calling `/vision/locate_target` with `metadata.learn_all_targets=true`, `dry_run=true`, and the captured screenshot path, then regenerates the learning draft from the calibrated response. Learn Deep coordinate trace is only attached when calibrated targets exist, so the UI can continue the intended workflow without pretending that observe-only evidence is already precise calibration.



Learn Deep overlays now also draw filtered non-actionable candidates and OCR text details as orange `R*` review-only boxes. These boxes make OCR/card-group regions visible on the screenshot even when `target_count=0`, but they stay outside executable targets and keep `execute_binding_enabled=false` / `artifact_is_authorization=false`. The panel forwards these boxes into the Learning Draft trial as read-only OCR inventory, so page details can include headings, card labels, and visible text without creating actions.



Card understanding now keeps card text as explicit `children` of the card review box instead of duplicating every card text line as a sibling numbered box. The overlap invariant is: same-level numbered boxes should not overlap unless an explicit parent-child relationship explains the overlap. Future observe runs also use a contiguous text-cluster card bbox rule so a card group does not swallow distant headings, and Learn Deep adds review-only boxes for left navigation rail icons when OCR/UIA does not expose them.



The Learning Recognition pipeline now has the first two-stage screen-understanding scaffold. Stage 1 produces coarse structure regions such as left navigation, header, main content, and lower content, then records a whole-region localization task and `precise_bbox` for each region before Stage 2 runs. Stage 2 numbers the candidates inside each localized structure region and keeps card text as children of the card item. The fused result writes a review-only overlay and exposes it through `page_details.pipeline_audit.precise_understanding_fusion_status`, so the Learning Draft screenshot panel can show boxes immediately after fusion instead of waiting for a lower-panel click. This scaffold is display/review evidence only: it is not Execute binding, not Runtime PathGraph promotion, and not a recognition accuracy claim.



For the current offset-debugging pass, Stage 1 can now be run by itself with `scripts\run_learn_stage1_region_localization.py`. It reads an existing learn-mode observe trace, builds only the top-level region inventory, applies conservative OCR/candidate-based region calibration, and writes a stage1-only overlay without Stage 2 numbering or PathGraph generation. Latest Apple Music replay: `logs\learn_stage1_region_localization\stage1_region_localization_report_20260706-211439.json`, overlay `artifacts\review-overlays\apple-music__observe-screen__applemusic__full-window__20260706-200734-125573__stage1-region-localization__20260706-211439-344665.png`. The visible bottom content is now merged back into the primary content area instead of being treated as a bottom bar. A real Qwen3-VL 8B model probe also ran against the same screenshot after removing heuristic precise bbox leakage: `logs\learn_stage1_region_model_probe\stage1_region_model_probe_report_20260706-211658.json`, overlay `logs\learn_stage1_region_model_probe\apple-music__observe-screen__applemusic__full-window__20260706-200734-125573__stage1-region-model-probe__20260706-211658.png`. These are prompt/model calibration artifacts for visual review; they are not model accuracy metrics or click authorization.



Stage 2 numbering has a matching actual-model probe in `scripts\run_learn_stage2_numbering_model_probe.py`. It takes the Stage 1 model report, crops each localized structure region, and restores crop-local coordinates to screen pixels. The current policy only runs homogeneous subregion grouping inside the primary/main content region; header/top bar and side navigation use direct whole-region numbering because subgrouping made those simple control rails noisier. Direct non-primary regions now also have a conservative `visual_small_control_segmenter` refinement: it only replaces model boxes when enough visual icon/control candidates exist and the model boxes have low overlap with those candidates. On the latest Apple Music run, this corrected the sparse top-bar icon boxes while leaving the side rail unchanged. For primary content media rows, the runner adds a framework-side `visual_card_segmenter` so different-size cards are not forced into one model crop and card artwork/text stays together. Latest report: `logs\learn_stage2_numbering_model_probe\stage2_numbering_model_probe_report_20260706-221519.json`, overlay `logs\learn_stage2_numbering_model_probe\apple-music__observe-screen__applemusic__full-window__20260706-200734-125573__stage2-numbering-model-probe__20260706-221519.png`, with 34 numbered items, 0 parent-region containment failures, and 0 JSON parse failures. This run is display/review evidence only, not a recognition-accuracy claim, Execute authorization, or Runtime PathGraph promotion.



The same scoped Stage 2 policy is now wired into the formal Learning Recognition path in `app.learn.recognition.two_stage`: `_stage2_numbering()` receives the captured screenshot path, applies main-content card-row grouping, preserves direct numbering for header/sidebar regions, and only uses visual small-control refinement when the visual candidates justify replacing sparse model boxes. The resulting `subregion_groups`, `visual_small_control_refinement`, fused review boxes, and overlay are part of `learning_draft.page_details.two_stage_understanding`, so this is no longer only a standalone probe. It remains review-only and still needs more real screenshots before any reliability claim.



Current sidebar direct-numbering invariant: narrow icon/OCR fragments are not allowed to remain as final sidebar buttons. When a left/right sidebar item has visual or semantic evidence, Stage 2 expands it into a full `nav_item` hit-area; when evidence is missing, the fragment is downgraded to a merged `sidebar_review_region` so it stays reviewable but cannot become an action candidate. The review-only sidebar region now renders as a gray-blue dashed `review-only` background box with low visual weight instead of the same orange style as controls. Section-title reconciliation creates display-only `section_parent` groups when a main-content title is clearly above a card/list group, and bottom-edge fragments under a trusted section title can now become `partial_visible_card` instead of loose text. P2.1 also allows the partial-card visual scan to extend horizontally beyond a too-narrow OCR/text union so same-row visible partial cards are not lost simply because they have no OCR text. P2.2 adds `learn_media_card_parent_validation_v1`: incomplete visual card parents are downgraded to `card_parent_incomplete`, marked `review_required=true` / `action_candidate=false`, and rendered as a warning dashed `needs review` box instead of a normal media card. The v11b pass adds horizontal control hit-area normalization for top/header bars. The v12c/v13 passes add semantic parent reconstruction for QQ-like surfaces: right-sidebar top text blocks can become `notice_region`, chat/card fragments can become display-only `message_item`, `notice_region` children are rewritten from misleading `nav_item` to `notice_item`, and a `nav_item` crossing the notice/member boundary is downgraded to display-only `boundary_review_region` with `notice_member_boundary_leak` evidence. The v14 pass extends the same common layer with display-only `member_list_region`, `conversation_row`, `message_bubble`, and `message_card` synthesis; merged sidebar review containers can expose original child member ids for review without becoming action candidates. The v15 pass adds same-screenshot visual recovery for chat image/sticker messages and text-only button hit-area normalization, so QQ now shows an `image_message` around the green sticker and a wider `text_button` around the blue send button. Latest Apple/QQ regression overlays live under `logs\benchmarks\learn_two_stage_applemusic_image_button_v15` and `logs\benchmarks\learn_two_stage_qq_image_button_v15`. GPT reviewer feedback still marks the overall result as `fail`: Apple has no new regression and QQ has real local improvement for image-message and send-button hit-area, but QQ still lacks a clean outer `message_item` for the image message, ordinary message bubble coverage is incomplete, `4.2 boundary_review_region` remains visually messy, and Apple topbar/player-strip parent containers remain open.

The v17c pass adds a message-flow boundary invariant: later timestamp/sender anchors split message parents even when an oversized previous `message_card` overlaps the following message, context anchors are assigned to the nearest following message core, and oversized message-card display boxes are clipped before the following start anchor. Latest fixed-trace overlays live under `logs\benchmarks\learn_two_stage_applemusic_message_card_clip_v17c` and `logs\benchmarks\learn_two_stage_qq_message_card_clip_v17c`. GPT reviewer feedback marks this as real progress for QQ because the giant cross-message `message_item` is gone, but the overall overlay remains `FAIL`; Apple regression is `CONDITIONAL PASS` with no obvious rollback. This is still review-only evidence, not demo readiness, not Runtime PathGraph promotion, and not Execute authorization.

The v18 pass adds a display-only `topbar_control_strip` parent for direct top/header regions so topbars no longer appear only as isolated glyph/control boxes. Latest fixed-trace overlays live under `logs\benchmarks\learn_two_stage_applemusic_topbar_parent_v18` and `logs\benchmarks\learn_two_stage_qq_topbar_parent_v18`. GPT reviewer feedback marks this as `CONDITIONAL PASS` only: Apple and QQ did not obviously regress, and Apple now has a topbar parent strip, but the strip is still coarse and must later split into player/now-playing, playback controls, right utility controls, window controls, search/header controls where evidence supports it. It remains display-only and non-authorizing.


## Learning Draft PathGraph review checkpoint (2026-07-05)



The learning-mode review bridge now has a scriptable offline detail-observe attachment path. `scripts\attach_pathgraph_candidate_detail_observe.py` attaches an existing detail-page learning draft/trial to pending `open_detail` requests inside a non-executable `pathgraph_candidate.json`, then writes `detail_observe_attach_result.json`.



Latest SEEK review evidence:



- source freshness bind: `logs\benchmarks\pathgraph_candidate_source_freshness_bind_seek_20260705\source_freshness_bind_result.json`

- detail fixture attach: `logs\benchmarks\pathgraph_detail_observe_attach_seek_fixture_20260705\detail_observe_attach_result.json`

- promotion gate replay: `logs\benchmarks\pathgraph_promotion_gate_replay_after_seek_detail_fixture_20260705\pathgraph_promotion_gate_replay_report.json`



The freshness-bound SEEK candidate now reaches `readiness_status=needs_promotion_review`, with `promotion_review_blockers=["review_only_not_promoted"]` and `promotion_gate_status=passed_for_human_promotion_review`. This is still review-only: no live click, no live detail observe, no Execute binding, no Runtime PathGraph promotion, no safe fill, and no submit.



The latest full-screen fused understanding status report is:



```text

logs\benchmarks\learn_precise_understanding_fusion_status_seek_full_corrected_20260705\learn_precise_understanding_fusion_status_corrected.json

```



It marks the SEEK full-screen overlay as `display_ready` with 10 fused items. Existing targeted `open_detail` dry-run evidence has been merged back into regions 4 and 5, so the corrected status now reports `calibration_status_counts={"gate_rejected":2,"needs_human_review":8}` and `gate_safety_counts={"passed_allowed_dry_run":8,"passed_rejected":2}`. PathGraph preparation still remains `blocked_from_pathgraph_candidate_review` because the items are display/review evidence, not promotion-ready actions. The loadable Learning Draft artifact with this corrected status attached to Page Detail is:



```text

logs\benchmarks\learn_precise_understanding_fusion_status_seek_full_corrected_20260705\actual_parser_output_with_fusion_status.json

```



Gate-rejection diagnosis is also attached: after the targeted rerun correction, the remaining 2 rejected page-structure items should remain blocked as non-actionable. The correction is display/review-only: no model was started, no live click was run, no Execute binding was enabled, and no Runtime PathGraph promotion was authorized.



`scripts\run_numbered_region_calibration_probe.py` now also writes a separate full-screen understanding overlay for the raw screen-understanding locator cards. `compiled_overlay_path` remains the calibrated selected-region view; `full_screen_understanding_overlay_path` draws every locator card and overlays calibration evidence only where Execute dry-run was attempted. A current offline preview is:



```text

logs\benchmarks\learn_full_screen_understanding_overlay_preview_20260706\full_screen_understanding_overlay.png

```



The preview report is `logs\benchmarks\learn_full_screen_understanding_overlay_preview_20260706\full_screen_understanding_overlay_preview_report.json`, with `total_locator_cards=10`, `calibrated_cases=2`, and `uncalibrated_locator_cards=8`. This is demo/display evidence only; it is not recognition accuracy, Execute authorization, or PathGraph promotion.



The full overlay path is now preserved through the fusion status report and surfaced by `load_learning_draft_review()` as part of `screen_understanding_preview`. The Learning Draft panel shows a `View full-screen understanding overlay / 查看全图识别图` button when this evidence exists, so the whole-image recognition result can be inspected without opening JSON files.



The same chain now carries `numbered_region_calibration_backlog_v1`, listing uncalibrated locator cards and their suggested next dry-run semantic action. The backlog includes actionability triage: interactive-looking regions are `ready_for_execute_dry_run`, while page-structure, placeholder, count, or indicator regions require `review_before_calibration`. The Learning Draft panel shows this as a read-only calibration backlog with `backlog_ready` / `backlog_review` chips. A current backlog preview is:



```text

logs\benchmarks\learn_full_screen_understanding_backlog_triage_preview_20260706\full_screen_understanding_backlog_triage_preview_report.json

```



For the current SEEK saved screenshot, the backlog reports 8 uncalibrated locator cards: 6 ready for future Execute dry-run calibration and 2 requiring review before calibration. These are not click authorization and are not PathGraph promotion.



The PathGraph integration readiness sidecar can now be generated from the Learning Draft panel with `Create PathGraph integration readiness`, through `POST /panel/create_pathgraph_integration_readiness`, or from the CLI:



```powershell

uv run python scripts\report_learn_fusion_pathgraph_integration_readiness.py `

  --pathgraph-candidate artifacts\learning-draft-review\actual_parser_output_with_fusion_status_7b471afc08\pathgraph_candidate\pathgraph_candidate.json `

  --out artifacts\learning-draft-review\actual_parser_output_with_fusion_status_7b471afc08\pathgraph_candidate `

  --json

```



`load_learning_draft_review()` reads the generated `learn_fusion_pathgraph_integration_readiness_report.json` sidecar, and the PathGraph readiness card displays both its checklist and `pathgraph_integration_report=...` evidence path. The panel action only writes/reloads this report; it does not start models, click, fill, submit, or promote Runtime PathGraph. The current sidecar is still `blocked_pending_calibration` with `ready_for_audited_pathgraph_review=false` and `ready_for_runtime_pathgraph_promotion=false`; it is no-model/no-execute review evidence only.



`GET /panel/learning_draft_sources` also carries this sidecar status and report path when it exists, so the Learning Draft source picker can show `pathgraph_integration=blocked_pending_calibration`, `pathgraph_integration_report=.../learn_fusion_pathgraph_integration_readiness_report.json`, `pathgraph_audit_ready=false`, and `pathgraph_runtime_promotion=false` before the candidate is loaded.



For a single offline evidence packet that combines the current full-screen understanding, calibration backlog, PathGraph readiness, and integration readiness, run:



```powershell

uv run python scripts\report_learn_fusion_current_evidence_packet.py `

  --source artifacts\learning-draft-review\actual_parser_output_with_fusion_status_7b471afc08\pathgraph_candidate\pathgraph_candidate.json `

  --out logs\benchmarks\learn_fusion_current_evidence_packet_20260706 `

  --json

```



Latest packet: `logs\benchmarks\learn_fusion_current_evidence_packet_20260706\learn_fusion_current_evidence_packet.json`. It reports `calibration_coverage_rate=0.2`, pending ready regions `1,2,3,6,8,9`, review-blocked regions `7,10`, and `integration_readiness_status=blocked_pending_calibration`. It is still an offline evidence summary only, not recognition accuracy, Execute authorization, model-start approval, or Runtime PathGraph promotion.



The Learning Draft panel also exposes the same step through `Create current evidence packet`, backed by `POST /panel/create_current_evidence_packet`. The panel action writes the packet beside the selected source by default and keeps `model_started=false`, `live_clicks=0`, `execute_binding_enabled=false`, and `runtime_pathgraph_promotion=false`. `load_learning_draft_review()` now reloads the sidecar `learn_fusion_current_evidence_packet.json`, so the source picker and PathGraph readiness card can show the packet path, calibration coverage, integration status, and no-model/no-promotion safety flags after refresh.



The next no-model bridge artifact is `learn_precise_understanding_candidate.json`, created by:



```powershell

uv run python scripts\build_learn_precise_understanding_candidate.py `

  --source artifacts\learning-draft-review\actual_parser_output_with_fusion_status_7b471afc08\pathgraph_candidate\pathgraph_candidate.json `

  --out artifacts\learning-draft-review\actual_parser_output_with_fusion_status_7b471afc08\pathgraph_candidate `

  --json

```



The Learning Draft panel exposes the same step as `Create precise understanding candidate`, backed by `POST /panel/create_precise_understanding_candidate`. The candidate compiles full-screen understanding, calibration backlog, and existing Execute dry-run evidence into a per-region review graph for future PathGraph preparation. Current SEEK smoke: `total_regions=10`, `pending_calibration_count=6`, `review_blocked_count=2`, `pathgraph_candidate_review_ready_count=0`, `readiness_status=needs_pending_calibration`, and `runtime_pathgraph_promotion=false`. This is still review-only evidence, not recognition accuracy, Execute authorization, or Runtime PathGraph promotion.



The next-batch plan is:



```text

logs\benchmarks\numbered_region_calibration_batch_plan_seek_20260706\numbered_region_calibration_batch_plan.json

```



It proposes ready regions `1,2,3,6,8,9` and keeps regions `7,10` review-blocked. The plan only previews a command; `command_executes_now=false` and the command does not include `--start-model`. When attached through `scripts\attach_learn_precise_understanding_fusion_status.py --calibration-batch-plan`, `load_learning_draft_review()` exposes the plan under `screen_understanding_preview`, and the Learning Draft panel renders it as a read-only `Next calibration batch / 下一批校准计划` card with `batch_ready`, `batch_review`, and `command_executes_now=false`.



The current loadable Learning Draft artifact with the batch plan attached is `logs\benchmarks\learn_precise_understanding_fusion_status_with_batch_plan_20260706\actual_parser_output_with_fusion_status.json`. The PathGraph preflight layer can also consume the same batch plan: `scripts\build_learn_fusion_pathgraph_preflight.py --calibration-batch-plan` now writes `pending_calibration_batch` into the review-only preflight plan, so the panel can show `preflight:pending_calibration_ready`, `preflight:pending_calibration_review`, and `command_executes_now=false` before any PathGraph wiring review.



The current loadable Learning Draft artifact with full queue + pending-batch preflight attached is `logs\benchmarks\learn_pathgraph_readiness_with_pending_batch_20260706\actual_parser_output_with_fusion_status.json`.



`scripts\report_learn_precise_understanding_readiness.py` now turns that attached draft into a compact readiness report. Current report: `logs\benchmarks\learn_precise_understanding_readiness_20260706\learn_precise_understanding_readiness_report.json`, with `readiness_status=needs_pending_calibration`, `calibrated_cases=2/10`, `uncalibrated_locator_cards=8`, pending ready regions `1,2,3,6,8,9`, and review-blocked regions `7,10`. This is the current honest checkpoint for "full-screen understanding + precise locator fusion": useful for demo/review, but not yet complete precise understanding or PathGraph promotion.



`scripts\merge_learn_fusion_targeted_rerun.py` now also handles the next offline merge step for future pending calibration batches. When new numbered-region dry-run evidence is merged by matching `region_no` and `source_item_id`, the script removes those regions from `calibration_backlog`, `calibration_batch_plan`, and `pathgraph_preflight_plan.pending_calibration_batch`, then recomputes `precise_understanding_readiness_summary`. It only emits review artifacts and keeps `execute_binding_enabled=false` / `artifact_is_authorization=false`. The latest no-model smoke is `logs\benchmarks\learn_fusion_pending_batch_merge_smoke_20260706\learn_fusion_targeted_rerun_merge_result.json`; it also confirms ordinary `attempted` counts are not converted into coverage rates unless the source has real full-screen coverage context.



`scripts\refresh_learn_fusion_after_calibration_batch.py` wraps the post-batch offline refresh path into one command: validate optional batch acceptance, merge dry-run evidence, attach the corrected fusion status back into a loadable Learning Draft, and rebuild the readiness report. When called with `--batch-plan`, refresh now runs `scripts\report_learn_fusion_calibration_batch_acceptance.py` first and blocks before merge if the rerun evidence is missing, incomplete, unexpected, review-blocked, or contains real clicks/authorization flags. The latest acceptance-block no-model smoke is `logs\benchmarks\learn_fusion_after_calibration_batch_refresh_acceptance_block_20260706\learn_fusion_after_calibration_batch_refresh_result.json`, with `refresh_status=blocked_by_calibration_batch_acceptance`, blocker `rerun_report_missing`, and `merge_skipped=true`. The older merge smoke remains `logs\benchmarks\learn_fusion_after_calibration_batch_refresh_smoke_20260706\learn_fusion_after_calibration_batch_refresh_result.json`; it correctly reports `calibration_coverage_rate=not_covered` for an older non-pending status. The real next use is after the pending regions `1,2,3,6,8,9` are actually dry-run calibrated with explicit model-start approval.



`scripts\build_numbered_region_calibration_batch_plan.py` can now include the post-batch refresh preview when called with `--trial` and `--base-status`. That preview now includes `--batch-plan <numbered_region_calibration_batch_plan.json>`, so copying the shown post-batch command keeps the refresh acceptance gate enabled by default. The current SEEK plan with both command previews is `logs\benchmarks\numbered_region_calibration_batch_plan_with_refresh_seek_20260706\numbered_region_calibration_batch_plan.json`. It still sets `command_executes_now=false` and `post_batch_refresh_command_executes_now=false`; the panel renders both commands as read-only text, with no run button.



The current loadable Learning Draft artifact with the full-screen overlay, pending batch, post-batch refresh preview, and PathGraph preflight status is:



```text

logs\benchmarks\learn_pathgraph_readiness_with_handoff_20260706\actual_parser_output_with_fusion_status.json

```



Its readiness report is `logs\benchmarks\learn_pathgraph_readiness_with_handoff_20260706\readiness\learn_precise_understanding_readiness_report.json`, with `readiness_status=needs_pending_calibration`, `calibration_coverage_rate=0.2`, pending ready regions `1,2,3,6,8,9`, review-blocked regions `7,10`, and `pathgraph_status=blocked_from_pathgraph_candidate_review`. This artifact is the best current panel demo source for the new numbered-region idea because it now includes the calibration handoff preflight in the Learning Draft preview.



The readiness report now also includes `evidence_integrity`, a PathGraph preflight evidence check for the source draft, source screenshot, full-screen understanding overlay, compiled calibration overlay, source status report, and source calibration report. The Learning Draft panel also surfaces the same integrity status in the Screen Understanding Preview, showing missing declared evidence plus per-file existence and SHA-256 prefixes. The current `with_handoff` report and panel preview are `evidence_integrity.status=complete`, so later PathGraph review can distinguish real missing/stale evidence from model or coordinate failures. If declared screenshot/overlay evidence is missing, the report adds `repair_missing_evidence_before_pathgraph_review` before any PathGraph review step.



PathGraph candidate validation now treats `evidence_integrity.status=missing_declared_evidence` as a hard blocker with `validation_status=blocked_missing_evidence` and a failed `precise_understanding_evidence_integrity_complete` check. This keeps missing screenshots or overlays from being misreported as model-quality, coordinate-quality, or promotion-ready outcomes. The current recommended `with_handoff` candidate still blocks for pending calibration, not evidence integrity, and keeps `execute_binding_enabled=false`.



`GET /panel/learning_draft_sources` now pins that same `with_handoff` artifact as `recommended_current_precise_understanding`, so the panel source picker can load the current best Learning Draft review source without hand-entering the path. Loading the source list also pre-fills the main Learning Draft review source path with the recommended artifact when that field is empty; selecting another source updates both the detail-observe source and the main Learning Draft review source. The Learning Draft panel also has a `Load recommended current draft` button that refreshes the source list, selects the pinned artifact, and loads the display-only review in one step for demos. Source entries expose `readiness_status`, `calibration_coverage_rate`, pending calibration counts, `handoff_status`, and `rerun_report_status`; the dropdown displays those values so the recommended artifact is visibly `needs_pending_calibration` rather than promotion-ready. The entry and button remain display/review-only and keep `execute_binding_enabled=false` / `artifact_is_authorization=false`; they do not start models, execute clicks, or promote a Runtime PathGraph.



Source entries that include the handoff consistency audit also expose `consistency_status`, `post_batch_refresh_has_batch_plan`, `refresh_blocks_before_future_rerun`, and `consistency_blocker_count`. The dropdown label shows `consistency=ready_for_explicit_model_start`, `refresh_gate=batch_plan`, and `prebatch_refresh=blocked` for the current recommended artifact, so the demo can verify the pre-start handoff state before loading the full draft view.



The next model-start handoff is also summarized as a standalone offline runbook:



```text

logs\benchmarks\learn_fusion_model_start_runbook_20260706\learn_fusion_model_start_runbook.json

```



It reports `runbook_status=awaiting_explicit_model_start_approval`, `may_start_model_after_user_approval=true`, `may_run_calibration_batch_now=false`, ready regions `1,2,3,6,8,9`, and review-blocked regions `7,10`. This runbook is only a checklist for the next approved calibration batch; it does not start models, click, fill, submit, refresh, merge, or promote Runtime PathGraph.



The recommended Learning Draft artifact embeds the same runbook and the panel shows it under Screen Understanding Preview as a read-only Model-start runbook card. It is intended to make the next manual checkpoint visible in the UI, not to add a run button or authorize execution.



The Learning Draft source picker also surfaces that runbook state in the option label: `runbook=awaiting_explicit_model_start_approval`, `start_after_approval=true`, `run_now=false`, and `runbook_ready=6`. This makes the current recommended artifact's next step visible before loading the full review panel.



PathGraph candidate validation carries the same runbook when the recommended draft is still blocked by pending calibration. The latest no-model candidate smoke is:



```text

artifacts\learning-draft-review\actual_parser_output_with_fusion_status_7b471afc08\pathgraph_candidate\promotion_validation_report.json

```



It remains `blocked_pending_calibration`, but now includes `model_start_runbook` so the blocker points to the explicit model-start approval step rather than appearing as a generic PathGraph failure.



When the same `pathgraph_candidate.json` is loaded in the Learning Draft panel, the PathGraph readiness card also displays that runbook status, ready-region list, and read-only calibration / post-batch refresh command previews. This keeps the panel and JSON report aligned: pending calibration remains a hard blocker, and no Runtime PathGraph promotion or model execution is implied.



The same card now includes a compact runbook checklist showing `approval_required`, `may_start_after_approval`, `may_run_now`, `display_only`, `execute_binding`, and `authorization`. This is a pre-approval safety summary for the operator: the current expected state is approval required, start allowed only after approval, run-now false, display-only true, execute binding false, and authorization false.



It also renders the next evidence requirements from the runbook: future rerun report status/path, ready regions, and review-blocked regions. This makes the current PathGraph blocker concrete: the candidate is waiting for explicit user-approved calibration evidence for regions `1,2,3,6,8,9`, while regions `7,10` remain review-blocked.



`scripts\report_learn_fusion_model_start_preflight.py` now provides the matching command-line preflight before that approval step. It cross-checks the model-start runbook and non-executable PathGraph candidate, follows the sibling `promotion_validation_report.json`, and blocks if the candidate is not `blocked_pending_calibration`, if safety flags become executable/authorizing, or if ready/review-blocked regions drift. Current report:



```text

logs\benchmarks\learn_fusion_model_start_preflight_20260706\learn_fusion_model_start_preflight_report.json

```



The current report is `preflight_status=ready_for_explicit_model_start`, `candidate_validation_status=blocked_pending_calibration`, ready regions `1,2,3,6,8,9`, review-blocked regions `7,10`, and safety fields `model_started=false`, `live_clicks=0`, `live_fills=0`, `live_submits=0`, `execute_binding_enabled=false`, `artifact_is_authorization=false`. It is still not approval to run calibration; it is the final offline check before asking for that approval.



When that report is written beside `pathgraph_candidate.json` as `learn_fusion_model_start_preflight_report.json`, `load_learning_draft_review()` now exposes it as `pathgraph_candidate_review.model_start_preflight` and mirrors it into the PathGraph readiness summary. The Learning Draft panel renders `preflight_status=ready_for_explicit_model_start` and `preflight_start_after_approval=true` beside the existing candidate blocker, so the UI can distinguish "ready to ask for model-start approval" from "PathGraph-ready".



`GET /panel/learning_draft_sources` also surfaces the same candidate/preflight sidecar metadata when it discovers a PathGraph candidate source. The source picker option can now show `preflight=ready_for_explicit_model_start`, `preflight_start_after_approval=true`, and `preflight_run_now=false` before the full review is loaded. A local source-list smoke found the current candidate entry at `artifacts/learning-draft-review/actual_parser_output_with_fusion_status_7b471afc08/pathgraph_candidate/pathgraph_candidate.json` with `candidate_validation_status=blocked_pending_calibration` and `preflight_blocker_count=0`.



The same candidate review flow now includes a no-model calibration pre-run check in the panel. Use `Create calibration pre-run check` after the model-start approval packet exists; it writes `learn_fusion_calibration_pre_run_check_report.json` beside `pathgraph_candidate.json`, reloads the Learning Draft review, and shows `calibration_pre_run=ready_after_explicit_approval` plus the ready/command region checklist in the PathGraph readiness card. The current sidecar is `artifacts\learning-draft-review\actual_parser_output_with_fusion_status_7b471afc08\pathgraph_candidate\learn_fusion_calibration_pre_run_check_report.json`. The loader now re-hashes the current approval packet on every review load and displays `approval_packet_checksum_status=matched/mismatch`; mismatch or missing checksum evidence becomes `effective_pre_run_status=stale_pre_run_evidence` with a blocker, and the source picker also shows `calibration_pre_run_checksum=...`. It still has `may_run_calibration_batch_now=false`; it does not start models, run calibration, click, fill, submit, bind Execute, refresh, merge, or promote Runtime PathGraph.



Before treating a refreshed fusion result as ready for PathGraph work, run the offline integration gate:



```powershell

uv run python scripts\report_learn_fusion_pathgraph_integration_readiness.py `

  --pathgraph-candidate artifacts\learning-draft-review\actual_parser_output_with_fusion_status_7b471afc08\pathgraph_candidate\pathgraph_candidate.json `

  --out logs\benchmarks\learn_fusion_pathgraph_integration_readiness_20260706 `

  --json

```



The current report is `logs\benchmarks\learn_fusion_pathgraph_integration_readiness_20260706\learn_fusion_pathgraph_integration_readiness_report.json` and correctly says `integration_readiness_status=blocked_pending_calibration`. A future passing report only means `ready_for_audited_pathgraph_review`; it still does not promote Runtime PathGraph or authorize Execute.



When a source-list entry includes `pathgraph_candidate_path`, the Learning Draft source picker now uses that path as the load value instead of the underlying reviewed candidate path. This preserves the PathGraph candidate review, blocker, runbook, and preflight sidecar context after selection. A local smoke confirmed the preflight-aware source loads `artifacts/learning-draft-review/actual_parser_output_with_fusion_status_7b471afc08/pathgraph_candidate/pathgraph_candidate.json`, not just `reviewed_template_candidate.json`.



The picker recommendation logic now prefers a preflight-aware candidate (`preflight_status=ready_for_explicit_model_start` plus `pathgraph_candidate_path`) over a raw pinned draft when choosing the default review source. This improves the demo path by loading the richer candidate/preflight context first; it does not execute the calibration command or promote the candidate.



Preflight-aware source options are also marked with `[Ready preflight]` in the picker label, so the selected demo source is visually distinct from a raw pinned draft while keeping the same display-only safety boundary.



The `Load recommended current draft` button now uses the same preflight-aware recommendation logic. If a ready preflight candidate exists, the button loads its `pathgraph_candidate.json` and reports both the original reviewed source path and candidate path in the response summary.



`scripts\report_learn_fusion_demo_readiness.py` now provides the corresponding one-command offline demo readiness check. Current report:



```text

logs\benchmarks\learn_fusion_demo_readiness_20260706\learn_fusion_demo_readiness_report.json

```



It reports `demo_readiness_status=ready_for_preflight_demo`, `recommended_load_path=artifacts/learning-draft-review/actual_parser_output_with_fusion_status_7b471afc08/pathgraph_candidate/pathgraph_candidate.json`, `candidate_validation_status=blocked_pending_calibration`, `preflight_status=ready_for_explicit_model_start`, `may_run_calibration_batch_now=false`, and no model/click/fill/submit evidence. This is a demo-readiness check only, not a model-start approval or Runtime PathGraph promotion.



When written beside `pathgraph_candidate.json` as `learn_fusion_demo_readiness_report.json`, the loader now exposes it as `pathgraph_candidate_review.demo_readiness` and mirrors it into the PathGraph readiness summary. The readiness card renders `demo_readiness=ready_for_preflight_demo` alongside `blocked_pending_calibration` and model-start preflight status.



`GET /panel/learning_draft_sources` also exposes the same demo-readiness sidecar metadata before the source is loaded. The source picker can now show `demo=ready_for_preflight_demo` and `demo_run_now=false` on the preflight-aware candidate entry, while continuing to load the non-executable `pathgraph_candidate.json` and block calibration until explicit model-start approval.



`scripts\report_learn_fusion_model_start_approval_packet.py` now creates the final no-execute approval packet for that handoff. It consumes the model-start runbook, model-start preflight, and demo-readiness report, then emits `learn_fusion_model_start_approval_packet_v1` with the exact calibration and post-batch refresh command previews, ready/review-blocked region lists, and safety flags. The current sidecar is:



```text

artifacts\learning-draft-review\actual_parser_output_with_fusion_status_7b471afc08\pathgraph_candidate\learn_fusion_model_start_approval_packet.json

```



Its status is `ready_for_user_approval`, `requires_explicit_user_approval=true`, and `may_run_calibration_batch_now=false`. The loader, PathGraph readiness card, and source picker can display `approval_packet=ready_for_user_approval` / `approval_run_now=false`; this still does not start models, run calibration, click, fill, submit, refresh, merge, or promote Runtime PathGraph.



The PathGraph readiness card now also expands the approval packet into read-only details: approval checklist, ready/review-blocked regions, future rerun report, and the exact calibration / post-refresh command previews. This keeps the next explicit approval step visible in the panel without opening JSON and without adding a run button.



The Learning Draft panel also has a `Create model-start approval packet` button. It sends only the current non-executable `pathgraph_candidate.json` to `POST /panel/create_model_start_approval_packet`; the backend derives the runbook/preflight/demo-readiness inputs from sibling sidecars or embedded metadata, writes the approval packet, and reloads the review display. The endpoint can also accept explicit runbook/preflight/demo paths for scripted checks. Both modes keep `may_run_calibration_batch_now=false` and do not start models.



`scripts\report_learn_fusion_calibration_pre_run_check.py` now verifies the approval packet before any model start: it checks the numbered-region task file exists, command regions match ready regions, the post-batch refresh command points at the expected future rerun report, the batch plan exists, and all no-model/no-click/no-submit flags remain clean. Current report:



```text

logs\benchmarks\learn_fusion_calibration_pre_run_check_20260706\learn_fusion_calibration_pre_run_check_report.json

```



It reports `pre_run_status=ready_after_explicit_approval`, ready regions `1,2,3,6,8,9`, and `blockers=[]`. This still does not start models; it only proves the future calibration command packet is internally runnable after explicit approval.



The recommended `with_handoff` artifact and its source batch plan have been rebuilt after the refresh acceptance hard gate landed. The panel-visible post-batch refresh preview now includes `--batch-plan`, so running that command before the future calibration batch produces `blocked_by_calibration_batch_acceptance` instead of merging stale or missing evidence.



The current package-level handoff consistency audit is:



```text

logs\benchmarks\learn_fusion_handoff_consistency_20260706\learn_fusion_handoff_consistency_report.json

```



It checks the recommended draft, batch plan, handoff report, acceptance report, and pre-batch refresh block result together. The current status is `ready_for_explicit_model_start` with no blockers, meaning the next batch is prepared for explicit user-approved model calibration, while still remaining display/review-only and not PathGraph-ready.



The recommended Learning Draft now embeds the same audit, and the panel renders it as a read-only handoff consistency card. This makes the final pre-start state visible in the demo UI: the materials are internally consistent, the refresh command is gated by `--batch-plan`, and no model/click/fill/submit has run.



A no-model PathGraph candidate smoke against this recommended source produced `validation_status=blocked_pending_calibration`, with the hard check `precise_understanding_ready_for_pathgraph_candidate=false`. Evidence: `artifacts\learning-draft-review\actual_parser_output_with_fusion_status_a6fcadf890\pathgraph_candidate\promotion_validation_report.json`. This confirms the recommended source is convenient to inspect, but still cannot bypass the pending calibration queue.



The post-batch refresh command now uses a composed refresh base status:



```text

logs\benchmarks\learn_pathgraph_readiness_with_refresh_plan_20260706\refresh_base\learn_fusion_refresh_base_status.json

```



That base status combines corrected fusion items with the full-screen overlay/backlog, pending batch plan, and preflight summary, so future `refresh_learn_fusion_after_calibration_batch.py` runs can reduce pending regions and preserve the coverage context instead of falling back to an older attempted-only status.



The current no-model calibration handoff preflight is:



```text

logs\benchmarks\learn_fusion_calibration_handoff_20260706\learn_fusion_calibration_handoff_report.json

```



It reports `handoff_status=ready_for_explicit_model_start`, ready regions `1,2,3,6,8,9`, review-blocked regions `7,10`, `rerun_report_status=awaiting_future_calibration_output`, and no blockers. This is only a preflight for a future explicitly approved model-start calibration batch; it does not start models, click, fill, submit, promote Runtime PathGraph, or prove recognition accuracy.



The post-batch acceptance gate is:



```text

logs\benchmarks\learn_fusion_calibration_batch_acceptance_20260706\learn_fusion_calibration_batch_acceptance_report.json

```



It is produced by `scripts\report_learn_fusion_calibration_batch_acceptance.py` and checks a future numbered-region calibration report before the refresh/merge step. The gate requires exact ready-region coverage, no review-blocked or unexpected regions, no real clicks, and disabled Execute/authorization flags. The current status is `acceptance_status=awaiting_future_calibration_output` with blocker `rerun_report_missing`, because the model-backed calibration batch has not been run yet.



The same acceptance check is now also enforced inside `scripts\refresh_learn_fusion_after_calibration_batch.py --batch-plan`. If the acceptance report is not `ready_for_post_batch_refresh=true`, refresh writes a blocked report and skips merge, draft attach, and readiness recomputation. This keeps the future full-screen understanding fusion path from bypassing calibration acceptance with a hand-run refresh command.



The current recommended `with_handoff` Learning Draft artifact embeds both the handoff preflight and this acceptance gate. In the panel, Screen Understanding Preview now shows the calibration handoff card, the calibration batch acceptance card, and the evidence integrity card together: `needs_pending_calibration`, `awaiting_future_calibration_output`, and `evidence_integrity.status=complete` are visible before any PathGraph handoff.



`load_learning_draft_review()` now computes the same readiness summary for the panel under `screen_understanding_preview.precise_understanding_readiness_summary`. The Learning Draft screen-understanding toolbar shows `readiness=needs_pending_calibration`, `coverage=0.2`, `pending_ready=6`, `pending_review=2`, and `pathgraph=blocked_from_pathgraph_candidate_review` when loading the current artifact.



The PathGraph candidate validator now also consumes `precise_understanding_readiness_summary`. If a reviewed learning draft still has `readiness_status=needs_pending_calibration` or pending ready regions, candidate validation returns `blocked_pending_calibration` and records the failed check `precise_understanding_ready_for_pathgraph_candidate`. This keeps the pending calibration queue as a hard review blocker, not just a UI warning.



The fusion-derived PathGraph candidate now also inherits the attached fusion screenshot as source-freshness evidence during reviewed-candidate save. When the fusion status contains an existing `screenshot_path`, the review layer verifies the file and binds its SHA-256 into `source_freshness_summary_v1`. Rebuilding `artifacts\learning-draft-review\actual_parser_output_with_fusion_status_2da5f3e228\pathgraph_candidate\pathgraph_candidate.json`, attaching the offline detail fixture, and replaying the promotion gate now gives `promotion_gate_status=passed_for_human_promotion_review` with `remaining_failed_checks=[]`. Latest reports: `logs\benchmarks\pathgraph_detail_observe_attach_fusion_candidate_freshness_20260705\detail_observe_attach_result.json`, `logs\benchmarks\pathgraph_promotion_gate_replay_fusion_candidate_freshness_20260705\pathgraph_promotion_gate_replay_report.json`, and `logs\benchmarks\learn_fusion_pathgraph_candidate_status_freshness_20260705\learn_fusion_pathgraph_candidate_status_report.json`. This is still human review readiness only: `readiness_status=needs_promotion_review`, `review_only_not_promoted` remains a blocker, and no Execute binding, live click, live safe fill, submit, or Runtime PathGraph promotion is authorized.



The passed candidate can now be packaged for simple human review without becoming executable:



```text

artifacts\learning-draft-review\actual_parser_output_with_fusion_status_2da5f3e228\pathgraph_candidate\assisted_template_review\assisted_template_review_package.json

```



`POST /panel/create_assisted_template_review_package` creates this `assisted_template_review_package_v1` only when the candidate's promotion-review gate has passed. `POST /panel/load_assisted_template_review_package` loads the same package back into the Learning Draft panel as a compact checklist: package status, gate checks, freshness evidence, counts, detail attachments, and state/region/action/transition items. It now also restores the sibling `assisted_template_review_record_v1` decisions and `assisted_template_asset_candidate_v1` summary when they exist, so the panel can reopen the human review state instead of showing every item as fresh pending. Each checklist item has lightweight fields for review note plus safe overrides for `label`, `semantic_action`, and `target_entity`; `POST /panel/save_assisted_template_review_decisions` writes the user's checklist decisions, notes, and safe overrides to `assisted_template_review_record_v1`. The current record is `artifacts\learning-draft-review\actual_parser_output_with_fusion_status_2da5f3e228\pathgraph_candidate\assisted_template_review\assisted_template_review_record.json`. `POST /panel/create_assisted_template_acceptance_suggestions` now writes `assisted_template_acceptance_suggestions_v1`, grouping each action with its target region, linked transitions, and from/to states so the reviewer can accept related checklist items together without hand-editing JSON; these suggestions do not write review decisions and do not authorize execution. The panel's suggestion cards include an `Apply to checklist` button that only pre-fills the visible, unsaved checklist controls with the suggested `accepted` decision, note, and safe action overrides; the reviewer must still save the decisions and export an asset candidate explicitly. The current suggestions artifact is `artifacts\learning-draft-review\actual_parser_output_with_fusion_status_2da5f3e228\pathgraph_candidate\assisted_template_review\assisted_template_acceptance_suggestions.json` with 3 review-only suggestion groups. `POST /panel/create_assisted_template_asset_candidate` then exports only checklist items marked `accepted` into a separate `assisted_template_asset_candidate_v1`, preserving accepted-item notes as `human_review_note` and applying safe overrides as `human_review_overrides`; the panel also has a `Save + create asset candidate` shortcut for that two-step review workflow. Asset candidates now include `assisted_template_asset_validation_summary_v1`, which flags missing action semantics, unaccepted target regions, broken transition/action links, unaccepted transition states, and forbidden final-submit-like actions before any Runtime PathGraph promotion is considered. The Learning Draft panel now renders that validation as a compact `PathGraph draft completeness` card, so the reviewer can see whether accepted items passed manual asset checks, have no accepted content, or are blocked by concrete linkage/safety issues. `POST /panel/create_assisted_template_graph_draft` can turn the asset candidate into a read-only `assisted_template_graph_draft_v1` with states, regions, action templates, and transitions laid out in PathGraph shape for manual review only; the Learning Draft panel renders those graph pieces as compact read-only lists so the reviewer can inspect the shape without opening JSON. The panel also has `Save + build graph draft preview`, which runs the existing human-save, asset-candidate export, and graph-draft creation calls in order after the reviewer has chosen checklist decisions. A `Review-to-graph diff` card compares accepted checklist counts against exported asset counts and graph-draft counts, making broken handoff visible before any promotion is considered. `POST /panel/create_assisted_template_promotion_preflight` and the panel preflight button write `assisted_template_promotion_preflight_v1`, a manual audit preflight that can be ready or blocked but still keeps Runtime promotion disabled; blocker details now include the failed check, reason, and recommended action. If that preflight is ready, `POST /panel/create_assisted_template_audited_promotion_request` and the panel audit-request preview button can write `assisted_template_audited_promotion_request_v1`, listing the external audit confirmations required before a separate Runtime promotion design; it remains preview-only and keeps `ready_for_runtime_pathgraph_promotion=false`, `execute_binding_enabled=false`, and `artifact_is_authorization=false`. The current asset candidate is `artifacts\learning-draft-review\actual_parser_output_with_fusion_status_2da5f3e228\pathgraph_candidate\assisted_template_review\assisted_template_asset_candidate.json` with `asset_candidate_status=no_accepted_items` and `asset_validation_status=no_accepted_items`; the current graph draft is `artifacts\learning-draft-review\actual_parser_output_with_fusion_status_2da5f3e228\pathgraph_candidate\assisted_template_review\assisted_template_graph_draft.json` with `graph_draft_status=no_accepted_items`, because the current review record has no accepted items yet. The package, review record, acceptance suggestions, asset candidate, graph draft, preflight, and audited request preview keep `ready_for_runtime_pathgraph_promotion=false`, `execute_binding_enabled=false`, and `artifact_is_authorization=false`.



`POST /panel/create_assisted_template_acceptance_simulation` adds a no-write rehearsal step between suggestions and real review decisions. It reads `assisted_template_acceptance_suggestions_v1`, simulates accepting those linked groups, runs the same manual asset validation in memory, and writes `assisted_template_acceptance_simulation_v1` without saving a review record or creating a Runtime PathGraph. The current simulation artifact is `artifacts\learning-draft-review\actual_parser_output_with_fusion_status_2da5f3e228\pathgraph_candidate\assisted_template_review\assisted_template_acceptance_simulation.json`: accepting the 3 suggested groups would produce 10 accepted/exported/graph items and a simulated preflight status of `ready_for_audited_runtime_promotion_review`. The panel can apply those simulated choices back into the visible checklist as unsaved selections, so a reviewer can inspect the exact items before pressing Save. This is still only a preview for human review; it does not authorize Execute or promotion.



For the demo path, the panel now also has `Save + build audit preview`. It saves the current visible checklist decisions, exports the asset candidate, rebuilds the graph draft, runs promotion preflight, and only then creates the audited request preview if the preflight is ready. This button is a review scaffold only: a blocked preflight stops the chain, and even a ready audited request preview keeps Runtime PathGraph promotion and Execute binding disabled.



The same chain has a copied-artifact smoke report at `logs\benchmarks\assisted_template_audit_preview_chain_smoke_20260706\assisted_template_audit_preview_chain_smoke_report.json`. It proves the simulated choices can produce a ready preflight and audited request preview in a `logs` copy while keeping the source package unchanged (`source_artifact_writes=[]`).



The same corrected artifact now includes a review-only PathGraph preparation queue:



```text

logs\benchmarks\learn_precise_understanding_fusion_status_seek_full_corrected_20260705\learn_fusion_pathgraph_review_queue.json

```



The queue splits the 10 fused items into `open_detail_candidate_review=2`, `same_screen_action_review=5`, `geometry_review_required=1`, and `blocked_non_action=2`. The Learning Draft panel shows these counts in the Pipeline audit chips as `pathgraph_queue:*` and renders a Page Detail queue card with each region's review bucket, candidate semantic action, and required next evidence. This prepares human PathGraph review; it is not Runtime PathGraph promotion or Execute authorization.



The latest review-only PathGraph preflight plan is:



```text

logs\benchmarks\learn_precise_understanding_fusion_status_seek_full_corrected_20260705\learn_fusion_pathgraph_preflight_plan.json

```



It proposes 2 `open_detail` transition candidates from `seek_results` to `model_detail_view`, keeps 5 same-screen actions in review, and blocks 3 items before wiring. The panel renders this as a preflight Page Detail card. It is still not a Runtime PathGraph and does not authorize dispatch.



The preflight can also be converted into a review-patch proposal:



```text

logs\benchmarks\learn_precise_understanding_fusion_status_seek_full_corrected_20260705\learn_fusion_review_patch_proposal.json

```



That proposal contains 1 state addition, 2 `open_detail` action additions, 2 transition additions, 3 blockers, and 2 verification rules. It can be reviewed by a human and then passed to the existing reviewed-candidate save path; the save path forces all additions back to `candidate_only=true`, `execute_binding_enabled=false`, and `artifact_is_authorization=false`.



The proposal has also been smoke-built into a non-executable PathGraph candidate:



```text

artifacts\learning-draft-review\actual_parser_output_with_fusion_status_2da5f3e228\pathgraph_candidate\pathgraph_candidate.json

```



The candidate validation status is `passed_candidate` and it contains 2 pending detail-observe requests. This is still only candidate review evidence: `execute_binding_enabled=false`, `artifact_is_authorization=false`, and no Runtime PathGraph promotion has happened.



The same candidate has now been enriched with the offline detail-surface fixture and replayed through the promotion gate:



```text

logs\benchmarks\learn_fusion_pathgraph_candidate_status_20260705\learn_fusion_pathgraph_candidate_status_report.json

```



The chain now has `detail_attachment_status=attached`, `attached_request_count=2`, `attached_detail_region_count=2`, and `attached_detail_action_count=1`. Promotion replay shows the only remaining failed check is `current_screen_freshness`; action taxonomy, verification rules, blockers, final-submit safety, and no-dispatch policy pass.



## Runtime architecture direction (2026-07-01)



The project architecture is being reorganized around a general GUI Agent Runtime, not around a single website workflow.



The default execution model is now **Agentic Loop-first**:



```text

user conversation

-> Agent understands the goal and decides the next intent

-> Operation observes the current screen

-> Agent decides from current evidence

-> Gate checks the real action

-> Operation executes

-> Trace records evidence

-> observe again

```



`Workflow` / `PathGraph` is treated as a learned, reusable asset rather than the mandatory entry point for execution. When a matching PathGraph exists, the Agent may use it as guidance; when a screen is unfamiliar, the runtime still proceeds through observe -> decision -> gate -> operation -> trace.



Layer ownership is now explicit:



- `Agent`: conversation understanding, task decomposition, prompt editing/versioning, content decisions, `ask_user_required`, and PathGraph selection.

- `Operation`: screen understanding, locate, click, input, scroll, read, form detection, window/app adapters, and skill execution.

- `Gate`: candidate freshness, coordinate validation, action taxonomy, danger detection, final-submit blocking, and policy enforcement.

- `Trace`: prompt/output records, screenshots/OCR/UIA/DOM evidence, operation evidence, gate decisions, audit, replay, and learning input.

- `Workflow / PathGraph asset`: abstract workflow templates and concrete learned graphs with states, transitions, skill bindings, gate requirements, and verification rules.



The detailed architecture is documented in `docs\GUI_AGENT_RUNTIME_ARCHITECTURE.zh-CN.md`. The first code-level contract slice lives in `app\runtime_architecture\contracts.py`, with a reusable app profile template at `artifacts\templates\app_profile_template_v1.json`.



The code-level layer entry points are now explicit:



- `app\operation` exposes the framework operation skill catalog, including observe, locate, click, input, scroll, read, form detection, window binding, and verification.

- `app\operation.page_structure`, `app\operation.screen_reading`, `app\operation.screen_inventory`, and `app\operation.recognition` own the screen-understanding and recognition pipeline used by `/vision/*`.

- `app\operation.vision_protocol` owns the vision-action execution adapter on top of Operation primitives.

- `app\operation.region_click` owns reusable region-click execution used by MouseTester baselines and vision-protocol actions.

- `app\operation.mousetester` owns MouseTester-specific post-click semantic verification used by live execution and trace evaluation.

- `app\agent.profile` owns deterministic CV-to-candidate-profile extraction used by job-search profile tooling.

- `app\gate` exposes common contracts such as bound-window matching, candidate freshness, action taxonomy, scoped danger detection, scroll precondition/effect validation, scroll scope, latest-detail dataflow, contextual OCR normalization, and target-at-point validation.

- `app\trace` exposes trace event recording and execution-action trace write policy on top of the bounded trace writer.



New runtime code should import shared safety contracts from `app\gate`, operation helpers from `app\operation`, and trace policy from `app\trace`.



SEEK is now represented as an app/software profile, not the root architecture. Its current profile is `artifacts\app_profiles\seek_app_profile_v1.json`; it records SEEK-specific Agent prompt requirements, Operation skills, Gate contracts, Trace requirements, learned PathGraph assets, and final-submit policy.



SEEK learning has now been decomposed into reusable `learning_pattern_template_v1` assets under `artifacts\learning_patterns\`. The SEEK profile references six patterns: list/detail page handling, long detail reading, full-content Agent review, apply-entry boundary, multi-step form progression, and final-submit danger-zone blocking. These patterns are guidance assets for future app profiles; they do not authorize clicks or replace current observation, Agent decision, Gate checks, or Trace evidence.



The incorrect SEEK learning draft workflow has been removed from the runtime surface. `GET /runtime/learning/seek/draft`, `GET /runtime/learning/seek/tune`, `GET /runtime/learning/fixtures/{fixture_id}/draft`, and `GET /runtime/learning/generalization` are no longer panel/API learning modes because they encouraged fitting existing assets or hidden templates instead of proving that an Observe model can learn from the current screen. The low-level vision task `learn_pattern_draft` remains only as an experimental Observe-model prompt primitive for the next rebuild; it is not exposed as a promoted learning workflow.



The replacement starts with a generic, non-SEEK-specific trial endpoint: `GET /runtime/learning/model_trial`. It requires an explicit `image_path`, calls the Observe model with task `learn_template_draft`, scores the raw `learning_template_draft_v1` output, and feeds missing-section / safety / action-semantics failures back into the next attempt's parameters. It never patches a scored artifact and never promotes Profile or PathGraph changes. The endpoint exposes request-budget controls (`max_output_tokens`, `temperature`, `timeout_seconds`, `learning_image_max_edge`) so slow model failures become structured `model_error` attempts with scorer feedback instead of a hung workflow. The scorer now supports private template-similarity grading through `target_contract.reference_template`: states, action templates, interface regions, and safety are compared against the reference template, while final-submit / promotion / real-click safety checks remain hard gates. `strict_blind` validation hides app/state/goal/evidence/expected-actions/reference-template from the model prompt; the reference template is scorer-only. Timeout/no-draft attempts tune only runtime parameters for the same quality profile by default; prompt/token/schema optimization starts only after a scored draft exists. The fixed default learning parameters are Qwen3VL-8B, `temperature=0.0`, `max_output_tokens=768`, `timeout_seconds=180`, `learning_image_max_edge=256`, and the legacy request field `direct_use_accuracy_threshold=0.9`. Reports now name this score `draft_reference_alignment_score` with alias `template_similarity_score`; it must not be interpreted as model accuracy, click success rate, gate success rate, or SEEK E2E success. Current strict-blind evidence at `artifacts\learning-runs\strict_blind_8b_template_similarity_after_canonical_20260701-222931\trial_result.json` shows a raw model draft with `draft_reference_alignment_score=94.02%`; the derived loader artifact produces one safe `fill_field` action and dry-run Execute step without dispatch. This only proves the learning draft pipeline is initially runnable on a small search-input/template-draft subtask; it does not prove general website learning ability or SEEK E2E stability.



Model learning products now have a separate read-only loading path. `POST /panel/load_model_artifact` calls `app.learn.model_artifact_loader.load_model_learning_artifact()`, reads a `learning_model_trial_v1` result, keeps the source `trial_result.json` immutable, records the source SHA-256, and writes derived replay artifacts under `artifacts\model-artifact-loader\...`: `runtime_path_graph.json` and `interface_map.json`. The panel's Learn Replay page can load that model artifact path and then render the derived Runtime PathGraph / Interface Map through the existing replay surface. Model-loaded graphs use the `model_artifact_single_step` task template so the panel can run one complete dry-run step through `/execute/available_actions -> /execute/step` without dispatching real input/clicks. This loader is a format adapter only: it does not optimize or patch the model draft, does not promote profile changes, and does not authorize clicks or final submit. Real smoke evidence on `artifacts\learning-runs\strict_blind_8b_template_similarity_after_canonical_20260701-222931\trial_result.json` produced one input action (`a1`, `low_level_action_type=input`, taxonomy `fill_field`) and `/execute/step` planned it as a dry-run path-graph-assisted input action without dispatch.



The Learn Replay panel also has a display/review-only **Learning Draft Review** workspace. Learning Studio can now capture the currently bound window for a draft-only trial, run the current primary `POST /panel/run_learning_recognition_trial`, save the result under `artifacts\learning-runs\...\trial_result.json`, and load it as a DraftGraph Preview in the review panel. The panel endpoint converts current Learn Fast / Learn Deep evidence into a `learn_observe_bundle_v1`, including screen-understanding model role, coordinate-calibration model role, current screenshot, coordinate overlay, reviewed target counts, full calibrated target coordinate-validation evidence, and screen_map candidates. It then calls the common `build_learning_recognition_trial()` parser/classifier/grounding/validator pipeline and stores a non-executable `learning_template_draft_v1`. The draft now includes display-only `page_details`, so whole-screen understanding evidence, rejected/read-only page regions, grounding candidates, model roles, inventory counts, and screenshot context are visible in the Learning Draft page-detail panel without becoming executable actions. Bbox-bearing detail items also expose a `Preview box` / full-image inspector path that shows the whole source screenshot with the bbox / point overlaid; Learning Draft regions/actions can use the same inspector in `Edit box` mode to drag-select a corrected bbox and save it as `region_bbox_updates` / `action_bbox_updates` in the reviewed candidate. Reviewed candidates preserve previous/updated bbox and click point, and the panel shows an `edited bbox` badge plus before/after geometry in region/action lists and draft PathGraph Page Detail. `manual_bbox_edit_summary_v1` also summarizes edited counts, point-inside-bbox pass/fail, invalid geometry, and non-authorization flags; it is copied into generated PathGraph candidate wrappers and promotion validation reports. This does not dispatch clicks, bind Execute, or authorize the edited coordinates for real action. The older `POST /panel/run_learning_model_trial` remains as a compatibility/experimental model-trial endpoint, but it is no longer the default panel button path. `POST /panel/load_learning_draft_review` loads the raw `learning_template_draft_v1` from a recognition trial or reviewed candidate and renders states, regions, actions, blockers, verification rules, evidence source chips, page understanding details, and safety status in a template-like layout. The Learning Draft subinterface also renders its own read-only draft PathGraph preview and page-detail panel directly from the draft sections; it does not reuse Template Replay's shared PathGraph/Page Detail canvas and never authorizes Execute or clicks. Learn Fast / Observe is a clean workbench stage: previous Template Replay PathGraph and Page Detail content are hard-hidden and cleared there, and `observe_screen` / `screen_observation_v1` / `screen_map_v1` responses are not allowed to write or restore the shared PathGraph surface; screenshot preview and API response remain visible. For demo handoff, `/panel?stage=learn_replay&learn_view=draft&draft_source=...` can preload a raw trial or reviewed candidate directly into the Learning Draft subinterface; `generate_pathgraph_candidate=1` additionally builds the non-executable candidate and refreshes the preview from the saved reviewed candidate. `POST /panel/save_learning_draft_review` lets the reviewer save a simple edited candidate without hand-editing JSON/Markdown. `POST /panel/generate_pathgraph_candidate` then turns the reviewed draft into a non-executable `pathgraph_candidate.json` wrapper plus `runtime_path_graph_candidate.json`, `interface_map_candidate.json`, and `promotion_validation_report.json`; the candidate runtime graph and interface map preserve `page_details` as read-only review context with `display_only=true`, `candidate_only=true`, and `execute_binding_enabled=false`. Saved candidates are forced to `source_after_review=mixed` or `assisted_generation`, `counts_as_pure_model_generated=false`, `artifact_is_authorization=false`, `execute_binding_enabled=false`, `authorization_scope=display_and_review_only`, and `final_submit_forbidden=true`. The Learning Studio trial result is `learn_recognition_trial` / `draft_only`, and the generated PathGraph is still only a candidate; neither is a promoted Runtime PathGraph, prompt/config improvement, click authorization, or Execute authorization.



Learning Draft Review also records `source_freshness_summary_v1` beside manual bbox edits. Missing source images, missing screenshot checksums, missing files, and checksum mismatches are surfaced as panel/wrapper/report warnings so human-edited geometry cannot look cleaner than its evidence. These warnings are audit-only and do not enable Execute binding or click authorization.



For a no-live-automation demo of those warning states, run `uv run python scripts\create_learning_draft_freshness_demo_fixtures.py --json`. It creates `artifacts\learning-draft-freshness-demo\freshness_demo_summary.json` plus three reviewed/PathGraph candidate samples: checksum matched, source file missing, and checksum mismatch. The summary now also records `pathgraph_promotion_review_gate_v1` replay outcomes: checksum matched can reach `passed_for_human_promotion_review`, while missing file and checksum mismatch are blocked by `current_screen_freshness`. The Learning Draft Review panel has a small `Load freshness demo` control that loads those reviewed candidates directly. These samples are offline display/review fixtures only; they do not call a model, click, fill, submit, or authorize Execute.



Promotion-review gate replay is also available for existing PathGraph candidates. Run `uv run python scripts\report_pathgraph_promotion_gate_replay.py --candidate-glob "artifacts/learning-draft-review/*/pathgraph_candidate/pathgraph_candidate.json" --out logs\benchmarks\pathgraph_promotion_gate_replay_20260705 --json` to produce `logs\benchmarks\pathgraph_promotion_gate_replay_20260705\pathgraph_promotion_gate_replay_report.json`. `scripts\bind_pathgraph_candidate_source_freshness.py` can also bind an existing source-trial screenshot path/checksum into a reviewed candidate copy and rebuild a candidate; it refuses missing or mismatched screenshots and never captures a new screenshot. The latest SEEK binding run wrote `logs\benchmarks\pathgraph_candidate_source_freshness_bind_seek_20260705\source_freshness_bind_result.json`, then replayed `logs\benchmarks\pathgraph_promotion_gate_replay_after_seek_freshness_bind_20260705\pathgraph_promotion_gate_replay_report.json`: 18 candidates, 15 non-demo, 3 demo, 1 non-demo `passed_for_human_promotion_review`, 1 demo `passed_for_human_promotion_review`, and 16 blocked. The new SEEK candidate proves current-screen freshness can be bound from real non-demo evidence, but it is still blocked from full readiness by missing detail-surface attachment/pending observe evidence. These reports are offline evidence audits only; they do not promote a Runtime PathGraph, bind Execute, click, fill, or submit.



Learn Deep coordinate preview now has a hard visual-target overlap and noise gate. Deterministic non-containment overlap pruning runs even when model review is skipped, the final `learn_all_targets` overlay removes parent container boxes when a higher-priority child action/link/input is selected inside them, and browser toolbar / address-bar / tab chrome plus tiny noise boxes are filtered before targets are rendered. Parent-child structure can still exist in the review data, but the final coordinate calibration overlay should not present stacked selectable regions as separate targets.



Learn Recognition now has an explicit layout-cleanup layer for the new learning-mode front half. `app.learn.recognition.layout_cleanup` runs after raw parser inventory and before classification / draft generation, merging duplicate same-target boxes and suppressing large semantic-only containers over concrete child actions. Actual parser smoke outputs now keep both `raw_screen_inventory` and cleaned `screen_inventory` plus a `learn_layout_cleanup_report_v1` audit record. This is a review/display and PathGraph-preparation step only; it is not an Execute authorization, click-success metric, live safe-fill result, or 90% recognition claim.



`Learn Layout Graph v1` now turns cleaned inventory into a display-only page structure before eligibility and ROI grounding. It groups candidates into surface zones, records node parent/child relationships, preserves reading order, and flags overlapping distinct targets as `split_roi_required`. Pipeline results, learning-draft `page_details`, actual parser smoke outputs, and batch reports now expose this graph or its summary. This gives the panel and future overlay work a structured way to show why boxes are grouped or need ROI splitting, without treating the graph as click authorization or reliability evidence.



`Grounding Eligibility Gate v1` now sits after cleanup and before ROI grounding. Cleaned candidates receive `evidence_strength`, `grounding_eligible`, `review_only`, `grounding_block_reason`, and `eligible_for`; smoke/batch reports expose `grounding_eligibility_gate` and `non_actionable_leaked_to_grounding`. `grounding_eligible=true` only means the candidate may be sent to ROI grounding for learning evidence. It does not authorize clicks, does not bind Execute, does not promote a PathGraph, and is not an accuracy metric.



Learn Recognition now also has the first surface-zone / split-ROI diagnostics. Browser chrome controls such as address bars, browser toolbars, tabs, and extension buttons are blocked as `browser_chrome_not_page_surface` before ROI grounding. Overlapping distinct eligible targets are preserved but marked with `roi_diagnostic.split_roi_required=true`, and batch reports aggregate `browser_chrome_rejection` plus `split_roi_required`. These are diagnostics for the next two-stage locator/ROI split work; they are not click-success, Execute, PathGraph, or reliability metrics.



Same-screenshot support repair now has an operator queue export. `uv run python scripts\build_learn_recognition_support_acquisition_queue.py --diagnosis-report <learn_pathgraph_readiness_blocker_diagnosis_report.json> --out <queue.json> --json` reads readiness diagnosis `support_repair_targets` and produces ordered acquisition tasks for missing UIA/OmniParser/calibrated-target support or bbox-alignment repair. The latest local queue is `logs\benchmarks\learn_recognition_support_acquisition_queue_next\support_acquisition_queue.json`: 4 tasks, 3 same-screenshot support captures, and 1 bbox/coordinate repair. Queue preflight checks screenshot existence, screenshot SHA-256 match, required scripts, and manifest presence; the current queue is `preflight_ready_count=4` / `preflight_blocked_count=0`. This means the next acquisition step is ready to run, not that support has been captured. P1 capture tasks still require the operator to reproduce the target window/screenshot state; `capture_learn_recognition_same_screenshot_support.py` captures the current bound window and does not read the saved screenshot as input. This queue is planning-only; it does not capture windows by itself, start models, run grounding, create PathGraph candidates, or authorize Execute.



Learn Mode recognition is now entering a rebuild phase. The current Learn Deep / `learn_all_targets` overlay remains useful as compatibility and diagnostics, but it is no longer the intended primary architecture for new learning experiments. The approved design is documented in `docs/superpowers/specs/2026-07-03-learning-recognition-rebuild-design.md`, with an implementation plan in `docs/superpowers/plans/2026-07-03-learning-recognition-rebuild-plan.md`. The new front half will parse a typed `screen_inventory_v2`, reject OCR-only/readable/semantic-only non-actionable regions, ground only actionable/form-field candidates with ROI crop + coordinate transform, and validate evidence before producing the existing display-only `learning_template_draft_v1`. Execute Mode model profiles, Gate, Trace, final-submit blocking, and the Learning Draft Review -> PathGraph candidate pipeline remain preserved.



The first Learn Recognition slice now exists under `app.learn.recognition`: contracts create non-executable `screen_inventory_item_v2` / `learning_template_draft_v1` structures, parser adapters convert existing OCR/UIA evidence into inventory without authorizing clicks, and the classifier rejects OCR-only text, code blocks, readonly cards, ungrounded semantic regions, and tiny calibrated noise boxes before grounding. Inventory items now also carry a read-only `parser_candidate_v1` evidence projection with `source_type`, `screenshot_sha256`, `coordinate_space`, `evidence_kind`, preliminary `review_only` / `grounding_eligible`, freshness, and authorization flags. This gives Qwen VLM, OCR, UIA, OmniParser, calibrated targets, and no-dispatch Execute candidates one common pluggable parser shape while preserving the rule that semantic-only / OCR-only evidence stays review-only unless same-screenshot interactable support exists. This is not a model download or accuracy claim yet; it is the safety/structure boundary for later ROI grounding and benchmark work.



The second slice adds replayable ROI grounding scaffolding: `build_roi_crop_metadata()` records `coordinate_transform_v1`, `restore_local_point_to_screen()` restores crop-local points to the source screenshot, and `validate_grounding_candidate()` rejects stale evidence, missing transform replay, point-outside-bbox, non-actionable content, and danger-zone/final-submit-like targets. This still does not call a grounding model or authorize Execute; it prepares the contract needed before any UGround/GUI-Actor/OmniParser experiment can be trusted.



The third slice adds the minimum Learn Recognition pipeline: `build_learning_recognition_trial()` connects existing OCR/UIA parser output, conservative classification, ROI metadata, a pluggable grounding adapter, hard validation, and the existing display-only `learning_template_draft_v1`. The pipeline result can be loaded by Learning Draft Review, but it remains non-executable and returns `needs_grounding_adapter` when no grounding adapter is supplied rather than inventing coordinates.



Validated Learn Recognition items now bridge into the downstream draft/PathGraph-candidate surface instead of stopping at raw coordinates. `learning_template_draft_v1` generated from validated grounding candidates includes region/action linkage, bbox/click-point evidence, default final-submit/stale-grounding blockers, verification rules, operation-skill hints, and gate-contract references. Its `page_details.pipeline_audit` now carries display-only BBox Cleanup, Grounding Eligibility Gate, and ROI validation summaries so the panel can show why candidates were removed, blocked, or accepted before human review. A focused regression proves this draft can be saved and converted into a `passed_candidate` non-executable PathGraph candidate through the existing review path. This is a structural handoff for demo/review and future promotion checks; it is not Execute authorization, live safe fill, live click, or SEEK E2E evidence.



The Learn Recognition benchmark scaffold is `scripts\run_learn_recognition_benchmark.py` with manifest `artifacts\benchmarks\learn_recognition_golden_manifest_v1.json`. It emits layered metrics (`parse_inventory`, `actionable_classification`, `form_field_classification`, `non_actionable_leaked_to_grounding`, `semantic_bbox_without_interactable_evidence`, `non_actionable_rejection`, `danger_zone_rejection`, `wrong_surface_rejection`, `roi_target_coverage`, `grounding_point`, `coordinate_transform`, `pathgraph_candidate_validation`) while excluding invalid fixtures from denominators. It now also reports `support_eligibility_summary` from shared `parser_candidate_v1` support logic, including source/evidence-kind distribution, same-screenshot interactable support, stale/missing candidate contracts, and semantic/OCR leakage. The latest support-eligibility report is `logs\benchmarks\learn_recognition_support_eligibility_shared_module\learn_recognition_benchmark_report.json`: 95 parser candidates, `semantic_or_ocr_leaked_to_grounding=0`, `missing_parser_candidate_contract=0`, and only 6 same-screenshot interactable support candidates, which keeps the next work focused on evidence acquisition rather than grounding-score promotion. This is not a 90% accuracy claim, not model ability evidence, and not Execute stability evidence.



The same runner also accepts minimal recorded-output cases through `recorded_parser_output_path` and `recorded_grounding_output_path`. Recorded parser/grounding outputs can now carry model-profile provenance, including profile-aware Qwen3-VL 8B parser replay and UGround/GUI-Actor grounding replay. Recorded-output reports mark these as `recorded_*_minimal_coverage`, not reliability proof; `actual_parser_call` and `actual_grounding_call` remain zero in offline manifest reruns.



The bounded actual-parser batch path is separate from the offline manifest. The latest Qwen3-VL 8B fixed-screenshot rerun is `logs\benchmarks\learn_recognition_actual_parser_batch_qwen8b_grounding_backlog_20260704\learn_actual_parser_batch_report.json`: 6/6 actual parser calls produced inventory, 2/6 cases produced grounding candidates, and every supplemental source used by the current manifest has a matching screenshot checksum. Two older python screenshots were deliberately moved back to review-only because their calibrated support came from a different source screenshot. Supplemental source files with `screenshot_sha256` are verified against the case screenshot; mismatches become invalid stale fixtures and do not enter parser denominators. Actual parser smoke now writes the current screenshot SHA256 into `learn_observe_bundle_v1` / `actual_parser_output_v1` and both smoke and batch reports expose the same `support_eligibility_summary` used by the offline benchmark. Batch reports expose `supplemental_source_validity_summary`, `grounding_candidate_backlog`, and support eligibility, so support freshness and PathGraph-wiring blockers are visible without hand-inspecting each case. Qwen's SEEK header vision bboxes still remain review-only when they do not overlap interactive evidence. Status report `logs\benchmarks\learn_recognition_experiment_status_20260704_pathgraph_readiness\learn_recognition_experiment_status_report.json` keeps the 90% target as not evaluable and adds `pathgraph_connection_readiness`: 2 cases are ready for PathGraph candidate review, 4 cases remain blocked, and the status is `not_ready_for_pathgraph_candidate_promotion`. The blocker diagnosis report `logs\benchmarks\learn_recognition_pathgraph_readiness_diagnosis_support_discovery_v2_20260704\learn_pathgraph_readiness_blocker_diagnosis_report.json` now includes same-screenshot support discovery across `artifacts` and `logs`: the 2 ready cases have matching interactable support, while all 4 blocked cases have `no_matching_support_json_found` for their screenshot SHA256. They must stay blocked until same-screenshot OCR/UIA/OmniParser/calibrated-target support or real bbox alignment evidence exists.



Same-screenshot support repair now has a stricter probe path. `scripts\create_learn_recognition_calibrated_support.py` can turn a saved screenshot plus reviewed target bboxes into a checksum-bound `learn_recognition_same_screenshot_support_v1` artifact. The first probe for `python_homepage_saved_template_screenshot` found exact-SHA calibrated support, and the updated readiness report `logs\benchmarks\learn_recognition_support_repair_coordinate_recovery_root_cause_v1\learn_pathgraph_readiness_blocker_diagnosis_report.json` keeps the case blocked while refining the cause: `root_cause=coordinate_space_recovery_needed`, `block_reason=same_screenshot_support_found_but_coordinate_recovery_not_applied`, `bbox_alignment_audit.status=support_found_but_bbox_alignment_failed`, `attempted=2`, `passed=0`, and `coordinate_failure_categories={"implicit_normalized_1000_recovery_needed":2}`. The raw Qwen output appears to use normalized 0-1000 coordinates even though it declares the 1280x660 inference image size; applying normalized-1000 recovery would align both search controls with reviewed support, but the old recorded parser output remains blocked until rerun through the opt-in recovery path and support alignment gate. This is coordinate-contract evidence, not PathGraph promotion, Execute binding, model accuracy, or a 90% recognition claim.



The same support artifact can now be replayed into the display-only draft bridge when it is explicitly provided as supplemental evidence. `scripts\bind_learn_recognition_support_to_manifest.py` resolves repo-relative screenshot paths before checksum binding, and `scripts\run_learn_recognition_actual_parser_smoke.py` can replay reviewed calibrated target click points through `grounding_validations` into `learning_template_draft_v1` regions/actions. The saved replay report is `logs\benchmarks\learn_recognition_python_saved_calibrated_support_replay_v2\learn_actual_parser_smoke_report.json`: it produced 2 grounding validations, 2 draft regions, and 2 draft actions from recorded Qwen output plus exact-SHA reviewed support. This is a display/review bridge for the Learning Draft panel; it does not override the parser bbox-alignment failure above, does not authorize Execute/clicks, and is not fresh model ability or 90% recognition evidence.



Recorded provider raw text can now be replayed through the same coordinate recovery and draft pipeline without starting a model. `replay_recorded_provider_raw_text()` marks `source_type=recorded_provider_replay`, keeps `actual_model_call.attempted=0`, and preserves raw parsed JSON separately from runtime-normalized JSON. The cleanup metrics rerun is `logs\benchmarks\learn_recognition_python_saved_recorded_provider_replay_cleanup_metrics_v1\learn_actual_parser_smoke_report.json`: recorded Qwen raw_text plus exact-SHA calibrated support produced 2 unique accepted grounding candidates, 2 grounding validations, 2 draft regions, and 2 draft actions after opt-in normalized-1000 recovery. `layout_cleanup` now reports `suppression_reason_counts={"cross_evidence_support_duplicate":2}` and suppresses the duplicate standalone support entries as explicit cross-evidence support merges, while `semantic_or_ocr_leaked_to_grounding=0`. This proves the coordinate-contract replay path can feed the existing Learning Draft / PathGraph-candidate review surface with duplicate support evidence merged and auditable; it is not a fresh model call, not an Execute authorization, and not a reliability or 90% recognition claim.



SEEK job-card candidates now have an explicit review-only open-detail transition hint. The multi-card dry-run report `logs\benchmarks\learn_locator_card_open_detail_multi_probe_20260705\numbered_region_calibration_report.json` validates two SEEK job cards through the full dry-run pre-click path with `real_clicks=0`. The replay output `logs\benchmarks\learn_locator_card_open_detail_multi_replay_transition_v1_20260705\actual_parser_output_v1.json` produces two non-executable `open_detail` actions, each with `learn_open_detail_transition_hint_v1` pointing toward a future detail-view observe step. The PathGraph candidate loader now turns those hints into review-only graph transitions: `artifacts\learning-draft-review\actual_parser_output_v1_fefeffe256\pathgraph_candidate\runtime_path_graph_candidate.json` contains two `seek_results -> model_detail_view` `open_detail` candidate edges. The Learning Draft panel renders the same hint in action metadata, derives a read-only `model_detail_view` preview node, and shows the edge in a Page Detail `Candidate transitions` card without inheriting source-page regions/actions into the derived detail node. This is PathGraph-candidate review evidence only; it does not promote a Runtime PathGraph, bind Execute, or authorize clicks.



Reviewed candidates and PathGraph candidates now expose `precise_understanding_summary_v1`. The summary is written to the reviewed candidate audit, the PathGraph candidate wrapper, and the validation report, so the panel and future review tooling can inspect a compact fused-understanding snapshot. The latest SEEK two-card replay records 2 bbox regions, 2 action click points, and 2 open-detail transition hints while keeping `candidate_only=true`, `artifact_is_authorization=false`, and `execute_binding_enabled=false`. This is not an accuracy metric and not Execute authorization.



Open-detail candidates also produce `pending_detail_observe_request_v1` entries. For the latest SEEK two-card replay, the PathGraph candidate wrapper and validation report contain 2 pending detail-observe requests from `seek_results` to `model_detail_view`, one per `open_detail` action. Each request is review-only (`requires_user_review=true`, `no_dispatch=true`, `candidate_only=true`, `execute_binding_enabled=false`) and exists only to queue the next safe learning step: observe the detail surface and merge that new understanding into the same candidate graph.



The first offline detail-surface attachment path is also available. `attach_detail_observe_result_to_candidate()` consumes one pending detail-observe request and a detail learning draft/trial, then namespaces that detail surface under `model_detail_view::*` inside the same candidate graph and interface map. The local fixture `logs\benchmarks\learn_detail_surface_attachment_fixture_20260705\detail_trial_result.json` attaches to the SEEK two-card candidate and updates the summary to 2 states, 4 regions, 3 actions, and 1 detail-surface attachment. `POST /panel/attach_detail_observe_result` exposes the same review-only merge path to the panel, and Learning Draft PathGraph Preview now has candidate path / pending request select / request id / recent detail draft select / detail source controls plus a bound attach button. Candidate generation and attachment responses refresh the pending request select, and `GET /panel/learning_draft_sources` fills the recent detail draft select from loadable learning drafts/trials, so the reviewer can choose both the request and detail source instead of manually copying ids and paths. After attachment, the panel reloads the updated `pathgraph_candidate.json`; Page Detail shows `PathGraph readiness`, `Detail attachments`, attached detail regions, and attached detail actions. `load_learning_draft_review(pathgraph_candidate.json)` also returns `pathgraph_candidate_review_v1` with `pathgraph_candidate_readiness_summary_v1` and `pathgraph_promotion_review_gate_v1`, so the fused list/detail evidence, promotion blockers, gate status, and failed checks remain inspectable after refresh. The gate checks current-screen freshness, action taxonomy, verification rules, blockers, final-submit safety, and no-dispatch policy. This is a no-dispatch review path only; it does not prove a live click, live observe, or Execute readiness.



Parser adapters now include an OmniParser-style input shape: `sources.omniparser.parsed_content_list[*]` with `type`, `content`, normalized or absolute `[x1,y1,x2,y2]` bbox, `interactivity`, and `source`. Interactive elements become non-authorizing actionable inventory candidates; non-interactive text remains readable/non-actionable. This is adapter coverage, not a real OmniParser model call.



The OmniParser-style recorded parser coverage now includes search, form fields, readonly helper text, and final-submit danger-zone surfaces. The latest report is `logs\benchmarks\learn_recognition_omniparser_recorded_parser_expansion\learn_recognition_benchmark_report.json` with 40 manifest cases and `recorded_parser_output=8`; `Email`, `Mobile phone`, and `Cover letter` classify as form fields, while `Submit application` is rejected as a danger zone. This remains recorded parser evidence only, not fresh OmniParser inference and not a reliability trend.



Parser adapters also include `sources.execute_candidate_result.candidates[*]` for recorded Execute recognition-plan traces. The adapter maps prior `candidate_result` elements into learn-only inventory with `source_evidence=["execute_candidate_result"]` and `interactable_evidence.execute_candidate_ranked=true`, while keeping `click_candidate=false`, `artifact_is_authorization=false`, and `execute_binding_enabled=false`. This lets existing docs / Google News recognition traces expand recorded parser coverage without treating Execute candidates as new authorization.



Recorded grounding adapters now also include a UGround-style ROI point shape. A recorded output may declare `coordinate_space=uground_0_999` / `normalized_0_999`, return a raw string such as `(500, 500)`, and the runner restores that ROI-local point through `coordinate_transform_v1` before validation. This is adapter coverage, not a real UGround model call.



The Learn Recognition benchmark now also reports recorded grounding evidence by model profile. The UGround recorded-per-model slice adds `learn_mode_uground_2b` and `learn_mode_uground_7b` samples to the manifest and writes `recorded_model_profile_breakdown` in `logs\benchmarks\learn_recognition_uground_recorded_profile_evidence\learn_recognition_benchmark_report.json`. The report has 42 manifest cases, `recorded_grounding_output=4`, and `actual_grounding_call=0`; this proves the UGround-style contract and ROI coordinate replay can be ingested, not that UGround 2B/7B has been freshly run or is reliable.



The same recorded-per-config path now includes two SEEK-header counterfactuals for real VISTA misses: `recorded_grounding_uground_7b_seek_search_button_point_valid` and `recorded_grounding_gui_actor_7b_seek_pay_filter_point_valid`. The latest report is `logs\benchmarks\learn_recognition_seek_recorded_per_config_counterfactual\learn_recognition_benchmark_report.json` with 45 manifest cases, `recorded_grounding_output=6`, `actual_grounding_call=0`, and profile breakdown entries for `learn_mode_uground_7b` and `learn_mode_gui_actor_7b`. This proves the same ROI/Validator contract can ingest alternative model-style points for the SEEK miss cases; it is not a fresh UGround 7B/GUI-Actor call and not model reliability evidence.



For the next actual-call step, `scripts\run_learn_recognition_actual_grounding_smoke.py` is now profile-aware. It accepts `--model-profile learn_mode_uground_2b` or another learn-only profile, records that profile in the single-case report, saved `actual_grounding_output_v1.json`, and batch `actual_model_profile_breakdown`, and resolves `model_config.model_name` from the profile when `--model` is not explicitly provided. It also runs `learn_actual_grounding_model_profile_readiness_v1` before calling a model: metadata-only, not-downloaded, non-launchable, or endpoint-missing profiles are blocked before model invocation and excluded from the actual-call denominator. UGround 2B has since been materialized and smoke verified as a learn-only local grounding profile on port `1245`; older readiness-preflight reports that blocked it as `model_profile_not_downloaded` are historical setup evidence, not the current profile state.



Current UGround 2B matrix evidence is `logs\benchmarks\learn_recognition_grounding_model_matrix_uground2b_current\learn_grounding_model_matrix_report.json`. It proves the learn-only UGround 2B endpoint can run through the ROI / coordinate-transform / Validator contract, but it also reports `point_center_bias_diagnostic.status=center_bias_risk`: most raw outputs are near normalized center `(500,500)`. This means the current 9/9 Validator pass is not reliability evidence and must not be reported as 90% accuracy, PathGraph execution, live click success, safe fill, or submit coverage. The next matrix needs non-centered crops and hard negatives where center-point answers fail.



The updated off-center matrix is `logs\benchmarks\learn_recognition_grounding_model_matrix_uground2b_offcenter\learn_grounding_model_matrix_report.json`. It expands the fixed candidate set to 15 cases with three benchmark-only `roi_bbox_override` hard cases. UGround 2B now has 11 passed / 12 attempted fresh ROI calls and one `model_point_outside_roi_candidate_bbox` failure, while still reporting `center_bias_risk`. Treat this as evidence that the benchmark is starting to expose center-point shortcuts, not as recognition reliability.



A learn-only VISTA baseline profile now wraps the existing local VISTA endpoint for bounded Learn Recognition experiments: `configs\model_profiles\learn_grounding_vista_4b_baseline.json`. It does not replace or mutate Execute Mode's `vista_4b_transformers` profile. The first profile-aware actual grounding baseline report is `logs\benchmarks\learn_recognition_actual_grounding_vista_profile_baseline\learn_actual_grounding_smoke_batch_report.json`: 5 calibrated-target ROI cases from one saved python.org screenshot, `actual_model_call.attempted=5`, `passed=5`, and `actual_model_profile_breakdown.actual_model_call.learn_grounding_vista_4b_baseline=5`. A second mixed baseline report, `logs\benchmarks\learn_recognition_actual_grounding_vista_mixed_baseline\learn_actual_grounding_smoke_batch_report.json`, uses `artifacts\benchmarks\learn_recognition_actual_grounding_vista_baseline_cases_v1.json` and separates 6 fresh VISTA ROI calls from 3 fixture-precondition safety stops (`case_count=9`, `actual_model_call.attempted=6`, `passed=6`, `blocked=3`, `blocked_categories.fixture_precondition_failed=3`). A saved SEEK header follow-up at `logs\benchmarks\learn_recognition_actual_grounding_vista_seek_header_point_quality\learn_actual_grounding_smoke_batch_report.json` ran 3 fresh VISTA ROI calls and intentionally preserves 2 model point misses as `model_point_outside_roi_candidate_bbox`, with Validator rejecting both bbox-outside points. This is still small saved-screenshot actual-call evidence and failure taxonomy, not a reliability trend or 90% recognition claim.



Learn Mode now also has sub-12B experiment profiles with explicit readiness status. `learn_mode_qwen3_vl_8b` is a learn-only wrapper around the existing local Qwen3-VL 8B understanding endpoint and weights; it is `launchable=true` for semantic inventory / learning-draft structure only, remains outside Execute defaults, and cannot authorize clicks. `learn_mode_uground_2b` is also now a learn-only launchable local ROI grounding candidate after materialization and no-action smoke verification. UGround 7B, ShowUI, GUI-Actor 3B/7B, and OmniParser V2 remain metadata-only / not-downloaded candidates until their actual/per-config evidence is available.



The UGround download/setup choice is now captured in `logs\benchmarks\learn_recognition_model_download_choice_v1\download_choice_report.json`. `learn_mode_uground_2b` is the risk-first materialization option for a smaller adapter-launch smoke, while `learn_mode_uground_7b` remains the quality-first option for testing current VISTA small-control misses. This is setup-order evidence only, not model ability, accuracy, live click, Execute authorization, or profile promotion.



The first Learn Recognition actual parser smoke is `logs\benchmarks\learn_recognition_actual_parser_qwen8b_python\learn_actual_parser_smoke_report.json`. It used Qwen3-VL 8B on a saved python.org full-window screenshot and produced 12 semantic `vision_regions_v1` regions, then saved replay evidence at `artifacts\benchmarks\learn_recognition_recorded_outputs\qwen8b_python_homepage_actual_parser_output_v1.json`. The profile-aware rerun is `logs\benchmarks\learn_recognition_actual_parser_learn_qwen8b_profile\learn_actual_parser_smoke_report.json`; it uses `--model-profile learn_mode_qwen3_vl_8b`, records the learn-only profile provenance, and again keeps all 12 regions as review-only semantic inventory. The replay benchmark `logs\benchmarks\learn_recognition_actual_parser_replay\learn_recognition_benchmark_report.json` intentionally keeps those regions as `semantic_region_only`: they become screen inventory / review evidence, not grounding authorization.



The classifier and benchmark now include a grounding eligibility gate. Every classified item records `grounding_eligible`, `review_only`, and `grounding_block_reason`; Qwen semantic-only regions without UIA/DOM/OCR/OmniParser/calibrated-target interaction evidence are marked `review_only=true` and `grounding_eligible=false`. Benchmark reports include `semantic_only_rejection`, `grounding_eligibility_breakdown`, and `parser_output_quality`, so parser usefulness for review is kept separate from ROI grounding, click success, PathGraph execution, or Execute authorization.



The first cross-evidence adapter is now wired in the parser layer. A Qwen/VLM semantic region may become `cross_evidence_grounded` only when it overlaps real interaction evidence from UIA, OmniParser, calibrated targets, or recorded Execute candidates; broad parent regions that merely contain a small control remain review-only. The current report is `logs\benchmarks\learn_recognition_cross_evidence_gate\learn_recognition_benchmark_report.json` with 38 cases. This is an eligibility-gate scaffold, not a reliability or accuracy claim.



Learning Draft Review now has a display-only `Screen Understanding Preview` for Learn Recognition sources that include `classification`. It shows review-only semantic/non-actionable regions, grounding candidates, and danger zones separately, so the learning draft demo can reveal what the parser/classifier saw without loading Template Replay, binding Execute, or authorizing clicks.



The detailed Learn Recognition parser / model / two-stage grounding boundary is documented in `docs\LEARN_RECOGNITION_PARSER_AND_GROUNDING.zh-CN.md`. In short, parser providers are evidence adapters: they translate OCR/UIA/DOM/OmniParser/VLM/calibrated-target evidence into `screen_inventory_v2`; whole-screen understanding only proposes page states, regions, actions, non-actions, and danger zones; ROI grounding only proposes candidate points; Validator/Gate still decide whether evidence is acceptable. The document now explicitly separates current launchable learn-only profiles from metadata-only candidates, and spells out the two-stage flow from full-screen parser evidence to ROI crop, coordinate-transform replay, validation, display-only draft, and PathGraph candidate. The output remains `learning_template_draft_v1` for display/review and PathGraph candidate generation, not Execute authorization.



Learn Recognition now also ingests validated Learn Deep / locate output as `sources.calibrated_targets`: only targets with valid `coordinate_validation` become grounding candidates, and the latest recorded-parser benchmark report is `logs\benchmarks\learn_recognition_calibrated_targets_parser_final\learn_recognition_benchmark_report.json`. The calibrated-target actual VISTA ROI batch first exposed a service contract issue: the old VISTA server labeled pixel-like points as `normalized_0_1000`, and a later prompt included fixed numeric examples that the model copied. The current endpoint supports `coordinate_space=roi_local_point`, the smoke prompt no longer includes fixed coordinate examples, and the latest 5-case fresh actual grounding smoke is `logs\benchmarks\learn_recognition_actual_grounding_smoke_batch_v2_prompt3\learn_actual_grounding_smoke_batch_report.json` with `passed=5/attempted=5`. This is a small saved-screenshot ROI smoke only, not a reliability trend, not a 90% claim, and not Execute authorization.



New-site validation evidence: `artifacts\learning-runs\new_site_python_org_20260702_after_similarity_fix\trial_result.json` was generated from a fresh python.org screenshot, not from SEEK assets. The raw model draft produced `draft_reference_alignment_score=92.58%` under strict-blind template similarity after the scorer learned that homepage search surfaces can transfer to the generic search-input template when the required search action and search/input region are present. Low-scoring or contested cases now require a `human_adjudication` record with an explicit scope such as `search_input_subtask_only`; they cannot be silently reclassified as scorer false negatives. Loading that trial through `POST /panel/load_model_artifact` produced a read-only `python.org` PathGraph with three safe actions; `/execute/step` planned the first `fill_field` action as dry-run input with no dispatch.



SEEK MVP benchmark evidence is now reviewer-style and layered, not a single success-rate claim. The fixed small manifest is `artifacts\benchmarks\seek_mvp_golden_manifest_v1.json` and is rerun with:



```powershell

uv run python scripts\run_seek_mvp_benchmark.py `

  --manifest artifacts\benchmarks\seek_mvp_golden_manifest_v1.json `

  --out logs\benchmarks\seek_mvp_%DATE% `

  --no-submit `

  --json

```



The benchmark emits per-layer `passed / attempted / rate`, uses metric-level `not_covered` when `attempted=0`, splits `scroll_dispatch` from `scroll_effect`, lists failed cases with failure category / trace path / screenshot path / expected / actual / root cause / proposed fix, and records `safe_stop` / `unsafe_prevented` separately. The manifest currently has 40 cases and classifies read terminal states, scroll effects, the external-ATS login safe-stop chain, two checksum-stable confirmed-point fixtures, one recognition-plan/VISTA point success fixture, one recognition-plan/VISTA point miss that is blocked by Gate, and fixture-only safe-fill decisions for allowed, sensitive, unsupported, final-submit, wrong-surface, and modal-blocked fields. It does not report one aggregate SEEK success rate. The previous point-grounding failure is treated as `invalid_point_grounding_fixture / evidence_missing`, so it is excluded from the point-grounding attempted denominator and reported through fixture validity. Current point-grounding coverage distinguishes `coverage_status=minimum_categories_covered` from `reliability_status=insufficient_sample_size`. `safe_fill_fixture` reports fixture-only classification evidence and redacted/hash-length value evidence; live `safe_fill` remains `not_covered`. This is still benchmark evidence only, not SEEK MVP end-to-end or live safe-fill stability evidence.



### Model-learning template feedback loop



Model-generated `learning_template_draft_v1` outputs now have a fixed offline benchmark and a bounded negative-feedback loop. The benchmark checks whether a raw model draft can become an Agent-usable template candidate by validating required template fields, final-submit safety, loader compatibility, and deterministic agent dry-run usability against fixed fixtures.



Baseline rerun:



```powershell

uv run python scripts\run_model_learning_template_benchmark.py `

  --manifest artifacts\benchmarks\model_learning_template_dev_manifest_v1.json `

  --out logs\benchmarks\model_learning_template_baseline `

  --json

```



Feedback-loop rerun:



```powershell

uv run python scripts\run_model_learning_feedback_loop.py `

  --manifest artifacts\benchmarks\model_learning_template_dev_manifest_v1.json `

  --holdout-manifest artifacts\benchmarks\model_learning_template_holdout_manifest_v1.json `

  --out logs\benchmarks\model_learning_feedback_loop_v2 `

  --max-trials 5 `

  --json

```



The loop changes only one parameter or strategy per trial on the dev manifest, then reruns the selected config on both dev and holdout manifests. Holdout results are final-evaluation evidence only and must not be used for tuning. Reports include source breakdown (`actual_model_call`, `recorded_model_output`, `recorded_output_per_config`, `assisted_generation`, `human_curated`, `mixed`, `fixture_only`), reference-leakage audit, prompt-profile safety inheritance audit, baseline-vs-selected delta tables, per-case recorded-model diagnosis, and `model_generated_failure_taxonomy`. Each parsed draft also runs canonical required-field validation for `states`, `regions`, `action_templates`, `safety_policy`, `blockers`, and `verification_rules`. The validator now reports `learning_template_required_contract_v1`, accepted schema paths such as `workflow_draft.action_templates` and `interface_draft.regions`, the matched path when present, and a non-executed `missing_sections_patch` retry plan for missing logical fields. Existing `safety` policy content can satisfy logical `safety_policy`, but it does not satisfy `blockers` unless blocker evidence exists. Missing sections set `required_field_retry_needed=true`, and without `actual_model_call` or `recorded_output_per_config` evidence the report marks `retry_not_executed` instead of faking improvement. Checkpoint 4 adds a small actual-call artifact at `logs\benchmarks\model_learning_actual_call_checkpoint4\actual_model_call_report.json`: 3 dev cases executed one required-field retry each, but hard fields remained missing, so no prompt/config improvement was accepted. Checkpoint 4.6 reran those saved actual outputs offline under `logs\benchmarks\model_learning_contract_alignment_checkpoint4_6\actual_call_saved_outputs\model_learning_template_benchmark_report.json`; after contract alignment, those cases are still not usable and now report the remaining logical gaps as `blockers` and `verification_rules`. Checkpoint 4.7 adds `scripts\run_model_learning_patch_retry.py`, a targeted missing-section patch retry runner. It sent one actual model retry per saved dev case with only the original draft, missing logical fields, target schema paths, and patch schema; retry prompts exclude hidden references, scoring diff answers, holdout data, and live PII. The 3 patch outputs parsed as JSON, but all were rejected because they omitted `schema_version` and returned empty/generic `blockers` and `verification_rules`; missing fields were not reduced and no merged template was produced. The report is `logs\benchmarks\model_learning_patch_retry_checkpoint4_7\missing_sections_patch_retry_report.json`. Only `actual_model_call` and compliant `recorded_output_per_config` may prove prompt/config improvement; baseline `recorded_model_output` can prove what a model previously produced but cannot validate a new prompt trial. Fixture-only improvements are reported as runner-logic evidence, not prompt or model improvement. Current recorded/actual model coverage is intentionally small and mostly search/homepage-surface oriented, so missing job-card/detail/apply/final-submit model-generated coverage remains visible. This is model-learning benchmark evidence only: it is not model accuracy, not SEEK E2E success, not live safe fill, and not live submit evidence.



### SEEK MVP benchmark demo scaffold



One-command offline rerun:



```powershell

uv run python scripts\run_seek_mvp_benchmark.py `

  --manifest artifacts\benchmarks\seek_mvp_golden_manifest_v1.json `

  --out logs\benchmarks\seek_mvp_final_scaffold `

  --no-submit `

  --json

```



Latest scaffold report: `logs\benchmarks\seek_mvp_final_scaffold\seek_mvp_benchmark_report.json`.



Key report fields:



| Area | Report field | Meaning |

| --- | --- | --- |

| Point grounding | `point_grounding_success` | Point-quality fixture metric only; not click success, system reliability, or E2E success. |

| Gate safety | `gate_rejected_click` | Wrong or unsafe point was rejected before click. Safe intercept is not an unsafe failure. |

| Safe fill policy | `safe_fill_fixture` | Fixture assertions / field-policy checks only; no live form filling. |

| Live safe fill | `layered_metrics.safe_fill` | Must remain `attempted=0 / rate=not_covered` until an approved live single-field smoke exists. |

| Submit safety | `final_submit_guard` | Fixture coverage for submit-like buttons; not live submit coverage. |



Invalid and not-covered interpretation:



- `invalid_cases` are stale or evidence-missing fixtures and do not enter pass/fail denominators.

- `not_covered` means no valid attempt exists for that layer; it must not be displayed as a passing rate.

- `safe_fill_fixture` can pass while live `safe_fill` remains not covered.



No-submit safety policy:



- Benchmark and demo scaffold use `--no-submit`.

- Final submit / send / complete / payment actions remain hard-blocked.

- Safe-fill fixture values must be redacted or represented as length/hash only.

- No fixture result authorizes live filling, uploading, account creation, privacy consent, or final submit.



Fixture-covered vs live-covered:



- Fixture-covered: read/scroll classifiers, external ATS login safe-stop chain, final-submit guard fixtures, point-grounding evidence classes, and safe-fill field-policy fixtures.

- Live-covered in this benchmark: none for safe fill, none for final submit.



Known limitations:



- Point-grounding categories are minimally covered, but sample size is still insufficient for reliability claims.

- Safe-fill coverage is offline fixture-only; it does not prove live ATS field focus, typing, verification, or recovery.

- `model_draft_alignment` remains not covered by this SEEK MVP manifest.

- The manifest is still small and intentionally exposes invalid/not-covered items.



Recommended next work:



- Add more VISTA success/miss, ROI crop, coordinate-transform, wrong-surface, and final-submit point-rejection fixtures.

- Add a larger safe-fill fixture matrix before any live field filling.

- Only after readiness gates pass, run at most one reviewed live no-submit smoke or one reviewed single-field safe-fill smoke; never final submit without explicit job-specific approval.



Optional live demo boundary: show SEEK results/detail navigation, Apply entry, external ATS or login blocker safe-stop, trace generation, zero submit clicks, and zero live fill. Do not run live safe fill or final submit for this demo scaffold.



The local panel has been updated to match this architecture. The shared Navigation Path / PathGraph card now shows the Agentic Loop strip, and each Runtime PathGraph node detail records the execution model, PathGraph role, Gate requirement, and app profile path so learned graphs are displayed as guidance assets rather than hardcoded scripts.



App/software profiles are now runtime resources. Use `GET /runtime/app_profiles` to list profiles and `GET /runtime/app_profiles/{app_id}` to load one profile. The panel's Artifact Replay page reads the SEEK profile through this API and shows the profile policy beside the loaded PathGraph.



Operation skills are runtime resources too. Use `GET /runtime/operation_skills` for the base framework skill catalog or `GET /runtime/operation_skills?app_id=seek` to see how SEEK profile skills map back to generic Operation skills such as `read_full_page`, `scroll_region`, and `open_apply_flow`.



As of 2026-07-01, operation skills are exposed as `operation_skill_v2` contracts through `operation_skill_catalog_v2`. Each skill now declares semantic actions, required inputs, outputs, preconditions, evidence requirements, failure modes, authorization requirements, decision boundaries, and trace fields. The core rule is explicit: Agent decides intent and business meaning, Gate authorizes safety/freshness/scope, Operation executes the bounded skill, and PathGraph can only provide guidance such as ROI hints or expected transitions.



The runtime now carries this through request/result evidence as `operation_runtime_context_v1` and `operation_trace_link_v1` on the concrete Operation entry points: app/window binding, observe, locate, recognition planning, OCR/read-region, form inventory, verify diff, click/open-apply execution, confirmed point, type text, and scroll. Side-effecting skills synthesize or carry a gate-linked id from existing runtime checks such as `pre_click_decision_v1` or `scroll_precondition_decision_v1`; read-only skills keep an authorized intent and capture identity without requiring a Gate decision.



Gate contracts are runtime resources as well. Use `GET /runtime/gate_contracts` for the base Gate catalog or `GET /runtime/gate_contracts?app_id=seek` to see the SEEK profile's safety/dataflow contracts, including bound-window matching, final-submit blocking, profile-mutation blocking, latest-detail snapshot checks, and contextual OCR normalization.



Agent prompts are also runtime resources. Use `GET /runtime/agent_prompts`, `GET /runtime/agent_prompts/{prompt_id}`, `GET /runtime/agent_prompts/{prompt_id}/versions`, `GET /runtime/agent_prompts/{prompt_id}/versions/{version}`, `GET /runtime/agent_prompts/{prompt_id}/diff`, `POST /runtime/agent_prompts/{prompt_id}/versions`, and `POST /runtime/agent_prompts/{prompt_id}/rollback` to list, load, compare, save, and rollback prompt versions. The panel can load, edit, diff, and rollback the full-JD suitability prompt `job_suitability_full_jd_v1`, preserving the rule that complete job text goes to the Agent before Apply Entry.



## Contract-first SEEK policy (2026-06-24)



Recent live SEEK failures are now handled as reusable runtime contracts instead of one-off site patches. Before any full SEEK apply run, keep the common regression set green for latest detail dataflow, candidate freshness, action taxonomy, scoped final-submit detection, scroll-scope validation, contextual OCR normalization, SEEK extraction, SEEK runners, and path-graph execution.



The next live order is intentionally staged: one job read/match/Apply dry-run first, then a 3-5 job no-apply smoke, and only then a station-internal application flow that stops at the final Review boundary. `Apply` / `Quick Apply` is an `open_apply_flow` action, not a final submit; submit-like labels including `Apply now` are blocked only inside an active application/final-review form or modal scope. `Submit` / `Send` / `Confirm` / payment remains hard-blocked inside that active scope.



Current SEEK template note: ordinary SEEK `Apply` is now allowed to open an external ATS application entry, and the runner records browser URL snapshots around the click when available. External account creation, privacy consent, login, captcha, upload, and final-submit surfaces remain user-review stop points. Live external-ATS testing on BambooHR also tightened a reusable ranking rule: when the goal names an explicit action such as Apply/申请, matching action buttons are promoted and unrelated share/context buttons are demoted; the broad word `application` is not treated as an Apply action.



Latest staged evidence: `logs\smoke\seek_no_apply_contract_smoke_3jobs_profile_after_dedupe_20260624.json` passed with `jobs_opened=3`, `jobs_fully_read=3`, `strong_apply=2`, `maybe_apply=1`, `wrong_scope_scroll_count=0`, and `final_submissions=0`. `logs\smoke\seek_apply_entry_contract_smoke_after_route_fix_20260624.json` proved Apply Entry can open a same-site SEEK `/apply` route without filling or submitting. A bare `/apply` route now produces `wait_for_form_readiness`; `seek_application_form_readiness_wait_v1` must observe real fields or a clear blocker before cover-letter, answer-plan, or safe-fill stages run. Direct apply URL observe evidence at `logs\smoke\seek_direct_apply_form_readiness_20260624.json` reached `cover_letter_field_detected` with `final_submit_visible=false`. The latest station-internal form debug run at `logs\smoke\seek_apply_92822270_contract_debug_20260624` reached `Review and submit`, filled the cover letter, answered 4/4 employer questions, kept profile mutation blocked, passed final-review extraction, and stayed at `submit_clicks=0` / `final_submissions=0`. Continue target validation is now a common action-candidate contract, with SEEK providing only label policy. The run is frozen as non-authorizing Learn evidence at `artifacts\seek\learned_seek_application_flow_92822270_20260624_contract_debug.json`; its replay and checkpoint both pass without authorizing clicks or final submit. A fresh learned-artifact live replay at `logs\smoke\seek_artifact_live_replay_92822270_20260624` followed the artifact-assisted path through cover-letter fill, 4/4 employer questions, profile review, and final Review extraction, again with `submit_clicks=0` and `final_submissions=0`; it is now exported as `artifacts\seek\learned_seek_application_flow_92822270_20260624_live_replay.json`, with replay/checkpoint passing.



Post-incident final-submit rule: a final `Submit application` click is no longer authorized by thread-level intent, a stale goal, or ad-hoc metadata such as `explicit_user_authorized_final_submit=true`. When the selected target matches final-submit language, `POST /action/execute_recognition_plan` requires a structured `final_submit_decision_v1` / `pre_submit_suitability_audit_v1` in request metadata. That decision must prove the current job was reviewed, the live match decision is `strong_apply` or an explicit reviewed override exists, GPT/user review has not requested `need_user_review`, and no unsupported employer-question `Yes` answers or hard risk flags remain. SEEK can build this metadata through `app.seek.pre_submit_audit.build_seek_final_submit_decision()`. The accidental 2026-06-24 submit is preserved as incident evidence, not as a reusable authorization pattern: `logs\smoke\seek_final_submit_completion_20260624.json` records `submitted=true`, `submit_clicks=1`, `final_submissions=1`, and confirmation screenshot `artifacts\screenshots\application-sent-seek-microsoft-edge__capture__full-window__20260624-055231-928897.png`.



Quality pass now also requires `title_extraction_from_body_count=0`. If a post-click detail header is reconstructed from a scrolled body fragment, `seek_mvp_accuracy_summary_v1.status` becomes `needs_review` even when clicks, reads, and zero-submit safety counters otherwise look clean.



## Runtime cleanup and trace budget update (2026-06-20)



Runtime traces now go through a bounded `write_trace` path. Normal small traces keep their original JSON shape, while very large strings, recursive scroll histories, binary/base64-like fields, and over-budget payloads are truncated or summarized with explicit `trace_truncated` metadata. This prevents `/action/scroll` and other long debug loops from writing multi-hundred-MB or GB JSON traces again.



The first cleanup pass moved old generated traces and visual artifacts out of the workspace into `D:\agent-gui-runtime_cleanup_quarantine_20260620`, deleted the regenerable `.uv-cache`, and kept models, `.venv`, `tools`, source code, tests, SEEK milestone JSON artifacts, templates, and skills in place. Manifests are recorded under `logs\cleanup\cleanup_manifest_20260620_v2.json` and `logs\cleanup\cleanup_manifest_20260620_v3.json`.



## Agent onboarding docs (2026-06-20)



Give other agents `AGENT_ONBOARDING.md` first. It links the minimum required docs for using the framework safely:



- `AGENT_API_WORKFLOW.md`

- `docs\AGENT_EXECUTION_PROTOCOL.md`

- `docs\AGENT_LEARN_MODE_TUTORIAL.md`

- `docs\VISUAL_ASSET_LEARNING_MODE.zh-CN.md`

- `docs\AGENT_TRACE_DEBUG_GUIDE.md`

- `docs\AGENT_PROMPT_TEMPLATE.zh-CN.md`



For SEEK-specific tasks, also give the agent `skills\seek-high-precision\SKILL.md`.



`POST /apps/open` now defaults `maximize_after_open=true` when it opens and binds a target window. External agents should keep that default for browser/SEEK tests so screenshots include the full list/detail layout before Observe or Execute.



For VISTA-backed Execute Mode, external agents should pass a reviewed card/result bbox as `metadata.seeded_candidate_v1` whenever it is available. The runtime now uses that seed as the primary compressed grounding path, crops a compact single-candidate ROI, and records `vista_roi_policy`, `vista_roi_source`, processed size, and fallback tier in the trace. Multi-candidate union crops and full-screen VISTA direct grounding are fallback paths.



For SEEK debug/application runs, step reports now expose lightweight machine-readable helpers before an agent needs to inspect raw screenshots: `execute_observation_v1` for current page state and safety blockers, `form_field_inventory_v1` for stable fill targets, `ui_diff_verification_v1` for before/after screenshot-change evidence, and `read_region_batch_v1` for multi-capture OCR reading of long detail panes. The same contracts are available through lightweight Execute APIs: `POST /execute/observe`, `POST /execute/form_inventory`, `POST /execute/verify_diff`, and `POST /execute/read_region_batch`. Detail reading can now use `scripts\seek_debug_step_runner.py --step read_detail_batch` so long-read pages do not advance by tiny one-scroll loops.



Apply Entry step reports also include `seek_application_flow_wait_v1`. The debug runner reuses the application-flow state already produced by Apply Entry when available and only polls whole-screen Observe up to the configured maximum when that state is unclear; the default maximum is 3 seconds, not a fixed sleep.



SEEK demo readiness can be checked without reading every trace manually:



```powershell

uv run python scripts\seek_demo_readiness_report.py --run-dir logs\smoke\seek_debug_step_run_latest --out logs\smoke\seek_demo_readiness_report.json

```



The report checks the operator demo goals: job/detail evidence, batch or scroll detail read evidence, station-internal application start, `Review and submit` reached, `final_submissions=0`, screenshot/trace evidence, and the configured time budget. The default budget is 5 minutes.



Latest fresh speed evidence: `logs\smoke\seek_speed_demo_20260623_fresh7_absolute` passed in `212048.417ms` with `within_budget=true`, `final_review_status=pass`, `submit_clicks=0`, and `final_submissions=0`. The live runner path now prefilters obvious unsuitable cards, adaptively increases result-list scroll strength when card fingerprints do not change, keeps the application-flow detector strict enough to reject generic search-page forms, and passes final-review extraction into the readiness report.



For the original 35-minute-demo optimization goal, run the stricter completion audit:



```powershell

uv run python scripts\seek_demo_goal_completion_audit.py `

  --run-dir logs\smoke\seek_speed_demo_20260623_fresh7_absolute `

  --fail-on-error

```



It emits `seek_demo_goal_completion_audit_v1` and checks the six evidence points tied to the user-reported bottlenecks: adaptive result scrolling, multi-capture batch reading, execute-scoped screen understanding after page changes, visual form inventory plus scroll/post-fill verification, `ui_diff_verification_v1`, and the 5-minute Review-before-submit boundary.



Reproduce the current 5-minute SEEK demo checkpoint with a reviewed SEEK search/job seed:



```powershell

uv run python scripts\seek_speed_demo_runner.py `

  --run-dir logs\smoke\seek_speed_demo_latest `

  --close-old-windows `

  --url "https://nz.seek.com/software-engineer-jobs/in-All-Auckland?jobId=92847815&type=standard" `

  --max-jobs 5 `

  --visible-jobs-per-page 4 `

  --max-result-scrolls 3 `

  --batch-max-captures 3 `

  --batch-stop-after-no-new-content 1 `

  --wheel-clicks 9 `

  --results-scroll-wheel-clicks 9 `

  --post-apply-capture-wait-seconds 0.5 `

  --time-budget-ms 300000

```



When another agent needs to inspect a trace, do not paste the full JSON into its prompt. First generate a compact handoff:



```powershell

uv run python scripts\agent_trace_digest.py "logs\traces\vision\TRACE.json" --format text

```



Use `--format json` when the receiving agent needs machine-readable `agent_trace_digest_v1` evidence.



## SEEK MVP execution update (2026-06-17)



The SEEK no-apply traversal path now uses seeded execution candidates for job cards. The runner sends `seeded_candidate_v1` metadata with the extracted card bbox, card click point, container id, title/company, and evidence texts into `POST /action/execute_recognition_plan`. The recognition path still runs VISTA ROI grounding and `pre_click_decision_v1`; when VISTA validates the seed bbox, the final click point is recorded as `seeded_candidate_v1_validated_by_vista_point_v1`.



Latest SEEK station-internal application-fill evidence now includes three live runs. `logs\smoke\seek_debug_homepage_20260620\application_fill_record.json` records the `Intermediate Engineer - AI Automation & Integration` / `Inde Technology` run: default SEEK resume kept, cover letter rewritten, two employer questions answered, `Update SEEK Profile` continued without Add/Edit mutations, and `Submit application` blocked at final review. `logs\smoke\seek_debug_homepage_20260620_next\application_fill_record.json` records the Plexure `0/0` employer-question sample and remains useful as a no-question control. The current default evidence sample is `logs\smoke\seek_apply_live_92822270_debug_20260620_selected_value\application_fill_record.json`: it records `Software Engineer (Business Systems)` / `Sourced | IT Recruitment Specialists`, keeps the default SEEK resume, replaces and then revises the cover letter to remove duplicated template phrasing, answers four employer-question items from the real candidate profile evidence, continues through Profile without Add/Edit mutations, and stops at `Review and submit` without clicking final submit. Its audit `logs\smoke\seek_apply_live_92822270_debug_20260620_selected_value\final_review_audit.json` passes as `pass_stopped_before_final_submit`, and `artifacts\seek\learned_seek_application_flow_92822270_20260620.json` freezes it as a non-authorizing Learn Mode artifact. The application state classifier exposes `current_step` from URL/title evidence so progress-bar text such as `Review and submit` does not misclassify earlier steps. The debug Continue path also rejects browser/header/right-edge floating-widget targets before execution and requires the step to change after a Continue click.



The reviewed stop-before-submit debug run is exported in three steps:



```powershell

uv run python scripts\seek_debug_export_application_fill_record.py `

  --run-dir logs\smoke\seek_apply_live_92822270_debug_20260620_selected_value `

  --out logs\smoke\seek_apply_live_92822270_debug_20260620_selected_value\application_fill_record.json



uv run python scripts\seek_application_final_review_audit.py `

  --record logs\smoke\seek_apply_live_92822270_debug_20260620_selected_value\application_fill_record.json `

  --out logs\smoke\seek_apply_live_92822270_debug_20260620_selected_value\final_review_audit.json `

  --fail-on-error



uv run python scripts\seek_debug_step_runner.py `

  --run-dir logs\smoke\seek_apply_live_92822270_debug_20260620_selected_value `

  --step extract_final_review `

  --application-fill-record logs\smoke\seek_apply_live_92822270_debug_20260620_selected_value\application_fill_record.json



uv run python scripts\seek_export_application_flow_artifact.py `

  --record logs\smoke\seek_apply_live_92822270_debug_20260620_selected_value\application_fill_record.json `

  --audit logs\smoke\seek_apply_live_92822270_debug_20260620_selected_value\final_review_audit.json `

  --final-review-extraction logs\smoke\seek_apply_live_92822270_debug_20260620_selected_value\final_review_extraction.json `

  --out artifacts\seek\learned_seek_application_flow_92822270_20260620.json

```



This writes `seek_application_flow_artifact_v1` with source provenance, screenshot/trace paths, a prefixed station-internal state machine, transitions, filled-content summary, action templates, verification rules, field-fill policy, safety policy, and optional `review_reconciliation_v1`. The `extract_final_review` step is read-only: it observes the current Review page, checks the visible resume / cover-letter summary / employer-question summary or answer text against `application_fill_record.json`, requires `Submit application` to be visible but not clicked, and writes `seek_final_review_extraction_v1`. The artifact now exports the reusable `skill:review_before_submit_reconciliation` learned skill for other multi-step form review pages. It is a milestone artifact only: `artifact_is_authorization=false`, final submit remains forbidden, and future replay still needs safe-fill focus/value verification before typing. Existing 92822270 screenshots show the folded Review summary (`You wrote a cover letter`, `You answered 4 out of 4`) but not the bottom Submit button; rerun `extract_final_review` while the Review page and Submit button are visible before marking that extraction as pass. `scripts\seek_application_flow_replay_report.py` and `scripts\learn_execute_checkpoint_report.py` can consume the 92822270 artifact; the latest checkpoint output is `logs\smoke\learn_execute_mvp_checkpoint_92822270_20260620.json`, which passes and exposes `employer_question_count=4`, `final_submissions=0`, and `seek_application_final_submit_forbidden=true`. `scripts\seek_debug_step_runner.py --step continue_application_flow` consumes the strict replay report through `--application-flow-replay` and records the selected `seek_apply:*` transition plus screenshot/safe-fill verification requirements in each one-step debug report.



The broader SEEK job-search/application experience is now abstracted into reusable non-authorizing workflow artifacts. `artifacts\templates\job_search_application_workflow_template_v1.json` models `results list -> job card/detail -> job/company record -> candidate-profile screening -> same-site nonfinal application -> review-before-submit block`. `artifacts\skills\job_search_application_workflow_skill_v1.json` is the matching orchestration skill artifact: it records inputs, outputs, composed skills, and the one-step-at-a-time run loop for company/job recording, screening, form filling, and Review reconciliation. It remains guidance only: external ATS application filling is deferred, `maybe_apply` requires user approval, and `final_submit_forbidden=true`.



`app\seek\employer_questions.py` is now the pre-click core for turning employer-question pages into scoped answer groups and profile-backed answer plans. It can combine `application_form_inventory_v1` with `screen_reading_v1`/Windows UIA controls, emits `employer_question_inventory_v1`, filters navigation/final-submit buttons out of answer candidates, ranks duplicate `Yes` / `No` controls only inside the current question group, emits `employer_question_answer_plan_v1` from `candidate_profile_v1` evidence, and emits dry-run `employer_question_answer_preview_v1` targets. The preview now also treats a visible, matching work-rights selected value as `action_type=already_selected` rather than opening the dropdown. The current 92822270 debug run records four-question coordinate execution evidence: q1 already selected, q2/q3 clicked through `execute_confirmed_point`, q4 typed through `type_text`, and then continued to the review boundary with `final_submissions=0`.



Latest real SEEK no-apply smoke:



```powershell

uv run python scripts\seek_mvp_traversal_runner.py --max-jobs 5 --max-detail-scrolls 6 --max-results-scrolls 10 --execute-clicks --candidate-profile tests\smoke\seek_candidate_profile_smoke.json --saved-jobs-dir artifacts\seek\saved-jobs-readonly-5jobs-after-parser-and-title-filter --out logs\smoke\seek_mvp_readonly_after_parser_title_filter_5jobs_20260617.json

```



Result: `jobs_seen=5`, `jobs_opened=5`, `jobs_fully_read=5`, `card_click_open_rate=1.0`, `post_click_layout_drift_count=0`, `wrong_scope_scroll_count=0`, and `final_submissions=0`. This slice also parses wrapped VISTA bbox output such as `{"status":"unparsed","raw_text":"[x, y, w, h]"}` and caps SEEK results-list width on wide windows to prevent right-pane detail text from becoming synthetic result cards.



The SEEK traversal runner now writes two artifacts: the compact `seek_mvp_run_report_v1` and an independent `seek_mvp_traversal_trace_v1` under `logs\traces\seek\...`. The report includes `traversal_trace_path`. Use that trace to inspect the card-click plan/action traces, nested scroll events, detail-read trace paths, matching decisions, saved-job evidence, Apply Entry stops, answer-plan previews, safe-fill attempts, and zero-submit safety counters.



CLI traversal runs also write per-job `seek_job_archive_v1` files by default beside the `--out` report, for example `logs\smoke\seek_mvp_traversal_report_job_archives\job_*.json`. Each archive stores the source card, click trace paths, detail-read result, scroll segments, match decision, optional Apply Entry summary, and final-submit safety state. Use `--job-archives-dir <dir>` to choose a different archive directory.



CLI traversal runs also write a compact `seek_clear_path_graph_v1` beside the report, named like `seek_path_verify_report_clear_path_graph.json`. This is the preferred handoff for agents that cannot read long traces: it lists stable SEEK regions (`results_list`, `job_card`, `job_detail`, `detail_header`, `detail_body`), reusable actions (`open_job_card`, `read_detail`, `load_more_results`), per-job click/read nodes, trace paths, and safety counters. The 2026-06-24 validation at `logs\smoke\seek_path_verify_fixed_20260624_001102\seek_path_verify_report_clear_path_graph.json` opened 1/1 job, fully read 1/1 detail, kept `wrong_scope_scroll_count=0`, and did not click Apply or Submit.



One-step debug runs write the same archive shape under `<run-dir>\job_archives\`. Each debug step appends its `step_report.json`, before/after/observe screenshot paths, and trace paths into the current job archive, so the operator can inspect the whole card-click/detail-scroll/match/apply-entry trail after running bounded commands such as `--step execute_card`, `--step read_detail_scroll`, and `--step match`.



Audit a SEEK run before continuing to riskier steps:



```powershell

uv run python scripts\seek_mvp_run_audit.py --report logs\smoke\seek_mvp_traversal_report.json --mode readonly --out logs\smoke\seek_mvp_run_audit.json

```



The audit emits `seek_mvp_run_audit_v1`. It fails old reports that lack `traversal_trace_path`, flags wrong scroll scopes or submit evidence, and treats `blocked_need_real_candidate_profile` as safe only when Apply Entry, live cover letters, and field filling did not happen.



SEEK remains a high-precision dedicated workflow in `skills/seek-high-precision/SKILL.md`. Reusable pieces have been moved into generic layers: `app/core/audit.py` for audit helpers and `app.agent.profile.cv` plus `scripts/candidate_profile_from_cv.py` for local CV-to-profile draft generation. A local draft profile can be generated from a CV, but live Apply Entry still requires readiness to pass and must not infer work rights or other sensitive answers from the CV.



Stable SEEK execution experience can also be exported into Learn Mode artifacts:



```powershell

uv run python scripts\seek_export_learn_artifacts.py `

  --report logs\smoke\seek_mvp_readonly_after_parser_title_filter_5jobs_20260617.json `

  --out artifacts\seek\learned_seek_mvp_from_5job_smoke_20260617.json `

  --profile-out artifacts\seek\learned_app_profile_seek_mvp_20260617.json `

  --path-graph-out artifacts\seek\path_graph_seed_seek_mvp_20260617.json `

  --runtime-graph-out artifacts\seek\runtime_path_graph_seek_mvp_20260617.json `

  --learned-skills-out artifacts\seek\learned_skills_seek_mvp_20260617.json `

  --visual-assets-out artifacts\seek\visual_assets_seek_mvp_20260617.json `

  --interface-map-out artifacts\seek\learned_interface_map_seek_mvp_20260617.json

```



`learned_app_profile_v1` records SEEK page type, scroll containers, entity patterns, action templates, verification rules, and safety policy. `path_graph_seed_v1` seeds the learned page structure as `top_search_area`, `results_list`, `job_detail`, `job_card`, `detail_header`, and `detail_body`. The SEEK runner may use `--learned-artifact` to prefer these learned rules, but real clicks still go through the existing gated Execute path.



The same export now also produces the first generic path-graph-mode artifacts. `runtime_path_graph_v1` upgrades the SEEK seed into states, regions, scroll containers, entities, transitions, action templates, coordinate evidence, visual asset refs, learned skill refs, safety policy, and `path_patterns`. The SEEK graph currently exports `list_detail_path_pattern_v1`, a reusable split-list/detail pattern with list/detail container ids, card-to-detail identity mapping, adaptive detail-read scrolling, wrong-scope stability checks, and detail-pane cleanup before the next card click. `learned_skill_v1` extracts reusable skills such as opening a card from a list, scrolling one container until new content appears, reading a detail pane, validating a seeded click point, resetting a detail pane to its header, and blocking final submit. `visual_asset_v1` records SEEK visual evidence slots such as Apply, Quick Apply, Save, job-card shape, selected-card highlight, and results/detail scrollbars. `learned_interface_map_v1` combines the runtime graph and visual assets into a panel-friendly state/region map with fixed visual assets, dynamic ROI areas, danger zones, and editor policy. When observed Apply / Quick Apply bbox evidence is present, `visual_asset_crop_export_v1` can crop and hash those fixed buttons as well as representative learned shapes such as the SEEK job-card body. These artifacts are guidance only; they do not authorize clicks. Use `uv run python scripts\visual_asset_local_smoke.py --out-dir artifacts\visual-match-smoke\local_seek_buttons` for a no-mouse local screenshot smoke of the learned button-crop path, then use `uv run python scripts\visual_asset_calibration_report.py --interface-map <map.json> --target-image <screenshot.png> --out <report.json>` to calibrate the same learned visual assets against another current screenshot.



When `POST /vision/observe_screen` recognizes the learned SEEK search-results surface, the default SEEK `runtime_path_graph_v1` now becomes the primary `screen_map` structure: regions are emitted as `top_search_area`, `results_list`, `job_detail`, `job_card`, `detail_header`, and `detail_body`, and `learned_path_graph_available_actions` exposes graph actions such as `open_job_card`, `read_detail`, and `load_more_results`. Model/OCR output remains supplemental current evidence; the artifact still does not authorize clicks. SEEK application-form states such as `Choose documents` / `Review and submit` are explicitly not matched to the search-results graph.



The first path-graph-assisted Execute API slice is also available:



- `POST /execute/available_actions` loads a `runtime_path_graph_v1`, resolves whether it can guide the current state, and returns `available_actions_v1`.

- `POST /execute/step` accepts one selected available action and returns `execute_step_response_v1` with `path_graph_action_context_v1`. Available actions now expose `action_kind` and `low_level_action_type`, so Execute Mode can show learned click, scroll, read, and input skills instead of treating the menu as click-only. With `dispatch_low_level=true`, it dispatches exactly one generated low-level request through the existing gated `/action/scroll`, `/action/execute_recognition_plan`, or `/action/type_text` path and records the low-level response/trace. Input actions require agent-provided text; they default to `submit=false` and do not turn learned artifacts into authorization.

- The browser panel now exposes the harness views inside their owning workspaces instead of a separate replay rail. Learn Mode shows Artifact Replay and PathGraph Safe Validation for learned `runtime_path_graph_v1` artifacts. Execute Mode shows PathGraph Task Run, which simulates an agent loop by repeatedly calling `/execute/available_actions` and `/execute/step`, while each backend call still performs only one step. The bundled `artifacts/demo/runtime_path_graph_input_demo.json` demonstrates that input skills can appear in the action menu and timeline as dry-run-only steps without calling `/action/type_text` or typing into a real website.

- Learn, Execute, and Replay/Test now share the same large Navigation Path / PathGraph card. Loading a runtime graph renders states and transitions in the existing canvas without child subpaths; Execute and validation steps update `path_graph_runtime_state_v1` so the card highlights the current node, current action edge, completed edges, failed edges, and forbidden/write-guarded actions. The timeline mirrors the same step evidence with skill, low-level action type, from/to states, and trace path.



This is intentionally single-step: the upper agent or smoke runner chooses the next action after each response. Real clicks still require the existing `pre_click_decision_v1` gate, and path-graph guidance never authorizes a click by itself.



Latest Execute skill matrix evidence: `logs/smoke/execute_mode_skill_matrix_20260619.json` passed with `click_planned=1`, `scroll_dispatched=1`, `input_dry_run_planned=1`, `failures=0`, and `final_submissions=0`. The second read-only website sample is `artifacts/wikipedia/runtime_path_graph_wikipedia_search_v1.json`; a real external Edge smoke wrote `logs/smoke/wikipedia_path_graph_scroll_real_20260619.json` after dispatching `read_article` as a page scroll through `/execute/step(dispatch_low_level=true)`.



The browser panel now also exposes Learn Mode -> Artifact Replay (`learn_replay`). The page has two subinterfaces: Template Replay for runtime PathGraph / Interface Map / validation-task replay, and Learning Draft for raw model trials, DraftGraph Preview, reviewed candidates, and PathGraph candidates. Template Replay loads SEEK, Wikipedia, GitHub Issues, Python Docs Search, Table Directory, or the input-demo runtime graph through the existing read-only `/panel/file` path, shows graph structure/actions/skills/safety, renders the shared PathGraph card, and can seed the Learn Mode safe-validation harness or the Execute Mode task-run harness. Demo-facing Template Replay actions are kept to the main load/use path by default, while prompt/profile/save/debug-run tools live under an Advanced actions disclosure. The Learning Draft subinterface hides the shared Template Replay PathGraph and Page Detail cards, so a loaded template graph does not appear as the current draft graph, and it now renders a separate read-only draft PathGraph/page-detail preview from the loaded draft itself. Learn Fast / Observe also hides the shared PathGraph and Page Detail cards; whole-screen understanding is a screenshot/response workspace, and draft graph inspection belongs to the Learning Draft subinterface. Loading a model artifact no longer auto-renders the raw learning draft. Learning Studio separately captures a bound-window screenshot for a draft-only model trial, saves the resulting `trial_result.json`, and loads that raw draft as a display-only DraftGraph Preview with summary/counts. Reviewed candidates and top-level drafts are accepted by the review loader as display-only inputs. The panel ships with a loadable python.org demo draft by default: `artifacts/learning-draft-review/trial_result_cae1c88703/reviewed_template_candidate.json` plus its candidate PathGraph and validation report. The same page now includes a SEEK Application Evidence inspector that loads `seek_application_fill_record_v1`, `seek_application_final_review_audit_v1`, and `seek_application_flow_artifact_v1`, then shows filled fields, screenshot/trace counts, audit decision, and final-submit safety counters. The task-run harness still calls `/execute/available_actions` and `/execute/step` one step at a time; it is a panel/test harness, not a new backend multi-step agent.



Latest artifact replay evidence:



- SEEK 1-job external Edge smoke: `logs\smoke\seek_artifact_replay_readonly_1job_20260619_after_reset.json` with `jobs_opened=1`, `jobs_fully_read=1`, `post_click_layout_drift_count=0`, `wrong_scope_scroll_count=0`, and `final_submissions=0`.

- SEEK 3-job external Edge smoke: `logs\smoke\seek_artifact_replay_readonly_3job_20260619_after_reset.json` with `jobs_opened=3`, `jobs_fully_read=3`, `card_click_open_rate=1.0`, `post_click_layout_drift_count=0`, `pre_click_detail_reset_count=2`, `pre_click_detail_reset_wrong_scope_count=0`, `title_extraction_from_body_count=0`, `wrong_scope_scroll_count=0`, and `final_submissions=0`. This fixed the root cause where a previous `read_detail` left the right SEEK detail pane scrolled down, causing the next post-click verification to read a body fragment as the title.

- Wikipedia page-scroll smoke remains read-only: `logs\smoke\wikipedia_artifact_replay_read_article_20260619.json` with page scroll passed, `wrong_scope_scroll_count=0`, `write_actions_clicked=0`, and `final_submissions=0`.

- GitHub Issues is the third read-only website family: `artifacts\github\runtime_path_graph_github_issues_v1.json` models `list -> detail page navigation` with `open_issue_from_list`, `read_issue_detail`, and `load_more_issues`. A real external Edge smoke wrote `logs\smoke\github_issues_artifact_replay_readonly_20260619.json`: dry-run first selected the first issue row title rather than the Open/Closed filter bar, then a reviewed live click opened issue `#41357`, and `read_issue_detail` dispatched a page scroll with `wrong_scope_detected=false`. Summary: `issue_opened=1`, `detail_scroll_passed=true`, `wrong_scope_scroll_count=0`, `write_actions_clicked=0`, `submit_clicks=0`, `final_submissions=0`, and `high_risk_actions_executed=0`.



Python Docs Search is now the fourth learned website family. `artifacts\docs_search\runtime_path_graph_python_docs_search_v1.json` models public documentation search input, seeded search-button click, seeded search-result opening, and article page scroll. The live external Edge smoke `logs\smoke\python_docs_search_artifact_replay_public_input_20260619.json` verified the continuous Execute sequence `type_public_search_query -> trigger_search -> open_search_result -> read_article`: it typed the public query `list comprehension`, clicked the learned search button seed, opened the learned first-result seed, observed the Glossary article page, and dispatched `read_article` as page scroll. It recorded zero private/PII input, write actions, final submissions, high-risk actions, and wrong-scope scrolls. For learned `seeded_candidate_v1` clicks, the seed bbox/click point is the primary execution coordinate and VISTA ROI grounding is recorded as audit evidence; when VISTA disagrees, trace records `coordinate_source=seeded_candidate_v1_model_disagreed` and `vista_point_disagrees_with_seed_bbox` instead of letting the model overwrite the learned point.



Table Directory is the fifth UI-family sample. `artifacts\table_directory\runtime_path_graph_table_directory_v1.json` models a public read-only `table/filter/sort -> row detail` workflow with `switch_filter_tab`, `sort_records`, `open_record_from_table`, `read_record_detail`, `return_to_table`, and `load_more_records`. Its real external smoke report is `logs\smoke\table_directory_datatables_real_1record_20260619.json`: DataTables row-details opened one record through the row expander, then `read_record_detail` scrolled the page to reveal `Full name: Airi Satou`, `Extension number: 5407`, and extra detail text. The first dry-run exposed the root prompt bug where the graph preferred row title text over the row expander; the graph was corrected to prefer explicit row expand/details controls before the live click was executed.



Unified artifact replay regression is now captured by `scripts\artifact_replay_regression_report.py`. The latest report `logs\smoke\artifact_replay_regression_20260619.json` passed five baselines (`seek`, `wikipedia`, `github_issues`, `python_docs_search`, and `table_directory`) and checks that learned graphs expose expected click/scroll/input/filter/sort/table actions while smoke reports retain zero wrong-scope/write/final-submit/high-risk evidence.



The Learn/Execute MVP checkpoint report is generated by `scripts\learn_execute_checkpoint_report.py`. It writes `seek_learn_safe_validation_report_v1`, `seek_learn_task_run_report_v1`, `seek_application_flow_checkpoint_report_v1`, `learned_skill_matrix_v1`, and `learn_execute_mvp_checkpoint_report_v1`. The latest checkpoint `logs\smoke\learn_execute_mvp_checkpoint_20260620.json` passed with reusable Execute skill coverage for click, scroll, public input, read, guarded/hidden actions, filter/tab switching, sort/filter clicking, table-row opening, and the SEEK station-internal application-flow artifact while keeping `artifact_authorizes_click=false`, `seek_application_final_submit_forbidden=true`, `seek_application_safe_fill_required=true`, and `seek_application_can_run_live_strict_replay=true`. `scripts\seek_application_flow_replay_report.py` writes the dry-run strict replay plan at `logs\smoke\seek_application_flow_replay_20260620.json`; it is the live-test script checklist, not a real page action. The unified regression report also includes `regression_gate`, with `can_continue_to_new_family=true` only when all learned baselines pass. `scripts\learn_sample_readiness_gate.py` combines both reports into `learn_sample_readiness_gate_v1`; the latest `logs\smoke\learn_sample_readiness_gate_20260620.json` has `ready_for_new_learn_sample=true`, requires the `artifacts\templates\learn_sample_template_v1.json` template, and records that Codex's in-app browser is reserved for ChatGPT while panel/site tests target an external browser or native app.



Windows 本地 GUI 自动化运行时。它不是完整 Agent，而是给上层 Agent 提供稳定的本地 HTTP API，用来发现应用、绑定窗口、截图、OCR/视觉识别、生成点击计划、执行受控点击和验证结果。



核心链路：



```text

Agent -> local HTTP API -> GUI runtime -> bound Windows window

```



## 部署和启动



### 1. 环境要求



- Windows 10 / Windows 11

- Python 3.11

- `uv`

- 本地视觉模型可选；没有模型时仍可打开测试面板和测试基础 API



### 2. 安装依赖



```powershell

uv sync

```



`FastAPI` 和 `uvicorn[standard]` 已写在 `pyproject.toml` 的依赖列表里，执行 `uv sync` 会自动安装，不需要单独 `pip install fastapi`。



可选验证：



```powershell

uv run python -c "import fastapi, uvicorn; print('FastAPI runtime deps ok')"

```



### 3. 一键启动测试面板



双击根目录：



```text

start_test_panel.bat

```



当前默认打开浏览器测试面板：



```text

http://127.0.0.1:8000/panel

```



`start_test_panel.bat` 是纯 `.bat` 启动器，不依赖 `.ps1`。它会：



- 检查 `http://127.0.0.1:8000/health`

- 如果 runtime 不可用，在最小化 `cmd` 窗口中启动 FastAPI runtime

- 等待 runtime 就绪

- 打开浏览器测试面板

- 将 runtime 日志写入 `logs/test-panel-runtime.log`



### 4. 手动启动 runtime



```powershell

uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

```



打开接口文档：



```text

http://127.0.0.1:8000/docs

```



浏览器测试面板：



```text

http://127.0.0.1:8000/panel

```



### 5. 启动本地视觉模型



推荐通过测试面板启动：



1. 打开 `整屏理解` 或 `精准定位` 阶段

2. 选择模型 profile

3. 点击 `启动本地视觉模型`

4. 点击 `测试模型 /v1/models`



模型刚启动时，`/v1/models` 可能短暂返回 `Loading model`。测试面板会将其显示为“模型正在加载”而不是服务失败；在此期间调用整屏理解或精准定位，runtime 会等待模型可用后继续当前识别请求。



模型统一放在：



```text

configs/model_profiles/

```



启动脚本统一放在：



```text

scripts/model_servers/

```



当前已有 profile：



- `configs/model_profiles/qwen3_vl_8b_q4_k_m.json`

- `configs/model_profiles/qwen3_vl_4b_q4_k_m.json`

- `configs/model_profiles/minicpm_v_4_6_transformers.json`

- `configs/model_profiles/vista_4b_transformers.json`



当前默认分工：学习模式 / 整屏观察 `observe` 使用 `Qwen3-VL 8B Q4_K_M`，优先保证模板、路径图和界面详情质量；`Qwen3-VL 4B Q4_K_M` 保留为可手动选择的快速理解 profile；精准定位/执行 grounding 使用 `VISTA-4B Transformers`。`MiniCPM-V-4.6 Transformers` 目前是 benchmark-only profile，当前后端不直接启动它的服务。旧 `Qwen3.6 35B` profile 与本地权重已经移除。



手动启动 llama.cpp 视觉模型：



```powershell

.\scripts\model_servers\start_llama_vision_server.ps1

```



停止本地视觉模型：



```powershell

.\scripts\model_servers\stop_local_vision_server.ps1

```



指定其他 GGUF 模型：



```powershell

.\scripts\model_servers\start_llama_vision_server.ps1 `

  -ModelPath .\models\some-model.gguf `

  -MmprojPath .\models\some-mmproj.gguf

```



VISTA-4B 是 Transformers/safetensors 点定位模型，不走 llama.cpp/GGUF。权重目录为 `models/vista-4b-safetensors`，profile 使用 `runtime="transformers"` 和 `output_contract="vista_point_v1"`，通过 `scripts/model_servers/start_transformers_vision_server.ps1` 启动一个本地 OpenAI-compatible 服务。首次运行前需要安装可选依赖：



```powershell

uv sync --group vista

```



手动启动 VISTA-4B：



```powershell

.\scripts\model_servers\start_transformers_vision_server.ps1 `

  -ModelPath .\models\vista-4b-safetensors `

  -ModelName inclusionAI/VISTA-4B `

  -Port 1244

```



如果缺少 `torch` / `transformers`，启动脚本会非零退出并在 runtime start trace/log 中给出明确错误；不会把依赖缺失伪装成模型已启动。



当前默认 `local_grounding` 已切到 VISTA-4B，用来替代原先 35B 精准定位模型。VISTA 只输出 `vista_point_v1` 点坐标，不输出 `vision_regions_v1` 区域列表；因此执行链路会先复用 Observe 阶段的 `screen_map_v1` 做 PathGraph recall，再把召回候选作为上下文发给 VISTA。VISTA 返回点必须落在召回候选 bbox 内，才会转成 `narrow_search_v1` 证据并进入 `pre_click_decision_v1`。如果没有可复用 PathGraph 候选，系统会返回 blocked plan，而不是凭 VISTA 点坐标直接点击。



VISTA Transformers 服务现在按单飞生成运行：同一时间只允许一个 `/v1/chat/completions` 推理请求，忙时返回 `503 model_busy`。`/health` 会返回 `status="ok"` 或 `status="busy"`，并带上 `pid` / `active_request`；runtime 的模型状态检查会把 busy 显示为 busy，不再仅凭 `/v1/models` 把卡住或旧进程误报为正常。



## 测试面板



测试面板是当前最推荐的调试入口，基于浏览器：



```text

http://127.0.0.1:8000/panel

```



左侧栏按 Agent workflow 排列：



1. 打开/绑定

2. 截图

3. 整屏理解

4. 精准定位

5. 点击闸门

6. 输入

7. Trace 解析

8. 模型测试



主要能力：



- `GET /health` runtime 健康检查

- `GET /runtime/models` 模型状态

- `POST /runtime/prepare` runtime 准备

- `POST /runtime/models/start` / `POST /runtime/models/stop` 模型启动和停止

- `GET /apps` 应用发现

- `POST /apps/open` 打开应用

- `GET /session/windows` 自动读取当前打开窗口

- `POST /session/bind_window` 绑定窗口

- `POST /session/resize_bound_window` 调整当前绑定窗口尺寸，用于稳定性/坐标漂移测试

- 窗口下拉选择 + 进程名/标题自动填入

- `POST /state/capture_window` 截图

- 拖拽图片作为测试截图

- `POST /vision/observe_screen` 整屏理解

- `POST /vision/locate_target` 精准定位

- 在精准定位阶段手动生成并预览候选框，用于核对模型定位结果

- `POST /action/execute_recognition_plan` dry-run 点击闸门

- `POST /action/execute_confirmed_point` 操作者确认坐标点击

- `POST /action/type_text` 文本输入

- `POST /action/scroll` 当前绑定窗口上下滚动

- 渲染识别 overlay

- 启动/停止本地视觉模型

- 修改附加视觉提示词

- 导航路径图，记录页面跳转和控件操作历史

- Trace 按阶段解析，点击阶段查看原始 JSON 和图片/坐标 overlay

- 模型直连测试，支持带图片和提示词直接调用视觉模型

- 查看每个阶段的原始 JSON 返回

- 语言切换按钮（中文 / English）



耗时的视觉请求在后台运行，调用整屏理解、精准定位或 dry-run 时测试面板仍可继续响应。整屏理解与精准定位分别保存提示词：整屏理解是候选发现和学习观察阶段，只要求简短界面摘要和可操作控件候选框，不让理解模型复述 OCR 坐标或生成详细关系证据；整屏理解现在还要求 `state_guess` 输出可直接传给精准定位 `state_hint` 的短区域提示，并在 `POST /vision/observe_screen` 返回 `suggested_state_hint`。测试面板收到成功的整屏理解结果后会自动把该提示填入精准定位的 State hint 输入框；旧的本地面板配置也会在加载时补上这条提示词规则。精准定位阶段只处理 agent 指定的目标，区分纯图标与含文字控件，并要求输出 OCR anchor 关系、四边约束、中心/尺寸/排除约束以及最终框理由。对不含文字的小图标，满足这些证据的大模型框会作为 `located_bbox` / `located_point` 返回供检查，但不会自动改点相邻 OCR 文字，也不会直接成为可执行坐标。



最新的同图测试中，`Qwen3-VL 8B Q4_K_M` 整屏理解从旧详细输出流程的约 `84.17s` 降至轻量候选流程的约 `16.08s`。新流程单次返回 `10` 个可操作候选和 `2` 个图标候选，没有触发模型重试。



精准定位现在对 `click_target` 使用单目标视觉模板，不再要求大模型枚举整屏控件。2026-05-26 的同图真实测试中，`Qwen3.6 35B A3B IQ4_XS` 对“`搜索游戏` 左侧的放大镜搜索图标”返回 `Search Icon`，`located_bbox={x:635,y:25,w:25,h:30}`，`text_inclusion_policy=exclude_text`，耗时约 `75.59s`；系统没有退回选择旁边的输入文字，且因图标尚无额外执行确认，`selected_click_point=null`。



同日的 QQ “关闭窗口”样例正确识别了语义目标，但在 `806px` 宽推理图上返回了越界横坐标 `965..985`，原结果因此被裁为空框并显示 `not_located`。运行时现在会在裁边前恢复这种 `0..1000` 比例坐标，使关闭按钮成为仍需人工确认的候选。测试面板会把定位返回的首候选自动填入“候选框校验”和“点击闸门”；操作者按下真实点击按钮后，`POST /action/execute_confirmed_point` 才向当前绑定窗口发送该窗口相对坐标。



修复后的同图真实复测在 `69.35s` 内返回 `close_window_button`、`located_bbox={x:797,y:13,w:17,h:26}`、`located_point={x:806,y:26}` 和 `location_status=requires_pre_click_confirmation`；`selected_click_point` 仍为空，因此复测没有触发点击。



2026-05-27 的后续工作压缩了精准定位输入：运行时仍保留全部 OCR 框用于 trace 与后验检查，`click_target` 当前默认按预算选择最多 `48` 个 anchor，使用 `relation_matrix_compact` 矩阵发送每个入选框的文字、坐标和目标匹配标记。矩阵还携带包含/排除关系策略，并要求在存在相关文字行时于 `anchor_relations` 中引用至少一个 anchor：关闭按钮这类纯视觉图标仍可利用附近文字定位边界，但最终 bbox 必须排除文字区域。此前不携带图标周围文字的 `geometry_compact` 试验已被这一契约替代。



最终 no-click 复测向模型发送了 `32` 行矩阵和 `32` 条文字（`prompt_goal_match_count=0`），模型输入为 `2735` tokens，低于当前 `4096` context；请求未 fallback，也未触发点击，返回 `located_bbox={x:783,y:5,w:27,h:27}`、`located_point={x:796,y:18}`。当前 Qwen 输出遵守了 `text_inclusion_policy=exclude_text`，但仍未回填 `anchor_relations`，因此显式关系引用仍作为已知模型限制继续观察。Trace: `logs/traces/vision/20260527-174308-069367__locate-target__browser.json`。



当 OCR 中存在与目标强匹配的文字时，精准定位矩阵现在优先扩展该文字附近的排布证据：默认在总共 `48` 行以内，为强匹配文字最多优先加入 `12` 个同排左右或同列上下邻居，并写入紧凑 `focus_relation_rows=[focus_id,neighbor_id,L|R|A|B,gap_px]`。调用方可通过 `metadata.ocr_anchors.prompt_focus_neighbor_limit` 调整该局部份额；这不会对没有目标文字命中的关闭按钮伪造关系。



在同一张 QQ 截图上用画面内文字 `若只群` 构造精准定位 prompt 时，运行时找到 `2` 个强匹配 anchor，并在仍为 `32` 行的矩阵中优先写入 `9` 条邻域排布关系；与关闭焦点扩展相比，完整文本 prompt 从 `1697` 增到 `1866` tokens，仅增加 `169` tokens。



同目标的实际 `POST /vision/locate_target` no-click 调用在 trace 中记录了 `prompt_goal_match_count=2`、`prompt_focus_relation_count=9`，模型总输入为 `2963` tokens，未触发 OCR fallback 或真实点击。因为画面中 `若只群` 同时出现在标题和会话列表，该运行只验证焦点排布证据成功入模，不证明重复文字目标已唯一消歧。Trace: `logs/traces/vision/20260527-182704-779212__locate-target__browser.json`。



将默认矩阵预算提升到 `48` 后，QQ `关闭窗口` 的真实 no-click 回归记录了 `prompt_anchor_count=48`、`prompt_text_anchor_count=48`，模型输入 `3165` tokens、总处理 `3608` tokens，仍在当前 `4096` context 内且未截断或 fallback；定位结果为 `located_bbox={x:787,y:0,w:21,h:36}`、`located_point={x:798,y:18}`，动作保持未执行。Trace: `logs/traces/vision/20260527-183444-432196__locate-target__browser.json`。



## 模型管理



模型配置现在由 registry 管理：



```text

configs/model_profiles/*.json

```



一个 profile 描述一个模型：



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



运行时当前选择写入：



```text

configs/vision.json

```



当前拆成两个本地视觉角色：



- `vision.local_understanding`：学习/观察理解模型，默认使用 8B 来提高模板、路径图和界面详情产物质量；4B 作为快速可选 profile

- `vision.local_grounding`：大模型，负责精准定位



测试面板的模型下拉只读取 `configs/model_profiles/`，避免同一个模型从多个来源重复出现。



## Agent 工作流



上层 Agent 应该按 API-first 的流程操作，不直接使用模型返回的原始坐标点击。



推荐顺序：



```text

GET  /apps

POST /runtime/prepare            可选，启动/探活本地视觉模型

POST /apps/open                 可选

GET  /session/windows

POST /session/bind_window

POST /state/capture_window      可选，接口内部也可 live capture

POST /vision/observe_screen

POST /vision/locate_target

POST /action/execute_recognition_plan  dry_run=true

POST /action/execute_recognition_plan  dry_run=false，携带 approved_plan_id

POST /action/scroll                    可选，仅当 fallback_plan 要求滚动补全可见信息

```



关键原则：



- 先用整屏理解得到简短候选列表，再对选中的目标精准定位

- `observe_screen.suggested_state_hint` 是下一次 `locate_target.state_hint` 的默认建议；测试面板会自动填入，agent 仍可按目标覆盖

- 面板现在只保留 `Learn Mode / Execute Mode` 两个工作模式切换；打开/绑定、截图、Trace 作为通用系统工具常驻在左侧，确保绑定窗口、截图和 trace 上下文能继续传给学习/执行流程。健康检查和模型测试收进齿轮设置入口。打开/绑定页把“可启动应用”和“可绑定窗口”分开：前者来自配置，用来打开应用或 URL；后者来自当前 OS 顶层窗口，用来决定截图、理解、定位和点击目标。Learn Mode 只放学习流程，整屏理解按钮是“快速建图”，固定发送 `agent_mode=learn, learn_depth=fast`，精准定位在 Learn Mode 下是“深度校准路径图”，固定发送 `agent_mode=learn, learn_depth=deep` 和 `metadata.learn_all_targets=true`；Execute Mode 的第一步是“当前状态 / 可用动作”，可先调用 `POST /vision/observe_screen` 执行态理解当前页面并写 trace，但 `write_policy.path_graph=false`，不污染学习路径图；随后调用 `POST /execute/available_actions` 基于已学习 `runtime_path_graph_v1`、当前屏幕清单和安全策略生成动作列表，后续才进入精准定位、点击 Gate 和输入。

- `Learn Deep` 现在由 Learn Mode 下的 `locate_target` 承担全量校准入口：复用上一条 Observe trace 的 `screen_map_v1`，再输出 `learn_all_targets` 和 `path_map_review_v1`。每个子路径控件都会带 `coordinate_validation`，汇总 `validated_count/invalid_count`，并生成 `coordinate_overlay_path` 坐标框图；面板截图预览会优先显示这张校验图。若配置的是非点定位 review 模型，可先调用模型审查补充遗漏子节点、修改错误坐标、重命名误标节点并删除重复/噪声节点；若 `local_grounding` 是 VISTA `vista_point_v1` 点模型，则跳过全图模型审查，避免用点定位模型做慢而无效的 full-map review。历史的 observe-stage deep review 仍作为模型语义审查能力保留，但面板主流程先按 Observe 快速建图、Locate 深度校准来组织。

- VISTA 可作为 Learn Deep 的逐节点坐标复核层：`metadata.learn_vista_coordinate_validation` 控制是否逐个 target 发送短指令给 VISTA。默认最多校验 5 个、每个 12 秒超时、失败即停；设置 `max_targets: "all"` 才会尝试全量。每个节点会写入 `vista_coordinate_validation`，点落入 bbox 才更新 click_point，点落框外或超时则标记 `needs_review` / `failed`。

- Learn Deep 路径校准增加重叠规则：同级子路径节点不允许明显重叠，只有一个 bbox 完整包含另一个 bbox 的父子关系允许重叠。模型审查上下文会要求 `resolve_non_containment_overlaps`，后端合并候选后也会确定性移除低优先级的非包含重叠候选，并把 `non_containment_overlap_removed` 写入 `path_map_review` / trace。

- `observe_screen.screen_map` 是整屏理解阶段生成的页面/动作地图，测试面板导航路径图会直接消费其中的页面分区、候选控件、风险等级和预期效果；observe trace 也保留这份地图，Trace Inspector 会显示为 `Path Map` 阶段，并先渲染整屏理解生成的动态路径图，再显示分区/候选清单与截图 overlay。路径图规则会把顶部导航区的有效 OCR 文字作为导航按钮候选，并把正文/推广区的相关 OCR 文本聚合成整张卡片候选，而不是只保留标题文字框

- `screen_map_v1` 候选生成按区域、控件、聚合、过滤四层规则补齐模型漏项：顶部导航文字强制作为导航候选，正文/右栏 OCR 文本可聚合为 `news_card` / `recommendation_item` 并保留 `children`；右侧推荐会归入 `right_sidebar`；`查看更多` / `More` / `See more` / `View more` / `Read more` 这类入口优先作为 `button`，不会再被当成新闻卡片；时间/来源/低质量短文本会被过滤为卡片证据而不是同级主候选。

- `screen_map_v1` 的区域划分现在区分浏览器网页和普通软件界面：浏览器/新闻网页继续使用 `browser_chrome/page_header/main_content/right_sidebar/lower_content`；普通客户端使用更中性的 `top_bar/primary_area/bottom_bar`。`right_sidebar` 只有在浏览器型页面且右侧有足够推荐/相关内容证据时才创建，不再仅凭窗口宽度生成。

- 导航路径图的子控件节点默认收起，点击页面主节点才展开；展开后会按 `page_header`、`main_content`、`right_sidebar`、`lower_content` 等区域分组显示子路径泳道，并按画布宽度和标签宽度自适应列数、行距和画布高度，避免大量导航按钮或新闻卡片子节点堆叠。点击子路径节点会打开同一页面详情，在顶部显示当前子路径的 label、类型、区域、candidate id、置信度、bbox/click point，并在详情列表里高亮对应控件。

- 新 Learn Recognition 前半段现在有 `learn_grounding_request_v1` 合同：Parser/Classifier 只生成候选，ROI grounding 模型返回的 `roi_local_point`、`uground_0_999` 或 `normalized_0_1` 点位会先通过 `coordinate_transform_v1` 还原并交给 Validator，再进入只读 `learning_template_draft_v1`。该产物仍然 `artifact_is_authorization=false`、`execute_binding_enabled=false`，不替代 Execute Gate。

- 单 ROI actual grounding smoke 已能对保存的 python.org 截图调用本地 VISTA endpoint，并在修正 `candidate_bbox_in_roi` 后通过 Search button 点位验证。报告位于 `logs\benchmarks\learn_recognition_actual_grounding_smoke_v3\learn_actual_grounding_smoke_report.json`；这只是单样本 actual grounding 证据，不是 90% 或 Execute 稳定性结论。

- Calibrated-target batch smoke 已完成一次 fresh actual VISTA ROI 复跑：`logs\benchmarks\learn_recognition_actual_grounding_smoke_batch_v2_prompt3\learn_actual_grounding_smoke_batch_report.json`。该 5-case saved-screenshot smoke 在移除固定示例坐标后 `passed=5/attempted=5`，说明当前 `roi_local_point` 服务合同和 prompt 不再触发 `[57,46]` 复制污染；但样本仍太少，不能宣传为 90% 或模型稳定性。

- 截图预览卡片位于导航路径图下方，右侧响应区保留页面详情和 API/trace 证据；Learn Mode 深度校准返回 `learn_all_targets_ready` 时，状态显示“路径图已校准”。

- `recognition_plan` / `execute_recognition_plan` 现在会接收 `observe_trace_path`。当 trace 与当前截图匹配且含 `screen_map_v1` 时，会先生成 `path_graph_recall_v1`，把与当前 goal 相关的路径候选、状态匹配、local OCR ROI 提示写进响应和 trace；召回候选会并入 `candidate_result`，参与后续局部 OCR grounding 和 `pre_click_decision_v1`；Trace Inspector 显示为 `Path Recall` 阶段。若 `local_grounding.output_contract=vista_point_v1`，PathGraph 主路径会直接裁候选 ROI 给 VISTA：top1 分数明显领先时只裁 top1，否则合并 top3，默认 padding 48px、最小 ROI 256px、最长边 640。模型输入、ROI crop bounds、候选 bbox 的 ROI 坐标 prompt、原始输出、解析 JSON 和换算后的原图点会写入 `model_io` 与 `parse_result.vista_point_grounding`，Gate 仍只验证原图坐标。

- `execute_recognition_plan` 也支持 `auto_observe_learning_artifacts=true`，或 `metadata.learning_artifacts.auto_observe=true`。当调用方没有传 `observe_trace_path` 时，执行接口会先用同一张截图做一次只读 Learn-fast Observe，生成带 learned PathGraph / Interface Map / visual assets 的 trace，再把该 trace 传给内部 recognition plan。这个自动 Observe 只装载学习产物和写 trace，不授权点击；如果失败会返回 `auto_observe_learning_artifacts_failed`，不会静默退回无学习产物路径。

- Execute Mode 现在会输出 `screen_inventory_v1` 作为快速“当前有什么可操作”的清单合同。它从结构化的 `screen_reading_v1` 证据生成，不额外调用全屏理解模型，并拆成 `available_actions`（可点击/输入/选择/切换/卡片候选）、`page_elements`（薪资、日期、posted/company/location 等可见文字和元数据）和 `cards`（职位/新闻/结果卡片及其子节点 id）。`POST /vision/screen_reading` 会内嵌它，普通 `recognition_plan_v1` 会在顶层和 `parse_result.screen_reading.screen_inventory` 暴露它；VISTA direct 分支会优先复用 Observe trace 里的 inventory，没有 Observe 时会用当前绑定窗口的 Windows UIA 快速生成 `execute_fast_inventory_v1`，并过滤浏览器 chrome、窗口容器、地址栏和无名泛容器。Trace Inspector 会显示独立 `Inventory` 阶段，展示 actions/text/cards 数量和坐标覆盖率。可用 `uv run python scripts\benchmark_screen_inventory.py --output artifacts\accuracy-checks\screen_inventory_benchmark_report.json` 复测 typed ground truth 下的 action/page/metadata/card recall、action precision、clickable false-positive rate、候选数、重复率、坐标覆盖和构建耗时。

- Execute Mode 支持 Direct VISTA fallback：当 `agent_mode=execute` 且没有可用 PathGraph recall 候选时，`recognition_plan` 会用 VISTA 直接对当前 goal 输出一个点，生成 `vista_direct_*` 临时候选，再交给 `pre_click_decision_v1`。成功时 `execution_path.vista_direct_point_grounding_used=true`；超时或失败时返回 blocked plan，并在 `model_io.status=failed` 和 trace 中记录错误，不会绕过 Gate 裸点点击。

- Agent 调用 `POST /action/execute_recognition_plan` 时如果没有显式传 `provider_mode`，Execute Mode 会默认使用 `local_grounding`，并启用受保护的 `vista_direct_grounding` 配置。Direct VISTA 的默认保护上限是 `timeout_seconds=45.0`、`max_edge=640`、`refine=true`、`refine_roi_size=512`：运行时保存原始截图作为 evidence，先把送入 VISTA 的全图缩放到最长边 640 做 coarse grounding，再围绕 coarse 原图点裁出 512x512 ROI 做 refine grounding，最终点映射回原图坐标后进入 Gate。`parse_result.vista_point_grounding` 会记录最终点，同时保留 `coarse_vista_point_grounding`、`refine_vista_point_grounding`、processed image、crop bounds、transform、模型原始输出和 processed/original 坐标。调用方仍可用 `metadata.vista_direct_grounding.timeout_seconds` / `max_edge` / `refine` / `refine_roi_size` 显式覆盖。接口返回 `agent_step_result_v1` 和 `agent_execution_guidance_v1`：dry-run 通过时给出下一次复用 `approved_plan_id` 的请求体，真实点击验证通过时返回 `next_action="done"`，失败或 Gate 拒绝时返回可恢复的 `fallback_plan`。推荐 agent 先 `dry_run=true` 生成可审查计划，再用 guidance 里的 approved-plan 请求执行真实点击。

- VISTA 缩放准确率可以用 `python scripts\benchmark_vista_scaling.py --cases artifacts\accuracy-checks\execute_mvp_vista_scaling_cases.json --max-edges 448,512,640,768 --output artifacts\accuracy-checks\execute_mvp_vista_scaling_report.json` 复测。case 需要包含保存截图、goal、expected bbox、expected click point 和允许距离；报告会输出 latency、点是否落入 bbox、到预期点距离、边界 margin、相邻目标误点和 Gate 结果。当前 Execute MVP 样本显示 448 失败、512 risky、640 pass、768 pass 但明显更慢，因此默认不全局升到 768/896，而是用 640 coarse + ROI refine 平衡速度和准确率。

- Execute Mode 的 PathGraph 召回会先过滤 `browser_chrome` 区域，避免地址栏、浏览器工具栏 OCR 被当成网页目标。`pre_click_decision_v1` 只在 ranker 已给出 `precision_text_target_matches_goal`、强文本匹配、本地 OCR 在候选框内命中且非广告风险时，放行精确文字按钮；普通精确文字卡片仍保持需要确认。

- `Execute Mode` 现在有闭环 MVP：真实点击必须通过 `pre_click_decision_v1`，验证成功后按 `write_policy.element_memory` 写入 `execute_transition_memory_v1`；失败时返回 `execute_fallback_plan_v1`，列出局部重扫、PathGraph review、滚动补全可见信息、全屏 OCR 刷新或重新 grounding 的下一步，但不会绕过 gate 自动点击。Trace Inspector 显示 `Memory` 和 `Fallback` 阶段。

- 如果 `fallback_plan.steps[]` 出现 `request_scroll`，表示当前截图可能没有露出足够信息。上层 agent 可调用 `POST /action/scroll` 对当前绑定窗口执行 `up/down` 滚轮动作，查看 `post_scroll_verification` 和 action trace，然后用同一个 goal 重新调用 `POST /action/execute_recognition_plan`。滚动只是 reveal/navigation 动作，不授予点击权限，也不会替代下一次 `pre_click_decision_v1`。

- SEEK 自动求职 MVP 的 no-apply traversal 已有真实 SEEK 5 岗 smoke 证据：`scripts/seek_mvp_traversal_runner.py --max-jobs 5 --max-detail-scrolls 6 --max-results-scrolls 8 --execute-clicks --candidate-profile tests\smoke\seek_candidate_profile_smoke.json` 生成 `logs\smoke\seek_mvp_traversal_real_5_profile_smoke_rerun12.json`，结果为 `jobs_seen=5`、`jobs_opened=5`、`jobs_fully_read=5`、`strong_apply=2`、`maybe_apply=2`、`need_user_review=1`、`saved_jobs=4`、`final_submissions=0`。最新 read-only regression 生成 `logs\smoke\seek_mvp_readonly_regression_3jobs_20260617.json`，`jobs_opened=3`、`jobs_fully_read=3`、详情滚动全部为 `seek:job_detail`、列表滚动全部为 `seek:results_list`、`final_submissions=0`。底座包含 container-aware scroll、可见岗位抽取、详情 header+body 读取、详情滚动停止条件、candidate profile 匹配和适合岗位保存；runner 的真实点击仍走 `recognition_plan_v1` / `pre_click_decision_v1` / post-click title-match verification。runner report 现在会把详情滚动和列表滚动的 `scroll_scope` / `target_pane` / `target_container_id` 写出来，用于检查 SEEK 嵌套滚动是否滚到 `seek:job_detail` 或 `seek:results_list`。`--apply-entry` 已实现 guarded Apply / Quick Apply 入口：只对 `strong_apply` 默认启用，请求带 `forbid_final_submit=true`，action 层输出 `final_submit_guard_v1` 并能在最终提交候选上点击前阻断；Apply 点击计划生成前还会写入 `pre_apply_detail_verification_v1`，重新 observe 当前右侧 title/company/apply state，不匹配则停止。最新 Apply Entry read-only smoke `logs\smoke\seek_mvp_apply_entry_readonly_1strong_20260617.json` 已进入一次申请流程且停在 `application_form_detected_stop_before_form_fill`，`form_fields_filled=0`、`continue_clicks=0`、`submit_clicks=0`、`final_submissions=0`。Apply 后现在会生成 `seek_application_flow_state_v1`、`final_submit_visible_blocker_v1`、`cover_letter_draft_v1` 和 `application_answer_plan_v1`；`final_submit_visible_blocker_v1` 会忽略 `Do not click Submit` 这类负约束说明，只把 action-like 控件或短按钮标签当作最终提交证据。`--fill-safe-fields` 是默认关闭的 opt-in 开关，只能填写 `auto_safe_known` 字段，并且先 gated focus 再 `type_text(click_before_typing=false, submit=false)`；每个 safe field 结果会嵌入 `safe_form_fill_trace_v1`，记录字段 bbox/source、value hash、focus trace、type_text flags 和零提交安全计数。`post_fill_verification_v1` 会在 type 后重新 observe、重跑 application state/blocker，并要求 DOM/UIA 风格字段值证据才把字段计为 verified；unverified 或 final submit 可见时停止后续字段。Continue / Next / Review / Submit 仍禁止。详细范围见 `SEEK_MVP_PLAN.md`。

- SEEK `seek_job_cards_v1` 的 synthetic 结果卡片现在必须有 location 或 company+SEEK 元数据锚点，会过滤详情分类、正文句和 section heading 假卡，并在 evidence 中记录 `synthetic_validation` 供 trace/report 审计；同一 company/location 且 bbox 高重叠的卡片候选会优先保留 UIA 完整标题，压掉混合 screen label 或不完整 hyperlink label；明显跨行标题会先合并再抽 company。详情完整性现在接受 `requirements` 或 `responsibilities` 作为 role evidence。最新 no-apply 3-job follow-up `logs\smoke\seek_mvp_readonly_after_role_evidence_3jobs_20260617.json` 达到 `jobs_fully_read=3`、`detail_read_completion_rate=1.0`、`post_click_layout_drift_count=0`、`card_click_open_rate=1.0`、`wrong_scope_scroll_count=0`、`final_submissions=0`。

- SEEK runner 的 `report.jobs[]` 现在从 `traversal_steps` 对齐生成：drift 卡片保留 `detail=null`，不会把后续详情错配到失败卡片；职位队列去重会归一化标点和常见粘连标题，例如 `SeniorSoftware`。最新 5-job no-apply `logs\smoke\seek_mvp_readonly_after_stuck_title_key_5jobs_20260617.json` 达到 `jobs_opened=5`、`jobs_fully_read=5`、`detail_read_completion_rate=1.0`、`wrong_scope_scroll_count=0`、`submit_clicks=0`、`final_submissions=0`，剩余一个 Vista Group synthetic-card 点击 drift 以 `detail=null` 明确记录。

- SEEK live debug should use `scripts\seek_debug_step_runner.py` before any unattended traversal. It runs one step per command, writes `seek_debug_step_report_v1` with screenshot paths and traces, and exits; use it to inspect card click timing, window-size drift, and `seek:job_detail` nested scroll behavior before returning to `scripts\seek_mvp_traversal_runner.py`. Detail-scroll debug reports include `left_results_visual_stability`, a screenshot-crop check that verifies the left results pane stayed still while the right detail pane moved.

- Execute Mode 只做单步原子动作，不在后端内部编排多步路线。上层 agent 读取 `agent_step_result_v1.status`、`next_agent_action`、overlay/trace 路径和 post-click before/after/diff 证据后，再决定是否再次调用 Execute 做下一步。

- SEEK `application_answer_plan_v1` 的 safe-known 字段识别保持保守：只把简单文本/email/url/tel 且 profile 有明确值的 first/last/preferred name、email、phone/mobile、city/suburb、GitHub、LinkedIn、portfolio/website 归为 `auto_safe_known`；button/radio/select/dropdown/file 和薪资、入职时间、搬家、健康、犯罪、背景调查、复杂签证、上传、Submit 仍不会自动填。

- SEEK safe-fill 默认最多只填 1 个字段：`--max-safe-fields-to-fill=1`。`cover_letter_draft_v1.draft` 默认不会被填写，除非显式传 `--allow-cover-letter-fill`；第一轮真实 safe-fill smoke 不应打开这个开关。

- SEEK runner 报告包含 `candidate_profile_readiness_v1` 和 `seek_apply_entry_profile_gate_v1`。如果当前 profile 是 smoke/test/synthetic、缺少 `profile_source="real_user_candidate_profile_v1"`、或缺少真实 name/email/phone/GitHub/LinkedIn 等低风险文本值，readiness 会给出 `blocked_need_real_candidate_profile`，Apply Entry 和真实 safe-fill 都必须停止。没有显式 real-user source 的 real-looking profile 仍可用于 no-apply matching，但不能进入 Apply Entry。Smoke/test 检测使用明确短语，不会把 `test automation` 这类真实技能误判为 test profile。

- 上层 Agent 应保留用户原文用于 trace，但发给视觉模型的 `goal` / `state_hint` / 排除约束建议规范化为英文；例如用户说“点击第一个自然搜索结果”，模型侧可写成 `Click the first organic Google search result title` 和 `main organic search results list below Google navigation tabs`

- OCR anchors 默认参与视觉定位；精准定位保留完整 OCR 结果用于校验，但向模型发送受预算控制的几何投影，只有目标文字高匹配时才附带文字

- `observe_screen` 只用于界面摘要、地图生成和候选发现；`screen_map` 里的 bbox/click_point 只是观察证据，不用于点击或最终坐标证明

- `locate_target` 如果复用了上一条 Observe trace，会返回 `path_map_review_v1`：根据本次精准定位的 AI/候选证据补入缺失路径候选，并删除同标签或高度重叠且被 Locate 替换的旧候选。测试面板只会删除未点击、未连到下一页面的控件。

- `locate_target` 只返回 no-click 定位结果

- `located_bbox` / `located_point` 是精准视觉模型建议的目标位置；只有 `selected_click_point` 表示已通过点击前闸门的可执行坐标

- 自主 agent 的真正点击只能走 `execute_recognition_plan`

- 测试面板的 `execute_confirmed_point` 仅用于操作者已查看候选框后的显式坐标点击，不是自动执行旁路

- 执行前必须通过 `pre_click_decision_v1`

- 成功 dry-run 会返回 `approved_plan_id`；真实点击应复用这个 ID，runtime 校验同一窗口和已批准点位后直接点击，不再第二次运行大视觉模型

- 外部最小 smoke 可用 `python scripts\smoke_execute_single_step.py --goal "click Learn more" --app-name edge`。默认只执行框架截图和 dry-run，不会真实点击；显式加 `--execute` 才会复用 approved plan 执行一次真实单步点击。

- Execute Smoke Matrix 的最小 runner 是 `python scripts\execute_smoke_runner.py --case tests\smoke\execute_cases\execute_mvp_start_dryrun.json`。case 使用 JSON，包含 `id/app/goal/mode/expect`；runner 默认只 dry-run，不真实点击，并把 `execute_smoke_result_v1` 写到 `logs/smoke/execute_smoke_results.jsonl`。`expect.point_in_rect` 可声明人工核对过的安全落点区域，runner 会把 `selected_click_point` 和 `coordinate_overlay_path` 打印出来并写入 JSONL，防止 API allowed 但坐标明显错误仍被算作通过。只有显式加 `--execute` 才会复用 approved plan 执行真实单步点击；标记 `mode.destructive=true` 的 case 会拒绝真实执行。批量 dry-run 可用 `--cases tests\smoke\execute_cases`，重复稳定性检查可用 `--repeat N`；当前样本包含受控页面 `execute_mvp_start_dryrun.json` / `execute_mvp_continue_dryrun.json`、第二应用 `notepad_file_menu_dryrun.json`、SEEK 类本地简历筛选流程 `seek_resume_screening_flow.json`，真实 SEEK 求职列表 dry-run 矩阵 `seek_real_jobs_dryrun.json`，每个目标前重新打开 SEEK 页面的 `seek_real_jobs_reopen_dryrun.json`，以及调整窗口尺寸后的 `seek_real_jobs_resized_dryrun.json`。

- runner 支持 `app.open_before=true`，会先调用 `/apps/open` 打开本地页面或浏览器 URL，再让 Execute Mode 做截图、dry-run、approved-plan 执行和 post-click 验证。`--execute` 结果现在同时记录 `dry_run_latency_ms` 和 `execute_latency_ms`；`expect.max_latency_ms` 检查的是 dry-run 决策耗时，也就是模型识图/坐标判断是否满足 10 秒目标。

- SEEK 类本地 smoke 可用：



```powershell

$env:PYTHONIOENCODING='utf-8'

$env:UV_CACHE_DIR='.uv-cache'

uv run python scripts\execute_smoke_runner.py `

  --case tests\smoke\execute_cases\seek_resume_screening_flow.json `

  --out logs\smoke\seek_resume_screening_flow_results.jsonl `

  --execute `

  --timeout 120

```



最新 clean 验证在本地 `app/web_panel/seek_resume_fixture.html` 上连续执行两步：`Click Shortlist Avery Chen` 和 `Click Open Next Candidate`。两步都先 dry-run 生成 overlay，再复用 `approved_plan_id` 真点。2026-06-16 的空闲窗口 `--repeat 3 --execute` 运行 6/6 通过；dry-run 决策耗时 `2149.517ms..2352.048ms`，真实执行耗时 `1743.997ms..1762.612ms`，post-click verification 全部成功，点位均落在声明的按钮矩形内。该轮确认了 approved-plan 复用偶发 `approved_plan_window_size_mismatch` 的根因修复：保存的 bound-window rect 可能是 Windows 最小化占位 `-32000`，复用校验现在使用 live capture 的 `coordinate_window_size` 作为点击坐标空间真值。



真实 SEEK 页面也有一个低风险 reviewed click smoke：`tests/smoke/execute_cases/seek_real_job_card_execute.json` 打开 `https://www.seek.co.nz/software-engineer-jobs/in-All-Auckland`，先 dry-run 第一个岗位标题，再复用 `approved_plan_id` 真实点击进入右侧岗位详情面板。2026-06-16 复跑通过，dry-run `2725.172ms`，真实执行/验证 `1793.901ms`，落点 `{x:148,y:552}`，overlay `artifacts/review-overlays/20260616-232018-701749-execute-mode-recognition-plan-edge__recognition-plan-overlay__20260616-232018-711749.png`，action trace `logs/traces/actions/20260616-232020-541876__execute-mode-click__edge.json`，post-click verification 为 `verified=true`。



真实 SEEK 页面只做 dry-run，不默认真实点击外站。复跑：



```powershell

$env:PYTHONIOENCODING='utf-8'

$env:UV_CACHE_DIR='.uv-cache'

uv run python scripts\execute_smoke_runner.py `

  --case tests\smoke\execute_cases\seek_real_jobs_dryrun.json `

  --out logs\smoke\seek_real_jobs_dryrun_results.jsonl `

  --timeout 120

```



当前 case 覆盖 `Click the first job result title`、`Click the Pay filter`、`Click the Listing time filter`。最新普通 dry-run 3/3 通过，决策耗时约 `2.12s..2.25s`，点位均落在人工矩形内。重复稳定性检查也已通过：`--repeat 2` 连续跑 6/6 通过，六次 dry-run 都在 `2.13s..2.21s` 内完成。`seek_real_jobs_reopen_dryrun.json` 会在每个目标前重新打开同一 SEEK URL 并重新绑定窗口，最新 3/3 通过，耗时约 `2.14s..2.19s`，overlay 抽查确认落点在目标控件上。`seek_real_jobs_resized_dryrun.json` 会把绑定窗口调整到 `1100x900` 后再执行判断，最新 3/3 通过，耗时约 `2.08s..2.22s`，overlay 抽查确认目标仍正确。负例：`Click the Date filter` 在当前 SEEK 页面上不是可见标签，模型曾误指向浏览器工具栏日期/扩展区域；现在 Direct VISTA 会在创建候选前拒绝浏览器 chrome 区域点，单测覆盖 `vista_direct_point_in_browser_chrome`。稳定 case 仍建议使用页面可见标签 `Listing time`。

- `learning_mode="instruction"` 是最简指令学习模式：成功真实点击并验证后，runtime 写入 `learned_instruction_v1`。后续调用带 `learned_instruction_id` 时，在验证 goal、窗口句柄、窗口尺寸和点坐标边界一致后复用点击点，仍会执行点击后验证

- 指令学习资产不是普通截图缓存。每条学习指令永久保存在 `artifacts/local-learning/instructions/{id}/` 下，含 `learned_instruction.json`、源窗口截图、点击前截图、点击后截图、diff 图和目标裁剪

- Agent 对外的 runtime、app、vision、识别执行路径现在均包含 `timings`，含 `total_ms` 和 `steps[]`，agent 可据此判断耗时花在模型启动、截图、OCR anchor 准备、视觉推理、排序、点击前闸门、点击派发还是点击后验证



完整 Agent API 调用规范见：



```text

AGENT_API_WORKFLOW.md

```



每个 API 的字段含义、设计目的、返回结构见：



```text

API_FIELD_REFERENCE.zh-CN.md

```



### Text-Card Localization Safety



Text-bearing clickable cards now have a conservative review path. A `card` region is retained only when it declares `include_referenced_text`, a destination, complete edge evidence, and bindable OCR text. Its proposed bbox and point come from matched OCR text rather than a drifting visual card boundary, and it is not an autonomous click approval.



A 2026-05-27 saved Seek localization for Serato showed that a dense page can overflow the anchor-enriched 48-row attempt and use the existing OCR-anchor fallback. Downstream OCR binding still corrected the reviewed candidate to `{x:58,y:649,w:276,h:51}` / `{x:196,y:674}` without clicking.



For list-style text targets, fusion also records an `unreferenced_text_contamination` from OCR text inside the visual bounding box that wasn't explicitly referenced by the vision model. If the model's semantic card bbox contains unreferenced OCR text, the target is forced into confirmation-only review mode while its OCR-derived candidate bbox remains usable for inspection.



## 主要接口



应用和窗口：



- `GET /apps`

- `POST /runtime/prepare`

- `GET /runtime/models`

- `POST /runtime/models/start`

- `POST /runtime/models/stop`

- `POST /apps/open`

- `GET /session/windows`

- `POST /session/bind_window`

- `POST /session/resize_bound_window`

- `GET /state`

- `POST /state/capture_window`



`POST /state/capture_window` uses screen-coordinate capture, so it brings the bound window to the foreground and waits briefly for the window to settle before grabbing pixels. It only calls window restore when the target is minimized, so a maximized browser should not briefly unmaximize during capture.



视觉：



- `POST /vision/analyze`

- `POST /vision/page_structure`

- `POST /vision/screen_reading`

- `POST /vision/observe_screen`

- `POST /vision/locate_target`

- `POST /vision/recognition_plan`

- `POST /vision/render_recognition_plan_overlay`



动作：



- `POST /action/execute_recognition_plan`

- `POST /action/execute_confirmed_point`（操作者确认坐标点击）

- `POST /action/type_text`

- `POST /action/click_text`



## 识别管线



当前主路径：



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



主要 agent 路径现在会返回 `timings`：其中 `total_ms` 是整次调用耗时，`steps[]` 会拆出模型启动、截图、OCR anchor 准备、视觉推理、候选排序、点击前闸门、真实点击和点击后验证等阶段。它只用于性能诊断和 trace 复盘；是否允许点击仍以 `pre_click_decision_v1` 为准。



重点：



- OCR 文字框会作为空间锚点传给视觉模型；`click_target` 默认发送 `relation_matrix_compact` 文字坐标与包含/排除策略矩阵，并按预算选择 anchor 而非注入整页冗长结构

- 图标和文字的关系会进入 grounding 证据

- 小图标定位优先参考 OCR anchors

- 候选点击点必须经过本地 ranking、narrow search 和 pre-click gate

- overlay 可用于人工复核



## 项目结构



```text

app/

  api/                FastAPI routes

  core/               window, screenshot, OCR, input, verifier

  web_panel/          浏览器测试面板 (HTML/JS/CSS)

  vision/             local/API vision providers and prompting

  page_structure/     page structure and screen reading logic

  models/             request/response schemas

configs/

  app_catalog.json

  settings_panel.json

  vision.json

  model_profiles/     model registry

scripts/

  start_test_panel.bat

  model_servers/      model server start/stop scripts

tests/

artifacts/

logs/

```



详细目录说明见：



```text

PROJECT_STRUCTURE.md

```



## 当前状态



已具备：



- 本地 FastAPI runtime

- Windows 窗口发现和绑定

- 截图和 ROI 截图

- OCR anchors

- local/API 视觉 provider 抽象

- `observe_screen` 整屏理解接口

- Learn Mode 自动从 `screen_map.candidates` 裁剪固定按钮/图标视觉资产，输出 `visual_asset_learning_v1`

- Execute recognition plan 会先尝试 `visual_asset_recall_v1`，把当前截图里的已学固定按钮匹配成 fresh `seeded_candidate_v1`；低风险按钮可跳过慢模型，高危提交类按钮仍只作为证据并强制过 Gate。匹配 trace 会记录当前 ROI、当前匹配 crop、灰度/边缘匹配方法、top candidates、score gap 和耗时。若 goal 已明确 Apply / Save / Search / Filter / Continue / Submit 等动作，visual asset fast-lane 必须匹配该动作本身；`SEEK`、`job`、`top search area` 这类品牌/上下文词不能单独授权 fast-lane。

- `pre_click_decision_v1` 对同一目标的重复 UIA 候选做等价处理：不同 element id、同文本且 bbox 重叠的 text/link 候选不会因为 `margin_to_second=0.0` 被误拒；但非等价的近邻文本仍会保留 `top_candidate_margin_too_small`。当 goal 有明确动作目标时，品牌词或介词候选会记录 `candidate_goal_action_mismatch` 并被拒绝。`Apply` / `Quick Apply` 仍是 `open_apply_flow`，不是 final submit；`Submit` / `Send` / `Confirm` / payment 仍硬阻断。

- Learn Replay 面板可以加载并编辑 `learned_interface_map_v1`，按区域展示固定视觉按钮、动态 ROI 区和危险区。`merge_visual_asset_match_evidence()` 会把当前截图匹配证据回填到固定按钮资产；点击 Inspect 可查看 source crop、current ROI、current match、bbox/click point、scope、match policy、semantic action、danger level、fast-lane eligibility 和 raw JSON，并通过 `/panel/save_interface_map` 保存编辑后的学习产物和 `learned_interface_map_edit_trace_v1`。面板现在把“看模板”和“看学习草稿”做成同页切换，避免输入模板和学习产物混在一起：模板视图显示 PathGraph、Interface Map、校准报告、Profile 和 Prompt 来源；学习草稿视图显示生成的 SEEK 模板草稿、导航 PathGraph 草稿、界面详情、pattern candidates、draft regions/actions、eval 和安全结果。学习草稿视图还提供本地审核标记、加载草稿 PathGraph 到 Navigation Path、加载草稿界面详情到 Interface Map 区的按钮；这些都是预览/审查动作，不写回 Profile、PathGraph，也不授权点击。本地 no-mouse smoke 同时覆盖低风险 `Quick apply` 和高风险 `Submit application`：前者可成为 fast-lane 候选，后者即使命中也保持 `final_submit_fast_lane_count=0` / `final_submissions=0`

- `locate_target` 精准定位接口

- no-click recognition plan

- pre-click decision gate

- gated click execution

- recognition overlay

- MouseTester 真实点击基线

- 浏览器测试面板（含 Trace 阶段解析、模型直连测试、导航路径图）

- 指令学习模式（instruction learning），可复用已学习的点击

- 模型 registry 和统一模型启动/停止脚本目录



最新重点模型实验：



- `Qwen3-VL 8B Q4_K_M`：llama.cpp CUDA，2/2 成功，平均单 case约 `4.59s`，平均召回 `0.7`。当前作为学习模式 / 整屏观察默认模型，用于提高模板、路径图和界面详情产物质量。

- `Qwen3-VL 4B Q4_K_M`：llama.cpp CUDA，2 个截图理解 case 全部成功，JSON 输出稳定，平均单 case约 `3.09s`，平均召回 `0.7`。当前保留为快速理解 profile，不再是学习模式上限。

- `MiniCPM-V-4.6 Transformers`：Transformers direct，2/2 成功，平均单 case约 `9.07s`，平均召回 `0.8`。当前 llama.cpp 后端无法加载其 `minicpmv4_6` projector，因此保留为 benchmark-only profile，不在面板里直接启动。

- 报告：`artifacts/accuracy-checks/understanding_model_benchmark_20260616.json`

- 结论：35B 不再作为本地基线；学习/观察默认使用 Qwen3-VL 8B，快速理解可手动切 Qwen3-VL 4B，精准点定位继续走 VISTA。



当前边界：



- 还不是生产级通用桌面 Agent

- 还需要更多页面、更多负例、更多窗口尺寸/DPI/缩放变化测试

- 学习写回还未成为主线能力



## 验证



浏览器面板路由测试、runtime 路由测试和执行识别计划测试：



```powershell

uv run pytest tests/test_web_panel_route.py tests/test_runtime_route.py tests/test_execute_recognition_plan_route.py -q

```



全量测试：



```powershell

uv run pytest -q

```



前端语法检查：



```powershell

node --check app\web_panel\panel.js

```

```



## 重要文档



- `README.en.md`：英文版 README

- `AGENT_API_WORKFLOW.md`：Agent 调用 API 的标准流程

- `API_FIELD_REFERENCE.zh-CN.md`：每个 API 的字段级中文设计参考

- `PROJECT_STRUCTURE.md`：文件结构、配置、产物位置

- `docs/PANEL_LEARN_EXECUTE_WORKFLOW.zh-CN.md`：测试面板 Learn / Execute 两套工作区的按钮级操作流程

- `docs/VISUAL_ASSET_LEARNING_MODE.zh-CN.md`：学习模式如何沉淀固定按钮/图标截图资产，执行模式如何用当前截图重新匹配并继续走 Gate

- `docs/LEARN_MODE_TWO_PASS_PIPELINE_CONTRACT.zh-CN.md`：学习模式两轮分栏识别流程合同和防跑偏执行清单，规定先整屏分栏、栏精准定位、再按栏编号/中栏二次分区；每次新识别要清空旧结果、自动刷新融合框、按证据推进进度，并用完整保护集做回归保护，禁止只回归 Apple Music 或用单图 heuristic 替代主流程

- `docs/LEARN_RECOGNITION_PARSER_AND_GROUNDING.zh-CN.md`：学习模式新识别链路的可插拔 Parser、候选模型参数和二阶段 ROI 定位说明

- `PROJECT_SUMMARY.md`：项目摘要

- `CURRENT_STATE.md`：当前状态

- `NEXT_STEPS.md`：下一步计划

- `LEARNING_MODE_PLAN.zh-CN.md`：学习模式设计，区分自我探索和点击后路径记录

- `ACCURACY_EVALUATION_STANDARD.md`：准确率评估标准

- `RUNTIME_STATE_GRAPH.md` / `RUNTIME_STATE_GRAPH.zh-CN.md`：状态图设计



## Learn Recognition support acquisition queue (2026-07-05)



当前 Learn Recognition 的 same-screenshot support acquisition 队列在：



- `logs\benchmarks\learn_recognition_support_acquisition_queue_next\support_acquisition_queue.json`



这个队列只是 operator acquisition / preflight artifact，不是模型能力证明，也不是 PathGraph 或 Execute 授权。`preflight_ready_count=4` 只表示目标截图文件、SHA256、脚本和 manifest 具备下一步采集条件。



其中 `capture_same_screenshot_support` 任务必须先由人工把目标网页/窗口复现到对应截图状态，再运行 `scripts\capture_learn_recognition_same_screenshot_support.py` 采集当前绑定窗口。该脚本不会读取保存截图作为输入；保存截图只用于 checksum 目标锁定和后续 freshness 验证。采集完成后，support artifact 的 `screenshot_sha256` 必须与 target screenshot SHA 完全一致，才能绑定到 actual parser manifest。



`repair_bbox_alignment` 任务不同：它可以对已有保存截图运行 `scripts\create_learn_recognition_calibrated_support.py --screenshot ... --out-dir ...` 做离线校准。两类任务都保持 `artifact_is_authorization=false`、`execute_binding_enabled=false`，不会执行点击、safe fill 或 submit。



队列里的 bind 命令会显式写入每个 case 自己的 `artifacts\benchmarks\learn_recognition_support_repair\<case_id>\learn_recognition_actual_parser_cases_with_support.json`，不直接覆盖 `artifacts\benchmarks\learn_recognition_actual_parser_cases_v1.json`。下一步 batch/diagnosis 需要人工确认后使用这个 per-case manifest。



采集或校准 support 后，应先运行队列里的 `support_validation_commands`。该命令调用 `bind_learn_recognition_support_to_manifest.py --validate-only --json`，只验证 case、目标截图 checksum 和 support sources，不写 manifest。只有返回 `status=validated` / `bindable=true` 后，才运行 bind 命令写 per-case manifest。



可以用下面命令批量巡检队列当前状态：



```powershell

uv run python scripts\report_learn_recognition_support_acquisition_status.py `

  --queue logs\benchmarks\learn_recognition_support_acquisition_queue_next\support_acquisition_queue.json `

  --out logs\benchmarks\learn_recognition_support_acquisition_queue_next\support_acquisition_status.json `

  --json

```



该报告只读取已有 support artifact 并复用 validate-only 校验。它不会采集窗口、不会启动模型、不会运行 grounding、不会写 manifest，也不会授权 Execute。

报告里的 `capture_readiness` 会单独检查目标截图是否存在、checksum 是否匹配，以及当前 pending capture 是否可以进入人工复现步骤。当前状态是 `pending_support_count=3`、`pending_capture_ready_count=3`、`pending_capture_blocked_count=0`；这只说明三条 P1 support 采集任务的目标截图可复现，不说明 support 已经采集完成。



可以生成下一步单 case 操作 brief：



```powershell

uv run python scripts\build_learn_recognition_support_acquisition_brief.py `

  --queue logs\benchmarks\learn_recognition_support_acquisition_queue_next\support_acquisition_queue.json `

  --status logs\benchmarks\learn_recognition_support_acquisition_queue_next\support_acquisition_status.json `

  --out logs\benchmarks\learn_recognition_support_acquisition_queue_next\next_support_acquisition_brief.json `

  --json

```



当前 brief 选择 `python_homepage_full_observe_20260703` 作为下一个 pending P1 target，并列出人工复现窗口、capture、validate-only、bind per-case manifest 的顺序。它仍然只是操作说明，不会自行捕获窗口或执行动作。

Brief 的 `target_screenshot` 会写入保存截图是否存在、尺寸、实际 SHA、`sha256_match`、`ready_for_reproduction` 和 `blockers`；当前目标图为 `2540x1380`、`sha256_match=true`、`ready_for_reproduction=true`，可作为人工复现窗口状态时的参照。若目标图缺失或 SHA 不匹配，brief 会把 `ready_for_reproduction=false` 并记录 `target_screenshot_missing` 或 `target_screenshot_sha256_mismatch`，避免 stale 目标继续进入采集步骤。



## Learn Recognition fusion support export (2026-07-05)



`scripts\export_learn_recognition_fusion_calibrated_support.py` 可以把 `scripts\run_numbered_region_calibration_probe.py` 生成的 `learn_precise_understanding_fusion_v1` 转成同截图 calibrated support：



```powershell

uv run python scripts\export_learn_recognition_fusion_calibrated_support.py `

  --report logs\benchmarks\learn_locator_card_execute_calibration_seek_full_20260705\numbered_region_calibration_report.json `

  --out logs\benchmarks\learn_locator_card_execute_calibration_seek_full_20260705\same_screenshot_support `

  --app-name seek `

  --state-hint seek_results `

  --json

```



导出器只保留 `vista_point_inside_seed_bbox`、`passed_allowed_dry_run`、`real_clicks=0` 的项，其余进入 rejected 审计。输出是 `learn_recognition_same_screenshot_support_v1`，但 `source_tracking=assisted_generation`、`counts_as_model_ability=false`、`artifact_is_authorization=false`、`execute_binding_enabled=false`。它的用途是给学习草稿/路径图候选 review 提供同图回灌证据，不是模型准确率、PathGraph promotion 或 Execute 点击授权。



当前 SEEK 回灌 smoke 在 `logs\benchmarks\learn_locator_card_execute_calibration_seek_replay_with_support_20260705\learn_actual_parser_smoke_report.json`。它证明 support 能被 parser 合并成 cross-evidence review candidates。Job card 目前仍被 pre-click 以 `candidate_goal_action_mismatch` 拦截；下一步应补 `open_detail` 语义，而不是放宽 gate。



Open-detail card 语义已补上第一条最小链路：`scripts\run_numbered_region_calibration_probe.py` 对 job/listing/result card 发送 `task=open_detail` 和 `operation_context.semantic_action=open_detail`；pre-click 的 action-term parser 不再把 `Do not click final submit/send/confirm...` 当作正向 submit 意图。单卡验证报告在：



- dry-run calibration: `logs\benchmarks\learn_locator_card_open_detail_semantic_probe_v2_20260705\numbered_region_calibration_report.json`

- support replay: `logs\benchmarks\learn_locator_card_open_detail_replay_v3_20260705\actual_parser_output_v1.json`



该 replay 生成了 `semantic_action=open_detail` 的学习草稿 action，但仍保持 `execute_binding_enabled=false`。这只是 PathGraph candidate review 的准备证据，不是路径图 promotion，也不是 Execute 点击授权。



### Learning Draft 界面详情候选 (2026-07-06)



学习草稿现在可以生成一个 display-only 的界面详情候选：`scripts\build_learn_page_detail_candidate.py` 会读取当前 `pathgraph_candidate.json` / precise-understanding sidecar，输出同目录 `learn_page_detail_candidate.json`。面板按钮 `生成界面详情候选` 调用 `POST /panel/create_page_detail_candidate`，然后在 Learning Draft 的路径图详情页显示一个按原截图空间位置排列的 mini layout 和分区明细。



当前 SEEK smoke 生成 `learn_page_detail_candidate_v1`：10 个 region、4 个布局 section、10 个 possible operation，状态为 `needs_pending_calibration`。目标验收报告和面板的 `demo_evidence_map.template_like_page_detail` 现在会继续展示 `layout_mode=spatial_bbox_order`、`layout_section_count=4`、`bbox_region_count=10` 和 operation kinds（`fill_field` / `open_detail` / `open_filter` / `read_only` / `submit_search`），所以面试 demo 可以直接说明界面详情已经按原截图空间布局生成，而不是只证明文件存在。该产物只用于 demo/review 展示，不启动模型、不点击、不填写、不提交、不绑定 Execute，也不 promotion Runtime PathGraph。



学习模式 demo 也有了一个串联入口：`scripts\build_learn_demo_scaffold.py` 和面板按钮 `生成学习 demo 串联包` / `POST /panel/create_learning_demo_scaffold` 会从当前候选路径刷新 precise-understanding、PathGraph integration readiness、current evidence packet、page-detail candidate 和 model-only preview，并写出 `learn_mode_demo_scaffold.json`。PathGraph detail 面板会把该 scaffold 渲染成流程卡，显示 full-screen/numbered-region evidence、precise candidate、PathGraph review、integration readiness 和 template-like page detail 的状态。当前 SEEK scaffold smoke 生成 5 个 sidecar，`pathgraph_detail_can_show_page_detail=true`，`model_only_demo_readiness_status=model_only_demo_ready`，但仍有 `precise_pending_calibration_count=6`，所以它证明的是 demo/review 展示链路可用，不是学习模式完整闭环完成。



该 scaffold 还会输出 `model_provenance_audit`，区分 fresh model output、recorded output、assisted generation 和人工 review。当前 SEEK scaffold 的底层有 `actual_model_call_evidence_count=1`，但也有 `assisted_or_human_review_evidence_count=2`，所以 `status=mixed_actual_model_and_assisted_review_evidence`，`meets_fully_model_generated_demo_requirement=false`。这正是下一步要修的 demo 缺口：需要一次 fresh model run 直接进入 scaffold，而不是依赖已审核/手工保存链路。



为贴近“模型输出直接接路径图”的 demo 要求，scaffold 现在还会从 raw actual model artifact 生成 `model_generated_pathgraph_preview_v1`。这条 preview 不经过 `reviewed_template_candidate`，会在 raw `learning_draft` 缺少 regions/actions 时从模型 `screen_inventory` 派生只读 regions/actions，并内嵌 `model_generated_page_detail_preview_v1`。当前 SEEK raw model artifact 可生成 `model_generated_preview_ready`，包含 10 个 preview regions、10 个 preview actions、4 个 page-detail sections 和 10 个 possible operations；`model_only_demo_readiness.status=model_only_demo_ready` 表示“raw 模型产物 -> 只读路径图预览 -> 只读界面详情预览”这条展示链可用。它仍然是 display-only，不授权 Execute 或 Runtime PathGraph promotion，也不改变正式候选仍为 mixed provenance 的事实。



为了防止 demo 口径被说过头，`scripts\report_learning_mode_demo_goal_readiness.py` 现在会从 `learn_mode_demo_scaffold.json` 生成目标级验收报告。面板按钮 `生成 demo 目标验收` 调用 `POST /panel/create_learning_demo_goal_readiness`，生成后 Learning Draft 的 scaffold 详情卡会显示逐项需求、blockers 和 no-execute/no-submit safety；source picker 也会显示 `demo_goal` 状态。当前 SEEK 报告是：



```text

artifacts\learning-draft-review\actual_parser_output_with_fusion_status_7b471afc08\pathgraph_candidate\learning_mode_demo_goal_readiness_report.json

```



结果为 `demo_goal_status=display_demo_ready_official_goal_blocked`、`display_demo_ready=true`、`final_goal_complete=false`。已通过的是整屏/编号证据、选择图、model-only 路径图预览、路径图详情、类似模板的界面详情和 no-execute/no-submit safety；仍阻断的是正式候选不是完全系统模型链、还有 pending calibration。



同一报告现在还输出 `fresh_model_chain_acceptance`，作为最终 demo 目标的严格 provenance gate。当前 SEEK 状态是 `acceptance_status=blocked_mixed_or_assisted_evidence`、`accepted=false`、`actual_model_call_evidence_count=1`、`assisted_or_human_review_evidence_count=2`，并明确 `counts_as_final_goal_completion=false`。面板会把该 acceptance 卡展示在目标验收卡里，说明展示链可 demo，但不能把 mixed/assisted 证据说成“完全由系统模型跑出”。



`fresh_model_chain_acceptance` 现在还内嵌 `replacement_plan`：当前 SEEK 的 plan 为 `replacement_required=true`、`plan_status=blocked_until_explicit_model_start_approval`，需要把 `assisted_or_human_review` 证据替换成 fresh `actual_model_call` 证据。面板会显示只读 replacement steps，包括先取得显式模型启动批准、再运行 fresh numbered-region calibration、刷新 model-generated scaffold、最后重跑 goal-readiness audit；所有步骤仍保持 `command_executes_now=false`、不点击、不填写、不提交、不授权 Execute。



目标验收报告现在还会输出 `next_action_status` 和 `next_actions`，并在面板卡片中直接显示下一步是否需要用户批准、是否允许无批准运行、预期输出和安全约束。当前 SEEK 报告的下一步是 `awaiting_explicit_model_start_approval`，`may_start_model_after_user_approval=true`，`may_run_without_user_approval=false`，待校准编号来自 sidecar 证据并显示为 `1,2,3,6,8,9`。`run_pending_numbered_region_calibration_batch` 会带出校准命令预览，`refresh_scaffold_after_calibration` 会带出校准完成后的 scaffold refresh 命令预览；两者都明确 `command_executes_now=false`，校准命令还明确 `start_model_flag_included=false` 和 `requires_user_or_runner_to_start_model=true`。这些字段只是下一步 runbook，不启动模型、不点击、不填写、不提交。



同一报告还会输出 `demo_evidence_map`，把 demo 所需的四段证据链集中展示：整屏编号识别 overlay、selection/precise-understanding 选择图、model-only PathGraph preview、template-like page detail preview。当前 SEEK 证据链分别指向 full-screen overlay、numbered-region calibration overlay、`runtime_path_graph_model_preview.json` 和 `learn_page_detail_candidate.json`；所有节点都保持 `display_only=true`、`execute_binding_enabled=false`、`artifact_is_authorization=false`。



`template_like_page_detail` 现在还带 `layout_section_summaries`，每个 section 都包含自己的 bbox、region count、possible operations 和 operation/readiness 分布。当前 SEEK 报告可直接解释 top search / left results / right detail / middle controls 四块的大概布局和可能操作，而不是只展示总数。



Learning Draft 面板的界面详情卡也会渲染这些 section summary 和 operation links：每块显示 bbox、region count、操作计数、readiness 计数，以及 region -> possible operation 的只读链接。这让路径图详情页更接近模板详情视图，同时仍不提供执行按钮。



同一报告还会输出 `demo_chain_manifest`，把面试 demo 的固定展示链写成四步清单：整屏编号图 -> selection/precise-understanding 选择图 -> model-only PathGraph preview -> template-like page-detail preview。每一步都会显示 artifact 是否存在、proof fields、`stage_ready_for_display`、`display_only`、`execute_binding_enabled=false` 和 `artifact_is_authorization=false`。当前 SEEK 报告里 `chain_can_be_demoed=true`，但 `chain_is_final_goal_complete=false`，所以它证明的是展示链可演示，不是最终学习模式闭环已经完成。



`GET /panel/learning_draft_sources` 和 Learning Draft source picker 也会摘取同一个 manifest，显示 `demo_chain=true/false`、`demo_chain_final=true/false`、`demo_chain_steps=ready/total`、`demo_chain_missing_proofs` 和 `demo_chain_blockers`。同一个入口现在还会显示 `fresh_acceptance`、`fresh_accepted`、`fresh_final`、actual-model evidence 数量、assisted/human-review evidence 数量和 fresh blocker 数量。这样面板入口就能区分“这份学习草稿适合演示展示链”与“是否满足完全由系统/模型生成的最终目标”。



source picker 还会把 fresh replacement plan 的摘要显示出来：`fresh_replacement_plan`、`fresh_replacement`、`fresh_replace_sources`、`fresh_required_source`、`fresh_replacement_steps` 和 `fresh_replacement_run_now`。当前 SEEK 会显示需要把 `assisted_or_human_review` 替换为 `actual_model_call`，且直接执行命令数量为 0。



source picker 的推荐加载顺序也会优先选择 `demo_chain=true` 且 `demo_chain_final=false` 的 PathGraph candidate，并在下拉选项中加 `[Demo chain]` 标记；如果没有这种候选，才回到 preflight-ready / pinned / 最近文件的旧顺序。



面试 demo 可以直接打开面板并预加载推荐展示链：



```text

http://127.0.0.1:8000/panel?stage=learn_replay&learn_view=draft&demo_chain=1&skip_boot_models=1

```



这个入口只会切到学习草稿页并加载 source picker 推荐的 demo-chain candidate；它仍然是 display-only/review-only，不启动模型、不点击、不填写、不提交、不绑定 Execute，也不 promotion Runtime PathGraph。



## 开发规则



本仓库要求代码和文档同步。行为、API、架构、配置、进度或限制发生变化时，需要同步更新相关文档。



实现代码时遵循：



```text

skills/code-implementation-loop/SKILL.md

```



最小闭环：



1. 做最小有意义改动

2. 跑最窄验证

3. 看结果

4. 修失败

5. 重跑直到通过或记录真实 blocker



## 维护备注



- Windows only

- local-only HTTP API

- 单 session / 单绑定窗口优先

- 不允许直接从模型原始 bbox 点击

- 所有真实点击都应走 gated action API

- 历史细节不要继续塞进 README，放到专门文档里



## 浏览器面板状态 (2026-06-02)



`/panel` 是当前唯一保留的本地测试面板入口。旧的 Tkinter 桌面面板代码、启动器、测试和 `tkinterdnd2` 依赖已移除。`start_test_panel.bat` 会在需要时启动 FastAPI runtime，然后打开 `http://127.0.0.1:8000/panel`。



浏览器面板现已使用分段语言切换按钮、`Learn Mode / Execute Mode` 双模式工作流、常驻系统工具、齿轮设置入口、按阶段显示/隐藏卡片的布局、基于 `/panel/inspect_trace` 的 Trace 阶段解析页面，以及通过 `POST /panel/model_test` 直接向视觉模型发送 prompt 和图片的模型测试页面。Execute Mode 的“当前状态 / 可用动作”页提供“理解当前页面”和“刷新可用动作”两个入口：前者给 agent 一次不写学习 PathGraph 的当前屏幕理解，后者调用 `/execute/available_actions`，用于在单步执行前查看已学习路径图能提供哪些安全动作。动作不再只按点击理解，返回菜单会区分 click / scroll / input 等低层动作和 read 等语义动作。新增的 Learn Mode / PathGraph Safe Validation 页面用于验证候选路径图的安全动作，新增的 Execute Mode / PathGraph Task Run 页面用于展示 agent/harness 连续调用单步 Execute 完成目标的 timeline。



### Trace UTF-8 兼容性更新 (2026-06-02)



浏览器面板 `/panel` 返回 `text/html; charset=utf-8`；Trace JSON 读取使用 `utf-8-sig` 兼容带 BOM 的文件。`/panel/inspect_trace` 支持当前 recognition/screen-reading trace，也支持旧版 overlay trace 和 `vision_layer_trace_v1` 层 trace，按阶段输出 `flow_stages` 并提供每阶段原始 JSON 供 Trace Flow UI 点击查看。



### UTF-8 中文识别规则 (2026-06-13)



所有识别到的中文必须按 UTF-8 端到端保留：OCR 文本、模型 prompt、模型原始输出、解析后的 JSON、trace、测试断言和面板展示都不能写入乱码、问号替换串或替换字符。Windows 下做 smoke 脚本时，不要让中文字面量经过可能使用 ANSI code page 的 shell；需要传中文时使用 UTF-8 文件、`uv run python`、`PYTHONIOENCODING=utf-8` 或 Unicode escape，并用 Python 按 `encoding="utf-8"` / `utf-8-sig` 读取实际文件核对，而不是相信 PowerShell 的乱码显示。



### Model I/O Trace Evidence (2026-06-09)



Vision-model calls now write `model_io_trace_v1` evidence into traces. Each local OpenAI-compatible model attempt records the full text prompt, source/inference image paths, max tokens, raw model text, raw endpoint response, parsed JSON, runtime-normalized JSON, and parse errors when present. Trace Inspector renders this as a `Model IO` stage for easier debugging.



### SEEK candidate profile readiness (2026-06-17)



Before any live SEEK safe-fill smoke, check the real candidate profile independently:



```powershell

uv run python scripts\seek_profile_readiness.py `

  --candidate-profile path\to\candidate_profile.json `

  --out logs\smoke\seek_profile_readiness.json `

  --fail-if-blocked

```



Generate a blank UTF-8 template:



```powershell

uv run python scripts\seek_profile_readiness.py `

  --write-template artifacts\seek\candidate_profile_template.json `

  --out logs\smoke\seek_profile_readiness_template.json

```



The CLI emits `seek_profile_readiness_cli_report_v1` with embedded `candidate_profile_readiness_v1`. Smoke/test/synthetic profiles remain blocked. A real live-smoke-ready profile must include `profile_source: "real_user_candidate_profile_v1"`, matching basics (`skills` or `target_roles`, plus `location_constraints`), `experience_summary`, `work_rights_summary`, and at least one low-risk safe-fill value such as name/email/phone/profile URL. The command-line summary now prints `profile_source`, `real_user_profile_source`, and `pii_redaction_enabled`; the report records safe-fill field names and value lengths only, and does not print full profile values.

### Learning Mode Region Content Boundary (2026-07-07)

Two-stage Learning Mode now treats Stage1 regions as parent containers and Stage2 numbered items / subregion groups as children. Child bboxes are clipped to the parent region bbox before report/overlay output, with `region_content_boundary` and per-child `bbox_boundary_clip` evidence when a model/OCR hint crosses a sibling region boundary. The v54 contract also writes `parent_region_id`, `parent_region_bbox`, and `parent_boundary_relation` on every Stage2 child so the panel/report can distinguish real parent-child overlap from non-parent boundary overlap. This is display/review-only structure evidence; it does not authorize Execute, clicks, fills, submits, or Runtime PathGraph promotion.

The follow-up v55 replay keeps that parent-container contract and repairs a right-sidebar ownership case: when an oversized `boundary_review_region` / `sidebar_review_region` contains a member-list title such as `members` / `群聊成员`, the member-list parent can recover that child as display-only `member_list_header` evidence while the oversized outer container remains review-only and non-executable. QQ and AppleMusic replays both keep `missing_parent_relation=0` and `outside_parent_bbox=0`.

The v58 replay adds a generic bottom composer parent rule for chat/comment-style screens. A bottom tool row plus `Send` / `发送` can synthesize a display-only `input_toolbar_region` that covers the toolbar, composer area, and send button while preserving `execute_binding_enabled=false` and `artifact_is_authorization=false`. AppleMusic remains unchanged at `39` numbered / `55` fused boxes; QQ gains one review-only input toolbar parent and still has `missing_parent=0` / `outside_parent=0`. GPT reviewer accepted only the text/contract checkpoint and explicitly did not give a visual pass because image upload to ChatGPT remains blocked.

The v60/v62 boundary pass defines Stage1 bars/regions as parent containers and Stage2 numbered items / subregion groups as children. `fused_review_boxes` now inherit `parent_region_id` / `parent_region_bbox`, the fusion/overlay layer clips every partially overflowing child box to its parent before display, and fully out-of-parent children are rejected instead of being fabricated as 1px clipped boxes. `fusion.region_content_boundary_summary` reports missing-parent children, fused child clips, and residual outside-parent boxes. Any missing-parent, clipped, or rejected child forces `pathgraph_promotion_allowed=false`; Stage2-skipped runs are marked `not_evaluated_stage2_skipped` instead of a boundary pass. Clipping/rejection is treated as human-review evidence, not recognition success. This is still review-only evidence, not a recognition accuracy claim or execution authorization.

The v61 Stage1 pass fixes a generic false-bottom-bar case found on Python.org: bottom-like content that is narrow, not left-aligned, and continuous with `primary_area` / `main_content` is merged back into the main region instead of being treated as a real `bottom_bar`. The report records this as `stage1_structure.zone_corrections[*].correction=bottom_bar_content_merged_into_primary_region` and `zone_correction_status=passed_with_correction`, so it is not confused with a clean Stage1 pass. Python.org now passes the Stage1 gate and reaches Stage2; AppleMusic and QQ keep their previous region/item counts. This does not claim that Python.org internal numbering is good enough yet; it only proves the Stage1 bar-selection blocker was removed without regressing the protected traces.

The v100 page-detail review-emphasis pass adds a display-only taxonomy for Learning Mode page-detail candidates. Fused review boxes now carry `page_detail_review_category` and `visual_emphasis`, so background/empty review regions, boundary review regions, and partial-visible items render as low-emphasis helper boxes while primary content remains visually distinct. Preview reports now include `primary_region_count`, `review_candidate_region_count`, and `low_emphasis_region_count`. Latest artifacts: Python.org `logs\benchmarks\learn_two_stage_python_v100_page_detail_review_emphasis\learn_page_detail_candidate_preview.png`, AppleMusic `logs\benchmarks\learn_two_stage_applemusic_v100_page_detail_review_emphasis\learn_page_detail_candidate_preview.png`, QQ `logs\benchmarks\learn_two_stage_qq_v100_page_detail_review_emphasis\learn_page_detail_candidate_preview.png`. ChatGPT audit `artifacts\chatgpt_reports\stage2_v100_page_detail_review_emphasis_audit_result.json` gives overall `CONDITIONAL PASS`: AppleMusic `PASS`, Python.org and QQ `CONDITIONAL PASS`. This remains display-only/review-only evidence, not Execute authorization, Runtime PathGraph promotion, recognition accuracy, or E2E success.
