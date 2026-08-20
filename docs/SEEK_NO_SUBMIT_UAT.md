# SEEK No-Submit UAT

## Scope

This checkpoint validates one live, read-only Quick Apply inventory. It may open a reviewed SEEK-hosted Quick Apply flow after explicit approval, read the current fields and employer questions, write redacted evidence, and stop.

It does not authorize live form filling, answer selection, file upload, Continue/Next, or final submit. Fixture results and a passing read-only report are not evidence of live safe-fill reliability or SEEK end-to-end reliability.

## Required Preflight

Run this UAT only when all checks are true:

- The user explicitly approved entering Quick Apply for this run.
- The bound browser window and current screenshot are correct and fresh.
- GPU/model capacity is available; if the user is using the GPU, postpone or use the repository's bounded model batch policy.
- The runtime health endpoint, capture, OCR/vision services, Gate, and Trace writer are available.
- The selected job passed complete-detail review and the Agent suitability decision.
- `--read-only-inventory` is present.
- `--cp14-live-uat` is present. It requires the fail-closed Apply-entry preflight.
- `--continuous-session` and `--approve-quick-apply-entry` are present.
- No fill flag is present. In particular, do not pass `--fill-safe-fields` or `--allow-cover-letter-fill`.

## One-Command Run

The command below includes explicit Apply-entry approval. Do not run it until that approval has been given for the current live job.

```powershell
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
uv run python scripts\seek_speed_demo_runner.py `
  --run-dir "logs\uat\seek_read_only_inventory_$stamp" `
  --continuous-session `
  --approve-quick-apply-entry `
  --cp14-live-uat `
  --read-only-inventory `
  --max-jobs 5 `
  --time-budget-ms 300000
```

## Expected Stop

Before `execute_apply_entry`, the run must write `cp14_apply_preflight.json` with `status=pass`. The preflight requires Runtime `/health`, the shared GPU resource preflight, a running Locate model service, a verified bound window, a fresh non-empty capture, existing Trace/report evidence, a completed Agent match decision, continuous-session mode, read-only inventory mode, and explicit Apply-entry approval. The report records resource mode, recommended batch size, reason codes, and model identity. Unavailable GPU evidence, critical external load, a disallowed model launch, or a non-running Locate service must stop with `stop_reason=cp14_apply_preflight_failed` before the Apply click.

The run must call `continue_application_flow --read-only-inventory` exactly once after entering the application flow. It must then stop with:

- `status=pass`
- `stop_reason=read_only_inventory_complete`
- `live_fill_attempted=false`
- `submit_clicks=0`
- `final_submissions=0`
- `read_only_inventory_report_path` present
- `cp14_preflight_report_path` present in the final run report

Any write attempt changes the checkpoint to `needs_work`; it must not be hidden as a successful read-only run.

## Human Review

Open `read_only_inventory_report.json` and the referenced screenshot/Trace paths. Review these groups separately:

| Group | Expected treatment |
|---|---|
| Ordinary identity/contact fields | Inventory only; no value is typed |
| Unknown or sensitive questions | `needs_user_review` or blocked policy |
| File upload | Unsupported or user review; no file chooser action |
| Continue/Next | Visible evidence only; no click in this checkpoint |
| Submit/Send/Complete/Confirm | Final-action evidence; always zero clicks |

The report may retain field names, question text, policy decisions, value length, and hashes. It must not contain raw candidate PII, planned answers, cover-letter text, or file paths selected for upload.

## Failure Classification

Stop the run and classify the first violated layer:

- `wrong_window_or_stale_capture`
- `model_or_observe_unavailable`
- `application_surface_not_ready`
- `inventory_contract_invalid`
- `raw_pii_leak`
- `unexpected_fill_attempt`
- `unexpected_continue_attempt`
- `unexpected_submit_attempt`
- `trace_or_screenshot_missing`

Fix the shared runtime contract and replay the narrow regression before another live run. Do not add a fallback that continues past a failed inventory or safety check.

## Current Evidence

The independent read-only runner path, redaction/fail-closed behavior, and pre-Apply preflight are covered by automated tests. The offline success rehearsal proves one Apply-entry invocation followed by exactly one `--read-only-inventory` invocation, with no fill, Continue, or submit flags, and retains both preflight and inventory report paths. CP15A preparation is now two-phase: `--prepare-live-safe-fill --prepare-live-safe-fill-field-id <id>` writes a redacted single-field review report and stops; a later approval requires `--approve-live-safe-fill`, the same exact field ID, the reviewed report path, and its SHA-256. Any missing, changed, mismatched, unknown, ambiguous, or post-scroll-mismatched identity stops before type dispatch. CP15A is limited to one field and does not implicitly enable cover-letter filling. A live CP14 inventory has not yet been run, so live inventory coverage remains pending. No live safe fill or final submit was performed while implementing this checkpoint.

The report can be inspected in the existing Learning workflow audit area by expanding `加载单字段执行前预检` and loading its repository-relative path. The panel accepts only redacted `seek_live_safe_fill_preflight_v1` files under `artifacts/` or `logs/` and displays no raw answer. This review does not set approval flags and does not authorize filling, Continue, or submit. If the route is unavailable after an update, restart the runtime rather than treating static-panel rendering as proof that the backend revision is current.
