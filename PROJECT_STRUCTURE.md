# PROJECT_STRUCTURE

## Purpose

This file is the concrete repository map for day-to-day development.

Use it when you need to answer:

- where a feature lives
- where a config file is loaded
- where runtime artifacts are written
- which entrypoint to call for a given capability

`README.md` should stay concise. This file can be more explicit.

## Learn / Execute Mode Structure

中文版本在本节后半部分。This section is the repository map for the current two-mode runtime architecture.

### Current Progress

Learn Mode is the map-building side. Execute Mode is the command-running side.

- `Learn Fast` is implemented as the Observe-stage quick map draft path. The panel's Observe button is "Fast Map Build"; it sends `agent_mode=learn, learn_depth=fast`, runs through `POST /vision/observe_screen`, produces `screen_map_v1`, and renders the result in Trace Inspector as `Path Map`.
- `Learn Deep` is implemented as the Learn-mode Locate-stage path calibration path. The panel's Locate button becomes "Deep Path Calibration" in Learn Mode; it sends `agent_mode=learn, learn_depth=deep` plus `metadata.learn_all_targets=true`, reuses the latest Observe trace, and returns `learn_all_targets` / `path_map_review_v1` for all child PathGraph controls. The older observe-stage deep semantic review hook remains available as a model-backed review capability.
- `Execute Mode` has a closed MVP. It reads a matching Observe trace through `observe_trace_path`, builds `path_graph_recall_v1`, merges safe recalled PathGraph candidates into `candidate_result`, verifies them through local OCR grounding and `pre_click_decision_v1`, executes only through `POST /action/execute_recognition_plan`, verifies after click, then writes `execute_transition_memory_v1` or returns `execute_fallback_plan_v1`. When the visible screenshot may be incomplete, the fallback plan can ask the upper agent to call `POST /action/scroll` and then rerun the same gated Execute goal.
- `screen_inventory_v1` is the fast Execute inventory layer. It is derived from `screen_reading_v1` plus compact Windows UIA controls and splits structured evidence into `available_actions`, `page_elements`, and `cards`, so the upper agent can inspect what can be operated without asking the whole-screen VLM again. Trace Inspector exposes it as an `Inventory` stage with action/text/card counts and coordinate coverage.
- SEEK automation now has a dedicated MVP plan in `SEEK_MVP_PLAN.md`. The current implemented slices are container-aware scroll, visible job extraction, bounded detail-scroll stop conditions, candidate matching/saved-job records, no-apply traversal, guarded Apply Entry state detection, state-layer final-submit visible blocking, draft-only cover-letter artifacts, read-only answer planning, and an opt-in safe form-fill primitive for the real SEEK search/detail layout: `scroll_containers_v1` exposes `seek:page`, `seek:results_list`, and `seek:job_detail`; `/action/scroll` accepts those containers and returns `scroll_action_v2` with `scroll_precondition_decision_v1` and `scroll_effect_validation_v1`; `app/seek/extraction.py` emits `seek_job_cards_v1` / `seek_job_card_v1` and `seek_job_detail_v1` from `screen_inventory_v1` evidence, including an expanded right-detail header read area; `app/seek/traversal.py` merges detail slices, emits `seek_job_detail_completeness_v1`, and builds the no-final-submit `seek_mvp_run_report_v1` shell; `app/seek/matching.py` loads `candidate_profile_v1`, emits `seek_job_match_decision_v1`, and writes `saved_seek_job_record_v1`; `app/seek/application.py` classifies the page reached after Apply / Quick Apply into `seek_application_flow_state_v1`, `application_form_inventory_v1`, and `final_submit_visible_blocker_v1`, filtering negative safety text such as `Do not click Submit`; `app/seek/cover_letter.py` emits `cover_letter_draft_v1` without UI paste; `app/seek/answer_plan.py` emits `application_answer_plan_v1`; `scripts/seek_mvp_traversal_runner.py` records detail/results scroll `target_container_id` in the run report and can emit `safe_form_fill_attempt_v1` behind `--fill-safe-fields`, using gated focus before schema-clean `type_text`; `/action/execute_recognition_plan` emits `final_submit_guard_v1` for Apply Entry and blocks final-submit candidates before click dispatch; the runner wires these pieces through existing runtime APIs and has live no-apply evidence for 5 opened/read SEEK jobs plus one guarded Apply Entry smoke with `final_submissions=0`.
- The SEEK runner also writes an independent `seek_mvp_traversal_trace_v1` and stores its path in `seek_mvp_run_report_v1.traversal_trace_path` for reviewing card clicks, nested scrolls, detail reads, match decisions, Apply Entry stops, answer-plan previews, safe-fill attempts, and safety counters.
- SEEK high precision workflow instructions live in `skills/seek-high-precision/SKILL.md`. Reusable audit helpers now live in `app/core/audit.py`, while generic CV text extraction and candidate-profile draft generation live in `app/profile/cv.py` and `scripts/candidate_profile_from_cv.py`.
- The first generic path-graph-mode export now converts the stable SEEK manual-learning sample into `runtime_path_graph_v1`, `learned_skill_v1`, and `visual_asset_v1`. These live under `artifacts/seek/runtime_path_graph_seek_mvp_20260617.json`, `artifacts/seek/learned_skills_seek_mvp_20260617.json`, and `artifacts/seek/visual_assets_seek_mvp_20260617.json`. They are guidance only; Execute still needs fresh observation, VISTA or equivalent validation, `pre_click_decision_v1`, and post-action verification.
- The panel no longer uses a separate replay rail. Learn Mode contains Artifact Replay (`learn_replay`) and PathGraph Safe Validation (`learn_validation`); Execute Mode contains PathGraph Task Run (`execute_task_run`). Switching workspaces hides the other workspace's functional pages while Session/System tools remain visible. These views turn learned artifacts into inspectable operator workflows without adding backend multi-step orchestration: each task-run button press still results in one `/execute/available_actions` call and at most one `/execute/step` call.
- `docs/PANEL_LEARN_EXECUTE_WORKFLOW.zh-CN.md` is the button-level operator manual for the current panel. It documents the shared session/system tools, Learn Fast, Learn Deep, Artifact Replay, Safe Validation, Execute available-actions refresh, Task Run, Locate/Gate, Input, expected API responses, and the recommended end-to-end smoke order.
- The panel's shared Navigation Path / PathGraph card is used by Learn, Execute, and Replay/Test. When a `runtime_path_graph_v1` is loaded, the card renders states and transitions as a large non-child-subpath graph; `/execute/step` responses update `path_graph_runtime_state_v1` so the same card highlights current state, current action edge, completed transitions, failed transitions, and forbidden/write-guarded actions.
- The SEEK artifact-assisted runner now resets `seek:job_detail` upward before opening the next card after a prior detail read. This keeps the next post-click title verification anchored on the detail header instead of a scrolled body fragment. `seek_mvp_accuracy_summary_v1` now reports `pre_click_detail_reset_count`, `pre_click_detail_reset_wrong_scope_count`, and `title_extraction_from_body_count`. Latest external Edge evidence: `logs\smoke\seek_artifact_replay_readonly_3job_20260619_after_reset.json` reached `jobs_opened=3`, `jobs_fully_read=3`, `post_click_layout_drift_count=0`, `wrong_scope_scroll_count=0`, and `final_submissions=0`.
- GitHub Issues is the third read-only website family. `artifacts/github/runtime_path_graph_github_issues_v1.json` models `list -> detail page navigation` with `open_issue_from_list`, `read_issue_detail`, and `load_more_issues`. It treats `github:page` as the default page scroll target and keeps `issues_list` as a region, not an internal scroll container, unless future current-state evidence proves otherwise. Latest external Edge smoke: `logs\smoke\github_issues_artifact_replay_readonly_20260619.json` opened one public issue row after a dry-run/overlay review, scrolled the issue detail page with `wrong_scope_detected=false`, and recorded zero write/final-submit actions.
- `scripts/artifact_replay_regression_report.py` is the unified regression gate for learned artifact replay. It reads the SEEK, Wikipedia, GitHub Issues, and Python Docs Search runtime graphs plus their latest smoke reports and emits `artifact_replay_regression_report_v1`; the latest output `logs\smoke\artifact_replay_regression_20260619.json` passed all four baselines.
- `scripts/learn_execute_checkpoint_report.py` is the Learn/Execute MVP checkpoint builder. It emits SEEK safe-validation and task-run replay reports, builds `artifacts\skills\learned_skill_matrix_v1.json`, and writes `learn_execute_mvp_checkpoint_report_v1` so the panel/test harness can prove Execute Mode covers click, scroll, input, read, and guarded-action skills before learning a new site.
- `scripts/learn_sample_readiness_gate.py` combines the Learn/Execute checkpoint and unified artifact replay regression into `learn_sample_readiness_gate_v1`. This is the hard gate before starting a new Learn Mode sample: five learned baselines must pass, common Execute skills must be covered, no write/final-submit counters may fire, and `artifacts\templates\learn_sample_template_v1.json` must exist.
- Python Docs Search is the fourth learned website family. `artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json` models public documentation search input, seeded search-button click, seeded search-result opening, and article page scroll. `type_public_search_query` requires explicit live smoke permission and `public_search_query` category; `trigger_search` and `open_search_result` carry `seeded_candidate_v1` bbox/click-point evidence. `logs\smoke\python_docs_search_artifact_replay_public_input_20260619.json` verified the real sequence `type_public_search_query -> trigger_search -> open_search_result -> read_article`, ending on the Glossary article page with zero private input, write actions, final submissions, high-risk actions, or wrong-scope scrolls. When VISTA ROI grounding disagrees with a learned seed, the trace records `coordinate_source=seeded_candidate_v1_model_disagreed` and `vista_point_disagrees_with_seed_bbox`; the learned seed remains the primary execution coordinate.
- Table Directory is the fifth UI-family sample. `artifacts/table_directory/runtime_path_graph_table_directory_v1.json` models `table/filter/sort -> row detail` with filter/tab switching, sort controls, table-row opening, detail reading, list return, list scrolling, and blocked write actions. `logs\smoke\table_directory_datatables_real_1record_20260619.json` is a real public DataTables smoke: the first dry-run exposed that row-detail tables may require clicking the row expander instead of row text, the graph was corrected, then a live approved-plan click opened the row detail and a second step scrolled to read the detail content.
- `screen_map_v1` candidate rules now distinguish page areas before aggregation: `main_content` produces `news_card`, `right_sidebar` produces `recommendation_item`, and More-style text such as `More`, `See more`, `View more`, `Read more`, or Chinese `查看更多` is treated as a `button` before card grouping. Source/time metadata is kept as child evidence and filtered out as a card seed.

