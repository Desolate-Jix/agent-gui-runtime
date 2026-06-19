---
name: seek-high-precision
description: Use for the SEEK automation MVP when accuracy, gated clicks, nested scroll control, trace evidence, and final-submit safety matter more than broad website generality.
---

# SEEK High Precision Skill

This skill keeps SEEK automation as a dedicated high-precision workflow.
Do not dilute it into a generic web agent path.

## Scope

Use this workflow for real SEEK search/detail/application pages.

The specialized layer remains in:

- `app/seek/scroll_containers.py`
- `app/seek/extraction.py`
- `app/seek/traversal.py`
- `app/seek/matching.py`
- `app/seek/application.py`
- `app/seek/cover_letter.py`
- `app/seek/answer_plan.py`
- `app/seek/profile.py`
- `app/seek/audit.py`
- `scripts/seek_mvp_traversal_runner.py`
- `scripts/seek_profile_readiness.py`
- `scripts/seek_mvp_run_audit.py`
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
6. Score jobs with `candidate_profile_v1`.
7. Save `strong_apply` and `maybe_apply` jobs.
8. Write `seek_mvp_run_report_v1` and `seek_mvp_traversal_trace_v1`.
9. Run `seek_mvp_run_audit_v1` before Apply Entry or safe-fill.
10. Export stable runs into `learned_app_profile_v1` and `path_graph_seed_v1` when the run should seed Learn Mode.
11. Stop before final Submit / Send application / Complete application.

## Safety Rules

- Never use smoke/template/generated-unreviewed profile data for real Apply Entry or safe-fill.
- `blocked_need_real_candidate_profile` is a safe stop, not a failure.
- Apply Entry must remain `strong_apply` only unless the user explicitly allows `maybe_apply`.
- Real clicks must go through the gated action API.
- Continue / Next / Review / Submit remain forbidden until a separate gated navigation slice exists.
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

For real profile preparation:

```powershell
uv run python scripts\candidate_profile_from_cv.py --cv path\to\cv.docx --out artifacts\seek\candidate_profile_draft.json
uv run python scripts\seek_profile_readiness.py --candidate-profile artifacts\seek\candidate_profile_draft.json --fail-if-blocked
```
