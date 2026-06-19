# SEEK Automation MVP Plan

Last updated: 2026-06-17.

## Goal

Build a SEEK-specific, explainable, gated, testable job-search MVP. The system may open job cards, read job details, score roles, enter application flows, generate and fill draft answers, and stop before final submission. It must not submit a real application.

## Safety Boundary

- Every click must go through `recognition_plan_v1`, `pre_click_decision_v1`, and post-click verification.
- Scroll is a reveal/navigation action only. It never grants click permission.
- `Apply`, `Quick Apply`, and form-fill actions may start or prepare an application flow, but the runtime must stop before `Submit`, `Send application`, `Complete application`, or equivalent final submission.
- Login, captcha, salary uncertainty, start date, relocation, background checks, health declarations, visa details, upload uncertainty, third-party ATS uncertainty, and final submission must return `blocked_need_user_or_gpt_decision`.
- All significant steps must write trace evidence.

## Target Run Flow

```text
bind SEEK browser window
-> discover_scroll_containers_v1
-> traverse visible results_list job cards
-> open job card through Execute gate
-> read full job_detail, scrolling only job_detail when needed
-> extract seek_job_card_v1 and seek_job_detail_v1
-> score with candidate_profile_v1
-> decide strong_apply / maybe_apply / skip / need_user_review
-> save matching job record
-> for strong_apply: click Apply / Quick Apply through Execute gate
-> generate truthful English cover letter from real resume + job detail
-> fill safe known fields and open questions
-> stop before risky or final-submit step
-> emit seek_mvp_run_report_v1
```

## Current Slice

Implemented in the current slice:

- `scroll_containers_v1` SEEK heuristic discovery for:
  - `seek:page`
  - `seek:results_list`
  - `seek:job_detail`
- `ScrollRequest` now supports container-aware fields:
  - `scroll_scope`
  - `target_pane`
  - `target_container_id`
  - `container_bbox`
  - `coordinate_window_size`
  - `goal_id`
  - `task_chain_id`
  - `reason`
  - `missing_evidence`
  - `expected_effect`
  - `scroll_history`
- `/action/scroll` now emits `scroll_action_v2` when a container target is used.
- `/action/scroll` now records `scroll_precondition_decision_v1`.
- `/action/scroll` now records `scroll_effect_validation_v1`.
- SEEK fallback planning can request `seek:job_detail` for detail-section goals and `seek:results_list` for list/card goals.
- `seek_job_card_v1` extraction from visible `screen_inventory_v1.cards`, child page text, and child action evidence.
- `seek_job_detail_v1` skeleton extraction from the currently visible `seek:job_detail` pane, including visible Apply/Save button state and section hints.
- `seek_job_detail_v1` now expands the detail read bbox upward to include the SEEK detail header above the scroll body, so title/company/location and Quick apply/Save evidence are not lost.
- Unit coverage for card extraction, filter-card exclusion, right-pane detail extraction, and detail-pane containment filtering.
- `seek_job_detail_completeness_v1` pure decision logic for whether the runner should keep scrolling the right detail pane.
- `merge_seek_job_details()` for deduplicating visible detail slices collected across scrolls.
- `seek_mvp_run_report_v1` no-final-submit report shell with counters and `final_submissions=0` invariant.
- `seek_mvp_traversal_trace_v1` independent traversal trace, with `traversal_trace_path` embedded in the run report.
- `seek_mvp_run_audit_v1` read-only audit for report + traversal trace evidence.
- `seek_mvp_accuracy_summary_v1` report summary with opened/read/decision coverage rates, card-click open rate, scroll-scope audit, Apply Entry counts, final-submit blocker count, and safety invariants.
- `candidate_profile_v1` JSON loading with UTF-8/UTF-8-SIG support.
- `seek_job_match_decision_v1` scoring for opened/read jobs, returning `strong_apply`, `maybe_apply`, `skip`, or `need_user_review` with evidence and `do_not_invent_experience` risk flags.
- Matching now reads profile exclusions and preferences:
  - `avoid_roles`, `excluded_roles`, `avoid_companies`, and `do_not_apply_to` can force `skip` with `candidate_profile_exclusion_matched`.
  - `preferred_work_modes` adds positive evidence when visible, but does not override safety.
  - visa/sponsorship/citizenship/residency/security-clearance/background-check terms force `need_user_review` with `work_rights_or_background_check_requires_review`.
- Incomplete job details force `need_user_review` with `detail_incomplete_do_not_apply`, even when profile keywords match.
- `saved_seek_job_record_v1` JSON records for `strong_apply` and `maybe_apply` jobs.
- `scripts/seek_mvp_traversal_runner.py` no-apply traversal runner skeleton:
  - opens/binds a SEEK URL through existing runtime APIs,
  - observes visible cards,
  - dry-runs each card through `POST /action/execute_recognition_plan`,
  - optionally clicks only approved job cards when `--execute-clicks` is explicit,
  - reads and merges the right detail pane,
  - scrolls only `seek:job_detail` when `seek_job_detail_completeness_v1.should_scroll=true`,
  - optionally loads `--candidate-profile` and saves suitable jobs under `--saved-jobs-dir`,
  - writes a `seek_mvp_run_report_v1` report,
  - writes a separate `seek_mvp_traversal_trace_v1` under `logs\traces\seek\...`,
  - stores that path in `report.traversal_trace_path`.
