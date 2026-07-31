# General Form Question Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable, evidence-backed form workflow that can understand changing application questions, ask for review when evidence is insufficient, fill approved answers through the gated execution chain, verify each result, and always stop before final submission.

**Architecture:** Operation inventories the current form and groups each question with its local controls. Agent normalizes each question into a reusable intent and plans an answer from reviewed profile facts, the latest job-detail snapshot, and approved answer policies. Gate classifies the plan as allowed, review-required, sensitive-blocked, unsupported, or final-submit-blocked; Operation then relocates allowed controls from the current capture, executes through the recognition-plan API, and verifies the changed field state. Trace records hashes, lengths, decisions, evidence references, and verification without exposing raw PII.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic/dict contracts already used by the runtime, pytest, existing OCR/UIA/VISTA/rerank pipeline, reviewed interface memory, PathGraph, Gate, and Trace.

## Global Constraints

- Agent owns question understanding, answer planning, and task decisions.
- Operation owns form inventory, current-capture control localization, clicking, typing, and post-action observation.
- Gate owns sensitive-field policy, ambiguity rejection, stale-capture rejection, and final-submit blocking.
- Trace owns evidence and audit records; raw PII must not be written to reports or logs.
- Learned assets and PathGraph are reusable evidence, never execution authorization.
- Every real click must use `POST /action/execute_recognition_plan`.
- Candidate freshness must include `capture_id`, viewport, source, bbox, click point, and freshness.
- Unknown, ambiguous, unsupported, or sensitive questions must stop for user review.
- `final_submit`, `send`, `confirm`, `complete`, and payment actions remain hard-blocked.
- The first live validation is no-submit and stops when final review or final submit becomes visible.
- Existing SEEK modules remain as compatibility adapters until the generic path passes regression tests.

---

### Task 1: Define Generic Question And Answer Contracts

**Files:**
- Create: `app/agent/form_question_contracts.py`
- Create: `tests/test_form_question_contracts.py`
- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`

**Interfaces:**
- Produces: `normalize_question_inventory(payload: dict) -> dict`
- Produces: contract versions `form_question_inventory_v1`, `normalized_form_question_v1`, `form_answer_decision_v1`
- Consumes: current-capture question/control evidence from Operation

- [ ] **Step 1: Write failing contract tests**

Cover required fields for question identity, full UTF-8 text, answer control type, local options, required/optional status, current capture evidence, normalized intent, polarity, confidence, safety class, answer source references, and review status.

- [ ] **Step 2: Run the focused test**

Run: `uv run pytest tests/test_form_question_contracts.py -q`

Expected: FAIL because the generic contracts do not exist.

- [ ] **Step 3: Implement strict normalization**

Reject missing question text, unsupported answer types, missing capture identity, invalid option structures, and decisions without evidence references. Do not accept bbox-only questions as Agent-readable evidence.

- [ ] **Step 4: Rerun the focused test**

Run: `uv run pytest tests/test_form_question_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Update architecture documentation**

Document the boundary between generic form evidence and site adapters. State explicitly that normalized intent is reusable while displayed question text remains current-page evidence.

---

### Task 2: Extract Generic Form Inventory Into Operation

**Files:**
- Create: `app/operation/form_inventory.py`
- Modify: `app/seek/form_inventory.py`
- Create: `tests/test_operation_form_inventory.py`
- Modify: `tests/test_seek_form_inventory.py`

**Interfaces:**
- Consumes: current screenshot, OCR/UIA/vision candidates, active form/modal container, capture metadata
- Produces: `build_form_question_inventory(...) -> dict`
- Preserves: `app.seek.form_inventory` compatibility API

- [ ] **Step 1: Write failing generic inventory tests**

Use fixtures for text input, yes/no radio, single-choice radio, checkbox multi-select, dropdown, textarea, file upload, disabled control, and repeated Yes/No labels in adjacent questions.

- [ ] **Step 2: Add scope and ownership regression tests**

Assert that each answer control belongs to one local question group, duplicate labels are resolved by local proximity, controls outside the active form are rejected, and candidates from stale captures are invalid.

- [ ] **Step 3: Run focused tests**

Run: `uv run pytest tests/test_operation_form_inventory.py tests/test_seek_form_inventory.py -q`

Expected: FAIL on missing generic module.

- [ ] **Step 4: Move reusable inventory logic**

Keep geometry, grouping, and control ownership in Operation. Leave only SEEK surface extraction and compatibility imports in `app/seek/form_inventory.py`.

- [ ] **Step 5: Rerun focused tests**

Run: `uv run pytest tests/test_operation_form_inventory.py tests/test_seek_form_inventory.py -q`

Expected: PASS.

---

### Task 3: Implement Agent Question Understanding

