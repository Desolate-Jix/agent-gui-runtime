---
name: seek-high-precision
description: Use for the SEEK automation MVP when accuracy, gated clicks, nested scroll control, trace evidence, and final-submit safety matter more than broad website generality.
---

# SEEK High Precision Skill

This skill keeps SEEK automation as a dedicated high-precision workflow.
Do not dilute it into a generic web agent path.

Before scoring or applying to any job, read and follow:

- `skills/seek-high-precision/JOB_REQUIREMENTS.md`

## Scope

Use this workflow for real SEEK search/detail/application pages.

The specialized layer remains in:

- `app/seek/scroll_containers.py`
- `app/seek/extraction.py`
- `app/seek/traversal.py`
- `app/seek/matching.py`
- `app/seek/application.py`
- `app/seek/application_artifacts.py`
- `app/seek/final_review.py`
- `app/seek/employer_questions.py`
- `app/seek/cover_letter.py`
- `app/seek/answer_plan.py`
- `app/seek/profile.py`
- `app/seek/audit.py`
- `scripts/seek_mvp_traversal_runner.py`
- `scripts/seek_profile_readiness.py`
- `scripts/seek_mvp_run_audit.py`
- `scripts/seek_debug_export_application_fill_record.py`
- `scripts/seek_application_final_review_audit.py`
- `scripts/seek_export_application_flow_artifact.py`
- `scripts/seek_export_learn_artifacts.py`

Reusable foundations live outside the SEEK layer:

- `app/core/audit.py`: generic audit check helpers.
- `app/profile/cv.py`: deterministic CV text extraction and candidate profile draft generation.
- `scripts/candidate_profile_from_cv.py`: CLI for local CV to `candidate_profile_v1` draft.
- `app/seek/learn_artifacts.py`: exports stable SEEK execution evidence into Learn Mode artifacts.

## Required Flow

1. Bind the SEEK browser window.
2. Discover `seek:page`, `seek:results_list`, and `seek:job_detail`.
3. Traverse cards with `recognition_plan_v1`, `pre_click_decision_v1`, and post-click verification.
4. Read details by scrolling only `seek:job_detail`.
5. Extract `seek_job_card_v1` and `seek_job_detail_v1`.
6. Score jobs with `candidate_profile_v1` and `JOB_REQUIREMENTS.md`.
7. Save `strong_apply` and `maybe_apply` jobs.
8. Write `seek_mvp_run_report_v1` and `seek_mvp_traversal_trace_v1`.
9. Run `seek_mvp_run_audit_v1` before Apply Entry or safe-fill.
10. For station-internal SEEK application forms, keep the default SEEK resume unless the user explicitly says otherwise, rewrite the cover letter from the reviewed job detail and real candidate profile, answer only evidence-backed employer questions, and choose privacy-preserving profile options such as `Don't include` for persistent SEEK Profile suggestions when those choices are shown.
11. Stop on the final `Review and submit` page before final Submit / Send application / Complete application.
12. Export stable runs into `learned_app_profile_v1` and `path_graph_seed_v1` when the run should seed Learn Mode.

## Safety Rules

- Never use smoke/template/generated-unreviewed profile data for real Apply Entry or safe-fill.
- `blocked_need_real_candidate_profile` is a safe stop, not a failure.
- Apply Entry must remain `strong_apply` only unless the user explicitly allows `maybe_apply`.
- Real clicks must go through the gated action API.
- Continue / Next / Review may be used only inside the dedicated station-internal application-fill slice after the current page evidence has been captured and checked. Submit / Send application / Complete application remain forbidden until the user explicitly approves that exact final action.
- Do not persist SEEK Profile suggestions, uploaded files, rewritten resumes, or profile edits without explicit user approval. Default to `Don't include` for application-time profile suggestions when shown; record `not_shown` when no suggestion choice appears.
- Do not infer work rights, visa status, salary, relocation, health, background checks, or availability from a CV.

## Evidence Rules

Every run must preserve:

- card-click recognition/action traces;
- nested scroll traces;
- detail-read trace paths;
- match decision evidence;
- saved-job records;
- Apply Entry stop reason;
- cover-letter draft status;
- answer-plan and safe-fill preview evidence;
- employer-question inventory, profile-backed answer plan, and local option-ranking evidence when questions are present;
- application-fill records when a station-internal form is filled;
- final-review audit records proving the run stopped before final submit;
- final Review extraction records when the Review page is visible enough to reconcile its summary or answer text against `application_fill_record.json`;
- `final_submissions=0`.

Before advancing, run:

```powershell
uv run python scripts\seek_mvp_run_audit.py --report logs\smoke\seek_mvp_traversal_report.json --mode readonly --fail-on-error
```

To create Learn Mode artifacts from a stable run:

```powershell
uv run python scripts\seek_export_learn_artifacts.py --report logs\smoke\seek_mvp_traversal_report.json --out artifacts\seek\learned_seek_mvp_latest.json
```

`learned_app_profile_v1` and `path_graph_seed_v1` are guidance artifacts only. They may assist scroll target selection, candidate constraints, verification policy, and safety policy, but they do not bypass the gated Execute path.

