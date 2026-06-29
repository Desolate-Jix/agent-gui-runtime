# agent-gui-runtime

[中文](README.md) | [English](README.en.md)

## Runtime architecture direction (2026-06-29)

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

The local panel has been updated to match this architecture. The shared Navigation Path / PathGraph card now shows the Agentic Loop strip, and each Runtime PathGraph node detail records the execution model, PathGraph role, Gate requirement, and app profile path so learned graphs are displayed as guidance assets rather than hardcoded scripts.

App/software profiles are now runtime resources. Use `GET /runtime/app_profiles` to list profiles and `GET /runtime/app_profiles/{app_id}` to load one profile. The panel's Artifact Replay page reads the SEEK profile through this API and shows the profile policy beside the loaded PathGraph.

Operation skills are runtime resources too. Use `GET /runtime/operation_skills` for the base framework skill catalog or `GET /runtime/operation_skills?app_id=seek` to see how SEEK profile skills map back to generic Operation skills such as `read_full_page`, `scroll_region`, and `open_apply_flow`.

Gate contracts are runtime resources as well. Use `GET /runtime/gate_contracts` for the base Gate catalog or `GET /runtime/gate_contracts?app_id=seek` to see the SEEK profile's safety/dataflow contracts, including bound-window matching, final-submit blocking, profile-mutation blocking, latest-detail snapshot checks, and contextual OCR normalization.

Agent prompts are also runtime resources. Use `GET /runtime/agent_prompts`, `GET /runtime/agent_prompts/{prompt_id}`, `GET /runtime/agent_prompts/{prompt_id}/versions`, `GET /runtime/agent_prompts/{prompt_id}/versions/{version}`, `GET /runtime/agent_prompts/{prompt_id}/diff`, `POST /runtime/agent_prompts/{prompt_id}/versions`, and `POST /runtime/agent_prompts/{prompt_id}/rollback` to list, load, compare, save, and rollback prompt versions. The panel can load, edit, diff, and rollback the full-JD suitability prompt `job_suitability_full_jd_v1`, preserving the rule that complete job text goes to the Agent before Apply Entry.

## Contract-first SEEK policy (2026-06-24)

Recent live SEEK failures are now handled as reusable runtime contracts instead of one-off site patches. Before any full SEEK apply run, keep the common regression set green for latest detail dataflow, candidate freshness, action taxonomy, scoped final-submit detection, scroll-scope validation, contextual OCR normalization, SEEK extraction, SEEK runners, and path-graph execution.

The next live order is intentionally staged: one job read/match/Apply dry-run first, then a 3-5 job no-apply smoke, and only then a station-internal application flow that stops at the final Review boundary. `Apply` / `Quick Apply` is an `open_apply_flow` action, not a final submit; `Submit` / `Send` / `Confirm` / payment remains hard-blocked inside the active form or modal scope.

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

The browser panel now also exposes Learn Mode -> Artifact Replay (`learn_replay`). It loads SEEK, Wikipedia, GitHub Issues, Python Docs Search, Table Directory, or the input-demo runtime graph through the existing read-only `/panel/file` path, shows graph structure/actions/skills/safety, renders the shared PathGraph card, and can seed the Learn Mode safe-validation harness or the Execute Mode task-run harness. The same page now includes a SEEK Application Evidence inspector that loads `seek_application_fill_record_v1`, `seek_application_final_review_audit_v1`, and `seek_application_flow_artifact_v1`, then shows filled fields, screenshot/trace counts, audit decision, and final-submit safety counters. The task-run harness still calls `/execute/available_actions` and `/execute/step` one step at a time; it is a panel/test harness, not a new backend multi-step agent.

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

当前默认分工：整屏理解 `observe` 使用 `Qwen3-VL 4B Q4_K_M`；精准定位/执行 grounding 使用 `VISTA-4B Transformers`。`Qwen3-VL 8B Q4_K_M` 保留为可手动选择的理解基线；`MiniCPM-V-4.6 Transformers` 目前是 benchmark-only profile，当前后端不直接启动它的服务。旧 `Qwen3.6 35B` profile 与本地权重已经移除。

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

耗时的视觉请求在后台运行，调用整屏理解、精准定位或 dry-run 时测试面板仍可继续响应。整屏理解与精准定位分别保存提示词：整屏理解是快速候选发现阶段，只要求简短界面摘要和可操作控件候选框，不让小模型复述 OCR 坐标或生成详细关系证据；整屏理解现在还要求 `state_guess` 输出可直接传给精准定位 `state_hint` 的短区域提示，并在 `POST /vision/observe_screen` 返回 `suggested_state_hint`。测试面板收到成功的整屏理解结果后会自动把该提示填入精准定位的 State hint 输入框；旧的本地面板配置也会在加载时补上这条提示词规则。精准定位阶段只处理 agent 指定的目标，区分纯图标与含文字控件，并要求输出 OCR anchor 关系、四边约束、中心/尺寸/排除约束以及最终框理由。对不含文字的小图标，满足这些证据的大模型框会作为 `located_bbox` / `located_point` 返回供检查，但不会自动改点相邻 OCR 文字，也不会直接成为可执行坐标。

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

