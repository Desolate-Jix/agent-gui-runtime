# Project Closeout And Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an evidence-backed project closeout package and a repeatable demo showing that human-corrected learning artifacts can become Agent operational memory, connect across changing interface states, and safely complete a SEEK Quick Apply flow up to but never including final submission.

**Architecture:** Keep the current panel as the engineering and debugging workbench. Add only a bounded presentation view for demonstrations; define the future user settings interface as a separate product surface. Closeout evidence is organized around the real system layers: Agent decision, Workflow orchestration, Operation/Skills, Gate safety, Trace audit, and reviewed Memory/Learning artifacts.

**Tech Stack:** FastAPI, vanilla HTML/CSS/JavaScript panel, Python/pytest, local Qwen3-VL/VISTA services, Windows window capture/input runtime, JSON artifacts and Trace.

## Global Constraints

- Do not describe draft-reference alignment, fixture assertions, safe-stop, or dispatch success as model accuracy or end-to-end reliability.
- Every reported metric must include its denominator; `attempted=0` is `not_covered`.
- Learning artifacts and historical coordinates are never execution authorization.
- Every execution acceptance case must use a current capture, current localization, Gate, Trace, and post-action verification.
- Final submit, send, confirm, delete, purchase, and payment remain blocked.
- SEEK job suitability must be decided from the complete current job detail by the Agent. Local title/company/classification keyword pruning is forbidden.
- The continuous SEEK demo handles SEEK-hosted Quick Apply only. External ATS or external login surfaces must safe-stop the current application path.
- Every interface transition requires a new current capture and state match. A learned interface memory may guide current localization but may not carry coordinates across states.
- An unknown interface pauses the same task session for Learning Mode and human review; publishing reviewed memory may resume that session.
- Local screenshots, traces, PII, model outputs, and runtime state remain ignored by Git unless explicitly privacy-reviewed as fixtures.
- The development panel remains available; presentation simplification must hide tools, not delete debugging capability.
- The future user settings interface is a separate surface and is not required to complete the current closeout.

---

### Task 1: Freeze The Final Claim Boundary

**Files:**
- Create: `docs/final/FINAL_SCOPE.md`
- Modify: `README.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Consumes: current architecture, current test evidence, current real-action traces.
- Produces: one authoritative statement of what the project proves, does not prove, and leaves for later.

- [ ] **Step 1: Write the claim inventory**

List every public claim under exactly four headings:

1. `verified_now`
2. `fixture_covered`
3. `partially_covered`
4. `not_covered`

The verified-now section must include the reviewed-memory Execute loop. General recognition accuracy and unattended operation must remain outside it.

- [ ] **Step 2: Audit misleading wording**

Run:

```powershell
rg "accuracy|success rate|E2E stable|90%|live safe fill|unattended" README.md PROJECT_SUMMARY.md ARCHITECTURE.md CURRENT_STATE.md NEXT_STEPS.md docs
```

Classify each match as an explicit prohibition, historical correction, compatibility field, or misleading current claim. Rewrite only the misleading current claims.

- [ ] **Step 3: Reconcile the status documents**

Make `FINAL_SCOPE.md` authoritative. `README.md`, `CURRENT_STATE.md`, and `NEXT_STEPS.md` must link to it and must not disagree about Execute coverage, live fill, model ability, or safety.

- [ ] **Step 4: Verify links and UTF-8**

Run a UTF-8 link/path audit and assert that every local evidence path named in `FINAL_SCOPE.md` exists.

- [ ] **Step 5: Checkpoint review**

Stop and report the final claim table. Do not continue until the user accepts the boundary.

---

### Task 2: Create A Concise Final Project Summary

**Files:**
- Create: `docs/final/PROJECT_FINAL_SUMMARY.md`
- Create: `docs/final/PROJECT_ITERATION_INDEX.md`
- Modify: `PROJECT_SUMMARY.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `FINAL_SCOPE.md`, architecture contracts, milestone history.
- Produces: a two-to-four-page reviewer summary plus a separate historical index.