- Real no-apply SEEK 5-job smoke evidence:
  - command: `uv run python scripts\seek_mvp_traversal_runner.py --max-jobs 5 --max-detail-scrolls 6 --max-results-scrolls 8 --execute-clicks --candidate-profile tests\smoke\seek_candidate_profile_smoke.json --saved-jobs-dir artifacts\seek\saved-jobs-smoke --out logs\smoke\seek_mvp_traversal_real_5_profile_smoke_rerun12.json`
  - result: `jobs_seen=5`, `jobs_opened=5`, `jobs_fully_read=5`, `strong_apply=2`, `maybe_apply=2`, `need_user_review=1`, `saved_jobs=4`, `final_submissions=0`, elapsed about `371s`.
  - the runner now treats `--max-jobs` as the target opened/read job count when `--execute-clicks` is used, while keeping a bounded attempt cap.
  - post-click success requires the opened detail title to match the clicked card title; mismatches are recorded as `post_click_layout_drift` and do not count as opened.
  - bottom-edge job cards are deferred until they reappear in a safer click band after results-list scrolling.
  - synthetic result-list cards must have a card anchor such as location or company plus SEEK metadata, reject detail classification/body/section-heading text, and write `synthetic_validation` evidence for accepted synthetic cards.
  - overlapping `screen_inventory_v1.cards` candidates with the same company/location are deduped, preferring UIA-backed complete titles over mixed screen/action labels or incomplete hyperlink labels.
  - obvious split synthetic titles such as `Lead Software Engineer - AI &` + `Automation` are merged before company extraction.
  - detail completeness accepts either `requirements` or `responsibilities` as role evidence; both missing still triggers a `role_evidence` scroll request.
  - follow-up smoke `logs\smoke\seek_mvp_readonly_after_role_evidence_3jobs_20260617.json` reached `jobs_seen=3`, `jobs_opened=3`, `jobs_fully_read=3`, `detail_read_completion_rate=1.0`, `post_click_layout_drift_count=0`, `card_click_open_rate=1.0`, `wrong_scope_scroll_count=0`, and `final_submissions=0`.
  - runner reports now align `jobs[]` from `traversal_steps`, so drifted cards keep `detail=null` and do not shift later details onto the wrong card.
  - queue dedupe normalizes punctuation and common stuck title words such as `SeniorSoftware`, reducing duplicate saved jobs after results-list scroll.
  - SEEK card execution now sends `metadata.seeded_candidate` (`seeded_candidate_v1`) to `POST /action/execute_recognition_plan`, carrying the extracted `seek_job_card_v1` title/company, `card_bbox`, `click_point`, `seek:results_list` container id, evidence texts, and safety policy. Recognition still runs VISTA and `pre_click_decision_v1`; the seed constrains the candidate ROI and the final click point is the extracted card point only after VISTA validates the seed bbox.
  - VISTA traces now distinguish seed-validated coordinates with `coordinate_source=seeded_candidate_v1_validated_by_vista_point_v1`, and `recognition_plan_v1` records `seeded_candidate`, `seeded_candidate_used`, and `seeded_candidate_selected`.
  - VISTA point parsing accepts wrapped unparsed bbox output such as `{"status":"unparsed","raw_text":"[36, 48, 426, 350]"}` by parsing the nested four-number bbox and using its pixel center. The raw wrapper and parsed point remain in `model_io`.
  - Pixel-space VISTA point/bbox outputs are now strict-bounds checked before coordinate conversion. Bad pixel output outside the inference image raises a model protocol error instead of being clamped to a screen edge and accidentally treated as valid.
  - SEEK results-list layout now caps the left `seek:results_list` width on wide windows so synthetic extraction does not absorb right detail text. Synthetic card filtering also rejects over-wide bboxes, `viewed/ago` status text as company/title evidence, and incomplete card labels such as `Engineering Manager -`.
  - latest 5-job no-apply smoke `logs\smoke\seek_mvp_readonly_after_parser_title_filter_5jobs_20260617.json` reached `jobs_seen=5`, `jobs_opened=5`, `jobs_fully_read=5`, `opened_rate=1.0`, `detail_read_completion_rate=1.0`, `match_decision_coverage_rate=1.0`, `card_click_open_rate=1.0`, `post_click_layout_drift_count=0`, `wrong_scope_scroll_count=0`, `submit_clicks=0`, and `final_submissions=0`. Opened jobs included Temperzone, Halter, Plexure, Absolute IT, and Enterprise Technology Recruitment; decisions were `strong_apply=3`, `maybe_apply=1`, and `need_user_review=1`.