### Mode Flows

```text
Learn Fast:
  screenshot
  -> broad observe / screen reading
  -> OCR-backed section and candidate rules
  -> screen_map_v1
  -> Path Map trace

Learn Deep:
  screen_map_v1 draft
  -> locate_target in Learn Mode
  -> learn_all_targets from screen_map candidates
  -> path_map_review_v1 additions
  -> PathGraph child-control coordinate writeback
  -> locate trace

Execute:
  user goal + current screenshot
  -> screen_inventory_v1 from latest screen_reading / observe trace
  -> observe_trace_path state/OCR reuse
  -> path_graph_recall_v1 top-k recall
  -> local OCR grounding on candidates
  -> pre_click_decision_v1
  -> gated click
  -> post-click verification
  -> execute_transition_memory_v1 or execute_fallback_plan_v1
  -> optional POST /action/scroll requested by fallback_plan
  -> rerun the same Execute goal after scroll evidence
```

### Main Fields And Contracts

Common request fields:

- `agent_mode`: `learn` or `execute`
- `learn_depth`: `fast`, `deep`, or `null` for Execute
- `write_policy.path_graph`: whether the response may update the structural PathGraph
- `write_policy.element_memory`: whether verified execution experience may write ElementMemory / transition memory
- `write_policy.trace`: whether Observe, Locate, RecognitionPlan, and ExecuteRecognitionPlan write main trace files
- `observe_trace_path`: latest matching Observe trace for OCR anchor reuse and PathGraph recall
- `model_io_trace_v1`: per-model-call trace payload that records provider, model name, attempt count, full text prompt, image path, raw model text, raw endpoint response, parsed JSON, runtime-normalized JSON, and parse errors when present

Learn outputs:

- `screen_map_v1`: state id, state hint, page sections, candidate actions, risk class, expected effect, bbox and point hints
- `learn_all_targets`: Learn Locate all-control coordinate review generated from the latest Observe `screen_map_v1`
- `path_graph_deep_review_v1`: deep-review decision list and summary
- `learn_deep_model_review_v1`: optional model semantic review embedded under `path_graph_deep_review.model_review`
- `path_graph_delta_v1`: additions, removals, and updates proposed against the draft map
- `element_memory_init_plan_v1`: planned memory entries, not verified execution experience

Execute outputs:

- `screen_inventory_v1`: fast inventory for agent planning, with `available_actions`, `page_elements`, `cards`, duplicate rate, coordinate coverage, and source counts
- `seek_job_cards_v1` / `seek_job_card_v1`: visible SEEK job-card extraction from inventory cards and child evidence
- `seek_job_detail_v1`: visible SEEK right-pane detail extraction from the current `seek:job_detail` container
- `seek_job_detail_completeness_v1`: bounded decision for whether the right detail pane should be scrolled again
- `candidate_profile_v1`: optional local candidate profile for SEEK matching
- `seek_job_match_decision_v1`: strong/maybe/skip/review scoring evidence for opened SEEK jobs
- `saved_seek_job_record_v1`: persisted local record for strong/maybe SEEK matches
- `seek_mvp_run_report_v1`: no-final-submit report shell for traversal/scoring/application-prep runs
- `seek_mvp_traversal_trace_v1`: independent SEEK traversal audit trace referenced by `seek_mvp_run_report_v1.traversal_trace_path`
- `seek_mvp_run_audit_v1`: read-only audit of a SEEK run report plus traversal trace before riskier steps
- `learned_app_profile_v1`: Learn Mode artifact exported from stable SEEK run evidence; records page type, scroll containers, entity patterns, action templates, verification rules, and safety policy
- `path_graph_seed_v1`: structural seed exported with the learned profile; represents SEEK as `top_search_area`, `results_list`, `job_detail`, `job_card`, `detail_header`, and `detail_body`
- `runtime_path_graph_v1`: generic path-graph-mode artifact converted from the SEEK manual-learning sample; records states, regions, scroll containers, entities, dynamic collections, transitions, action templates, coordinate policy, visual asset refs, learned skill refs, metrics, and safety policy
- `learned_skill_v1`: reusable skill set extracted from the SEEK sample, including list-card opening, scoped scrolling, detail-pane reading, seeded click validation, and final-submit blocking
- `visual_asset_v1`: reusable visual evidence slots extracted from the SEEK sample, including Apply / Quick Apply / Save, job-card shape, selected-card highlight, and results/detail scrollbars
- `visual_asset_crop_export_v1`: optional screenshot-derived crop/hash export for representative visual assets; it is evidence only and cannot authorize clicks
- `available_actions_v1`: Execute-facing action menu generated from a `runtime_path_graph_v1`; guarded Apply is hidden by default and artifact guidance never authorizes clicks
- `learned_skill_matrix_v1`: cross-artifact summary of reusable Execute skills and their safety scopes; current checkpoint requires click, scroll, input, read, and guarded-action coverage
- `table_directory_artifact_replay_report_v1`: report for the fifth UI family; current real DataTables smoke proves row-expander opening and detail reading while keeping write/input/submit counters at zero
- `learn_execute_mvp_checkpoint_report_v1`: compact checkpoint report proving SEEK safe validation, SEEK 3-job replay invariants, skill matrix coverage, and coordinate policy audit before moving to a new website family
- `regression_gate`: field inside `artifact_replay_regression_report_v1` that says whether all learned baselines passed and whether it is safe to continue to a new website family
- `learn_sample_template_v1`: fixed starting schema for the next manual/agent learning sample, including target-window policy, safety mode, expected artifacts, required dry-run/live sequence, and smoke acceptance counters
- `learn_sample_readiness_gate_v1`: combined gate report that exposes `ready_for_new_learn_sample` for the panel and CLI
- `docs_search_smoke_report_v1`: Python Docs Search live public-input smoke report; records explicit public query input/submit, result opening, article scroll, and zero private/write/final-submit/high-risk/wrong-scope counters
- `artifact_replay_board`: panel harness state for loading a learned runtime graph, inspecting graph/actions/skills/safety, and replaying safe validation or task-run steps through existing single-step Execute APIs
- `github_issues_runtime_path_graph_v1`: third-family read-only path graph sample for public GitHub issue lists and issue detail pages; validates list-row opening, detail-title navigation, page scroll, issue metadata/sidebar regions, and write-action blocking
- `seek_application_flow_state_v1`: Apply / Quick Apply entry state classification that always stops before form fill or final submission
- `path_graph_recall_v1`: state match, recalled map candidates, scores, and local OCR ROI hints
- `candidate_result`: merged visual, page-structure, and safe recalled candidates
- `pre_click_decision_v1`: the mandatory click gate
- `execute_transition_memory_v1`: verified real-click writeback result
- `execute_fallback_plan_v1`: safe next-step plan for failed execution, including optional scroll-to-reveal, never permission to auto-click
- `scroll_action_v1`: dry-run or real up/down mouse-wheel scroll evidence for the currently bound window