- [ ] **Step 1: Write the one-sentence objective**

Use this product-level objective:

> Learn a GUI once with machine assistance and low-cost human correction, publish the reviewed result as reusable Agent operational memory, and safely reuse it against the current interface to reduce repeated daily work.

- [ ] **Step 2: Summarize the actual architecture**

Describe these layers without inventing a separate Goal layer:

1. Agent: dialogue, task decomposition, and decisions.
2. Workflow: lifecycle and stage ownership.
3. Operation/Skills: observe, locate, click, type, scroll, and verify.
4. Gate: action safety and current-evidence checks.
5. Trace: evidence, replay, diagnosis, and audit.
6. Memory/Learning: draft, human correction, reviewed memory, and execution feedback.

- [ ] **Step 3: Separate current state from chronology**

Keep `PROJECT_FINAL_SUMMARY.md` focused on current behavior, evidence, limitations, and next work. Move the long milestone list into `PROJECT_ITERATION_INDEX.md` or link to the existing chronological archive.

- [ ] **Step 4: Add an evidence table**

For every major claim, include:

| Claim | Scope | Evidence type | Trace/test path | Limitation |
|---|---|---|---|---|

No row may rely only on prose.

- [ ] **Step 5: Checkpoint review**

Ask a reviewer to explain the project back in five sentences. Revise any section they misunderstand.

---

### Task 3: Produce The Final Architecture Audit

**Files:**
- Create: `docs/final/ARCHITECTURE_AUDIT.md`
- Modify: `ARCHITECTURE.md`
- Review: `RUNTIME_STATE_GRAPH.md`
- Review: `RUNTIME_STATE_GRAPH.zh-CN.md`

**Interfaces:**
- Consumes: current code paths and state contracts.
- Produces: a code-to-document audit of the real learning, review, memory, and Execute dataflow.

- [ ] **Step 1: Trace the complete dataflow from code**

Verify:

```text
bind/capture
-> screen understanding
-> numbered map
-> precise calibration
-> model review/repair
-> fusion
-> human bbox correction
-> reviewed candidate
-> operational memory publish
-> natural-language action resolution
-> current capture/localization
-> Gate
-> low-risk dispatch
-> post-action verification
-> Trace or human-review feedback
```

- [ ] **Step 2: Audit ownership boundaries**

For each transition, record which layer owns it and which layer is forbidden from authorizing it. Confirm that Workflow controls lifecycle while Agent controls decisions.

- [ ] **Step 3: Audit freshness**

Confirm capture ID, viewport, source, bbox, click point, and freshness remain current through Execute. Confirm historical geometry is prior evidence only.

- [ ] **Step 4: Audit bilingual state-graph consistency**

If the runtime graph changed, update both state-graph documents in the same checkpoint.

- [ ] **Step 5: Checkpoint review**

The architecture checkpoint passes only when every diagram arrow maps to a concrete API, artifact, or function.

---

### Task 4: Run Functional Closeout Acceptance

**Files:**
- Create: `docs/final/FINAL_ACCEPTANCE_MATRIX.md`
- Create: `scripts/run_final_closeout_acceptance.py`
- Create: `tests/test_final_closeout_acceptance.py`
- Modify: `CURRENT_STATE.md`

**Interfaces:**
- Consumes: stable test fixtures, reviewed memories, safe live targets.
- Produces: a machine-readable report and a reviewer-facing acceptance matrix.

- [ ] **Step 1: Define three representative surfaces**

Use:

1. SEEK results/detail for the learned job-card path.
2. Python.org for a low-risk non-SEEK browser action.
3. One Windows application for learning, correction, and memory publication; real click is optional unless a clearly harmless action is available.

- [ ] **Step 2: Measure the learning-to-usable-memory path**

Report per case:

- meaningful regions recalled before review
- manual additions, deletions, moves, resizes, relabels
- correction time
- save/reload consistency
- page-detail and read-only PathGraph regeneration
- publish result
- Agent action resolution result

Use `time_to_usable_memory` and `manual_edits_to_pass`; do not publish a single recognition score.

- [ ] **Step 3: Exercise safe Execute**

For SEEK and Python.org:

1. dry-run first
2. confirm current OCR/VISTA/rerank evidence
3. confirm Gate result
4. execute one low-risk action
5. confirm post-action verification
6. save Trace

- [ ] **Step 4: Exercise failure return**

Run changed-layout, wrong-surface, missing-anchor, and ambiguous-action cases. Each applicable case must safe-stop and create feedback that points to the reviewed candidate and stable element.

- [ ] **Step 5: Fix the stale committed fixture**

Repair `tests/fixtures/learning_practical_targeted_rerun_manifest_v1.json` using the original checksum-matching QQ screenshot moved into a privacy-reviewed fixture location. If the original evidence cannot be recovered, mark the case invalid and replace it with a newly frozen case; never substitute a different screenshot under the old checksum.

- [ ] **Step 6: Run regression**

Run:

```powershell
uv run pytest tests/test_final_closeout_acceptance.py -q
uv run pytest tests/test_reviewed_interface_memory.py tests/test_reviewed_interface_memory_execution.py -q
uv run pytest tests/test_final_submit_guard_fixtures.py -q
uv run pytest tests -q
```

The final checkpoint requires zero unexplained failures.

- [ ] **Step 7: Checkpoint review**

Report every attempted, passed, failed, invalid, safe-stopped, and unsafe-prevented case separately.

---

### Task 5: Complete The Safety And Privacy Audit

**Files:**
- Create: `docs/final/SAFETY_PRIVACY_AUDIT.md`
- Modify: `.gitignore`
- Review: `app/gate/`
- Review: `app/api/action.py`
- Review: `app/agent/reviewed_interface_memory.py`

**Interfaces:**
- Consumes: action taxonomy, Gate decisions, traces, repository status.
- Produces: a threat-oriented audit with reproducible safety evidence.

- [ ] **Step 1: Audit action classes**

Confirm independent handling of `open_detail`, `open_apply_flow`, `fill_field`, `continue_next_step`, and final submit/send/confirm/payment actions.

- [ ] **Step 2: Audit current-target evidence**

Confirm wrong-surface and local-target mismatch stop before dispatch. Confirm successful planning exposes current local-target evidence.

- [ ] **Step 3: Audit final-submit fixtures**

Re-run all final-submit vocabulary and context fixtures. `Apply now` must remain allowed only as an entry action and blocked in final-review context.

- [ ] **Step 4: Audit privacy**

Search committed files and generated reports for raw email, phone, names, addresses, CV paths, cookies, tokens, screenshots, and model prompts. Retain only redacted preview, hash, length, field name, and policy decision where applicable.

- [ ] **Step 5: Audit Git hygiene**

Run:

```powershell
git status --short
git ls-files artifacts logs runtime_state
git check-ignore -v artifacts logs runtime_state
```

No local runtime output may remain tracked unintentionally.

- [ ] **Step 6: Checkpoint review**

Require zero unresolved high-risk or privacy findings before demo sign-off.

---

### Task 6: Prepare A Bounded Presentation View

**Files:**
- Modify: `app/web_panel/index.html`
- Modify: `app/web_panel/panel.css`
- Modify: `app/web_panel/panel.js`
- Modify: `tests/test_web_panel_route.py`
- Modify: `tests/js/learning_draft_editor.test.cjs`
- Create: `docs/final/DEMO_GUIDE.md`

**Interfaces:**
- Consumes: existing development-panel controls and workflow state.
- Produces: a presentation view that hides diagnostics without removing them.

- [ ] **Step 1: Freeze the development-panel boundary**

The existing panel remains the engineering workbench. Do not delete model controls, artifact paths, Trace tools, or diagnostics.