**Files:**
- Create: `app/agent/form_question_understanding.py`
- Create: `tests/test_form_question_understanding.py`
- Modify: `app/seek/employer_questions.py`

**Interfaces:**
- Consumes: `form_question_inventory_v1`
- Produces: `normalized_form_question_v1`
- Keeps: original question text and hash separate from normalized intent

- [ ] **Step 1: Write failing paraphrase tests**

Map differently worded questions into stable intents including `identity`, `contact`, `current_location`, `work_authorization`, `sponsorship`, `experience_duration`, `skill_experience`, `salary_expectation`, `relocation`, `availability`, `role_motivation`, `demographic_optional`, `criminal_history`, `health_or_disability`, and `unknown`.

- [ ] **Step 2: Add polarity and constraint tests**

Verify that “require sponsorship” and “work without sponsorship” preserve opposite polarity, numeric ranges remain constraints, and company-specific names do not become generic intents.

- [ ] **Step 3: Run focused tests**

Run: `uv run pytest tests/test_form_question_understanding.py -q`

Expected: FAIL because the understanding module is absent.

- [ ] **Step 4: Implement layered understanding**

Use reviewed deterministic mappings first, semantic classification second, and `unknown` when confidence or polarity is insufficient. The model may classify intent but may not invent profile facts or answer values.

- [ ] **Step 5: Convert SEEK logic into an adapter**

Remove company-specific answer generation from the generic path. Preserve legacy behavior behind explicit SEEK compatibility functions until Task 8 completes.

- [ ] **Step 6: Rerun focused and compatibility tests**

Run: `uv run pytest tests/test_form_question_understanding.py tests/test_seek_employer_questions.py -q`

Expected: PASS.

---

### Task 4: Build Evidence-Backed Answer Planning

**Files:**
- Create: `app/agent/form_answer_planner.py`
- Create: `app/agent/form_answer_policy_memory.py`
- Modify: `app/agent/reviewed_interface_memory.py`
- Create: `tests/test_form_answer_planner.py`
- Create: `tests/test_form_answer_policy_memory.py`

**Interfaces:**
- Consumes: normalized question, reviewed candidate profile, latest job-detail snapshot, approved answer policies
- Produces: `plan_form_answer(...) -> form_answer_decision_v1`
- Stores: reviewed policies scoped as `global_profile`, `workflow_class`, `site`, or `one_time`

- [ ] **Step 1: Write failing answer-source precedence tests**

Assert precedence: explicit current user confirmation, reviewed scoped policy, reviewed profile fact, latest job-detail evidence, generated open-text draft, otherwise review-required.

- [ ] **Step 2: Add freshness tests**

Assert that open-text answers use the latest job-detail snapshot only and reject stale job-detail evidence from another job.

- [ ] **Step 3: Add negative-feedback tests**

