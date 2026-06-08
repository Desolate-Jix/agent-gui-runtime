# AGENTS.md

## Scope

These instructions apply to the repository root `D:\agent-gui-runtime`.

## Required Workflow

When implementing or modifying code, follow the execution loop defined in:

- `skills/code-implementation-loop/SKILL.md`

That means:

1. make the smallest meaningful change
2. run the narrowest relevant verification
3. inspect the result
4. fix failures
5. rerun until the path is verified or a real blocker remains

Do not stop at draft code when a runtime or smoke check is possible.

## Code Search / Context Gathering Rule

To reduce token usage and repeated file reads, prefer codegraph before raw text search when understanding code structure.

Use codegraph first for:

- architecture, flow, and "how does X reach Y" questions
- locating symbols, definitions, callers, or callees
- planning edits that depend on how several functions or files connect
- understanding an area before changing code

Use `rg` or direct file reads after codegraph only when:

- confirming exact lines or nearby implementation details
- checking plain text that codegraph does not index well
- verifying generated files, docs, configs, or non-code assets

If codegraph is unavailable or stale for the files being changed, fall back to `rg` and record that assumption when it matters.

## Documentation Sync Rule

When code changes affect behavior, API shape, architecture, progress, or known limitations, update documentation in the same work session.

At minimum, review and update the relevant files:

- `README.md`
- `PROJECT_SUMMARY.md`
- `ARCHITECTURE.md`
- `CURRENT_STATE.md`
- `NEXT_STEPS.md`
- `OPENCLAW_RECOVERY.md` when recovered OpenClaw history or migration notes change

For bilingual design docs, keep both language versions in sync in the same work session:

- `RUNTIME_STATE_GRAPH.md`
- `RUNTIME_STATE_GRAPH.zh-CN.md`

Update only the files impacted by the change, but do not leave `README.md` stale when public behavior changed.

## Definition Of Done

A code task is not done unless both are true:

- the changed path was verified with the narrowest meaningful check available
- the affected documentation was brought back in sync

If full execution is blocked, record:

- what changed
- what was verified
- what remains blocked
- what document state was updated despite the blocker

## Error Handling

Errors must be clear and actionable. Do not hide failures.

Prefer:

- explicit validation with meaningful exception messages
- structured error responses (`APIResponse` + `ErrorModel`)
- safe fallback only when justified

Avoid:

- broad `except Exception` without handling
- returning `None` for unknown failure
- logging only without surfacing failure
- pretending success when an operation failed

## GUI Agent Safety

Safety is more important than speed.

Before executing actions:

- verify target window
- verify target element
- verify coordinates
- verify confidence
- reject ambiguous actions

Every click action must produce evidence:

- input goal → screenshot or OCR evidence → selected candidate → confidence score → click point → pre-click decision (`pre_click_decision_v1`) → post-click verification

Do not click when:

- target is ambiguous
- candidate score gap is too small
- OCR / local evidence disagrees with vision model
- click point is outside target bbox
- action could be destructive
- validation is unavailable for a risky action

Prefer controlled refusal over unsafe execution. All real clicks must go through the gated action API (`POST /action/execute_recognition_plan`).

## Response Format

After finishing a task, summarize:

### Changed

- concise list of what changed

### Tested

- commands actually run and their results

### Notes

- assumptions made
- limitations
- recommended next step

Do not claim something works if it was not verified.

## Notes

- The summary/recovery docs are intentionally `.gitignore`d in this repo, but they still must be kept up to date locally.
- Prefer evidence-based status notes over optimistic summaries.