- [ ] **Step 2: Add a presentation-view switch**

Presentation view exposes only:

1. choose and bind interface
2. learn interface
3. review/edit result
4. publish and test Agent memory

The nine backend stages remain visible as a compact progress summary, not nine user decisions.

- [ ] **Step 3: Make the primary action state-driven**

Show one primary command at a time:

```text
Bind and capture
Start learning
Review detected interface
Save correction
Publish memory
Preview action
Confirm low-risk execution
```

- [ ] **Step 4: Keep diagnostics accessible**

Advanced mode restores the full current panel without data loss or reload.

- [ ] **Step 5: Test both views**

Assert that presentation view hides development controls, Advanced mode reveals them, and workflow state/results remain identical.

- [ ] **Step 6: Checkpoint review**

Give the presentation view to a person who has not seen the project. They should complete the safe demo without being told which internal artifact button to press.

---

### Task 7: Specify The Separate User Settings Surface

**Files:**
- Create: `docs/final/USER_SETTINGS_INTERFACE_SPEC.md`

**Interfaces:**
- Consumes: runtime configuration and safety requirements.
- Produces: a later product-interface specification; no current runtime behavior.

- [ ] **Step 1: Define user-owned settings**

Include only:

- language
- model/resource preference
- action permission policy
- operational memory list and deletion
- data retention/privacy
- Trace export
- confirmation requirements

- [ ] **Step 2: Define exclusions**

Exclude raw artifact paths, model protocol controls, calibration batches, scaffold generation, parser internals, and benchmark tooling.

- [ ] **Step 3: Define the API boundary**

Every setting must map to an existing runtime contract or be explicitly marked as a future API. The settings page must never bypass Gate.

- [ ] **Step 4: Review scope**

Keep this document as post-closeout product work unless a missing setting blocks the demonstration.

---

### Task 8: Connect The Continuous SEEK Quick Apply Demo

**Files:**
- Modify: `scripts/seek_speed_demo_runner.py`
- Create: `app/agent/continuous_task_session.py`
- Create: `tests/test_continuous_task_session.py`
- Modify: `tests/test_seek_speed_demo_runner.py`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Consumes: reviewed interface memories, complete SEEK detail snapshots, Agent match decisions, application form inventory, answer plans, Gate decisions, and post-action verification.
- Produces: one resumable task session spanning results, detail, Quick Apply steps, questions, and final-review safe-stop.

- [x] **Step 1: Remove local keyword pruning**

Every visible job card remains eligible for detail reading. `summer`, `internship`, `senior`, `manager`, and similar words cannot cause a local skip. The Agent receives the complete detail snapshot and makes the suitability decision.

- [x] **Step 2: Define the continuous-session contract**

The initial contract covers:

```text
known interface -> Agent decision
unknown interface -> pause for learning and human review
reviewed memory published -> resume the same task session
Quick Apply entry -> explicit confirmation boundary
verified action -> observe the next current interface
external ATS -> safe_stop
final submit visible -> safe_stop
```

The contract preserves current-capture, Gate, post-action verification, and final-submit prohibition.

- [x] **Step 3: Bind the session contract to the real SEEK runner**

Persist the session under its run directory. Each state change records current screenshot identity, matched reviewed memory state, Agent decision, selected action, Gate summary, post-action verification, and resulting interface state. Focused runner tests cover this binding.

- [x] **Step 4: Resume after learning (backend/CLI contract)**

When a Quick Apply step has no reviewed memory, pause without filling or continuing. Matching memory publication plus `--resume-continuous-session` resumes the original run directory without reopening SEEK.

- [x] **Step 4a: Connect the panel handoff**

The Learning Draft view loads the checksum-verified paused screenshot and pending interface without operating the target app. Reviewed-memory publication refreshes the handoff. One explicit Resume control starts the same run only after the screenshot, Quick Apply checkpoint, paused session, and matching active-memory gates pass.

