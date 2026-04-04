---
name: code-implementation-loop
description: Implement and debug code features with a mandatory execution loop. Use when writing or modifying code for applications, APIs, scripts, libraries, automation runtimes, or project scaffolds where the result must be working, not just drafted. Triggers when the user asks to implement a feature, fix a bug, scaffold a project, wire up an endpoint, integrate a dependency, or make code actually run end-to-end.
---

# Code Implementation Loop

Use this skill whenever code must become **working behavior**, not just a plausible patch.

## Core rule

Do not stop after generating code.
Treat code as incomplete until it has been executed, checked, and corrected enough to give reasonable confidence that it works.

Follow this loop:

1. write the code
2. run the code, tests, server, script, or the narrowest executable check available
3. inspect errors, warnings, logs, and incorrect behavior
4. fix the issue
5. repeat until the feature works as expected or a real blocker remains

If execution is not possible, simulate execution by reasoning step by step through runtime behavior and explicitly identify likely failures, but prefer real execution whenever tools allow it.

## Definition of done

A coding task is not done just because:
- files were written
- syntax looks valid
- types look reasonable
- the code “should work” in theory

A coding task is done when one of these is true:
- the feature was actually exercised successfully
- the narrowest meaningful runtime/test check passed
- a real external blocker prevents full execution, and that blocker is clearly reported with evidence

## Required workflow

### 1. Start from the smallest vertical slice

Prefer implementing a thin working path over building broad empty abstractions.

Good:
- make one endpoint really work
- make one command actually run
- make one closed loop succeed end-to-end

Avoid:
- scaffolding many layers with no runtime proof
- adding future abstractions before current behavior works

### 2. Run immediately after changes

After implementing a feature, run the most relevant check you can.
Examples:
- `python -m py_compile ...` for import/syntax sanity
- unit tests for targeted modules
- start the API server and hit the endpoint
- run the CLI command you just added
- run a minimal integration path with sample input

Do not batch many unverified changes if a smaller check is possible.

### 3. Use evidence, not optimism

When checking results, look for:
- tracebacks
- import errors
- runtime warnings
- incorrect JSON shape
- wrong HTTP status
- missing files
- dependency issues
- platform-specific failures
- behavior mismatches against the requested feature

Trust observed behavior over expectations.

### 4. Fix the real failure, then rerun

When something fails:
- identify the concrete failure
- patch the smallest correct surface
- rerun the same check
- only move on after the failing path is revalidated

Do not assume one fix solved nearby issues without rerunning.

### 5. Report execution status honestly

In your user-facing update, say what was actually verified.
Examples:
- “server starts and `/docs` loads”
- “endpoint returns structured JSON”
- “syntax/import check passes, but real OCR not tested yet”
- “blocked by missing dependency on this machine”

Do not blur “written” and “working”.

## Preferred check order

When implementing backend or automation code, use this order when relevant:

1. file-level sanity
   - syntax/import compile
2. module-level sanity
   - direct import or smoke call
3. service startup
   - server/process launches cleanly
4. endpoint/command behavior
   - actual request/response or CLI execution
5. feature-path behavior
   - the intended scenario succeeds

## Scope control

Prefer the smallest check that proves the feature.
Do not run huge test suites if a focused smoke test is enough for the current change.
But do not skip runtime checks just because a smaller syntax check passed.

## For local runtimes and APIs

When working on services such as FastAPI apps, automation runtimes, tool servers, or local agents:

- verify the app imports cleanly
- start the server when possible
- hit the changed endpoint
- inspect the returned payload shape
- verify required routes are registered
- verify startup does not crash because of imports or config assumptions

## For automation and GUI code

When working on GUI automation, window control, OCR, or input dispatch:

- verify the code path that can be checked locally right now
- separate “API works” from “real automation works”
- if runtime environment limits full GUI verification, say exactly which layer was verified:
  - import only
  - route only
  - window binding only
  - screenshot only
  - full click loop

Do not claim end-to-end automation if only the API wrapper was tested.

## For dependency changes

When adding a dependency:
- update project files
- install/sync if possible
- rerun startup/import checks
- confirm the dependency is actually importable where used

## Failure reporting rule

If you cannot get the feature fully working, end with:
- what was implemented
- what was actually tested
- what failed
- what blocker remains
- what the next smallest step should be

This is acceptable.
Pretending draft code is done is not.

## Output style

Keep updates concrete.
Prefer:
- what changed
- what you ran
- what happened
- what you fixed
- current status

Avoid vague claims like:
- “should work now”
- “completed” without execution evidence
- “done” when only scaffolding exists

## Bottom line

The goal is **working code with evidence**.
Not merely code generation.
