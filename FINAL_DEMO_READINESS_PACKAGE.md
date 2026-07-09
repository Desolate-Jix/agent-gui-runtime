# Final Demo Readiness Package

Last updated: 2026-07-02.

## Project Position

This project is a benchmark-driven Windows GUI Agent Runtime with a SEEK no-submit MVP scaffold. It supports traceable action planning, safety gating, benchmarked point-grounding evidence, final-submit guard fixtures, safe-fill policy fixtures, a display-only Learning Draft Review workspace, and model-learning template validation.

It does not claim live safe-fill reliability, live submission, stable SEEK end-to-end automation, or model accuracy from template-similarity scores.

## One-Command Benchmark Rerun

```powershell
uv run python scripts\run_seek_mvp_benchmark.py `
  --manifest artifacts\benchmarks\seek_mvp_golden_manifest_v1.json `
  --out logs\benchmarks\seek_mvp_final_scaffold `
  --no-submit `
  --json
```

Latest SEEK scaffold report:

```text
logs\benchmarks\seek_mvp_final_scaffold\seek_mvp_benchmark_report.json
```

Latest model-learning final validation report:

```text
logs\benchmarks\model_learning_feedback_loop_final\feedback_report.json
```

Latest controlled live no-submit smoke summary:

```text
logs\smoke\seek_live_no_submit_checkpoint6\checkpoint6_live_smoke_summary.json
```

## Key Metrics To Show

Use these as layered evidence, not as one combined success rate.

| Area | Current evidence | Interpretation |
| --- | --- | --- |
| SEEK manifest | 40 cases | Offline benchmark scaffold size. |
| Point grounding | `point_grounding_success` is fixture-covered with `coverage_status=minimum_categories_covered` and `reliability_status=insufficient_sample_size` | Point-quality evidence only; not reliability or E2E success. |
| Gate safety | `gate_rejected_click` records safe intercept evidence | Wrong or unsafe point was rejected before execution. |
| Safe fill | `safe_fill_fixture` is fixture-only; live `safe_fill` remains `not_covered` | Field-policy checks exist, but no live form filling is proven. |
| Final submit guard | Fixture coverage for submit-like buttons | Not live submit coverage. |
| Model learning | Selected config remains baseline in final dev/holdout validation | Feedback harness works, but no accepted model-ability improvement. |
| Live no-submit smoke | One controlled run opened/captured SEEK results and extracted cards | Safe live trace only; it did not cover detail/apply/external ATS. |

## Invalid And Not Covered

- Invalid fixtures do not enter pass/fail denominators.
- `seek_point_grounding_missed_failure` remains `invalid_point_grounding_fixture / evidence_missing`.
- `not_covered` means no valid attempt exists for that layer; it must not be displayed as a pass.
- Live safe fill is still `attempted=0 / rate=not_covered`.
- CP6 live smoke did not cover job detail opening, Apply entry, external ATS, login blocker, final submit visible blocker, or live safe fill.

## No-Submit Safety Policy

- Benchmark and demo commands use no-submit boundaries.
- Final submit / send / complete / confirm / payment actions remain hard-blocked unless the user explicitly approves the exact live action.
- Safe-fill fixture values must be redacted or represented only by hash/length evidence.
- Fixture results do not authorize live filling, uploading, account creation, privacy consent, or final submit.
- Real clicks must go through the gated action API and produce trace evidence.

## Fixture-Covered vs Live-Covered

Fixture-covered:

- read terminal-state classifiers
- scroll-effect classifiers
- external ATS/login safe-stop chain
- final-submit guard fixtures
- point-grounding evidence categories
- safe-fill field-policy fixtures

Live-covered in the final package:

- one controlled SEEK results-page observation trace
- card extraction on a live SEEK page
- no-submit/no-fill/no-upload counters

Not live-covered:

- live safe fill
- live final submit
- live file upload
- live sensitive-field handling
- live Apply-entry/external-ATS blocker in CP6

## Learning Draft Review Workspace

The Learn Replay panel can display a raw `learning_template_draft_v1` in a template-like layout. The reviewer can save a `reviewed_template_candidate.json` without editing JSON or Markdown manually.

Saved review candidates are still display/review-only:

- `counts_as_pure_model_generated=false`
- `artifact_is_authorization=false`
- `execute_binding_enabled=false`
- `authorization_scope=display_and_review_only`
- `final_submit_forbidden=true`

This supports interview/demo review. It is not Execute authorization and not proof that the model learned a production-ready template.

## What Not To Claim

Do not claim:

- 90% model accuracy
- SEEK E2E stable
- live safe-fill reliability
- live submit coverage
- fixture pass equals live pass
- template similarity equals click success
- safe stop equals completed application flow
- CP6 covered Apply entry or external ATS login blocker

## Interview Summary Draft

I built a local Windows GUI Agent Runtime organized around an Agentic Loop: the Agent decides intent, Operation observes and acts, Gate enforces safety, Trace records evidence, and learned Workflow/PathGraph assets guide but do not authorize actions.

The project uses SEEK as a no-submit MVP scaffold. Instead of claiming production automation, it builds a replayable benchmark: layered metrics, fixed manifests, checksum-stable fixtures, point-grounding evidence, final-submit guard fixtures, safe-fill policy fixtures, invalid-fixture handling, and explicit not-covered reporting.

The learning layer separates raw model drafts from executable assets. Model drafts can be shown in the panel, reviewed by a human, and saved as assisted candidates, but they do not become executable templates without validation. The current model-learning feedback loop has dev/holdout separation, leakage audits, source tracking, and hard safety gates; it does not yet prove general model-generated template ability.

The final demo should show the benchmark scaffold, Learning Draft Review workspace, trace evidence, no-submit policy, and known limitations rather than pretending the system is a finished job-application bot.

## Recommended Next Work

1. Add more independent point-grounding fixtures before making reliability claims.
2. Add more model-generated dev/holdout cases from non-SEEK surfaces.
3. Expand safe-fill fixtures before any live single-field smoke.
4. Add a second reviewer-approved live no-submit smoke only if the final demo specifically needs Apply-entry evidence.
5. Keep final submit hard-blocked unless the user explicitly approves one exact live final-submit action.
