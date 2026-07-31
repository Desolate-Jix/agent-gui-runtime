# General Review Repair And Nine-Interface Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现不依赖应用名称的审核修复请求、确定性修复执行器和九界面污染回归报告。

**Architecture:** 新增独立 repair contract/compiler 和 deterministic executor，消费已验证 review patch、Stage2 原子元素和父区域证据，输出可审计 replacement results。现有 review workflow 负责状态机与 integrity gate；独立九界面 runner 负责 before/after diff 和规则晋升判定，正式 Stage1/Stage2/Execute/PathGraph/Gate 不变。

**Tech Stack:** Python 3.11、pytest、Pillow、现有 JSON Stage2 contracts。

## Global Constraints

- 不允许应用名称、固定坐标、固定标题或 checksum 特判。
- 模型 rough ROI 只能选择证据，不能成为最终 bbox。
- 所有原子 child 必须保留且唯一归属。
- 所有输出保持 display-only；真实点击、填写和提交计数必须为 0。
- 九界面出现新增数据完整性退化时，候选规则不得晋升。

---

### Task 1: Generic Repair Request Compiler

**Files:**
- Create: `app/learn/recognition/repair_contract.py`
- Modify: `app/learn/recognition/review_workflow.py`
- Test: `tests/test_learning_repair_contract.py`

**Interfaces:**
- Consumes: `stage2: dict[str, Any]`, `validated_patch: dict[str, Any]`, `repair_handoff: dict[str, Any]`
- Produces: `compile_generic_repair_requests(...) -> dict[str, Any]`

- [ ] **Step 1: Write failing tests** proving one aggregated request lists every overlapping removed wrapper, deduplicates all preserved child IDs, includes a completion contract, and contains no application-specific fields.
- [ ] **Step 2: Run** `uv run pytest tests/test_learning_repair_contract.py -q` and confirm the import/function failure.
- [ ] **Step 3: Implement** deterministic grouping by repair request ID, parent ID, route, overlap evidence, and source group records. Emit `learning_review_generic_repair_requests_v1` with safety fields.
- [ ] **Step 4: Integrate** the compiled requests into `run_review_repair_workflow` and require every repair-linked removal to appear in exactly one request.
- [ ] **Step 5: Rerun** the targeted tests until green.

### Task 2: Deterministic Evidence Repair Executor

**Files:**
- Create: `app/learn/recognition/repair_executor.py`
- Modify: `app/learn/recognition/review_workflow.py`
- Test: `tests/test_learning_repair_executor.py`

**Interfaces:**
- Consumes: generic repair request, Stage2 parent/atomic items, screenshot dimensions
- Produces: `execute_deterministic_repair_requests(...) -> dict[str, Any]` using contract `learning_review_repair_results_v1`

- [ ] **Step 1: Write failing tests** for evidence-derived replacement geometry, empty evidence safe-stop, child uniqueness, parent containment, and rough-ROI/non-evidence rejection.
- [ ] **Step 2: Run** `uv run pytest tests/test_learning_repair_executor.py -q` and confirm the missing implementation failure.
- [ ] **Step 3: Implement** replacement bbox from the union of declared atomic child evidence, clip to the existing parent, reject empty/duplicate/out-of-parent evidence, and record `geometry_source=deterministic_atomic_evidence_union_v1`.
- [ ] **Step 4: Add** the new geometry source to the workflow trusted-source allowlist and verify incomplete requests remain pending/failed rather than silently completing.
- [ ] **Step 5: Rerun** repair contract, executor, workflow, and model-review tests.

### Task 3: Nine-Interface Repair Regression Runner

**Files:**
- Create: `scripts/run_learning_review_repair_nine_interface.py`
- Create: `tests/test_learning_review_repair_nine_interface.py`
- Use: `tests/fixtures/deterministic_first_recognition_manifest_v1.json`

**Interfaces:**
- Consumes: checksum-pinned nine-interface manifest and per-case Stage2 outputs
- Produces: `learning_review_repair_nine_interface_report_v1`

- [ ] **Step 1: Write failing tests** for nine-case accounting, `improved/unchanged/regressed/invalid_fixture/not_applicable`, rule-family support, and promotion blocking on any integrity regression.
- [ ] **Step 2: Run** `uv run pytest tests/test_learning_review_repair_nine_interface.py -q` and confirm failure.
- [ ] **Step 3: Implement** manifest loading, trace-to-Stage2 replay through the existing read-only chain, controlled review repair invocation, before/after structural diff, and four-image evidence paths.
- [ ] **Step 4: Implement** promotion policy: improvement in two distinct structure families or one data-integrity invariant, zero new integrity/safety regressions, and no application-specific rule markers.
- [ ] **Step 5: Run** the frozen nine-interface manifest and save the report under `logs/benchmarks/learning_review_repair_nine_interface_v1/`.

### Task 4: Regression, Documentation, And Reviewer Evidence

**Files:**
- Modify: `README.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Consumes: nine-interface report and test outputs
- Produces: evidence-scoped project status without accuracy claims

- [ ] **Step 1: Document** changed files, nine-case outcomes, candidate rules, regressions, invalid fixtures, and pending repair categories.
- [ ] **Step 2: Run** `uv run pytest tests/test_learning_repair_contract.py tests/test_learning_repair_executor.py tests/test_learning_review_workflow.py tests/test_learning_overlay_model_review.py tests/test_learning_review_repair_nine_interface.py -q`.
- [ ] **Step 3: Run** protected root/recognition/hierarchy regressions and `uv run pytest tests -q`.
- [ ] **Step 4: Run** Python compilation, `git diff --check`, model-port checks, and confirm zero live action counters.
- [ ] **Step 5: Report** fixture/replay scope honestly; do not claim general recognition reliability or completed real QQ repair unless its integrity gate passes.