### File Ownership

- `app/models/request.py`: mode fields and write-policy request contracts
- `app/api/vision.py`: Learn Fast, Learn Deep, OCR anchor reuse, PathGraph recall, and recognition-plan candidate fusion
- `app/api/vision.py`: Screen Map candidate rules for sections, controls, OCR text actions, OCR card aggregation, and noise filtering
- `app/screen_inventory/`: builds `screen_inventory_v1` from `screen_reading_v1`, compact UIA controls, OCR text, and UI elements
- `scripts/benchmark_screen_inventory.py`: measures typed-ground-truth inventory recall for actions, page elements, metadata, and cards, plus action precision, clickable false-positive rate, duplicate rate, coordinate coverage, candidate count, and build latency
- `app/vision/local_provider.py`: OpenAI-compatible local model calls and `model_io_trace_v1` / `model_io_attempt_v1` recording for every successful or failed attempt
- `app/api/action.py`: Execute Mode gated click, bound-window scroll actions, post-click verification, transition memory writeback, and fallback planning
- `app/core/input_controller.py`: low-level SendInput click, text helper support, and mouse-wheel dispatch
- `app/seek/scroll_containers.py`: SEEK-specific three-container scroll discovery for `seek:page`, `seek:results_list`, and `seek:job_detail`
- `app/seek/extraction.py`: SEEK-specific extraction for `seek_job_card_v1`, `seek_job_cards_v1`, and visible `seek_job_detail_v1`
- `app/seek/traversal.py`: SEEK-specific detail-slice merge, completeness/scroll-stop decision, and no-final-submit report shell
- `app/seek/matching.py`: SEEK-specific candidate profile loading, job scoring, and saved suitable-job records
- `app/seek/application.py`: SEEK-specific application-flow state detection after Apply / Quick Apply
- `app/seek/cover_letter.py`: SEEK-specific draft-only cover-letter artifact generation with truthfulness checks
- `app/seek/answer_plan.py`: SEEK-specific read-only application answer planning and risk classification
- `app/seek/profile.py`: candidate profile readiness checks for real cover-letter generation and single-field safe-fill
- `app/core/audit.py`: reusable audit helper functions shared by domain auditors
- `app/profile/cv.py`: generic local CV text extraction and `candidate_profile_v1` draft generation
- `scripts/candidate_profile_from_cv.py`: CLI for generating a reviewed local candidate-profile draft from a CV without printing raw contact values
- `app/seek/learn_artifacts.py`: exports stable SEEK traversal experience into `learned_app_profile_v1` and `path_graph_seed_v1`, plus helper functions for artifact-assisted execution
- `app/learn/path_graph_artifacts.py`: converts the SEEK manual-learning export into generic `runtime_path_graph_v1`, `learned_skill_v1`, and `visual_asset_v1` artifacts
- `app/learn/skill_matrix.py`: builds `learned_skill_matrix_v1` from existing runtime path graphs so Execute Mode can prove reusable click, scroll, input, read, and guard coverage
- `app/execute/available_actions.py`: builds `available_actions_v1` from a runtime path graph so an upper agent can choose among safe graph-assisted actions before normal gated execution
- `app/execute/path_graph_step.py`: converts one selected `available_actions_v1` item into a single-step Execute plan with `path_graph_action_context_v1` and a low-level click, scroll, or input request payload
- `app/learn/path_graph_resolver.py`: emits `path_graph_resolution_v1` by matching a runtime graph against provided inventory/scroll-container evidence and safety constraints
- `app/api/execute.py`: exposes `POST /execute/available_actions` and `POST /execute/step` for path-graph-assisted single-step Execute planning and optional one-step dispatch through existing gated `/action/*` routes
- `app/learn/visual_asset_crops.py`: optional crop/hash builder for representative visual asset evidence from a current screenshot
- `scripts/seek_export_learn_artifacts.py`: CLI for exporting Learn Mode artifacts from `seek_mvp_run_report_v1` and optional `seek_mvp_traversal_trace_v1`; it can also split out the generic runtime graph, learned skills, visual assets, and screenshot-derived visual crop export
- `scripts/learn_execute_checkpoint_report.py`: CLI for writing `seek_learn_safe_validation_report_v1`, `seek_learn_task_run_report_v1`, `learned_skill_matrix_v1`, and `learn_execute_mvp_checkpoint_report_v1`
- `scripts/learn_sample_readiness_gate.py`: CLI for writing `learn_sample_readiness_gate_v1` from the checkpoint and regression reports
- `app/api/panel.py`: Trace Inspector stages for `Model IO`, `Inventory`, `Path Map`, `Path Deep`, `Path Recall`, `Memory`, and `Fallback`
- `app/web_panel/`: Learn/Execute mode controls, workspace-scoped replay/validation/task-run harnesses, shared PathGraph card rendering/highlighting, and panel request wiring
- `app/core/transition_memory.py`: writes verified execution transition records under `logs/app-transitions/`
- `logs/traces/vision/`: Observe, Locate, and RecognitionPlan traces
- `logs/traces/actions/`: ExecuteRecognitionPlan traces
- `logs/app-transitions/`: `execute_transition_memory_v1` transition records

### 中文：当前两种模式结构

Learn Mode 负责“把界面变成地图”。Execute Mode 负责“从地图里找路并执行当前命令”。