- [ ] **Step 5: Use structured answers only**

Answer deterministic questions only from the approved candidate profile or answer memory. Unknown, sensitive, complex visa, salary, relocation, health, disability, criminal-history, or unsupported upload fields require review. Never invent an answer.

- [x] **Step 6: Stop at the final boundary (offline runner evidence)**

The successful terminal Demo state is:

```text
status=safe_stop
stop_reason=final_submit_visible
final_submissions=0
submit_clicks=0
```

`Apply now` is allowed only as a scoped application-flow entry and blocked in final-review context.

- [ ] **Step 7: Verify with offline and live no-submit evidence**

First replay fixtures for known state, unknown-state learning pause/resume, external ATS, sensitive question, and final-submit guard. Then run one bounded live SEEK Quick Apply smoke. Do not submit.

Checkpoint evidence: `logs/smoke/seek_continuous_live_confirmation_20260727` verifies the live recommendations-to-detail-to-Agent-decision path and stops at explicit Quick Apply confirmation with zero submit clicks. The panel renders the current screenshot and confirmation action. The button has not been clicked, so the post-confirmation learning pause and final-review safe-stop remain open.

- [ ] **Step 8: Checkpoint review**

The checkpoint passes only when the report shows the complete state timeline, every transition has current evidence, no local keyword filter was used, and the final action was prevented.

---

### Task 9: Assemble The Final Demo And Reviewer Pack

**Files:**
- Create: `docs/final/DEMO_GUIDE.md`
- Create: `docs/final/REVIEWER_CHECKLIST.md`
- Create: `docs/final/EVIDENCE_INDEX.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: accepted scope, summary, architecture audit, acceptance report, and safety audit.
- Produces: the final interview/demo package.

- [ ] **Step 1: Write a six-minute demo script**

Use this order:

1. explain the repeated-work problem
2. learn a current interface
3. show imperfect automatic recognition
4. correct one visible mistake
5. publish the reviewed memory
6. ask the Agent to perform a natural-language low-risk task
7. show current re-grounding, Gate, execution, and Trace
8. show a stale-memory safe-stop

- [ ] **Step 2: Prepare evidence fallback**

Keep original screenshot, reviewed overlay, page details, PathGraph, successful Trace, safe-stop Trace, and post-action screenshot ready in case a model service is slow during the interview.

- [ ] **Step 3: Write the reviewer checklist**

The reviewer must separately decide:

- architecture coherence
- workflow ownership
- correction usability
- memory usefulness
- Execute freshness
- safety behavior
- Trace completeness
- claim accuracy
- demo usability

- [ ] **Step 4: Rehearse twice**

Run one normal rehearsal and one failure rehearsal. Record elapsed time, manual interventions, model wait time, and every unexpected panel state.

- [ ] **Step 5: Final sign-off**

The project is demo-ready only when:

- SEEK and non-SEEK low-risk loops remain reproducible
- one stale/changed case visibly safe-stops
- no dangerous action occurs
- all named evidence exists
- no unexplained test failure remains
- the presentation view can be followed without internal artifact knowledge
- documentation makes no unsupported reliability claim

---

## Recommended Checkpoint Order

1. Claim boundary and concise project summary.
2. Architecture and dataflow audit.
3. Functional acceptance and stale-fixture repair.
4. Safety, privacy, and Git hygiene audit.
5. Continuous SEEK Quick Apply integration.
6. Presentation view.
7. Demo rehearsal and final reviewer sign-off.

## Estimated Effort

- Documentation and claim audit: 0.5-1 day.
- Architecture/evidence audit: 0.5-1 day.
- Functional, continuous-session, and safety acceptance: 2-3 days, depending on model availability and whether a live Quick Apply sample is available.
- Presentation view: 1-2 days.
- Rehearsal and final corrections: 0.5-1 day.

Expected total: 5-7 focused working days without expanding recognition features or building the separate user settings page.