When the user corrects an answer, store the normalized intent, scope, approved value or review policy, evidence hash, and timestamp. Do not store current-page coordinates.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_form_answer_planner.py tests/test_form_answer_policy_memory.py -q`

Expected: FAIL on missing modules.

- [ ] **Step 5: Implement deterministic and generated decisions**

Fixed profile facts may become `ready`. Salary, relocation, ambiguous visa questions, and generated motivation answers default to `needs_user_review` until explicitly approved. Unknown questions never receive demo defaults.

- [ ] **Step 6: Implement redacted persistence**

Store value hashes, lengths, policy decisions, and source references in Trace-facing records. Keep raw values only in the protected reviewed profile or policy memory object.

- [ ] **Step 7: Rerun focused tests**

Run: `uv run pytest tests/test_form_answer_planner.py tests/test_form_answer_policy_memory.py -q`

Expected: PASS.

---

### Task 5: Add Hard Form Safety Policy To Gate

**Files:**
- Create: `app/gate/form_policy.py`
- Modify: `app/gate/danger.py`
- Create: `tests/test_form_policy_gate.py`
- Modify: `tests/test_final_submit_guard_fixtures.py`

**Interfaces:**
- Consumes: answer decision, current form context, action taxonomy, active container
- Produces: `form_action_gate_decision_v1`

- [ ] **Step 1: Write failing safety tests**

Cover allowed reviewed identity/contact fields, review-required salary and relocation, blocked criminal/health/disability questions, unsupported file upload, wrong-surface controls, ambiguous duplicate options, stale candidates, and final-submit vocabulary.

- [ ] **Step 2: Run focused tests**

Run: `uv run pytest tests/test_form_policy_gate.py tests/test_final_submit_guard_fixtures.py -q`

Expected: FAIL on missing generic form policy.

- [ ] **Step 3: Implement policy independent of prompts**

The hard validator must reject sensitive, ambiguous, stale, unsupported, and final-submit actions even if an Agent prompt incorrectly marks them allowed.

- [ ] **Step 4: Rerun focused tests**

Run: `uv run pytest tests/test_form_policy_gate.py tests/test_final_submit_guard_fixtures.py -q`

Expected: PASS.

---

### Task 6: Implement Generic Gated Form Execution And Verification

**Files:**
- Create: `app/operation/form_fill_executor.py`
- Create: `app/operation/form_fill_verification.py`
- Create: `tests/test_form_fill_executor.py`
- Create: `tests/test_form_fill_verification.py`
- Modify: `scripts/seek_debug_step_runner.py`

**Interfaces:**
- Consumes: allowed `form_action_gate_decision_v1`, current recognition candidates, current capture
- Produces: `form_fill_action_result_v1` and a new observed form snapshot
- Executes: only through `POST /action/execute_recognition_plan`

- [ ] **Step 1: Write failing executor tests**

Cover text fill with `clear_existing`, radio click, checkbox multi-click, two-stage dropdown open/select, already-selected value, and unsupported file upload.

- [ ] **Step 2: Write failing verification tests**

Require post-action evidence that the field value, selected option, checked state, or current wizard step changed as expected. Dispatch success alone must not count as fill success.

- [ ] **Step 3: Run focused tests**

Run: `uv run pytest tests/test_form_fill_executor.py tests/test_form_fill_verification.py -q`

Expected: FAIL on missing modules.

- [ ] **Step 4: Implement one-action-at-a-time execution**

For every action: observe, relocate, Gate, execute, Trace, observe, verify. Abort the remaining batch on stale capture, failed verification, wrong surface, or unexpected navigation.

- [ ] **Step 5: Replace debug-runner direct execution**

Make `scripts/seek_debug_step_runner.py` call the generic executor. Keep its CLI contract compatible, but remove direct generic-question execution through `/action/execute_confirmed_point`.

- [ ] **Step 6: Rerun focused tests**

Run: `uv run pytest tests/test_form_fill_executor.py tests/test_form_fill_verification.py tests/test_seek_employer_questions.py -q`

Expected: PASS.

---

### Task 7: Integrate Human Review Into The Learning Panel

**Files:**
- Modify: `app/web_panel/learning_workflow_review.js`
- Modify: `app/web_panel/index.html`
- Modify: `app/web_panel/panel.css`
- Modify: `app/web_panel/panel.js`
- Modify: `tests/js/learning_workflow_review.test.cjs`
- Modify: `tests/test_web_panel_route.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: normalized questions and answer decisions
- Produces: reviewed policy memory and updated Agent-readable interface evidence

- [ ] **Step 1: Add failing UI contract tests**

Require a question list showing original text, normalized intent, answer type, evidence source, proposed answer preview, risk status, and verification requirement.

- [ ] **Step 2: Add review actions**

Support approve once, approve for workflow class, approve for site, always ask, correct answer, mark sensitive, and mark unsupported. Never display raw PII in generated diagnostics.

- [ ] **Step 3: Add save/reload tests**

Saving a correction must refresh the evidence projection immediately. Reopening the same interface must display the approved policy and preserve the original question evidence.

- [ ] **Step 4: Run focused panel tests**

Run:

```powershell
node --test tests/js/learning_workflow_review.test.cjs
uv run pytest tests/test_web_panel_route.py -q
```

Expected: PASS.

- [ ] **Step 5: Update README**

Explain that review trains reusable answer policies and evidence mappings, not model weights.

---

### Task 8: Wire The Generic Multi-Step Form State Machine

**Files:**
- Create: `app/agent/form_workflow_controller.py`
- Modify: `app/learn/application_interface_graph.py`
- Modify: `app/seek/answer_plan.py`
- Create: `tests/test_form_workflow_controller.py`
- Modify: `tests/test_application_interface_graph.py`

**Interfaces:**
- Consumes: reviewed application workflow, current interface evidence, latest form snapshot
- Produces: one of `answer_current_question`, `continue_next_step`, `request_user_review`, `safe_stop`, or `completed_without_submit`

- [ ] **Step 1: Write failing state-machine tests**

Cover form inventory, partial fill, review interruption, continue-to-next-step, new-question rediscovery, login blocker, external ATS transition, failed verification, and final-review safe stop.

- [ ] **Step 2: Run focused tests**

Run: `uv run pytest tests/test_form_workflow_controller.py -q`

Expected: FAIL on missing controller.

- [ ] **Step 3: Implement state transitions**

Do not assume question order or count. Re-inventory every step after navigation. A previously learned interface provides semantic expectations only; current content and controls must come from the latest observation.

- [ ] **Step 4: Rerun focused tests**

Run: `uv run pytest tests/test_form_workflow_controller.py -q`

Expected: PASS.

---

### Task 9: Build A Non-Inflated Form Benchmark