For a station-internal application-fill run, write `application_fill_record.json` and audit it before declaring success:

```powershell
uv run python scripts\seek_debug_export_application_fill_record.py `
  --run-dir logs\smoke\seek_application_fill_<job_id> `
  --out logs\smoke\seek_application_fill_<job_id>\application_fill_record.json

uv run python scripts\seek_application_final_review_audit.py `
  --record logs\smoke\seek_application_fill_<job_id>\application_fill_record.json `
  --out logs\smoke\seek_application_fill_<job_id>\final_review_audit.json `
  --fail-on-error

uv run python scripts\seek_debug_step_runner.py `
  --run-dir logs\smoke\seek_application_fill_<job_id> `
  --step extract_final_review `
  --application-fill-record logs\smoke\seek_application_fill_<job_id>\application_fill_record.json
```

The exporter can merge root-level debug evidence into the same record:

- `seek_cover_letter_revision_v1` supplies a later reviewed/retyped cover letter, its type-text trace, and before/after screenshots.
- `seek_employer_questions_manual_debug_v1` supplies reviewed employer-question answers and evidence sources.
- Automated `employer_question_fill_attempt` reports from `scripts/seek_debug_step_runner.py --step continue_application_flow` supply profile-backed employer-question answers when the fill status is `filled_until_review`.
- `seek_final_review_extraction_v1` supplies `review_reconciliation_v1`, cover-letter latest hash, employer-question match counts, submit visibility, and zero-submit counters. If SEEK only shows folded text such as `You wrote a cover letter` / `You answered 4 out of 4`, record the verification depth as summary-based rather than pretending the hidden answer text was visible.
- `seek_review_submit_stop_before_submit_v1` supplies the bottom-of-review screenshot, `final_submit_text_visible=true`, and `final_submissions=0`.

The current complete sample is:

- record: `logs\smoke\seek_apply_live_92822270_debug_20260620_selected_value\application_fill_record.json`
- audit: `logs\smoke\seek_apply_live_92822270_debug_20260620_selected_value\final_review_audit.json`
- artifact: `artifacts\seek\learned_seek_application_flow_92822270_20260620.json`

The audit must pass as `seek_application_final_review_audit_v1` with:

- `decision=pass_stopped_before_final_submit`;
- `final_submissions=0`;
- `submit_clicks=0`;
- `cover_letter_filled=true`;
- employer questions answered from profile/evidence; when no employer-question step is visible, record the explicit `0/0` count and do not invent answers;
- `persistent_profile_updates=0`;
- `seek_profile_suggestions_choice="Don't include"` when suggestion choices are shown, or `"not_shown"` when no suggestion choice appears;
- a final Review screenshot and type-text trace.

For employer-question selects/dropdowns, first inspect the visible selected value inside the question group. If the selected text matches the profile-backed planned answer, record `selected_value_candidates` and preview `target.action_type=already_selected` with bbox/source/match score; do not open the dropdown. If no visible selected value matches, stop at preview with `select_choice_requires_dropdown_option_mapping` until dropdown option mapping is implemented and verified.

Export the reviewed stop-before-submit run as non-authorizing Learn Mode evidence:

```powershell
uv run python scripts\seek_export_application_flow_artifact.py `
  --record logs\smoke\seek_application_fill_<job_id>\application_fill_record.json `
  --audit logs\smoke\seek_application_fill_<job_id>\final_review_audit.json `
  --final-review-extraction logs\smoke\seek_application_fill_<job_id>\final_review_extraction.json `
  --out artifacts\seek\learned_seek_application_flow_<job_id>.json
```

`seek_application_flow_artifact_v1` is a milestone artifact only. It records provenance paths, screenshot/trace evidence, the prefixed station-internal application state machine, transitions, filled content summary, action templates, verification rules, review reconciliation, learned skills, and safety policy, but it is not authorization to replay final submit or bypass safe-fill verification. The reusable learned skill exported from this path is `skill:review_before_submit_reconciliation`: compare a visible final review page against the saved fill record, report missing/mismatched fields, and stop before final submit.

The broader SEEK job-search/application workflow is also abstracted outside this SEEK-specific skill:

- `artifacts/templates/job_search_application_workflow_template_v1.json`
- `artifacts/skills/job_search_application_workflow_skill_v1.json`

These artifacts capture job/company recording, profile-based screening, same-site nonfinal application entry, multi-step form review, and final-submit blocking as reusable guidance for future job-board samples. They remain non-authorizing; real execution still requires fresh screenshots, current coordinates, gated clicks, post-action verification, and explicit final-submit refusal.

Safe-fill focus reuse must fail closed: the dry-run selected focus point must be inside the planned field bbox before the approved plan is executed for real. If the focus point is outside or unavailable, stop with `safe_field_focus_point_outside_field_bbox`; do not click first and then fall back to a synthetic type point.

For real profile preparation:

```powershell
uv run python scripts\candidate_profile_from_cv.py --cv path\to\cv.docx --out artifacts\seek\candidate_profile_draft.json
uv run python scripts\seek_profile_readiness.py --candidate-profile artifacts\seek\candidate_profile_draft.json --fail-if-blocked
```
