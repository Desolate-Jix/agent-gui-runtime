# Learning Overlay Model Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个默认关闭的学习框图模型复核实验，删除或重标明显错误区域，把缺失内容转换为现有精准定位任务，并报告复核前后的人工标注对齐变化。

**Architecture:** 新模块只消费原始截图、Stage2 JSON 和合成框图，输出受限 `review_patch`。确定性 validator 拒绝未知区域、非法角色、跨根区修改和模型直接生成的最终坐标；合法 patch 生成 reviewed Stage2 和 missing locator tasks。独立 probe 负责真实模型调用、产物落盘、overlay 和对比评测，暂不接入正式面板链。

**Tech Stack:** Python 3.11、Pydantic/现有 dict contract、Pillow、现有 `LocalVisionProvider`、pytest。

## Global Constraints

- 不修改 Execute、PathGraph、正式 Stage1、正式 Stage2 和安全 Gate。
- 模型不能自由生成最终精确 bbox；missing 只能包含粗 ROI，并必须返回现有精准定位链。
- 所有输出保持 `display_only=true`、`execute_binding_enabled=false`、`artifact_is_authorization=false`、`real_clicks=0`。
- 无效模型协议必须显式失败，不使用宽松 fallback 掩盖错误。
- 中文 prompt、JSON、trace 和报告全程使用 UTF-8。

---

### Task 1: Review Patch Contract And Validator

**Files:**
- Create: `app/learn/recognition/model_review.py`
- Test: `tests/test_learning_overlay_model_review.py`

**Interfaces:**
- Produces: `validate_review_patch(stage2: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]`
- Produces: `apply_review_patch(stage2: dict[str, Any], validated_patch: dict[str, Any]) -> dict[str, Any]`

- [ ] **Step 1: Write failing tests** covering valid remove/relabel, unknown region rejection, illegal role rejection, model final-bbox rejection, and preservation of the input Stage2 object.
- [ ] **Step 2: Run** `uv run pytest tests/test_learning_overlay_model_review.py -q` and confirm failure because the module does not exist.
- [ ] **Step 3: Implement** strict action parsing with allowed roles including `list_container`, `list_item`, `message_item`, `member_list`, `toolbar`, `navigation`, `content_region`, `input_region`, `card`, and `review_only`; require existing IDs for keep/remove/relabel and forbid `bbox`, `final_bbox`, or `click_point` in missing entries.
- [ ] **Step 4: Apply** patches on a deep copy, annotate every changed item with `model_review_decision`, and preserve root-region containment.
- [ ] **Step 5: Rerun** the targeted tests until green.

### Task 2: Missing-Region Locator Task Handoff

**Files:**
- Modify: `app/learn/recognition/model_review.py`
- Test: `tests/test_learning_overlay_model_review.py`

**Interfaces:**
- Produces: `build_missing_locator_tasks(stage2: dict[str, Any], validated_patch: dict[str, Any], screenshot_path: str) -> dict[str, Any]`

- [ ] **Step 1: Write failing tests** proving missing entries require an existing parent, accept only `rough_roi`, and produce display-only tasks compatible with the numbered-region calibration request shape.
- [ ] **Step 2: Run** the missing-task tests and confirm expected failure.
- [ ] **Step 3: Implement** task generation with `prompt`, `expected_role`, `parent_region_id`, `rough_roi`, `screenshot_path`, `requires_precise_grounding=true`, and all authorization flags disabled.
- [ ] **Step 4: Rerun** the targeted tests until green.

### Task 3: Model Prompt, Parsing, And Independent Probe

**Files:**
- Modify: `app/learn/recognition/model_review.py`
- Create: `scripts/run_learning_overlay_model_review_probe.py`
- Test: `tests/test_learning_overlay_model_review.py`

**Interfaces:**
- Produces: `build_model_review_prompt(stage2: dict[str, Any]) -> str`
- Produces: `parse_model_review_response(raw_text: str) -> dict[str, Any]`
- Probe inputs: `--screenshot`, `--overlay`, `--stage2-json`, `--out`, optional `--recorded-response`, optional `--start-model/--stop-model`.

- [ ] **Step 1: Write failing tests** for prompt constraints, fenced JSON parsing, raw-response preservation, and protocol-error reporting.
- [ ] **Step 2: Run** targeted tests and confirm expected failure.
- [ ] **Step 3: Implement** a concise prompt that asks the 8B reviewer to compare the original screenshot and composite overlay, use JSON evidence, and output only keep/remove/relabel/missing/review actions.
- [ ] **Step 4: Implement** the probe using the existing local-understanding provider for an actual model call, or an explicitly tagged recorded response for deterministic tests; save prompt input, raw response, parsed patch, validation result, reviewed Stage2, and missing locator tasks separately.
- [ ] **Step 5: Rerun** targeted tests and `uv run python -m py_compile app/learn/recognition/model_review.py scripts/run_learning_overlay_model_review_probe.py`.

### Task 4: Before/After Overlay And Accuracy Comparison

**Files:**
- Modify: `app/learn/recognition/model_review.py`
- Modify: `scripts/run_learning_overlay_model_review_probe.py`
- Test: `tests/test_learning_overlay_model_review.py`

**Interfaces:**
- Produces: `render_reviewed_overlay(...) -> str`
- Produces: `score_review_against_adjudication(before_stage2, after_stage2, adjudication) -> dict[str, Any]`

- [ ] **Step 1: Write failing tests** for removed-region suppression, relabel visualization, missing-region dashed ROI, and denominator-based precision/recall/F1 reporting.
- [ ] **Step 2: Run** targeted tests and confirm expected failure.
- [ ] **Step 3: Implement** before/reviewed/diff overlays and an optional human-adjudication manifest. Report region classification precision/recall/F1 and missing-target recall separately; never call the result general recognition accuracy.
- [ ] **Step 4: Run** the QQ sample with actual model output, inspect all artifacts, and record whether obvious false cards were removed without deleting valid message/list items.
- [ ] **Step 5: Run** protected old-interface fixtures and verify the experimental module causes zero production-output drift while disabled.

### Task 5: Documentation And Final Verification

**Files:**
- Modify: `README.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

- [ ] **Step 1: Document** the default-off experiment, artifact paths, measured sample result, known limitations, and no-click boundary.
- [ ] **Step 2: Run** `uv run pytest tests/test_learning_overlay_model_review.py -q`.
- [ ] **Step 3: Run** the nearest recognition and hierarchy regression tests.
- [ ] **Step 4: Run** `uv run pytest tests -q` only after focused checks pass.
- [ ] **Step 5: Confirm** no live click/fill/submit, no Runtime PathGraph promotion, and no production Stage1/Stage2 behavior change.