- `SEEK Apply Entry Guarded v1` implementation:
  - CLI flag: `--apply-entry`.
  - Only `strong_apply` jobs enter the stage by default; `maybe_apply` requires explicit `--allow-maybe-apply`.
  - Apply / Quick Apply is clicked only through `POST /action/execute_recognition_plan` dry-run + approved-plan execution.
  - The Apply goal carries a hard negative constraint: do not click Submit, Send application, or Complete application.
  - Immediately before Apply / Quick Apply, the runner emits `pre_apply_detail_verification_v1` from a fresh observe pass and blocks if the current right-pane title/company no longer match the selected `strong_apply` job or Apply is no longer visible.
  - Apply Entry requests carry metadata `forbid_final_submit=true` and `required_container_id=seek:job_detail`.
  - `/action/execute_recognition_plan` now emits `final_submit_guard_v1` and blocks before `click_point` if the selected candidate text matches final-submit terms.
  - The runner records `apply_click.container_id=seek:job_detail`, `submit_clicks=0`, `form_fields_filled=0`, and `final_submit_guard` evidence in `seek_apply_entry_attempt_v1`.
  - After Apply / Quick Apply, the runner observes once, emits `seek_application_flow_state_v1`, records `blocked_need_user_or_gpt_decision`, and stops the traversal before form fill, next-step clicks, or final submission.
  - Unit/mock evidence verifies `application_flows_started` increments, `forms_filled_until_review=0`, `form_fields_filled=0`, `submit_clicks=0`, `cover_letters_generated=0`, and `final_submissions=0`.
  - Live evidence: `logs\smoke\seek_mvp_apply_entry_live_1_strong_guarded_after_guard_goal_filter.json` recorded `jobs_seen=1`, `jobs_opened=1`, `jobs_fully_read=1`, `strong_apply=1`, `application_flows_started=1`, `cover_letters_generated=0`, `forms_filled_until_review=0`, `form_fields_filled=0`, `submit_clicks=0`, `final_submissions=0`, and `final_submit_guard_active=true`.
  - The live Apply entry used action trace `logs\traces\actions\20260617-090119-791457__execute-mode-click__edge.json`, with `pre_click_decision_v1.allowed=true`, `final_submit_guard_v1.allowed=true`, and post-click verification `verified=true`.
  - Two live-smoke root causes are fixed: Apply text fallback now accepts right-pane page text such as `Apply C` when action bboxes drift outside `seek:job_detail`, and `final_submit_guard_v1` now filters negative goal/instruction text before checking final-submit terms.
  - Latest read-only regression after adding application-flow/answer-plan/safe-fill primitives:
    - `logs\smoke\seek_mvp_readonly_regression_3jobs_20260617.json`: `jobs_seen=5`, `jobs_opened=3`, `jobs_fully_read=3`, `strong_apply=2`, `saved_jobs=2`, `application_flows_started=0`, `form_fields_filled=0`, `submit_clicks=0`, `final_submissions=0`; all detail scrolls targeted `seek:job_detail`, and all results-list scrolls targeted `seek:results_list`.
    - `logs\smoke\seek_mvp_apply_entry_readonly_1strong_20260617.json`: `jobs_seen=1`, `jobs_opened=1`, `jobs_fully_read=1`, `strong_apply=1`, `application_flows_started=1`, `application_state_type=application_form_detected`, `forms_filled_until_review=0`, `form_fields_filled=0`, `submit_clicks=0`, `final_submissions=0`; action trace `logs\traces\actions\20260617-100030-224309__execute-mode-click__edge.json` has `pre_click_decision_v1.allowed=true`, `final_submit_guard_v1.allowed=true`, and post-click verification `verified=true`.
- `Application Flow Read-Only Detector v1` implementation:
  - `seek_application_flow_state_v1` now emits `detected_states`, `application_form_inventory_v1`, and `final_submit_visible_blocker_v1`.
  - The detector distinguishes `final_submit_visible`, `login_required`, `captcha_or_verification`, `third_party_ats`, `resume_upload_required`, `risky_application_questions`, `review_step_detected`, `screening_questions_detected`, `cover_letter_field_detected`, `application_form_detected`, `application_flow_opened`, and `unknown_after_apply`.
  - `final_submit_visible_blocker_v1` is a state-layer STOP when action-like controls or short button labels include `Submit application`, `Send application`, `Complete application`, `Review and submit`, `Finish application`, or equivalent final-submit terms. Negative instruction text such as `Do not click Submit` is not treated as button evidence.
  - The runner now records `continue_clicks=0`, `final_submit_visible_blocker`, and report-level `final_submit_visible_blockers` during Apply Entry. This does not replace action-layer `final_submit_guard_v1`; both layers remain required.
