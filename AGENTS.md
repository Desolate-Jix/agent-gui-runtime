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

## Root Cause Before Fallback

When a feature fails, fix the primary failure path before adding fallback behavior.

Required order:

1. identify the exact failing layer with trace/log/screenshot evidence
2. fix the broken primary path
3. verify the primary path with the narrowest meaningful check
4. only then add fallback/recovery behavior if it is still useful

Do not add fallback behavior that hides:

- model protocol errors
- model service hangs
- stale or duplicate model processes
- bad JSON/model output contracts
- screenshot/window binding drift
- candidate generation bugs
- coordinate transform bugs

Fallback is acceptable only when the root cause is understood, the primary path remains intact, and the response clearly reports that fallback was used.

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

## ChatGPT Reporting / Consultation Rule

When a task is substantial, architectural, risky, ambiguous, blocked, or explicitly requests outside review, report to or consult a visible ChatGPT web session through the `codex-chatgpt-control` skill/SDK when it is installed and a compatible browser bridge is available.

Use this as a visible, user-directed workflow:

- Treat the Codex in-app browser as reserved for ChatGPT consultation by default. Reuse the default ChatGPT conversation `https://chatgpt.com/c/6a313e9c-e2d4-83e8-b487-83e69eb0ff58` unless the user gives a different session. Do not use the Codex in-app browser as the default test target for the local panel or real website automation; bind an external browser or application window instead. Use the in-app browser for panel testing only when external browser/window control is unavailable and clearly report that exception.
- summarize the current user goal, plan, key evidence, blockers, and proposed next step
- reuse the user's already-open ChatGPT thread when they say one is open
- do not send secrets, credentials, private files, screenshots, traces, or externally sensitive data unless the user approved that specific content
- if the ChatGPT window is already open but `globalThis.agent` / the browser bridge is missing, first attempt to restart or bootstrap the Chrome bridge instead of immediately reporting failure. In `node_repl`, load the Chrome plugin runtime with `setupBrowserRuntime({ globals: globalThis })`, then set `globalThis.browser = await agent.browsers.get("extension")`, rerun the ChatGPT Control doctor/bridge check, and retry the consult once.
- if ChatGPT link/session control fails because the browser bridge, tab handle, or selected session link went stale, run this recovery before giving up:
  1. record the selected ChatGPT conversation URL or session identifier from the current request/context
  2. close the currently controlled ChatGPT tab/window completely through the bridge when possible
  3. restart or re-bootstrap the Chrome bridge and reacquire `globalThis.agent` / `globalThis.browser`
  4. reopen ChatGPT at the selected conversation URL instead of starting an unrelated new chat
  5. run the ChatGPT Control doctor/bridge check, then retry the consult once against that same selected session
  6. if the reopened session hits login, captcha, selector drift, rate limit, permission, or ambiguous confirmation blockers, stop and report the structured blocker
- stop on login, captcha, selector drift, rate limit, upload/download permission, bridge bootstrap failure, or ambiguous confirmation blockers
- report the structured blocker instead of retrying blindly or pretending ChatGPT was consulted

This is a consultation/reporting layer only. It does not replace the local implementation loop, tests, trace evidence, GUI safety gates, or the user's final approval.

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

## UTF-8 / Chinese Text Rule

All recognized Chinese text must be preserved as UTF-8 end to end. Do not introduce mojibake, replacement characters, or question-mark replacement sequences into source code, prompts, traces, tests, docs, or user-facing output.

Rules:

- Read text and JSON with `encoding="utf-8"` or `encoding="utf-8-sig"` when BOM compatibility is needed.
- Write JSON with `ensure_ascii=False` and `encoding="utf-8"` so Chinese remains readable in traces.
- Do not pass Chinese literals through a shell command that may use the Windows ANSI code page. For smoke scripts, prefer `uv run python` with UTF-8 source, a UTF-8 file, or Unicode escapes for test literals.
- If PowerShell output shows mojibake, verify the actual file or payload with Python using `encoding="utf-8"` and `PYTHONIOENCODING=utf-8` before deciding the data is corrupt.
- Never add hard-coded mojibake or replacement-marker literals as matching rules. Match the real Unicode string, use Unicode escapes in tests, or normalize/repair at the boundary with an explicit comment and test.
- Model input/output trace must record the original UTF-8 prompt, OCR text, raw model text, parsed JSON, and parse errors without lossy replacement.
- When a test covers Chinese recognition, assert on the real Chinese value or a Unicode-escaped equivalent, not on console-garbled output.

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
