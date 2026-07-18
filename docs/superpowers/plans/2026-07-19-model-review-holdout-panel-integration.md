# Model Review Holdout And Panel Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用真实模型调用验证通用界面复核与确定性修复闭环，并在九界面无污染及一个未参与调试的新界面 smoke 后，把该闭环接入 Learn Mode 面板的 Stage2 candidate graph 与精准校准之间。

**Architecture:** 新增 development-validation manifest/runner 统一调用现有 model review probe、validated patch、generic repair compiler 和 deterministic repair executor，并输出三图与分层结果。复核前编号仅用于 before-review 展示；repair 与 integrity gate 后必须重新生成 final numbering 并绑定新的 graph revision。面板新增只读 review/repair endpoint，消费当前 Stage2 candidate graph 并保存 reviewed/repaired/final-numbered Stage2；前端只有在完整性 gate 通过后才继续精准校准。

**Tech Stack:** Python 3.11、FastAPI/Pydantic、pytest、Pillow、原生 JavaScript、OpenAI-compatible local Qwen3-VL 8B endpoint。

## Global Constraints

- 实际模型输出只能决定 keep/remove/relabel/missing、optional role 和 rough ROI。
- rough ROI 不能成为最终 bbox；最终 bbox 只能来自可复盘的原子证据 union 与 parent clip。
- 模型协议失败、证据缺失、stale fixture、坐标不一致和 unresolved human review 必须阻止精准校准。
- 所有产物保持 display-only；Execute、真实点击、填写、提交和 Runtime PathGraph promotion 全部为 0/false。
- 不允许应用名称、固定坐标、固定标题或 screenshot checksum 特判。
- 每例必须保留 original、before-review fusion、final-repaired fusion 三图。
- 报告不输出 accuracy；attempted=0 必须显示 not_covered。
- 每次 actual model call 必须记录 capture checksum、prompt/schema/parser/repair 版本、模型版本、推理参数、raw response 和 graph revision。
- 校准 target ID 必须来自 repair 后 final numbering；provisional numbering 不得跨 graph revision 复用。

---

### Task 1: Development Validation Contract And Runner

**Files:**
- Create: `artifacts/benchmarks/learning_model_review_development_manifest_v1.json`
- Create: `scripts/run_learning_model_review_validation.py`
- Create: `tests/test_learning_model_review_validation_runner.py`
- Modify: `scripts/run_learning_review_repair_closure.py`

**Interfaces:**
- Consumes: checksum-pinned Stage2 source, original screenshot, fusion overlay, local model endpoint
- Produces: `learning_model_review_development_validation_report_v1` and per-case three-image evidence

- [ ] **Step 1:** Write failing tests for manifest checksum validation, actual model-call accounting, provenance/version fields, three-image completeness, invalid fixture exclusion, repair closure, and no-action safety counters.
- [ ] **Step 2:** Run `uv run pytest tests/test_learning_model_review_validation_runner.py -q` and confirm missing runner/contract failures.
- [ ] **Step 3:** Implement a three-case manifest for Notepad, Python.org, and Apple Music using current frozen nine-interface evidence.
- [ ] **Step 4:** Implement the runner so each case calls `run_probe`, then deterministic closure, then renders final repaired fusion from the final recomposed Stage2.
- [ ] **Step 5:** Rerun the targeted tests until green.

### Task 2: Model Review Protocol Hardening

**Files:**
- Modify: `app/learn/recognition/model_review.py`
- Modify: `app/learn/recognition/review_workflow.py`
- Modify: `app/learn/recognition/repair_contract.py`
- Modify: `app/learn/recognition/repair_executor.py`
- Test: `tests/test_learning_overlay_model_review.py`
- Test: `tests/test_learning_review_workflow.py`
- Test: `tests/test_learning_repair_contract.py`
- Test: `tests/test_learning_repair_executor.py`

**Interfaces:**
- Consumes: actual model response and frozen Stage2 atomic evidence
- Produces: validated review patch, repair requests/results, integrity-gated reviewed/repaired Stage2

- [ ] **Step 1:** Run the three actual-model holdouts once and classify every failure as protocol, adjudication, evidence, geometry, integrity, or fixture failure.
- [ ] **Step 2:** For each reusable failure, write the narrowest failing regression test before editing production code.
- [ ] **Step 3:** Apply only common-contract fixes; reject unsupported role creation, ungrounded missing regions, duplicate ownership, parent escape, or child loss.
- [ ] **Step 4:** Rerun the failing holdout and targeted tests after each fix.
- [ ] **Step 5:** Allow expansion when at least two cases improve; require all three to have no data-integrity regression, no silent fallback, and every unresolved case explicitly safe-stopped.