- `cover_letter_draft_v1` draft-only implementation:
  - `app/seek/cover_letter.py` builds a pure JSON draft artifact from `candidate_profile_v1`, `seek_job_detail_v1`, `seek_job_match_decision_v1`, and optional `seek_application_flow_state_v1`.
  - Draft generation is allowed only for `strong_apply` and only when the profile looks like real resume evidence. Smoke/test profiles, missing experience summaries, and no matched skill evidence return blocked draft artifacts instead of invented content.
  - The runner records `cover_letter_draft` per Apply Entry and report-level `cover_letter_drafts`; `cover_letters_generated` increments only when status is `draft_only_not_pasted`.
  - This slice does not paste into the UI, does not click Continue/Next, and does not fill any fields.
- `application_answer_plan_v1` read-only implementation:
  - `app/seek/answer_plan.py` classifies visible fields/actions from `application_form_inventory_v1` into `auto_safe_known`, `needs_user_review`, `blocked_sensitive`, `unsupported`, and `danger_final_submit`.
  - The plan can mark known profile fields, known work-rights answers, and available cover-letter drafts as safe-known, but it does not fill them.
  - Common simple text/email/url/tel fields are recognized only when `candidate_profile_v1` has a clear value: first name, last name, preferred name, email, phone/mobile, city/suburb, GitHub, LinkedIn, portfolio, and website.
  - Button, radio, select, dropdown, and file controls are not auto-filled even when their label resembles a safe field.
  - Salary/start-date/relocation/background/criminal/health/unknown work-rights questions are sensitive-blocked; upload/file controls are unsupported; final-submit visible evidence becomes `blocked_final_submit_visible`.
  - The runner records `application_answer_plan` per Apply Entry and report-level `application_answer_plans`; `filled=false` and all click/fill counters remain zero.
- `safe_form_fill_attempt_v1` primitive:
  - CLI flag: `--fill-safe-fields`; default is off.
  - CLI safety limits: `--max-safe-fields-to-fill` defaults to `1`, and `--allow-cover-letter-fill` defaults to off.
  - The runner only considers `application_answer_plan_v1.planned_answers` with `category=auto_safe_known` and a non-empty `value_preview`.
  - Cover-letter drafts are skipped unless `--allow-cover-letter-fill` is explicitly set.
  - Each field first uses `POST /action/execute_recognition_plan` dry-run + approved-plan execution to focus the field with `forbid_final_submit=true`; only after gated focus succeeds does it call `POST /action/type_text`.
  - The text call stays inside the `TypeTextRequest` schema and uses `click_before_typing=false`, `clear_existing=true`, and `submit=false`, so typing does not bypass the gated focus click and never presses Enter.
  - `application_answer_plan_v1`, `safe_form_fill_trace_v1`, and `post_fill_verification_v1` now redact safe-field values in report/trace payloads. They keep `value_length` and SHA-256 hashes, while the runner resolves the real value from in-memory `candidate_profile_v1` / `cover_letter_draft_v1` only at fill time.
  - Continue / Next / Review / Submit remain forbidden by the focus goal, state-layer blocker, action-layer guard, and report counters.
- `safe_form_fill_trace_v1` evidence:
  - embedded in each `safe_field_fill_result_v1.safe_form_fill_trace`, including preview-only field results when `--fill-safe-fields` is off;
  - records field id/label/category/bbox, answer source, value length/hash, focus dry-run, approved focus reuse, `type_text` request flags, post-fill verification placeholder, and zero safety counters;
  - keeps `type_text.submit=false`, `click_before_typing=false`, and `final_submissions=0` explicit in the trace.
- `post_fill_verification_v1` implementation:
  - after successful `type_text`, the runner re-observes the application surface and reruns `seek_application_flow_state_v1` plus `final_submit_visible_blocker_v1`;
  - structured field value evidence (`value` / `dom_value` / `input_value`, then `uia_value` / `value_pattern` / `text_pattern`) is required for `decision=verified`; OCR/text evidence is recorded only as secondary;
  - field relocation failure, value mismatch, unsafe application state, or final-submit visibility returns `unverified` or `stop_required` and prevents filling the next field;
  - report safety remains `continue_clicks=0`, `submit_clicks=0`, and `final_submissions=0`.
- `candidate_profile_readiness_v1` standalone CLI:
  - command: `uv run python scripts\seek_profile_readiness.py --candidate-profile path\to\candidate_profile.json --out logs\smoke\seek_profile_readiness.json`;
  - optional template writer: `--write-template artifacts\seek\candidate_profile_template.json`;
  - smoke/test/synthetic profiles remain blocked before live safe-fill;
  - `--apply-entry` and `--fill-safe-fields` now share `seek_apply_entry_profile_gate_v1`; if `candidate_profile_readiness_v1.live_smoke_ready` is false, the runner records `blocked_need_real_candidate_profile` and does not click Apply / Quick Apply;
  - live Apply Entry requires explicit `profile_source: "real_user_candidate_profile_v1"`; real-looking temporary/test data without this source may still support no-apply matching, but it cannot enter Apply Entry or safe-fill;
  - readiness and CLI summaries expose `profile_source`, `real_user_profile_source`, and `pii_redaction_enabled` so an upper agent can decide whether Apply Entry is allowed without inspecting full profile contents;
  - smoke/test detection uses explicit smoke/test-profile phrases and must not treat real skills such as `test automation` as a test profile marker;
  - live-smoke readiness now requires explicit real-user profile source, matching basics (`skills` or `target_roles`, plus `location_constraints`), truthful cover-letter basics (`experience_summary`), at least one safe text field, and `work_rights_summary`;
  - the generated template includes education, availability, preferred work modes, avoid roles/companies, and do-not-apply exclusions so the next real profile can support matching decisions without fabricating context;
  - the report records low-risk field names and value lengths, not full profile values;
  - `--fail-if-blocked` exits with code `2` unless the profile is ready for a single safe-field live smoke.