- `Learn Fast` 已实现为整屏理解阶段的快速建图路径：面板整屏理解按钮显示“快速建图”，发送 `agent_mode=learn, learn_depth=fast`，调用 `POST /vision/observe_screen`，产出 `screen_map_v1`，Trace Inspector 显示为 `Path Map`。
- `Learn Deep` 已实现为 Learn Mode 下精准定位阶段的深度校准路径：面板精准定位按钮显示“深度校准路径图”，发送 `agent_mode=learn, learn_depth=deep` 和 `metadata.learn_all_targets=true`，复用最新 Observe trace，返回所有子路径控件的 `learn_all_targets` / `path_map_review_v1`。旧的 observe-stage deep 语义审查钩子仍作为模型审查能力保留。
- `Execute Mode` 已有闭环 MVP：通过 `observe_trace_path` 读取匹配的 Observe trace，生成 `path_graph_recall_v1`，把安全的 PathGraph 召回候选合并到 `candidate_result`，再经过局部 OCR grounding 和 `pre_click_decision_v1`，只通过 `POST /action/execute_recognition_plan` 真实点击，点击后验证，最后写入 `execute_transition_memory_v1` 或返回 `execute_fallback_plan_v1`。当当前截图信息不完整时，fallback plan 可以要求上层 agent 先调用 `POST /action/scroll`，再用同一个目标重新进入 gated Execute。
- `screen_inventory_v1` 是 Execute Mode 的快速可操作清单层：从 `screen_reading_v1` 和 compact Windows UIA 控件生成，拆成 `available_actions`、`page_elements`、`cards`，让上层 agent 不需要再次调用全屏 VLM 就能知道当前页面有哪些可操作入口和可见元数据。Trace Inspector 会把它显示成独立 `Inventory` 阶段，并展示 action/text/card 数量和坐标覆盖率。
- SEEK 自动求职现在有独立 MVP 计划 `SEEK_MVP_PLAN.md`。当前已实现的切片是真实 SEEK 搜索/详情布局的 container-aware scroll、可见岗位抽取、详情滚动停止条件、候选人匹配、适合岗位保存记录、guarded Apply Entry 状态检测、状态层最终提交可见拦截、draft-only 求职信 artifact、只读答题计划和 opt-in safe form-fill primitive：`scroll_containers_v1` 暴露 `seek:page`、`seek:results_list`、`seek:job_detail`，`/action/scroll` 可引用这些容器并返回 `scroll_action_v2`、`scroll_precondition_decision_v1` 和 `scroll_effect_validation_v1`；`app/seek/extraction.py` 会从 `screen_inventory_v1` 证据抽取 `seek_job_cards_v1` / `seek_job_card_v1` 和 `seek_job_detail_v1`，并向上扩展右侧详情读取范围以包含标题/公司/Quick apply 区域；`app/seek/traversal.py` 会合并详情片段、判断是否继续滚右侧详情，并生成 no-final-submit 的 `seek_mvp_run_report_v1` shell；`app/seek/matching.py` 会读取 `candidate_profile_v1`、输出 `seek_job_match_decision_v1`，并为 strong/maybe 岗位写 `saved_seek_job_record_v1`；`app/seek/application.py` 会在 Apply / Quick Apply 后输出 `seek_application_flow_state_v1`、`application_form_inventory_v1` 和 `final_submit_visible_blocker_v1` 并停止，且不会把 `Do not click Submit` 这类负约束说明误判为真实提交按钮；`app/seek/cover_letter.py` 会输出不粘贴 UI 的 `cover_letter_draft_v1`；`app/seek/answer_plan.py` 会输出 `application_answer_plan_v1`；`scripts/seek_mvp_traversal_runner.py` 会在报告中记录左右 pane 滚动的 `target_container_id`，可在 `--fill-safe-fields` 下输出 `safe_form_fill_attempt_v1`，并先 gated focus 再 schema-clean `type_text`。当前已有真实 SEEK no-apply 5 岗打开/读取 smoke 证据和一次 guarded Apply Entry live smoke，`final_submissions=0`。
- SEEK runner 还会额外写入独立 `seek_mvp_traversal_trace_v1`，并在 `seek_mvp_run_report_v1.traversal_trace_path` 中回填路径，用于审计卡片点击、嵌套滚动、详情读取、匹配判断、Apply Entry 停止点、答题计划预览、safe-fill 尝试和安全计数。
- `screen_map_v1` 候选规则会先区分页面区域再聚合：`main_content` 生成 `news_card`，`right_sidebar` 生成 `recommendation_item`；`More` / `See more` / `View more` / `Read more` / `查看更多` 这类入口在卡片聚合前优先标成 `button`；来源和时间文本保留为子证据，但不会作为卡片种子。
- 当前第一份通用路径图样本已经从 SEEK 人工学习样本导出：`runtime_path_graph_v1` 记录状态、区域、滚动容器、实体、动态集合、动作边、坐标策略、视觉资产引用、通用 skill 引用和安全策略；`learned_skill_v1` 抽出列表卡片打开、指定容器滚动、详情 pane 读取、seeded 点击校验和最终提交阻断；`visual_asset_v1` 记录 Apply、Quick Apply、Save、职位卡片形状、选中高亮和左右滚动条等视觉证据槽。这些 artifact 只能作为 guidance，不能绕过当前截图验证、VISTA 校验、`pre_click_decision_v1` 和点击后验证。
- 面板不再使用独立的测试/回放分组。Learn Mode 内显示 Artifact Replay（`learn_replay`）和 PathGraph Safe Validation（`learn_validation`）；Execute Mode 内显示 PathGraph Task Run（`execute_task_run`）。切换工作区时会隐藏另一个工作区的功能页，但 Session/System 工具保持可见。这些页面把学习产物变成可检查的操作员 workflow，但不新增后端多步编排：每次任务运行按钮仍然只调用一次 `/execute/available_actions`，最多派发一次 `/execute/step`。
- `docs/PANEL_LEARN_EXECUTE_WORKFLOW.zh-CN.md` 是当前测试面板的按钮级操作手册，记录全局会话/系统工具、Learn Fast、Learn Deep、学习产物回放、安全验证、Execute 可用动作刷新、任务运行、精准定位/Gate、输入、预期 API 响应和推荐端到端 smoke 顺序。
- `learn_sample_readiness_gate_v1` 现在是进入下一个 Learn Mode 样本前的硬门禁。它由 `scripts/learn_sample_readiness_gate.py` 合成 checkpoint 和统一回归结果，要求五个 baseline 全通过、点击/滚动/输入/读取/guard skill 覆盖完整、写操作和最终提交计数为 0，并要求 `artifacts\templates\learn_sample_template_v1.json` 存在。面板的 Learn Mode / Artifact Replay 会直接显示 `ready_for_new_learn_sample`。
- 面板的共享 Navigation Path / PathGraph 卡片现在同时服务 Learn、Execute 和 Replay/Test。加载 `runtime_path_graph_v1` 时，它把 states/transitions 渲染成大尺寸、无子路径展开的图；`/execute/step` 返回的 `path_graph_runtime_state_v1` 会驱动同一张图高亮当前状态、当前动作边、已完成 transition、失败 transition 和被禁止/写入保护的动作。
- SEEK artifact-assisted runner 已修复连续调用里的右侧详情滚动状态污染：读完上一个岗位详情后，下一次打开卡片前会先把 `seek:job_detail` 向上复位，避免 post-click 标题验证从正文片段抽取 title。`seek_mvp_accuracy_summary_v1` 新增 `pre_click_detail_reset_count`、`pre_click_detail_reset_wrong_scope_count` 和 `title_extraction_from_body_count`。最新外部 Edge 证据 `logs\smoke\seek_artifact_replay_readonly_3job_20260619_after_reset.json` 达到 `jobs_opened=3`、`jobs_fully_read=3`、`post_click_layout_drift_count=0`、`wrong_scope_scroll_count=0`、`final_submissions=0`。
- GitHub Issues 是第三个只读网站 family。`artifacts/github/runtime_path_graph_github_issues_v1.json` 表示 `list -> detail page navigation`，包含 `open_issue_from_list`、`read_issue_detail` 和 `load_more_issues`。它默认把 `github:page` 作为 page scroll 目标，把 `issues_list` 当成区域而不是内部滚动容器；除非后续当前证据明确发现独立 overflow 容器，否则不使用 `github:issues_list`。最新外部 Edge smoke `logs\smoke\github_issues_artifact_replay_readonly_20260619.json` 在 dry-run/overlay 复核后真实打开一个公开 issue row，再以 page scroll 阅读详情，`wrong_scope_detected=false`，写入/最终提交动作均为 0。
- `scripts/artifact_replay_regression_report.py` 是学习产物回放的统一回归门禁。它读取 SEEK、Wikipedia、GitHub Issues、Python Docs Search 的 runtime graph 和最新 smoke report，输出 `artifact_replay_regression_report_v1`；最新 `logs\smoke\artifact_replay_regression_20260619.json` 已通过四个基线。
- Python Docs Search 是第四个已验证的网站 family。`artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json` 表示公开文档搜索输入、seeded 搜索按钮点击、seeded 结果打开和文章页滚动。`type_public_search_query` 需要显式 live smoke 权限和 `public_search_query` 分类；`trigger_search` / `open_search_result` 带 `seeded_candidate_v1` bbox/click point 证据。`logs\smoke\python_docs_search_artifact_replay_public_input_20260619.json` 已验证真实连续流程 `type_public_search_query -> trigger_search -> open_search_result -> read_article`，最终落在 Glossary 文章页，且 private input、write action、final submission、高风险动作和 wrong-scope scroll 都为 0。当 VISTA ROI 点与 learned seed 不一致时，trace 记录 `coordinate_source=seeded_candidate_v1_model_disagreed` 和 `vista_point_disagrees_with_seed_bbox`；执行坐标仍以学习产物 seed 为主。

流程：

```text
Learn Fast:
  截图
  -> 整屏观察 / screen reading
  -> OCR 规则补充分区和候选
  -> screen_map_v1
  -> Path Map trace

Learn Deep:
  screen_map_v1 草图
  -> Learn Mode 下调用 locate_target
  -> 从 screen_map candidates 生成 learn_all_targets
  -> path_map_review_v1 additions
  -> 写回 PathGraph 子控件坐标
  -> locate trace

Execute:
  用户目标 + 当前截图
  -> 从最新 screen_reading / observe trace 生成 screen_inventory_v1
  -> observe_trace_path 状态/OCR 复用
  -> path_graph_recall_v1 top-k 召回
  -> 候选局部 OCR grounding
  -> 选择一个低层动作：click / scroll / input
  -> click 进入 pre_click_decision_v1 和 gated click
  -> scroll 进入 scoped/page scroll 证据链
  -> input 进入 type_text 计划；真实输入必须由安全策略显式允许
  -> 动作后验证
  -> execute_transition_memory_v1 或 execute_fallback_plan_v1
```

主要字段：

