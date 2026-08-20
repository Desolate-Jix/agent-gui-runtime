# Learning Review Repair Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让审核层对每个删除框记录内容去向，在修复未完成时安全停住，并在替代证据完整时重新组合为只读审核产物。

**Architecture:** 在现有 `model_review.py` 旁新增独立闭环模块，消费已验证 patch、审核前后 Stage2 和 repair handoff，输出 removal resolutions、替代完整性 Gate 和状态机报告。实验 probe 使用该模块，但正式 Stage1、Stage2、Execute、PathGraph 和安全 Gate 不变。

**Tech Stack:** Python 3.11、Pillow、pytest、现有 Stage2 dict contract。

## Global Constraints

- 删除错误 group 时不得删除其原子 `numbered_items`。
- 每个 remove 必须有内容去向；无去向不得完成。
- 模型 rough ROI 不能直接成为最终 bbox。
- repair 未完成时状态必须是 `repair_pending` 或 `needs_human_review`。
- 所有产物保持 display-only，不授权点击、填写、提交或 Runtime PathGraph。

---

### Task 1: Removal Resolution Contract

**Files:**
- Create: `app/learn/recognition/review_workflow.py`
- Test: `tests/test_learning_review_workflow.py`

**Interfaces:**
- Consumes: Stage2、validated review patch、`learning_overlay_missing_repair_handoff_v1`
- Produces: `build_removal_resolutions(stage2, reviewed_stage2, validated_patch, repair_handoff) -> list[dict[str, Any]]`

- [x] **Step 1: Write failing tests** proving children remain after wrapper removal, local repair maps to `precise_locator`, structural repair maps to `stage1_repartition`, and unresolved removal maps to `needs_human_review`.
- [x] **Step 2: Run** `uv run pytest tests/test_learning_review_workflow.py -q` and confirm import/function failure.
- [x] **Step 3: Implement** deterministic resolution matching by existing IDs, preserved child IDs, parent ID, repair route, and rough-ROI overlap. Never synthesize replacement geometry.
- [x] **Step 4: Rerun** the targeted tests until green.

### Task 2: Replacement Integrity Gate And State Machine

**Files:**
- Modify: `app/learn/recognition/review_workflow.py`
- Test: `tests/test_learning_review_workflow.py`

**Interfaces:**
- Produces: `run_replacement_integrity_gate(...) -> dict[str, Any]`
- Produces: `run_review_repair_workflow(...) -> dict[str, Any]`

- [x] **Step 1: Write failing tests** for `repair_pending`, `needs_human_review`, `replacement_incomplete`, and `completed_review_only`.
- [x] **Step 2: Run** the focused tests and confirm state assertions fail.
- [x] **Step 3: Implement** state selection with denominator-based counts, child-preservation validation, exact repair-result ID matching, and display-only safety fields.
- [x] **Step 4: Add a completed fixture** where a trusted repair result supplies a replacement region and every removed region is resolved.
- [x] **Step 5: Rerun** until green.

### Task 3: Probe Integration And QQ Reality Check

**Files:**
- Modify: `scripts/run_learning_overlay_model_review_probe.py`
- Modify: `tests/test_learning_overlay_model_review.py`
- Test: `tests/test_learning_review_workflow.py`

**Interfaces:**
- Probe report adds: `workflow_state`, `removal_resolutions`, `replacement_integrity_gate`, `repair_pending_count`

- [x] **Step 1: Write a failing probe test** proving unresolved Stage1 repair prevents a completed report.
- [x] **Step 2: Integrate** the workflow after patch validation and before overlay/report completion.
- [x] **Step 3: Replay** the existing actual QQ v8 validated patch without another model call and save a closure report.
- [x] **Step 4: Assert** seven removed wrappers retain child content or repair routes, the member pane is `stage1_repartition`, and workflow state is `repair_pending` rather than complete.
- [x] **Step 5: Run** the full review tests.

### Task 4: Documentation And Verification

**Files:**
- Modify: `README.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

- [x] **Step 1: Document** the closure state, real QQ pending result, fixture-complete result, and production isolation.
- [x] **Step 2: Run** `uv run pytest tests/test_learning_review_workflow.py tests/test_learning_overlay_model_review.py -q`.
- [x] **Step 3: Run** protected recognition regressions.
- [x] **Step 4: Run** `uv run pytest tests -q`, Python compilation, and `git diff --check`.
- [x] **Step 5: Confirm** zero live click/fill/submit and no model service left running.