- High-precision SEEK skill and reusable foundation split:
  - SEEK-specific operating rules remain in `skills/seek-high-precision/SKILL.md`. This skill is intentionally narrow: SEEK traversal, seeded card clicks, nested scroll, Apply Entry guard, no-final-submit proof, and report/trace audit.
  - Reusable audit helpers live in `app/core/audit.py`; SEEK keeps only domain-specific audit rules in `app/seek/audit.py`.
  - Generic CV text extraction and local candidate-profile draft generation live in `app/profile/cv.py` and `scripts/candidate_profile_from_cv.py`.
  - The CV draft generator emits `candidate_profile_v1` with `profile_source="real_user_candidate_profile_v1"`, but it deliberately leaves `work_rights_summary` blank and marks review required. It must not infer work rights, salary, availability, or sensitive answers from a resume.
  - A Wenqing Ji local draft was generated from `D:\资料\CV\WENQING JI.docx` to `artifacts\seek\candidate_profile_wenqingji_draft.json`. The readiness check blocks live Apply/safe-fill until the missing `work_rights_summary` is explicitly supplied by the user.
- Learn Mode artifact export from stable execution experience:
  - `app/seek/learn_artifacts.py` exports `learned_app_profile_v1` and `path_graph_seed_v1` from `seek_mvp_run_report_v1` plus optional `seek_mvp_traversal_trace_v1`.
  - `learned_app_profile_v1` records `page_type=seek_search_results_with_detail`, the SEEK scroll containers, job-card/detail entity patterns, action templates, verification rules, and the no-final-submit safety policy.
  - `path_graph_seed_v1` represents the learned SEEK page as `top_search_area`, `results_list`, `job_detail`, `job_card`, `detail_header`, and `detail_body`.
  - `app/learn/path_graph_artifacts.py` converts the SEEK manual-learning sample into generic `runtime_path_graph_v1`, `learned_skill_v1`, and `visual_asset_v1` outputs. The runtime graph records states, regions, scroll containers, entities, transitions, action templates, coordinate policy, visual asset refs, learned skill refs, baseline metrics, and safety policy.
  - `app/learn/visual_asset_crops.py` can derive `visual_asset_crop_export_v1` from a representative screenshot. The current minimal slice crops and hashes learned job-card shape evidence; action-button crops remain pending until a current screenshot provides stable bboxes.
  - `app/execute/available_actions.py` builds `available_actions_v1` from the runtime graph. Guarded Apply is hidden by default, and all returned actions mark `artifact_is_authorization=false`.
  - `app/learn/path_graph_resolver.py` emits `path_graph_resolution_v1` from a runtime graph plus current inventory/scroll evidence.
  - `app/execute/path_graph_step.py` converts one selected available action into `execute_step_response_v1` with `path_graph_action_context_v1` and a low-level click/scroll request plan.
  - `app/api/execute.py` exposes `POST /execute/available_actions` and `POST /execute/step`; this is a single-step Execute layer, not a multi-step runner. When `dispatch_low_level=true`, `/execute/step` dispatches exactly one generated request through the existing gated `/action/scroll` or `/action/execute_recognition_plan` route.
  - `scripts/seek_export_learn_artifacts.py` writes the bundle and can also split profile/path-graph/runtime-graph/learned-skills/visual-assets outputs, plus optional screenshot-derived visual crop exports.
  - `scripts/seek_mvp_traversal_runner.py` now accepts `--learned-artifact`; when present, it keeps the existing SEEK runner and gates, but prefers the artifact's scroll targets, candidate constraints, verification policy, and safety policy in request metadata.
  - Current exported 5-job smoke artifact: `artifacts\seek\learned_seek_mvp_from_5job_smoke_20260617.json`. Its baseline records `jobs_opened=5`, `jobs_fully_read=5`, `post_click_layout_drift_count=0`, `wrong_scope_scroll_count=0`, and `final_submissions=0`.
  - Current generic exports: `artifacts\seek\runtime_path_graph_seek_mvp_20260617.json`, `artifacts\seek\learned_skills_seek_mvp_20260617.json`, and `artifacts\seek\visual_assets_seek_mvp_20260617.json`.
