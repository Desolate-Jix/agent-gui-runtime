# Deterministic Root Hard Replace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 deterministic root partition 变成 Learning Mode 唯一正式 Stage1，优化下游融合，并删除不再使用的旧路径和实验代码。

**Architecture:** 正式实现从 `app/learn/experiments` 迁移到 `app/learn/recognition`，取消所有运行时 strategy 选择。下游 Stage1.5/Stage2/fusion 合同保持不变；删除以引用可达性审计为前置条件，九界面 benchmark 作为回归主证据。

**Tech Stack:** Python 3.11、FastAPI/Pydantic、Pillow、vanilla JavaScript、pytest。

## Global Constraints

- 不修改 Execute、Runtime PathGraph promotion、安全 Gate、真实点击、填写或提交。
- 学习产物始终只读，不能成为执行授权。
- root validator 和 Stage1 gate 失败时不得自动回退旧 Stage1。
- 九界面固定回放不是通用识别准确率证明。
- 所有中文文件按 UTF-8 读写。

---

### Task 1: Promote The Canonical Root Module

**Files:**
- Move: `app/learn/experiments/deterministic_root_partition_mvp.py` -> `app/learn/recognition/root_partition.py`
- Modify: `app/learn/recognition/two_stage.py`
- Modify: `tests/test_deterministic_root_partition.py`

**Interfaces:**
- Produces: `build_deterministic_root_partition`, `adapt_root_partition_to_stage1_contract`, `detect_vertical_separator_cuts` from the production recognition package.

- [ ] Move the module and update imports.
- [ ] Add a failing test that production imports no deterministic implementation from `app.learn.experiments`.
- [ ] Run `uv run pytest tests/test_deterministic_root_partition.py -q`.

### Task 2: Remove Runtime Strategy Selection

**Files:**
- Modify: `app/learn/recognition/two_stage.py`
- Modify: `app/learn/recognition/pipeline.py`
- Modify: `app/api/panel.py`
- Modify: `scripts/run_learn_stage1_region_localization.py`
- Modify: `scripts/run_deterministic_first_recognition_benchmark.py`
- Modify: `app/web_panel/panel.js`
- Modify: `tests/test_deterministic_root_partition.py`
- Modify: `tests/test_learn_recognition_pipeline.py`
- Modify: `tests/test_web_panel_route.py`

**Interfaces:**
- Removes: `stage1_region_strategy` from public/runtime APIs.
- Produces: unconditional deterministic Stage1 provenance.

- [ ] Write/update tests asserting request models, pipeline and builders expose no strategy selector.
- [ ] Remove normalization/dispatch and call the canonical root builder directly.
- [ ] Remove CLI and frontend strategy payload fields.
- [ ] Run focused recognition, panel and runner tests.

### Task 3: Verify The Hard Replace Before Optimization

**Files:**
- No production edit unless verification exposes a defect.
- Output: `logs/region_partition_mvp/first_recognition_hard_replace_v1/`

**Interfaces:**
- Consumes: nine-case fixed manifest.
- Produces: original/root/final triplets and aggregate report.

- [ ] Run the nine-interface benchmark.
- [ ] Verify 9 attempted, 0 invalid, validator/gate/Stage2/three-image counts all 9.
- [ ] Compare root and final hashes with the accepted v19 run; investigate any difference before continuing.

### Task 4: Reduce Final Fusion Noise

**Files:**
- Modify: `app/learn/recognition/two_stage.py`
- Modify: `tests/test_learn_recognition_pipeline.py`

**Interfaces:**
- Preserves: root regions and Stage1 gate.
- Improves: child/parent display ownership and final review-box density.

- [ ] Add focused failing tests for duplicated child evidence and broad partial/group boxes identified by three-image review.
- [ ] Implement the smallest generic ownership/filtering correction.
- [ ] Rerun focused tests and the nine-interface benchmark.
- [ ] Inspect all nine final fusion images; record remaining review-required cases.

### Task 5: Remove Dead Legacy And Experiment Code

**Files:**
- Modify: `app/learn/recognition/two_stage.py`
- Delete only after zero production/benchmark references: superseded adjudication modules, runners, tests, fixtures and duplicate plans.
- Create/Modify: one concise historical experiment summary.

**Interfaces:**
- Preserves: all Stage2/fusion helpers still reachable from the canonical flow.

- [ ] Build a definition/reference report for old Stage1 helpers.
- [ ] Delete only helpers exclusively reachable from `_stage1_structure_regions`.
- [ ] Search imports for each experiment asset before deletion.
- [ ] Delete superseded experiment-only assets and retain one history summary.
- [ ] Run focused tests after each deletion group.

### Task 6: Final Verification And Documentation

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Produces: current architecture and evidence-based limitations.

- [ ] Run `uv run python -m py_compile` on changed Python modules and runners.
- [ ] Run focused tests, then `uv run pytest tests -q`.
- [ ] Run the final nine-interface benchmark and generate the three-image contact sheet.
- [ ] Search for stale runtime `legacy_v1`, experiment imports and misleading reliability wording.
- [ ] Update affected docs with exact commands, report paths, remaining failures and non-hermetic limitation.
