# Agent Onboarding

This document is the short entry point for another agent that needs to use this Windows GUI automation runtime.

## Core Idea

Learn Mode turns an interface into a reusable map.

Execute Mode uses the current screenshot, learned PathGraph, local evidence, and gated action APIs to perform one step at a time.

The upper agent owns task planning. This runtime owns evidence, coordinates, safety checks, execution, and trace output.

## Required Reading Order

1. `AGENT_API_WORKFLOW.md`
2. `docs/AGENT_EXECUTION_PROTOCOL.md`
3. `docs/AGENT_LEARN_MODE_TUTORIAL.md`
4. `docs/AGENT_TRACE_DEBUG_GUIDE.md`

For SEEK-specific work, also read:

5. `skills/seek-high-precision/SKILL.md`

## Non-Negotiable Rules

- Do not click from raw model coordinates.
- Do not use old hard-coded coordinates after a window resize, tab switch, scroll, or page transition.
- Do not bypass `pre_click_decision_v1`.
- Do not treat a learned artifact as authorization. Artifacts guide execution; they do not approve actions.
- Do not click final submit, purchase, delete, send, save changes, or irreversible actions unless the user explicitly approves that exact live action.
- Do not add fallback behavior before identifying the failing layer with trace, log, screenshot, or OCR evidence.
- Every real click, scroll, and input must leave trace evidence.

## Runtime Address

Default local runtime:

```text
http://127.0.0.1:8000
```

Panel:

```text
http://127.0.0.1:8000/panel
```

The panel is for operators. External agents should prefer API calls and use the panel/trace only for inspection.

## Minimal Execute Loop

```text
bind target window
-> capture / observe current state
-> get available actions or locate one target
-> dry-run / preview when available
-> inspect candidate, bbox, overlay, and gate
-> execute exactly one low-level action through the runtime
-> inspect post-action verification and trace
-> decide the next step
```

Execute Mode is intentionally single-step. A multi-step task is a loop in the upper agent, not one giant runtime call.

## Minimal Learn Loop

```text
bind target window
-> Learn Fast: observe full screen and draft PathGraph
-> Learn Deep: calibrate child nodes, boxes, names, and missing/duplicate controls
-> export or load learned artifact
-> validate safe actions
-> use Execute Mode to consume the artifact one step at a time
```

Learn Mode is allowed to be slower and more complete. Execute Mode must stay fast, scoped, and evidence-driven.

## What To Return To The User

After a task, report:

- what was attempted
- which window/page was bound
- which actions were executed
- trace paths and important screenshot paths
- extracted records or decisions
- failures and exact failing layer
- safety counters, especially final submissions or destructive actions

Never claim a task succeeded if the trace or post-action verification does not prove it.