- `agent_mode`：`learn` 或 `execute`
- `learn_depth`：`fast`、`deep`，Execute 时为 `null`
- `write_policy.path_graph`：是否允许更新结构性 PathGraph
- `write_policy.element_memory`：是否允许把验证成功的执行经验写入 ElementMemory / transition memory
- `write_policy.trace`：是否写 Observe、Locate、RecognitionPlan、ExecuteRecognitionPlan 主 trace
- `observe_trace_path`：最新匹配的 Observe trace，用于 OCR anchor 复用和 PathGraph recall
- `model_io_trace_v1`：每次模型调用的 trace 证据，记录 provider、模型名、attempt 数、完整文本 prompt、图片路径、模型原始文本、endpoint 原始响应、解析后的 JSON、运行时归一化 JSON，以及解析失败原因
- `screen_map_v1`：状态、页面分区、候选动作、风险、预期效果、bbox/point 观察证据
- `screen_inventory_v1`：执行模式快速清单，包含可操作控件、页面文本/元数据、卡片分组、重复率、坐标覆盖和来源统计
- `seek_job_cards_v1` / `seek_job_card_v1`：从左侧职位卡片和子证据抽取可见岗位摘要
- `seek_job_detail_v1`：从右侧 `seek:job_detail` 容器抽取当前可见岗位详情骨架
- `seek_job_detail_completeness_v1`：判断右侧详情是否还需要 bounded scroll 的停止条件
- `candidate_profile_v1`：可选的本地求职者画像，用于 SEEK 匹配
- `seek_job_match_decision_v1`：对已读岗位输出 strong/maybe/skip/review 及证据
- `saved_seek_job_record_v1`：strong/maybe 岗位的本地保存记录
- `seek_mvp_run_report_v1`：用于 traversal/scoring/application-prep 的 no-final-submit 报告骨架
- `seek_mvp_traversal_trace_v1`：独立 SEEK traversal 审计 trace，由 `seek_mvp_run_report_v1.traversal_trace_path` 引用
- `seek_mvp_run_audit_v1`：对 SEEK run report 和 traversal trace 的只读审计结果，用于进入更高风险步骤前复核
- `runtime_path_graph_v1`：从 SEEK 人工学习样本转换出的通用路径图模式 artifact，包含状态、区域、滚动容器、实体、动作边、动作模板、坐标证据、安全策略和 baseline metrics
- `learned_skill_v1`：从 SEEK 样本抽象出的通用 skill 集合，包括打开列表卡片、滚动容器、读取详情、校验 seeded click point 和阻断最终提交
- `visual_asset_v1`：从 SEEK 样本抽象出的视觉证据槽，包含按钮、图标、卡片形状、选中态和滚动条
- `available_actions_v1`：从 `runtime_path_graph_v1` 生成给 Execute Mode / 上层 agent 的可选动作菜单；包含 `action_kind` 和 `low_level_action_type`，可区分 click、scroll/read、input；默认不暴露 guarded Apply，且 artifact 本身不是点击授权
- `artifact_replay_board`：面板侧 harness 状态，用于加载学习出的 runtime graph、检查图结构/动作/skill/safety，并通过现有单步 Execute API 回放安全验证或任务运行步骤
- `github_issues_runtime_path_graph_v1`：第三个网站 family 的只读路径图样本，用于公开 GitHub issue 列表和 issue 详情页；验证列表行打开、详情标题跳转、页面级滚动、issue 元数据/侧栏区域和写入动作拦截
- `seek_application_flow_state_v1`：Apply / Quick Apply 后的申请状态分类，默认停止在表单填写和最终提交前
- `path_graph_recall_v1`：执行模式里的状态匹配和地图候选召回
- `pre_click_decision_v1`：真实点击前必须通过的闸门
- `execute_transition_memory_v1`：验证成功的真实点击写回
- `execute_fallback_plan_v1`：失败后的安全下一步计划，不代表允许自动点击

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
  - `configs/mousetester_eval_cases.json` defines the trace-based MouseTester smoke cases, including the 2026-05-13 golden live execute baseline

### Evidence and persistence

- `artifacts/`
  - screenshots
  - verification diff images
  - vision region image bundles
  - golden trace baselines, including `artifacts/golden-traces/mousetester-live-execute-20260513-182111-unicode-goal/`
    - contains copied `recognition_trace.json`, `action_trace.json`, `execute-response.json`, `before_full.png`, `after_full.png`, `diff.png`, `validation_summary.json`, and `manual_regression_checklist.md`
- `logs/`
  - structured JSON traces
  - action/state memory JSON
  - replay cases
  - transition records

### Tests

- `tests/`
  - pytest coverage for extracted logic and route-level behavior
- `tests/smoke/execute_cases/`
  - JSON smoke cases consumed by `scripts/execute_smoke_runner.py`
  - includes controlled Execute MVP page cases, Notepad File-menu dry-run, `seek_resume_screening_flow.json` for the local SEEK-like resume-screening two-step live flow, `seek_real_jobs_dryrun.json` for non-destructive real SEEK job-list dry-runs, `seek_real_jobs_reopen_dryrun.json` for reopening the real SEEK URL before each goal, and `seek_real_jobs_resized_dryrun.json` for resizing the bound Edge window before each goal

### Scripts

- `start_test_panel.bat`
  - root-level double-click launcher for the browser workflow test panel at `http://127.0.0.1:8000/panel`
  - pure batch launcher, avoiding `.ps1` quarantine by antivirus tools
  - can start the FastAPI runtime in a minimized `cmd` window if `/health` is not already reachable, then open the browser panel
  - writes runtime output to `logs/test-panel-runtime.log`
- `scripts/evaluate_mousetester_traces.py`
  - evaluates saved MouseTester recognition/action traces
  - writes JSON reports under `logs/evaluations/`
  - includes the 2026-05-13 live execute golden baseline through `configs/mousetester_eval_cases.json`
- `scripts/record_uia_smoke.py`
  - binds a target window, collects a Windows UIA snapshot, writes a `uia_smoke_trace_v1` trace, and scores it
  - default target is MouseTester.cn in Microsoft Edge
  - writes JSON reports under `logs/evaluations/`
- `scripts/execute_smoke_runner.py`
  - loads Execute Mode JSON smoke cases from `tests/smoke/execute_cases`
  - can open a browser URL or app before a case through `/apps/open`, bind or resize a target window, run dry-run recognition, and optionally reuse `approved_plan_id` for a real click with `--execute`
  - supports `--repeat N` to run the same case set repeatedly and records `repeat_index` / `repeat_count` in each JSONL row
  - writes `execute_smoke_result_v1` JSONL rows under `logs/smoke/`
  - records `selected_click_point`, `coordinate_overlay_path`, `dry_run_latency_ms`, `execute_latency_ms`, trace paths, post-click verification, and pass/fail reasons
  - evaluates `expect.point_in_rect` and treats `expect.max_latency_ms` as the dry-run decision latency threshold when real execution is enabled
- `scripts/seek_mvp_traversal_runner.py`
  - runs the SEEK no-apply traversal slice through existing runtime APIs
  - can open/bind the SEEK URL, observe visible cards, dry-run each card, optionally click only approved job cards with `--execute-clicks`, verify post-click detail-title match, read/merge right-pane details, scroll only `seek:job_detail` when incomplete, score with `--candidate-profile`, save suitable jobs with `--saved-jobs-dir`, optionally run `--apply-entry` for strong_apply jobs, write `seek_mvp_run_report_v1`, and write `seek_mvp_traversal_trace_v1` through `report.traversal_trace_path`
  - default live traversal budgets are `--max-detail-scrolls 6` and `--max-results-scrolls 8`; with `--execute-clicks`, `--max-jobs` targets opened/read jobs rather than raw attempted cards
- `scripts/seek_mvp_run_audit.py`
  - audits `seek_mvp_run_report_v1` plus `seek_mvp_traversal_trace_v1`
  - supports `--mode readonly`, `--mode apply_entry`, `--mode safe_fill`, `--trace`, `--out`, and `--fail-on-error`
  - emits `seek_mvp_run_audit_v1` without clicking, scrolling, model calls, or memory writes
- `scripts/seek_mvp_report_audit.py`
  - compatibility entry point used by the recommended run-audit script
- `scripts/candidate_profile_from_cv.py`
  - generates a local `candidate_profile_v1` draft from a `.docx`, `.txt`, or `.md` CV using deterministic extraction
  - prints only summary lengths/counts, not raw email or phone values
  - leaves `work_rights_summary` empty for user confirmation instead of inferring sensitive eligibility
- `scripts/model_servers/`
  - unified PowerShell launch/stop scripts for local multimodal servers
  - `start_llama_vision_server.ps1` starts a llama.cpp-compatible vision model from profile-supplied paths and runtime parameters
  - `start_transformers_vision_server.ps1` starts a Transformers/safetensors vision model profile such as VISTA-4B
  - `vista_openai_server.py` exposes VISTA-style point grounding through `/v1/models` and `/v1/chat/completions`
  - `stop_local_vision_server.ps1` stops a model server by profile PID file and/or port

