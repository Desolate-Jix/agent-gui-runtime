# Review Confirmation And Multi-Box Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ordered box corrections persist safely, make successful approval immediately visible, and prove the workflow by adding and approving a second control through the panel.

**Architecture:** Keep the existing fail-closed `human_review_patch` contract. Repair the backend working-state simulation so ordered bbox operations are validated against the result of the preceding operation, then refresh the frontend projection only after durable approval succeeds. Use the real panel editor for the final two-box acceptance instead of editing reviewed JSON directly.

**Tech Stack:** Python, pytest, browser-native JavaScript, Node test runner, FastAPI panel, Git checkpoints.

**Spec:** User-approved design in the 2026-08-24 review-confirmation task: preserve strict stale checks, repair ordered bbox handling, refresh visible approval state, add one more box, and persist the interface as human-reviewed.

## Global Constraints

- Do not weaken stale-bbox equality or add pixel tolerance.
- Do not mark an interface reviewed by directly editing JSON; approval must pass through the panel/API path.
- Do not execute a target-application action; editing screenshot evidence is review-only.
- Keep inherited `tests/test_agent_runtime_actual_adapter_portfolio_v1.py` untouched and uncommitted.
- Each independently verified slice receives one conventional commit; do not push.

---

### Task 1: Ordered bbox normalization

**Files:**
- Modify: `app/learn/draft_review.py`
- Test: `tests/test_learning_draft_review.py`

**Interfaces:**
- Consumes: ordered `human_review_patch.operations` containing `update_bbox` entries.
- Produces: normalized operations whose working bbox advances after every accepted operation.

- [ ] Add a regression test with one region and the ordered sequence `A -> B`, `B -> C`.
- [ ] Run the single test and verify it fails with `operation 1 before_bbox is stale`.
- [ ] Update the normalizer's working item bbox after appending each valid `update_bbox`.
- [ ] Rerun the single test and the focused human-review patch tests.
- [ ] Stage only the two allowed files, run staged checks and secret/path checks, then commit `fix(review): preserve ordered bbox corrections`.

### Task 2: Approval projection refresh

**Files:**
- Modify: `app/web_panel/panel.js`
- Test: `tests/js/learning_review_apply_editor.test.cjs`

**Interfaces:**
- Consumes: successful durable workflow approval and the approved isolated draft state.
- Produces: live workflow state plus a rerendered approval counter/status; failed saves remain visible failures.

- [ ] Add a VM regression proving a successful session approval rerenders `human_approved` state.
- [ ] Run the single JS file and verify the new assertion fails because render count is zero.
- [ ] Add the narrow post-persistence render/projection refresh without changing failure guards.
- [ ] Rerun the focused editor and workflow-selection JS tests.
- [ ] Stage only the two allowed files, run staged checks and secret/path checks, then commit `fix(panel): refresh confirmed review state`.

### Task 3: Two-box live acceptance and durable approval

**Files:**
- Runtime artifact updated through the panel: `artifacts/interface-workflow-reviews/portfolio_v1_seek_apply_entry/**`
- Local status documentation if behavior/status changed: `CURRENT_STATE.md`, `NEXT_STEPS.md`

**Interfaces:**
- Consumes: the repaired review-save API and current `Job Detail` screenshot evidence.
- Produces: a persisted reviewed interface containing the existing `Quick apply` control and a second non-destructive review control, plus visible `human_approved` state after reload.

- [ ] Restart or reload the local panel so the repaired code is active.
- [ ] Open `Job Detail` in **修正与确认** and add a second box around a non-destructive visible control such as `Save`.
- [ ] Give the second box explicit name, semantic role, read-only purpose, and evidence metadata.
- [ ] Confirm and store through the panel; do not directly edit the reviewed JSON.
- [ ] Reload the panel and verify two controls remain and the interface is visibly human-approved.
- [ ] Inspect persisted JSON for the approved revision, two boxes, and provenance; run focused route/API tests.
- [ ] Commit only tracked acceptance evidence/docs that belong to this slice; do not add private screenshots or unrelated generated artifacts.

### Task 4: Integration gate and mainline continuation

**Files:**
- Review only: `NEXT_STEPS.md`, `docs/superpowers/plans/2026-08-22-portfolio-release-v1-plan.md`

**Interfaces:**
- Consumes: verified review-save and two-box approval evidence.
- Produces: the next unfinished Portfolio v1 implementation slice selected from the canonical dependency chain.

- [ ] Run the combined Python/JavaScript focused suite covering review save, workflow approval, and panel routes.
- [ ] Obtain an independent read-only review of the complete diff and acceptance evidence.
- [ ] Record the verified state and any deferred limitations.
- [ ] Select the next uncompleted mainline slice without widening Portfolio v1 scope.
