# Agent Execution Protocol

This protocol is for an upper-layer agent using `agent-gui-runtime` as a GUI execution kernel.

## Role Split

The upper agent:

- interprets the user goal
- chooses the next action
- reads runtime evidence
- decides whether to continue, stop, ask the user, or learn more

The runtime:

- binds windows
- captures screenshots
- runs OCR / model / PathGraph lookup
- generates candidates and overlays
- gates clicks, scrolls, and input
- writes traces

## Session Setup

1. Start or verify the runtime.
2. Bind the target external application/window.
3. Verify the bound window title, process, size, and screenshot.
4. Keep the Codex in-app browser reserved for ChatGPT consultation unless no external browser/window control is available.

Useful operator panel:

```text
http://127.0.0.1:8000/panel
```

## API-First Execute Flow

### 1. Understand Current State

Use one of:

```http
POST /vision/observe_screen
POST /execute/available_actions
POST /state/capture_window
```

Expected evidence:

- current screenshot path
- state hint
- visible controls or PathGraph actions
- scroll containers if relevant

### 2. Choose One Action

A selected action must include:

- goal
- expected target
- target container or region when relevant
- allowed low-level action type: click, scroll, input, or read
- safety constraints

Do not execute a list of actions in one request. Pick one.

### 3. Preview / Dry Run

For recognition clicks, run the preview path first when possible. Inspect:

- candidate list
- selected bbox
- selected click point
- coordinate source
- overlay image
- OCR / local grounding evidence
- `pre_click_decision_v1`

If the gate rejects, fix the primary failing layer first. Do not bypass the gate.

### 4. Execute One Low-Level Action

Use the runtime action endpoint matching the selected action:

```http
POST /action/execute_recognition_plan
POST /action/scroll
POST /action/type_text
POST /execute/step
```

Rules:

- Real clicks must go through gated execution.
- Real scrolls must name the intended scroll scope/container when known.
- Real input must use safe-field evidence and must not submit unless explicitly approved.
- `/execute/step` may dispatch exactly one generated low-level action when `dispatch_low_level=true`.
- Low-risk navigation clicks, such as opening a card/result row/title/detail link for reading, may be allowed after grounding even when the learned source was originally `safe_dry_run_only`.
- Apply, Quick apply, Submit, Delete, Pay, Purchase, Send, Save changes, Upload, and other side-effect actions are not low-risk navigation and must stop unless explicitly approved.

### 5. Verify And Continue

After the action, read:

- API response
- trace path
- screenshot path
- post-click/post-scroll/post-input verification
- updated state
- no-progress or wrong-scope markers

Then decide the next step. Continue only if the current result proves progress.

## Stop Conditions

Stop and report when:

- target window is not bound or changed unexpectedly
- screenshot does not match the intended app/page
- target is ambiguous
- candidate score gap is too small
- OCR/local evidence disagrees with the selected candidate
- click point is outside bbox
- scroll target is wrong or content repeats
- login, captcha, permission prompt, or rate limit appears
- destructive/final-submit action is visible
- verification is unavailable for a risky action

## Free-Form Task Pattern

For a task such as "find two suitable jobs", the upper agent should run:

```text
task goal
-> observe current page
-> choose one safe action
-> execute one action
-> extract evidence
-> update task memory
-> repeat until done or blocked
-> summarize results and traces
```

The runtime response is not the final answer. It is evidence for the upper agent's next decision.