### Browser test panel

- `app/api/panel.py`
  - serves the browser control surface at `GET /panel`
  - exposes browser-panel support routes for uploaded screenshots and safe artifact/log image preview
- `app/web_panel/`
  - static browser panel assets served under `/panel/assets/`
  - uses existing runtime APIs for health, model start/stop/status, app discovery/open, window binding, screenshot capture, whole-screen observation, precise localization, recognition-plan execution, operator-confirmed point execution, controlled text input, and overlay rendering
  - provides screenshot/upload/overlay preview and candidate bbox overlay for human review
- `app/web_panel/execute_test_page.html`
  - local controlled Execute Mode page used for safe Start/Continue/Done click-loop smoke tests
- `app/web_panel/seek_resume_fixture.html`
  - local SEEK-like resume-screening page used to validate agent-style multi-step Execute calls without touching a real external account
  - exposes shortlist and next-candidate actions with visible post-click state changes for verification

### Desktop settings panel

  - modular bilingual desktop control surface for stage-by-stage runtime testing
  - keeps the left sidebar aligned with the agent workflow: workflow diagram, app discovery, open/bind, screenshot capture, whole-screen understanding, precise localization, and dry-run gated clicking
  - each stage page exposes the parameters for that stage API and shows returned JSON on the same screen through the fixed response panel
  - the fixed response panel also renders an animated action path graph from the latest API response, linking goal, screen capture, OCR/UIA/vision evidence, candidate ranking, pre-click gate, click, verification, timings, and trace artifact nodes
  - each stage page is scrollable, so long model/API sections are still reachable in smaller windows
  - keeps local/API model configuration on a bottom sidebar gear page
  - supports two local model profiles in `configs/vision.json`: `local_understanding` for small-model screen understanding and `local_grounding` for large-model precise localization
  - stdlib HTTP client for the local FastAPI runtime
  - paths and JSON load/save helpers for `configs/vision.json`, `configs/settings_panel.json`, and panel artifacts
  - Chinese/English labels for the panel UI

### Project memory and takeover docs

- `README.md`
  - concise overview, setup, endpoints, roadmap
- `ACTION_PATH_GRAPH_SPEC.zh-CN.md`
  - Chinese contract spec for `runtime_path_graph_v1`, including node/edge fields, allowed types/statuses/relations, deterministic generation rules, and how the graph supports stability testing and future learning records
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
- `AGENT_API_WORKFLOW.md`
  - required API-first workflow for upper-layer agents, including endpoint order, request/response shapes, OCR-anchor prompt handoff, and gated click decision rules
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

- `app/api/apps.py`
  - `GET /apps`
  - `POST /apps/open`
  - responsibility:
    - expose `app_discovery_v1` with configured launchable apps, visible windows, current bound window, and agent next-step hints
    - launch catalog apps from `configs/app_catalog.json`, including browser URL arguments and executable fallback candidates
    - optionally bind the launched app window

- `app/api/runtime.py`
  - `GET /runtime/models`
  - `POST /runtime/models/start`
  - `POST /runtime/prepare`
  - responsibility:
    - expose configured local vision model profile status
    - start observe/locate model servers through profile-defined scripts
    - provide an API-first preparation step before an agent asks vision routes to run

- `app/api/session.py`
  - `GET /session/windows`
  - `POST /session/bind_window`
  - `POST /session/resize_bound_window`
  - responsibility: list visible windows, bind the runtime to one target window, and resize the current bound window for stability/coordinate-drift tests

- `app/api/state.py`
  - `GET /state`
  - `POST /state/capture_window`
  - responsibility: expose current bound-window state and screenshot capture

- `app/api/vision.py`
  - `POST /vision/ocr_region`
  - `POST /vision/analyze`
  - `POST /vision/page_structure`
  - `POST /vision/screen_reading`
  - `POST /vision/observe_screen`
  - `POST /vision/locate_target`
  - `POST /vision/recognition_plan`
  - `POST /vision/layer_trace`
  - `POST /vision/render_review_overlay`
  - `POST /vision/render_recognition_plan_overlay`
  - responsibility:
    - OCR a bound-window ROI through the OCR adapter
    - run provider-based vision analysis through the `app/vision/` abstraction
    - normalize learned regions
    - fuse semantic regions with OCR text boxes into `page_structure_v1`
    - build `screen_reading_v1` as the READ-facing UI layer, including connected Windows UIA provider evidence plus reserved browser/learned-UI provider slots
    - expose `screen_observation_v1` as the agent-facing broad screen-understanding step before target choice
    - expose `target_location_v1` as the no-click precise target localization step before gated action execution
    - return a no-click staged recognition plan with ranked candidates, including bounded screen-reading rank evidence
    - expose a test/debug trace that shows every layer result and schema validation
    - redraw region/OCR boxes on the original screenshot for human review
    - redraw recognition-plan candidates, decisions, and refined points for human review
    - optionally feed the local provider a light pixel-grid reference overlay for bbox-accuracy experiments
    - optionally feed the recognition-plan provider prompt OCR text boxes as `ocr_anchors_v1` spatial hints, with fallback to the unanchored provider call if needed
    - persist annotated screenshots and per-region crops for later page-structure building

- `app/api/action.py`
  - `POST /action/execute_recognition_plan`
  - `POST /action/execute_confirmed_point`
  - `POST /action/type_text`
  - `POST /action/click_text`
  - `POST /action/click_mouse_tester_left_region`
  - responsibility:
    - controlled execution of a `recognition_plan_v1` selected click point after `pre_click_decision_v1` allows it
    - MouseTester target-area semantic post-click verification
    - bounded retry for retry-safe post-click verification failures
    - operator-reviewed coordinate click diagnostic path
    - real bound-window text input through SendInput plus clipboard paste
    - OCR-driven text click
    - MouseTester-specific region click with validation and persistence

- `app/evaluation/mousetester_trace_eval.py`
  - trace-evaluation helpers for MouseTester recognition/action evidence
  - reports top-1, pre-click, action execution, semantic verification, and retry facts

- `app/evaluation/uia_smoke_eval.py`
  - trace-evaluation helpers for Windows UIA smoke evidence
  - scores scan status, control count, button count, and expected control-name substrings such as `杩斿洖`, `鍒锋柊`, and `鐐瑰嚮姝ゅ娴嬭瘯`

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
  - low-level mouse movement, click dispatch, and text input through `SendInput`

- `app/core/model_server.py`
  - loads model profiles from `configs/model_profiles/`
  - checks OpenAI-compatible `/v1/models`
  - starts profile-defined local llama.cpp-compatible or Transformers-backed model servers

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
    - `TypeTextRequest`
    - `RuntimePrepareRequest`
    - `ModelServerRequest`
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
  - includes optional `ocr_anchors_v1` guidance so the model can use OCR text boxes as relative-position anchors for nearby visual controls
  - compacts OCR anchors for the prompt as `id/t/b/c/s/g` while preserving all text boxes and coordinates
  - requires `anchor_relations` and `grounding_constraints` so each returned region records which OCR anchors constrained its bbox and how those anchors set edges, centers, size, exclusions, text-anchor frame, relative frame position, and text inclusion policy
  - appends `metadata.prompt_overrides.additional_rules` when the settings panel or an agent supplies extra grounding rules
- `ocr_anchors.py`
  - builds compact OCR anchor payloads from `OCRResult`
  - sorts anchors by goal similarity and confidence
  - keeps all OCR text boxes by default; `metadata.ocr_anchors.max_anchors` can explicitly cap the prompt when needed
  - scales anchor coordinates into resized provider inference images
- `anchor_grounding.py`
  - evaluates model-returned OCR anchor relations against known OCR text boxes
  - enforces the two grounding policies: visual-only icon bboxes should exclude referenced text anchors, while text-bearing controls should include referenced text anchors
  - writes `grounding_evaluation` evidence and `anchor_corrected_bbox` suggestions into region `grounding_constraints`
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
- `app/recognition/plan_overlay.py`
  - renders human-review overlays from saved `recognition_plan_v1` JSON files
  - shows candidate boxes, allow/reject status, local OCR matches, and refined click points
- `ocr_region_refiner.py`
  - experimental OCR-assisted box correction that shifts semantic regions toward matching OCR text without editing OCR output

Current status:

- structure exists
- `/vision/analyze` can call into it
- the local provider can invoke a configured local multimodal endpoint and normalize model JSON
- local provider traces preserve per-attempt metadata such as scaled inference size, compact retry mode, coordinate remap evidence, and optional grid-reference artifact paths
- local provider traces also record when OCR anchors were included in the prompt and which coordinate space they used
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
  - rejects far ambiguous OCR bindings, especially short repeated text, unless geometry also supports the match
  - clusters additional bound OCR text around the best local OCR anchor instead of unioning distant same-label fragments
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

### Screen reading layer

- `app/screen_reading/`
  - READ-facing screen interpretation layer above `page_structure_v1`
  - outputs `screen_reading_v1`
  - keeps UI recognition separate from action execution
  - exposes conservative placeholders for future browser accessibility and learned-UI-memory providers
  - connects a Windows UIA provider for bound-window accessibility controls
  - keeps icon-like candidates as reserved visual targets without catalog-level icon matching

Key files:

- `uia_provider.py`
  - defines the Windows UI Automation provider
  - enumerates controls from the currently bound window through pywinauto's `uia` backend
  - converts screen-space UIA rectangles into window-relative bboxes for screenshot matching
  - skips unavailable pywinauto UIA pattern descriptors instead of failing the full scan
  - returns structured `unavailable` results when no window is bound or UIA scanning fails
- `builder.py`
  - consumes normalized `vision_regions_v1`, OCR output, and `page_structure_v1`
  - merges optional Windows UIA matches into `ui.elements[*].provider_matches.uia`
  - promotes OCR-backed page elements into `ui.elements`
  - preserves visual-only semantic UI regions as low-confidence/reserved candidates
  - extracts `ui.icon_candidates` for no-text or icon-like controls without marking them safe for execution
  - builds `ui.modules` from larger semantic regions and records child element/text ids
  - emits `provider_slots` and `learning_hooks` so later browser/learning work has a stable integration point

Runtime output:

- `contract_version`
  - always `screen_reading_v1`
- `texts`
  - normalized OCR text boxes
- `ui.elements`
  - UI objects with `role_guess`, `type`, label, bbox, click point, evidence level, locator hints, memory key, and provider matches such as `uia`
- `ui.icon_candidates`
  - reserved icon-like candidates without catalog-level icon identity matching
  - includes `uia_match` when a bound-window UIA control overlaps the icon candidate
  - candidates still need sufficient combined evidence and post-action verification before execution
- `ui.provider_slots`
  - provider interfaces for `uia`, `browser_accessibility`, and `learned_ui_memory`
  - `uia` is connected to the Windows UIA scanner; scan status can be `ok` or `unavailable`
- `execution_relevance`
  - safe, risky, and unknown candidate id buckets for later grounding
- `uncertainties`
  - explicit gaps such as `visual_only_ui_requires_grounding`

Route:

- `POST /vision/screen_reading`

Execution sequence:

1. validate `image_path`
2. run configured vision provider and normalize to `vision_regions_v1`
3. run OCR
4. build `page_structure_v1`
5. build `screen_reading_v1`
6. write a vision trace under `logs/traces/vision/`

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

### `configs/app_catalog.json`

Current purpose:

- list launchable apps for `GET /apps`
- define each app's `app_id`, display name, launch command, process/title binding hints, and capability tags
- let an upper-layer agent discover what local software can be opened before it decides how to act

Current entries:

- `edge`
- `notepad`

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
- local understanding defaults target `Qwen3-VL 4B Q4_K_M` through `http://127.0.0.1:1241/v1/chat/completions`
- local grounding defaults target `VISTA-4B Transformers` through `http://127.0.0.1:1244/v1/chat/completions`
- `Qwen3-VL 8B Q4_K_M` is installed as an optional understanding baseline on port `1240`
- `MiniCPM-V-4.6 Transformers` is benchmark-only until a compatible OpenAI-compatible server path is added
- local default provider timeout is conservative, but current execution performance work should prefer preprocessing, PathGraph/ROI recall, and model-specific max-edge controls over simply raising timeouts
- full-page stability is now improved in provider code through inference scaling plus compact retry fallback
- local deployment assets are stored under ignored `models/` and `tools/` directories
- API provider remains a stub unless replaced with a real endpoint

### `configs/model_profiles/`

Current purpose:

- one JSON file per model profile
- centralizes model label, role, endpoint, input format, runtime, local model path, optional mmproj path, start/stop script paths, port, context size, GPU layers, image token budget, output contract, and known strengths/limitations
- launchable local GGUF profiles include `model_path` and `mmproj_path`; launchable Transformers profiles include a safetensors model directory and `start_transformers_vision_server.ps1`; endpoint-only profiles can be tested but not started by the local script

Current entries:

- `qwen3_vl_8b_q4_k_m.json`
- `qwen3_vl_4b_q4_k_m.json`
- `minicpm_v_4_6_transformers.json`
- `vista_4b_transformers.json`

### Other config folders

Current status:

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

- `artifacts/settings-panel/`
  - desktop settings panel manual-box overlays and review images

- `artifacts/review-overlays/`
  - human-review overlay images rendered from saved traces

- `artifacts/recognition-crops/`
  - local candidate ROI crops generated by `narrow_search_v1`

- `artifacts/local-learning/instructions/{id}/`
  - permanent instruction-learning bundle for `learned_instruction_v1`
  - contains `learned_instruction.json`, source window screenshot, pre-action screenshot, post-action screenshot, post-action diff image, and target crop
  - shown by the desktop response path graph as a learning-asset artifact node

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

- `logs/learned-instructions/`
  - legacy location for early `learned_instruction_v1` JSON-only records
  - the loader still accepts this path for compatibility, but new learning writes go to `artifacts/local-learning/instructions/{id}/`

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

### vision screen reading

- route: `app/api/vision.py`
- endpoint: `POST /vision/screen_reading`
- builder: `app/screen_reading/builder.py`

Use this when the upper layer wants a fuller READ result instead of only the older page-structure fusion result. The current implementation strengthens the UI part of READ by returning OCR-backed elements, visual-only/icon candidates, module grouping, locator hints, reserved provider slots, and learning hooks.

This endpoint still does not execute actions. Visual-only candidates are intentionally risky/reserved until enough combined evidence from UIA, browser accessibility, icon catalog, shape/template matching, or learned UI memory confirms them.

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
    - request: `CandidateRankRequest(goal, page_structure, top_k=5, state_hint=None, screen_reading=None)`
    - response: `CandidateRankResult`
    - response version: `candidate_rank_v1`
    - candidate id: stable `candidate_<element_id>` form
    - ranking evidence: `ScoreBreakdown`
    - geometry evidence: original `element.bbox` plus optional OCR-derived `refined_bbox`
    - optional `screen_reading_v1` evidence can supply UIA accessible names and UIA matches
    - `ScoreBreakdown.screen_reading_score` is a bounded rank signal; it does not override blocked/ad-like interaction policy
  - current scoring signals:
    - goal text similarity
    - supported interaction role
    - interaction policy priority and zone type
    - fusion and coordinate confidence
    - optional state hint similarity
    - optional screen-reading provider evidence
    - ad and blocked-policy penalties
  - current bbox refinement:
    - uses `source_text_ids` from `page_structure_v1`
    - prefers source OCR texts that match the current goal before falling back to all bound text
    - unions matching OCR text boxes with padding
    - only enables `refined_bbox` when the OCR union is tighter than the original element bbox
    - stores `bbox_refine_reason` without mutating the original element bbox
- `narrow_search`
  - add new module:
    - `app/recognition/local_grounding.py`
  - responsibility:
    - crop and rerun local analysis on candidate ROIs
  - current contract:
    - request: `LocalGroundingRequest(image_path, goal, candidates, ocr_scan, app_name=None, crop_padding=24)`
    - response: `LocalGroundingResult`
    - response version: `narrow_search_v1`
    - evidence: crop path, crop bbox, matched local OCR text, refined full-image click point
  - current implementation:
    - OCR-first local grounding baseline
    - crops `candidate.refined_bbox` first when available, otherwise `candidate.element.bbox`
    - maps local OCR bbox centers back into full screenshot coordinates
    - falls back to candidate element click point when no local OCR match is found
- `verify`
  - first reuse:
    - `app/core/verifier.py`
  - then add task-specific decision logic:
    - `app/recognition/decision.py`
  - current pre-click contract:
    - response: `PreClickDecisionResult`
    - response version: `pre_click_decision_v1`
    - decision fields: allow/reject, selected candidate id, selected click point, per-candidate reasons
  - current checks:
    - candidate score threshold
    - top-1 margin threshold
    - candidate goal text match
    - interaction policy allowed
    - ad-candidate rejection
    - local OCR text match
    - refined click point inside candidate refined bbox when present, otherwise original candidate bbox