- Traversal trace evidence:
  - `seek_mvp_traversal_trace_v1` is written independently from `seek_mvp_run_report_v1` so the operator can inspect the actual traversal timeline without digging through every report field.
  - It includes `traversal_events`, `scroll_events`, `match_decisions`, `saved_jobs`, `apply_entries`, `application_answer_plans`, `safe_form_fill_attempts`, `accuracy_summary`, and zero-submit safety counters.
  - Each traversal event summarizes the card, gated card-click trace paths, detail-read trace paths, completeness result, detail scrolls, match decision, Apply Entry summary, and search restore evidence.
  - Regression coverage asserts that raw profile email/phone values are absent from the report, saved-job records, and traversal trace payload.
- Run audit evidence:
  - `scripts\seek_mvp_run_audit.py` reads `seek_mvp_run_report_v1` plus `traversal_trace_path` or an explicit `--trace`.
  - It emits `seek_mvp_run_audit_v1` with hard safety checks, traversal quality checks, nested-scroll checks, profile-gate checks, Apply Entry stop checks, and a recommended next step.
  - `blocked_need_real_candidate_profile` is treated as a safe pass only when Apply Entry was not entered, fields were not filled, and no live cover letter was generated.
  - Historical reports that predate `traversal_trace_path` intentionally audit as `needs_review` until rerun with the current runner.

Not implemented yet:

- Browser DOM scroll detection.
- UIA ScrollPattern extraction.
- Visual scrollbar detector.
- Cover-letter UI paste.
- Live safe form-fill smoke on a real SEEK application flow.
- Final-submit-before-stop proof on a live application flow.

## Current Extraction Contracts

### seek_job_card_v1

Initial fields:

- `job_id`
- `title`
- `company`
- `location`
- `posted_at_text`
- `work_type`
- `salary_text`
- `classification`
- `card_bbox`
- `click_point`
- `source_url`
- `source_card_id`
- `primary_action_id`
- `child_action_ids`
- `child_page_element_ids`
- `evidence`

### seek_job_detail_v1

Initial fields:

- `job_id`
- `title`
- `company`
- `location`
- `work_type`
- `classification`
- `salary_text`
- `description_sections`
- `requirements`
- `responsibilities`
- `benefits`
- `apply_button_state`
- `save_button_state`
- `detail_container`
- `detail_read_bbox`
- `detail_scroll_history`
- `trace_paths`
- `evidence`

These contracts currently describe visible evidence only. They do not yet prove that the full detail pane has been scrolled to completion.

### seek_job_detail_completeness_v1

Initial fields:

- `complete`
- `should_scroll`
- `missing_evidence`
- `scroll_count`
- `max_scrolls`
- `stop_reason`
- `next_scroll_request`

The current default required detail evidence is title, company, location, at least one description section, and responsibilities. Requirements, benefits, and currently visible Apply state are useful evidence, but they are not required for read-completeness because many SEEK posts do not expose those headings consistently.

## Matching Contracts

### candidate_profile_v1

Minimum fields:

- `skills`
- `experience_summary`
- `target_roles`
- `location_constraints`
- `work_rights_summary`
- `salary_preference`
- `risk_do_not_invent`

Recommended fields for live MVP testing:

- `candidate_name`
- `email`
- `phone`
- `city`
- `suburb`
- `education_summary`
- `availability_summary`
- `preferred_work_modes`
- `avoid_roles`
- `avoid_companies`
- `do_not_apply_to`

The current scorer requires at least one of `skills` or `target_roles`. Missing or incomplete profiles produce `need_user_review` instead of inventing fit.
The scorer also honors explicit exclusions before scoring: matching `avoid_roles`, `excluded_roles`, `avoid_companies`, or `do_not_apply_to` produces `skip` and prevents saved-job records. `preferred_work_modes` can add positive evidence when the job detail visibly matches. Visa/work-rights/background-check terms are treated as review blockers, not as apply-positive evidence.

### seek_job_match_decision_v1

Minimum fields:

- `decision`: `strong_apply`, `maybe_apply`, `skip`, or `need_user_review`
- `score`
- `positive_evidence`
- `negative_evidence`
- `unknowns`
- `risk_flags`
- `trace_path`

`scripts/seek_mvp_traversal_runner.py` attaches these decisions to `report.match_decisions`, each traversal step, and `report.jobs[].match_decision`.
Current risk flags include `do_not_invent_experience`, `detail_incomplete_do_not_apply`, `candidate_profile_exclusion_matched`, and `work_rights_or_background_check_requires_review`.

### saved_seek_job_record_v1

Saved only for `strong_apply` and `maybe_apply`:

- `job_id`
- `decision`
- `card`
- `detail`

### seek_mvp_run_report_v1

Initial no-final-submit counters:

- `jobs_seen`
- `jobs_opened`
- `jobs_fully_read`
- `strong_apply`
- `maybe_apply`
- `skip`
- `need_user_review`
- `application_flows_started`
- `cover_letters_generated`
- `forms_filled_until_review`
- `form_fields_filled`
- `continue_clicks`
- `final_submissions`
- `submit_clicks`
- `final_submit_guard_active`
- `accuracy_summary`
- `accuracy_notes`
- `traversal_trace_path`
- `elapsed_ms`

`final_submissions` must always be `0`.
`traversal_trace_path` points to the independent `seek_mvp_traversal_trace_v1` trace written under `logs\traces\seek\...`.
The report remains the compact run artifact; the traversal trace is the audit timeline for card clicks, scrolls, detail reads, match decisions, Apply Entry stops, answer plans, safe-fill attempts, and safety counters.

### seek_mvp_traversal_trace_v1

Written by `scripts\seek_mvp_traversal_runner.py` after `seek_mvp_run_report_v1` is assembled:

- `source_report_contract`
- `mode`
- `source_url`
- `execute_clicks`
- `candidate_profile_readiness`
- `apply_entry_profile_gate`
- `summary`
- `traversal_events`
- `scroll_events`
- `match_decisions`
- `saved_jobs`
- `apply_entries`
- `application_answer_plans`
- `safe_form_fill_attempts`
- `accuracy_summary`
- `safety`

Inspect this trace first when a job card opens the wrong detail pane, a right-pane read is incomplete, a scroll targets the wrong container, matching looks wrong, Apply Entry is blocked, or a safe-fill preview/fill needs review.

### seek_mvp_run_audit_v1

Generated by `scripts\seek_mvp_run_audit.py`:

- `stage`: `no_apply`, `apply_entry`, or `full_mvp`
- `decision`: `pass` or `needs_review`
- `report_path`
- `traversal_trace_path`
- `summary`
- `counts`
- `checks`
- `next_step`

Useful commands:

```powershell
uv run python scripts\seek_mvp_run_audit.py --report logs\smoke\seek_mvp_traversal_report.json --mode readonly --out logs\smoke\seek_mvp_run_audit.json
uv run python scripts\seek_mvp_run_audit.py --report logs\smoke\seek_mvp_traversal_report.json --mode apply_entry --fail-on-error
```

The audit does not click, scroll, call models, or change memory. It is a regression gate for deciding whether a run has enough evidence to continue.

### seek_mvp_accuracy_summary_v1

Derived from `seek_mvp_run_report_v1`:

- `opened_rate`
- `detail_read_completion_rate`
- `match_decision_coverage_rate`
- `card_click_open_rate`
- `post_click_layout_drift_count`
- `results_list_scroll_count`
- `detail_scroll_count`
- `wrong_scope_scroll_count`
- `apply_entry_count`
- `application_flow_started_count`
- `final_submit_visible_blocker_count`
- `safety_invariants`
- `status`

`status=needs_review` indicates the report saw a safety invariant break such as submit/final submission evidence or wrong-scope scrolling. It is an audit summary only; trace evidence remains authoritative for debugging.

### final_submit_guard_v1

Generated inside `POST /action/execute_recognition_plan` when the request metadata includes `forbid_final_submit=true`:

- `enabled`
- `allowed`
- `selected_candidate_id`
- `selected_texts`
- `matched_terms`
- `reason`

If `allowed=false`, the action route returns `final_submit_guard_rejected` before any click is dispatched.

### seek_application_flow_state_v1

Generated after Apply / Quick Apply entry:

- `status`: currently always stops at `blocked_need_user_or_gpt_decision`
- `state_type`: `application_flow_opened`, `application_form_detected`, `cover_letter_field_detected`, `screening_questions_detected`, `review_step_detected`, `resume_upload_required`, `final_submit_visible`, `login_required`, `captcha_or_verification`, `third_party_ats`, `risky_application_questions`, or `unknown_after_apply`
- `detected_states`
- `stop_reason`
- `application_flow_started`
- `final_submit_visible`
- `final_submit_visible_blocker`
- `final_submission_performed`: must be `false`
- `risk_flags`
- `application_form_inventory`
- `trace_path`
- `source_job`
- `evidence.texts`

### final_submit_visible_blocker_v1

Generated inside `seek_application_flow_state_v1` from post-Apply observe evidence:

- `enabled`
- `blocked`
- `matched_terms`
- `matched_items`
- `reason`

If `blocked=true`, the runner must stop before planning form fill or navigation. This is a page-state blocker; action-layer `final_submit_guard_v1` still protects every real click.

The blocker intentionally ignores negative safety/instruction text such as `Do not click Submit`; real STOP evidence must be an action-like item or a short final-submit button label.

### cover_letter_draft_v1

Generated after Apply Entry state detection, but never pasted by this slice:

- `job_hash`
- `job_id`
- `title`
- `company`
- `status`: `draft_only_not_pasted`, `blocked_need_real_resume_profile`, `blocked_decision_not_strong_apply`, or `blocked_no_profile_skill_evidence`
- `draft`
- `evidence_used`
- `truthfulness_checks`
- `blocked_reason`
- `source_contracts`