### Task 3: Nine-Interface Model Review Regression

**Files:**
- Modify: `scripts/run_learning_model_review_validation.py`
- Create: `artifacts/benchmarks/learning_model_review_nine_interface_manifest_v1.json`
- Test: `tests/test_learning_model_review_validation_runner.py`

**Interfaces:**
- Consumes: frozen nine-interface Stage2 evidence
- Produces: per-case actual-model review/repair reports and a nine-interface summary

- [ ] **Step 1:** Extend tests for nine-case denominators, structural-family breakdown, safe-stop accounting, and regression blocking.
- [ ] **Step 2:** Add the remaining six frozen cases without changing model configuration or prompt from the holdout gate.
- [ ] **Step 3:** Run all nine cases and manually inspect original, before-review, and final-repaired images for each case.
- [ ] **Step 4:** Classify all remaining failures and rerun only when a common-contract change has a regression test.
- [ ] **Step 5:** Block panel integration if any case loses atomic children, escapes its parent, fabricates a region, or silently bypasses review uncertainty.

### Task 4: Unseen Final Smoke

**Files:**
- Create: `artifacts/benchmarks/learning_model_review_unseen_smoke_v1.json`
- Modify: `scripts/run_learning_model_review_validation.py`
- Test: `tests/test_learning_model_review_validation_runner.py`

**Interfaces:**
- Consumes: one fixed screenshot not used while changing prompt, validator, or repair rules
- Produces: one actual-model three-image smoke report with `used_for_tuning=false`

- [ ] **Step 1:** Freeze one non-Calculator interface after the development and nine-interface rules are final.
- [ ] **Step 2:** Run it exactly once with the selected configuration and record `used_for_tuning=false`.
- [ ] **Step 3:** Require no data-integrity regression; improvement, unchanged, or explicit safe-stop are acceptable, silent degradation is not.
- [ ] **Step 4:** Do not change prompt or repair behavior based on this result; record any failure as post-demo backlog.

### Task 5: Panel Review And Repair Stage

**Files:**
- Modify: `app/api/panel.py`
- Modify: `app/web_panel/panel.js`
- Modify: `app/web_panel/index.html`
- Modify: `tests/test_learning_draft_review.py`
- Modify: `tests/test_web_panel_route.py`

**Interfaces:**
- Produces endpoint: `POST /panel/run_learning_model_review_repair`
- Consumes: `two_stage_report_path`, screenshot path, model profile/endpoint
- Produces: reviewed Stage2 report path, final numbering, graph revision, three-image evidence, integrity status, calibration permission

- [ ] **Step 1:** Write failing endpoint tests for passed, needs-human-review, invalid model output, evidence missing, and no-action safety paths.
- [ ] **Step 2:** Implement endpoint orchestration using the same runner components as the CLI, not a parallel panel-only algorithm.
- [ ] **Step 3:** Write failing front-end route tests proving the review/repair stage runs after Stage2 and before precise calibration.
- [ ] **Step 4:** Add one visible progress step and render the final repaired fusion image plus blocker explanation.
- [ ] **Step 5:** Regenerate final numbering after repair, bind calibration candidates to the repaired graph revision, and reject stale provisional IDs.
- [ ] **Step 6:** Require `integrity_gate.passed=true`, `needs_human_review=0`, complete repair resolution, unique atom ownership, preserved atom identity/count, current capture/revision references, trusted geometry provenance, and unchanged action/danger safety semantics before `runLearningDeepCalibration`; otherwise stop safely.

### Task 6: End-To-End Verification And Documentation

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `PROJECT_SUMMARY.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Consumes: holdout, nine-interface, panel smoke, and test evidence
- Produces: evidence-scoped maturity report

- [ ] **Step 1:** Run focused model-review/repair/panel tests and Python compilation.
- [ ] **Step 2:** Start the local panel, run a real display-only Learn Mode flow, and verify Stage2 -> review/repair -> integrity gate -> precise calibration ordering.
- [ ] **Step 3:** Confirm the panel displays the final repaired fusion rather than the source or pre-review overlay.
- [ ] **Step 4:** Run protected recognition regressions and `uv run pytest tests -q`.
- [ ] **Step 5:** Sync documentation with exact covered/not-covered claims, run `git diff --check`, stop all model/panel processes, and only then shut down Windows.
