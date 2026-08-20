# SEEK Learn-Review-Execute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用现有 Learn Mode 学习 SEEK 的岗位列表、岗位详情和 Quick Apply/申请界面，由人工修订生成 Agent 可读资产，连接为多界面流程，并通过 Gate 约束的执行链验证到最终提交前停止。

**Architecture:** 自动识别只产生可审核草稿；错误优先通过面板人工修订。只有根因明确、修改很小且通过跨界面回归的通用问题允许保留代码修复，否则立即回退并人工修订。审核资产进入 `ReviewedInterfaceMemoryStore`，界面连接进入 `interface_workflow_review`，真实动作始终走 `POST /action/execute_recognition_plan`。

**Tech Stack:** Python 3.11、FastAPI、HTML/CSS/JavaScript 面板、pytest、Windows GUI Operation/OCR/VISTA、JSON Trace。

## Global Constraints

- 不为 SEEK 增加网站名称、固定坐标或专用识别规则。
- 不追求 Learn Mode 自动草稿 100% 可执行。
- `semantic_name`/`label` 与 `observed_text`/`visible_text_anchors` 必须职责分离。
- 未审核资产不得提供给 Agent 直接执行。
- 历史坐标仅作先验；执行时必须使用当前截图重新定位。
- 所有真实点击必须通过 `POST /action/execute_recognition_plan`。
- `final_submit`、`send`、`complete`、支付和确认类最终动作保持硬阻断。
- 不做 live final submit；不在未经审核的字段上自动填写。

---

### Task 1: Current-state audit and runtime restart

**Files:**
- Inspect: `artifacts/agent-memory/registry.json`
- Inspect: `artifacts/interface-workflow-reviews/registry.json`
- Inspect: `artifacts/learning-runs/`

**Interfaces:**
- Consumes: existing SEEK screenshots, reviewed candidates, agent memory objects, dry-run traces.
- Produces: an authoritative inventory of reusable assets and concrete blockers.

- [ ] Confirm the API, model services, Edge/SEEK window, active reviewed memories, and workflow registry.
- [ ] Start only the services required for the next narrow step.
- [ ] Verify `/health`, `/panel/learning_draft_sources`, reviewed-memory registry, and workflow-library endpoints.

### Task 2: Separate semantic labels from current-surface text evidence

**Files:**
- Modify: `app/agent/reviewed_interface_memory.py`
- Test: `tests/test_reviewed_interface_memory.py`
- Test: `tests/test_reviewed_interface_memory_execution.py`

**Interfaces:**
- Consumes: reviewed region metadata (`label`, `observed_text`, `visible_text_anchors`).
- Produces: semantic Agent label plus explicit current-surface text anchors for Gate validation.

- [ ] Run `uv run pytest tests/test_reviewed_interface_memory.py::test_reviewed_memory_keeps_semantic_label_separate_from_visible_text_anchor -q` and confirm the new test fails because the semantic label is currently reused as OCR evidence.
- [ ] Implement the minimum compiler change: preserve `label`, derive `visible_text_anchors` only from explicit human-reviewed evidence, mirror it into legacy `text_anchors`, and mark the anchor source.
- [ ] Preserve a clearly marked `legacy_label_fallback` only for older reviewed assets that have no explicit observed-text field.
- [ ] Run `uv run pytest tests/test_reviewed_interface_memory.py tests/test_reviewed_interface_memory_execution.py -q`.

### Task 3: Learn and human-review SEEK single interfaces

**Files:**
- Generate: `artifacts/learning-runs/panel_*_seek*/trial_result.json`
- Generate: `artifacts/learning-draft-review/*/human_review_patch.json`
- Generate: `artifacts/learning-draft-review/*/reviewed_template_candidate.json`
- Generate: `artifacts/agent-memory/objects/*.json`

**Interfaces:**
- Consumes: stable full-window screenshots captured after the target surface finishes loading.
- Produces: approved Agent-readable assets for results, detail, Apply entry, form step(s), and final-review blocker when reachable.

- [ ] Learn the SEEK results surface and review obvious box/semantic errors in the panel.
- [ ] Learn the selected job-detail surface and review its read region and Apply entry.
- [ ] Learn each Quick Apply/form surface reached through low-risk actions.
- [ ] For every interface, explicitly record semantic purpose, observed text, available low-risk actions, verification rules, blockers, and `artifact_is_authorization=false`.
- [ ] Publish only `approved_as_assisted_template` candidates to reviewed interface memory.

### Task 4: Connect reviewed interfaces into one SEEK workflow

**Files:**
- Generate: `artifacts/interface-workflow-reviews/<workflow_id>/reviewed_workflow.json`
- Update: `artifacts/interface-workflow-reviews/registry.json`
- Test: `tests/test_interface_workflow_review.py`

**Interfaces:**
- Consumes: active reviewed-memory interface IDs and human-confirmed source controls.
- Produces: a single workflow graph with source interface, source control, semantic action, target interface, and verification rule per edge.

- [ ] Create or update one SEEK workflow instead of separate disconnected single-interface demos.
- [ ] Connect results → detail with the reviewed job-card action.
- [ ] Connect detail → application flow with the reviewed Apply action.
- [ ] Connect non-final form transitions only after their controls are reviewed.
- [ ] Mark the final review/submit boundary as a blocker and safe-stop terminal state.
- [ ] Verify the panel reloads the complete workflow and each node opens its own evidence.

### Task 5: Agent decision and gated execution validation

**Files:**
- Generate: `logs/smoke/seek_real_learn_*/`
- Generate: action and transition traces under `logs/`.
- Test: `tests/test_reviewed_workflow_navigation.py`
- Test: `tests/test_execute_recognition_plan_route.py`

**Interfaces:**
- Consumes: reviewed workflow plus current screenshots.
- Produces: Agent decision, current-grounding evidence, Gate decision, action effect, target-state verification, and safe-stop evidence.

- [ ] Dry-run every edge and classify failures as evidence, Agent, recall, grounding, Gate, effect, or state verification.
- [ ] Fix simple common invariants once and run cross-interface regression; revert if ineffective or harmful.
- [ ] Repair remaining draft errors through panel human review rather than recognition-rule expansion.
- [ ] Execute low-risk results → detail → Apply/form navigation through the gated action endpoint.
- [ ] Verify every transition with a fresh observation and stop before final submit.

### Task 6: Regression, documentation, and shutdown

**Files:**
- Modify: `README.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Consumes: verified traces and workflow artifacts.
- Produces: reproducible status, limitations, and shutdown confirmation.

- [ ] Run targeted reviewed-memory, workflow, panel, Gate, and final-submit tests.
- [ ] Run the narrow SEEK no-submit smoke from the reviewed workflow.
- [ ] Document what was learned automatically, what was human-corrected, what was executed, and what remains unverified.
- [ ] Confirm no final submit occurred and shut down local model services after verification.

\n