Truthfulness checks include no commercial-years claim, no submitted-application claim, no invented skills, no graduation overstatement, and draft-only status. Smoke/test profiles are blocked.

### application_answer_plan_v1

Generated after `cover_letter_draft_v1`, but never filled by this slice:

- `status`: `planned_only_not_filled`, `blocked_final_submit_visible`, or `no_fields_detected`
- `filled`: must be `false`
- `field_count`
- `action_count`
- `counts`
- `planned_answers`
- `stop_reason`
- `source_contracts`

Plan categories are `auto_safe_known`, `needs_user_review`, `blocked_sensitive`, `unsupported`, and `danger_final_submit`. Only a later safe-fill slice may use `auto_safe_known`; this plan alone does not authorize UI input.

### safe_form_fill_attempt_v1

Generated when Apply Entry has an answer plan:

- `enabled`
- `status`: `disabled`, `dry_run_ready`, `no_safe_known_fields`, `filled_until_review`, or `blocked_need_user_or_gpt_decision`
- `filled`
- `fields_attempted`
- `fields_filled`
- `continue_clicks`
- `submit_clicks`
- `final_submissions`
- `stop_reason`
- `field_results`

Real filling is only attempted when `--fill-safe-fields` is set. Each `safe_field_fill_result_v1` must show gated focus evidence before `type_text`; `type_text` must have `click_before_typing=false` and `submit=false`, and the request payload must stay within `TypeTextRequest`.

### candidate_profile_readiness_v1

Generated by `app.seek.profile.assess_candidate_profile_readiness()` and exposed through `scripts/seek_profile_readiness.py`:

- `profile_present`
- `is_smoke_or_test_profile`
- `smoke_or_test_markers`
- `matching_ready`
- `cover_letter_ready`
- `safe_fill_ready`
- `live_smoke_ready`
- `safe_fill_values`: field names, source keys, and value lengths only
- `missing_requirements`
- `optional_profile_gaps`
- `decision`: `ready_for_single_safe_field_live_smoke` or `blocked_need_real_candidate_profile`

The CLI wrapper report contract is `seek_profile_readiness_cli_report_v1`. Use it before live SEEK safe-fill; do not proceed when the decision is blocked. `safe_fill_ready=true` alone is not enough; `live_smoke_ready` and `decision=ready_for_single_safe_field_live_smoke` are the gate for a real single-field fill.

## Next Implementation Step

Next, review the generated local draft profile, explicitly fill `work_rights_summary`, then run `scripts\seek_profile_readiness.py --fail-if-blocked`. If the profile is blocked, do not run live safe-fill. After readiness passes, rerun no-apply traversal + matching with the real profile; only if a `strong_apply` job appears should Apply Entry read-only be run. If the real SEEK form then exposes any `auto_safe_known` simple text field with `safe_form_fill_trace_v1` preview evidence, run at most one controlled live safe-fill field and inspect traces:

```powershell
$env:PYTHONIOENCODING='utf-8'
uv run python scripts\candidate_profile_from_cv.py --cv "D:\资料\CV\WENQING JI.docx" --out artifacts\seek\candidate_profile_wenqingji_draft.json
uv run python scripts\seek_profile_readiness.py --candidate-profile artifacts\seek\candidate_profile_wenqingji_draft.json --out logs\smoke\seek_profile_readiness_wenqingji_draft.json --fail-if-blocked
uv run python scripts\seek_export_learn_artifacts.py --report logs\smoke\seek_mvp_readonly_after_parser_title_filter_5jobs_20260617.json --out artifacts\seek\learned_seek_mvp_from_5job_smoke_20260617.json --profile-out artifacts\seek\learned_app_profile_seek_mvp_20260617.json --path-graph-out artifacts\seek\path_graph_seed_seek_mvp_20260617.json --runtime-graph-out artifacts\seek\runtime_path_graph_seek_mvp_20260617.json --learned-skills-out artifacts\seek\learned_skills_seek_mvp_20260617.json --visual-assets-out artifacts\seek\visual_assets_seek_mvp_20260617.json
uv run python scripts\seek_mvp_traversal_runner.py --max-jobs 5 --max-detail-scrolls 6 --max-results-scrolls 8 --execute-clicks --candidate-profile artifacts\seek\candidate_profile_wenqingji_draft.json --out logs\smoke\seek_mvp_traversal_report.json
```

Then inspect the generated report, card-click overlays, action traces, scroll traces, completeness decisions, `seek_application_flow_state_v1`, `final_submit_visible_blocker_v1`, `cover_letter_draft_v1`, `application_answer_plan_v1`, `safe_form_fill_attempt_v1`, and `final_submit_guard_v1`. First run without `--fill-safe-fields`; only run with `--fill-safe-fields` if a low-risk `auto_safe_known` field is visible. Continue / Next / Review / Submit remain forbidden.