- `vision.local_understanding`：小模型，负责快速整屏理解和候选控件索引
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
- 截图预览卡片位于导航路径图下方，右侧响应区保留页面详情和 API/trace 证据；Learn Mode 深度校准返回 `learn_all_targets_ready` 时，状态显示“路径图已校准”。
- `recognition_plan` / `execute_recognition_plan` 现在会接收 `observe_trace_path`。当 trace 与当前截图匹配且含 `screen_map_v1` 时，会先生成 `path_graph_recall_v1`，把与当前 goal 相关的路径候选、状态匹配、local OCR ROI 提示写进响应和 trace；召回候选会并入 `candidate_result`，参与后续局部 OCR grounding 和 `pre_click_decision_v1`；Trace Inspector 显示为 `Path Recall` 阶段。若 `local_grounding.output_contract=vista_point_v1`，PathGraph 主路径会直接裁候选 ROI 给 VISTA：top1 分数明显领先时只裁 top1，否则合并 top3，默认 padding 48px、最小 ROI 256px、最长边 640。模型输入、ROI crop bounds、候选 bbox 的 ROI 坐标 prompt、原始输出、解析 JSON 和换算后的原图点会写入 `model_io` 与 `parse_result.vista_point_grounding`，Gate 仍只验证原图坐标。
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

`POST /state/capture_window` uses screen-coordinate capture, so it lightly restores the bound window, brings it to the foreground, and waits briefly for the window to settle before grabbing pixels.

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
- Execute recognition plan 会先尝试 `visual_asset_recall_v1`，把当前截图里的已学固定按钮匹配成 fresh `seeded_candidate_v1`；低风险按钮可跳过慢模型，高危提交类按钮仍只作为证据并强制过 Gate。匹配 trace 会记录当前 ROI、当前匹配 crop、灰度/边缘匹配方法、top candidates、score gap 和耗时
- Learn Replay 面板可以加载并编辑 `learned_interface_map_v1`，按区域展示固定视觉按钮、动态 ROI 区和危险区。`merge_visual_asset_match_evidence()` 会把当前截图匹配证据回填到固定按钮资产；点击 Inspect 可查看 source crop、current ROI、current match、bbox/click point、scope、match policy、semantic action、danger level、fast-lane eligibility 和 raw JSON，并通过 `/panel/save_interface_map` 保存编辑后的学习产物和 `learned_interface_map_edit_trace_v1`。本地 no-mouse smoke 同时覆盖低风险 `Quick apply` 和高风险 `Submit application`：前者可成为 fast-lane 候选，后者即使命中也保持 `final_submit_fast_lane_count=0` / `final_submissions=0`
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

- `Qwen3-VL 4B Q4_K_M`：llama.cpp CUDA，2 个截图理解 case 全部成功，JSON 输出稳定，平均单 case约 `3.09s`，平均召回 `0.7`。在当前 smoke 中与 8B 召回持平但更快，已切为默认整屏理解模型。
- `Qwen3-VL 8B Q4_K_M`：llama.cpp CUDA，2/2 成功，平均单 case约 `4.59s`，平均召回 `0.7`，保留为可选理解基线。
- `MiniCPM-V-4.6 Transformers`：Transformers direct，2/2 成功，平均单 case约 `9.07s`，平均召回 `0.8`。当前 llama.cpp 后端无法加载其 `minicpmv4_6` projector，因此保留为 benchmark-only profile，不在面板里直接启动。
- 报告：`artifacts/accuracy-checks/understanding_model_benchmark_20260616.json`
- 结论：35B 不再作为本地基线；默认快速理解切到 Qwen3-VL 4B，精准点定位继续走 VISTA。

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
- `PROJECT_SUMMARY.md`：项目摘要
- `CURRENT_STATE.md`：当前状态
- `NEXT_STEPS.md`：下一步计划
- `LEARNING_MODE_PLAN.zh-CN.md`：学习模式设计，区分自我探索和点击后路径记录
- `ACCURACY_EVALUATION_STANDARD.md`：准确率评估标准
- `RUNTIME_STATE_GRAPH.md` / `RUNTIME_STATE_GRAPH.zh-CN.md`：状态图设计

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