- orchestration
  - add one thin coordinator:
    - `app/recognition/pipeline.py`

#### Current MVP planning endpoint

The first debug-first planning route is implemented:

- `POST /vision/recognition_plan`

Request:

- `image_path`
- `task`
- `goal`
- optional `state_hint`
- optional `top_k`

Response includes:

- `parse_result`
  - includes `ocr_anchors` when OCR anchor prompting was used successfully; `null` means the route continued without anchored prompt evidence
- `candidate_result`
- `narrow_search_result`
- `pre_click_decision`
- `verification_plan`
- `recommended_target`
- `trace_path`

This route should not click yet.
It should exist to prove that the staged selection logic is working before action dispatch is attached.
Current response version: `recognition_plan_v1`.

Current recognition-plan provider preparation:

1. run OCR first and build `ocr_anchors_v1` from all detected text boxes by default
2. add the anchor payload to `VisionAnalyzeRequest.metadata.ocr_anchors`
3. let the local provider scale anchors into the actual inference image size when screenshots are resized
4. include compact anchor guidance in the vision prompt so nearby icons/buttons/cards can be grounded by relative position without dropping all-page OCR text boxes
5. require every returned region to include `anchor_relations` and `grounding_constraints`, including `text_anchor_frame`, `relative_frame_position`, and `text_inclusion_policy`, before its final bbox evidence is normalized
6. if the anchored provider call fails, retry once without `ocr_anchors` and record `ocr_anchor_grounding_fallback_used`
7. evaluate returned bbox policy against referenced OCR anchors and record `grounding_evaluation`
8. reuse the OCR result for page-structure fusion when possible

The local InternVL3.5 server is started with `-c 8192 --parallel 1` so full-page OCR anchor prompts can fit in a single slot.
`scripts/serve_internvl3_5_server.ps1` accepts `-ModelPath`, `-MmprojPath`, `-ServerPath`, `-Port`, and `-ContextSize` so compatible GGUF multimodal models can be swapped without changing the recognition-plan code.

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
   - status: OCR-first `narrow_search_v1` exists under `app/recognition/local_grounding.py`
3. connect pre-click `verify`
   - status: `pre_click_decision_v1` exists under `app/recognition/decision.py`
4. expose a no-click planning route
   - status: `POST /vision/recognition_plan` exists and returns `recognition_plan_v1`
5. attach action execution only after the planning path is measured

This keeps the MVP small, inspectable, and reversible.

### Long-Term Agent Roadmap

Long-term product goal:

- build toward an agent that can operate unknown pages by observing the UI, forming a structured plan, executing cautiously, validating the result, and recovering from failure
- the runtime should not jump directly from one successful click to unknown-page autonomy
- each stage must be backed by trace evidence, regression cases, and explicit failure modes

#### Stage 1: Single-Page Stable Loop

Goal:

- fixed website
- fixed task
- stable execution

Current representative target:

- MouseTester.cn in Microsoft Edge
- task: click `鐐瑰嚮姝ゅ娴嬭瘯`
- route: `POST /action/execute_recognition_plan`
- golden baseline: `artifacts/golden-traces/mousetester-live-execute-20260513-182111-unicode-goal/`

What the MouseTester baseline proves:

- the system is not randomly succeeding from a raw coordinate
- it uses structured reasoning: page parse, screen-reading evidence, candidate ranking, local grounding, pre-click gate, click execution, and post-click validation
- the internal recognition trace preserves the Unicode goal
- the top target carries UIA name/Invoke evidence and target-area OCR validation
- the clicked point comes from `pre_click_decision_v1.selected_click_point`, not from unverified full-screen vision output

Next work inside this stage:

- turn the one golden success into a stable loop over repeated runs
- add successful-run learning write-back for the recognition execution mainline
  - status: first `instruction_learning` slice exists behind `learning_mode="instruction"` and writes `learned_instruction_v1` after verified `execute_recognition_plan` clicks
  - status: `learned_instruction_id` reuse can skip recognition/model inference after validating the same goal, app name, bound-window handle, window size, and point bounds, while still running post-click verification
- after recognition, click, and validation all succeed, persist a reusable record with goal, site/app identity, state fingerprint or state hint, candidate id, `memory_key`, bbox/refined bbox, selected/clicked point, OCR/UIA evidence, before/after screenshots, validation result, recognition trace path, and action trace path
- bridge successful `execute_recognition_plan` runs into the existing memory vocabulary: `ReplayCase`, `TransitionRecord`, future `TargetAsset`, and `learned_ui_memory`
- use learned records only as additional evidence on later runs; fresh observation, pre-click gate, and post-click validation remain mandatory
- keep the website and task fixed while varying the session conditions
- measure top-1 target stability, pre-click allow/reject stability, selected point drift, action execution, semantic validation, and learning-record reuse stability

#### Stage 2: Cross-Session Stability

Goal:

- prove that a task that works today still works tomorrow
- measure robustness before broadening to unknown sites

Stability variables to test:

- page state changes and light layout changes
- window size changes
- DPI or display scaling changes
- OCR fluctuation
- visual model fluctuation
- browser/session differences such as reloads, zoom, focus, and page scroll position

Expected evidence:

- repeated MouseTester traces across sessions
- pass/fail reports that separate OCR failures, vision-region failures, page-structure failures, screen-reading failures, candidate-ranker failures, pre-click failures, action failures, and validator failures
- baselines for acceptable bbox/click-point drift
- evidence that learned records survive across sessions and improve reuse without bypassing safety gates

#### Stage 3: Semantic Generalization

Goal:

- move from exact text matching toward intent matching across similar controls

Example:

- known target: `鐐瑰嚮姝ゅ娴嬭瘯`
- possible unknown-site labels: `寮€濮嬫祴閫焋, `Launch Test`, `Run Benchmark`, `Start`

Core challenge:

- the hard part becomes semantic understanding, not OCR or clicking
- the system must infer that several labels can express the same user intent while still avoiding unsafe or unrelated controls

Expected future components:

- intent schema for user goals
- semantic candidate matching with explanations
- negative examples for misleading labels
- confidence and abstention rules when intent is ambiguous

#### Stage 4: Multi-Step Stateful Workflows

Goal:

- execute workflows that require state tracking and planning, not only one click

Example workflow shape:

- login
- wait for navigation
- handle popup
- find menu
- submit form
- validate result

Core challenge:

- agent memory and planning become more important than the click primitive
- the runtime needs durable state observations, step results, and workflow-level validation

#### Stage 5: Recovery And Self-Healing

Goal:

- recover when the expected path fails instead of blindly repeating the same click

Failure modes to handle:

- button does not appear
- page is stuck or still loading
- OCR fails
- popup blocks the target
- click has no visible effect
- validation fails after action execution

Expected recovery behavior:

- observe again
- explain the failure category
- re-plan with bounded alternatives
- execute only if the new plan passes safety gates
- record the recovery trace for later regression

## Active Vs Legacy

### Active mainline

- `session`
- `state`
- `vision/ocr_region`
- `vision/analyze`
- `vision/page_structure`
- `vision/screen_reading`
- `vision/recognition_plan`
- `vision/layer_trace`
- `vision/render_review_overlay`
- `vision/render_recognition_plan_overlay`
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

## Browser Panel Current Structure (2026-06-02)

- `app/api/panel.py`: serves `/panel`, static artifact files, trace listing/inspection, path graph saving, manual candidate-box rendering, model-profile application, and `POST /panel/model_test` for direct prompt/image calls to configured vision models.
- `app/web_panel/index.html`: browser-only operator UI. Stage pages are Open/Bind, Capture, Observe, Locate, Execute, Input, Trace, and Models.
- `app/web_panel/panel.js`: stage-specific layout controller, trace-stage renderer, navigation path graph, model test caller, API response renderer, and browser-panel event wiring.
- `app/web_panel/panel.css`: browser panel layout and graph/trace/model-test styling.

## SEEK MVP utilities (2026-06-17)

- `app/seek/profile.py`: evaluates `candidate_profile_v1` readiness for truthful cover-letter generation and single-field safe-fill.
- `scripts/seek_profile_readiness.py`: standalone UTF-8 CLI for checking a real candidate profile before live SEEK safe-fill and for writing a blank `candidate_profile_v1` template.
- `tests/test_seek_profile.py`: pure readiness rules.
- `tests/test_seek_profile_readiness_cli.py`: CLI report/template behavior.
- `artifacts/seek/candidate_profile_template.json`: generated local template when the CLI is run with `--write-template`.
- `logs/smoke/seek_profile_readiness_*.json`: readiness smoke reports.