**Files:**
- Create: `artifacts/benchmarks/general_form_workflow_manifest_v1.json`
- Create: `scripts/run_general_form_workflow_benchmark.py`
- Create: `tests/test_general_form_workflow_benchmark.py`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Consumes: fixed screenshots/traces with checksums and expected outcomes
- Produces: layered metrics with `passed / attempted / rate`, invalid cases, trace paths, and screenshot paths

- [ ] **Step 1: Add 12–16 high-value cases**

Include paraphrased work-rights questions, opposite polarity, duplicated Yes/No labels, text input, textarea, dropdown, checkbox multi-select, salary review, sensitive blocker, file upload unsupported, wrong surface, stale capture, final review, and final-submit visible.

- [ ] **Step 2: Add benchmark integrity tests**

Checksum mismatch and missing evidence become invalid fixtures and do not enter pass/fail denominators. Fixture-only results cannot be described as live reliability.

- [ ] **Step 3: Add layered metrics**

Report question inventory, intent normalization, answer evidence retrieval, policy decision, candidate recall, point grounding, fill dispatch, fill effect, step transition, final-submit guard, and full no-submit workflow separately.

- [ ] **Step 4: Run benchmark tests and fixture replay**

Run:

```powershell
uv run pytest tests/test_general_form_workflow_benchmark.py -q
uv run python scripts/run_general_form_workflow_benchmark.py `
  --manifest artifacts/benchmarks/general_form_workflow_manifest_v1.json `
  --out logs/benchmarks/general_form_workflow_v1 `
  --no-submit `
  --json
```

Expected: report generated without a combined promotional success rate.

---

### Task 10: Perform One Reviewed No-Submit UAT

**Files:**
- Create: `docs/GENERAL_FORM_WORKFLOW_UAT.md`
- Update: `README.md`
- Update: `PROJECT_SUMMARY.md`
- Update: `ARCHITECTURE.md`
- Update: `CURRENT_STATE.md`
- Update: `NEXT_STEPS.md`

**Interfaces:**
- Uses: one reviewed multi-page application workflow
- Produces: trace-backed acceptance report and known limitations

- [ ] **Step 1: Run preflight**

Verify target window, memory pressure, model availability, current profile, no-submit mode, final-submit Gate, capture freshness, and Trace output directory.

- [ ] **Step 2: Run dry-run**

Exercise inventory, Agent decisions, review pauses, control relocation, Gate decisions, and expected verification without real filling.

- [ ] **Step 3: Run explicit low-risk live fill**

Only after user approval, fill reviewed non-sensitive fields and approved options. Stop on the first unknown or sensitive question. Do not upload files and do not click final submit.

- [ ] **Step 4: Verify final safe stop**

Require `submit_clicks=0`, `final_submissions=0`, current final-review screenshot, blocker evidence, complete action traces, and no raw PII in generated reports.

- [ ] **Step 5: Run regression suite**

Run:

```powershell
uv run pytest tests/test_form_question_contracts.py tests/test_operation_form_inventory.py tests/test_form_question_understanding.py -q
uv run pytest tests/test_form_answer_planner.py tests/test_form_answer_policy_memory.py tests/test_form_policy_gate.py -q
uv run pytest tests/test_form_fill_executor.py tests/test_form_fill_verification.py tests/test_form_workflow_controller.py -q
uv run pytest tests/test_final_submit_guard_fixtures.py tests/test_seek_employer_questions.py tests/test_seek_form_inventory.py -q
uv run pytest tests -q
```

- [ ] **Step 6: Record evidence-based status**

State exactly which capabilities were fixture-covered, dry-run covered, and live no-submit covered. Do not call template similarity, fixture pass rate, or partial fill evidence model accuracy or end-to-end reliability.

---

## Delivery Checkpoints

1. **Checkpoint A — Understand:** Tasks 1–3; differently worded questions normalize into safe, reusable intents.
2. **Checkpoint B — Decide:** Tasks 4–5; answers are evidence-backed and unsafe/unknown questions stop for review.
3. **Checkpoint C — Act:** Task 6; allowed fields execute one at a time through the gated recognition-plan path and require effect verification.
4. **Checkpoint D — Teach:** Tasks 7–8; human corrections become scoped reusable memory and the workflow handles changing multi-step forms.
5. **Checkpoint E — Prove:** Tasks 9–10; benchmark and one reviewed no-submit UAT expose failures without inflating claims.

## Estimated Schedule

- Days 1–2: Tasks 1–3.
- Days 3–4: Tasks 4–5.
- Days 5–6: Task 6.
- Days 7–8: Tasks 7–8.
- Days 9–10: Tasks 9–10 and documentation.

The first useful MVP is available after Checkpoint C. The interview-ready no-submit workflow requires Checkpoints D and E.
