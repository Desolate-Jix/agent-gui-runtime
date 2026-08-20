# Generic Quick Apply No-Submit Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不点击最终提交的前提下，让 Agent 使用人工审核后的通用学习资产，从岗位列表连续完成岗位读取、详情读取、进入申请流程、逐步处理表单和动态问题，并在最终确认页安全停止。

**Architecture:** 继续使用现有 `observe -> Agent -> Gate -> Operation -> Trace -> observe` 执行环。学习资产只提供界面语义、可选操作、读取策略和跳转预期；每次真实操作都必须基于当前截图重新定位。表单能力以通用 `form inventory + answer policy + gated single-field operation + effect verification` 实现，SEEK 只保留为薄适配层和首个真实验证对象。

**Tech Stack:** Python 3.11+、FastAPI、pytest、现有 OCR/UIA/VISTA/rerank 定位链、`ReviewedInterfaceMemoryStore`、`continuous_task_session_v1`、PathGraph、Gate、Trace、原生 HTML/CSS/JavaScript 面板。

## Global Constraints

- Agent 负责理解、决策和任务推进；Operation 负责当前界面观察、定位、点击、输入、选择和滚动。
- 每个真实动作必须经过 Gate，并保存动作前证据、候选、点击点、Gate 决定和动作后验证。
- 学习资产、PathGraph 和历史坐标都不是执行授权。
- 任何候选必须携带当前 `capture_id`、viewport、source、bbox、click point 和 freshness。
- `final_submit`、`submit application`、`send application`、`complete`、最终确认和 payment 始终硬阻断。
- `Apply` 或 `Quick Apply` 只表示进入申请流程，不等于最终提交。
- 每次只执行一个字段或一个导航动作；动作后重新观察并验证，失败立即停止当前批次。
- 未知、歧义、敏感、证据不足和不支持的字段必须进入人工审核，不允许模型猜答案。
- Trace、报告和 stdout 不保存原始 PII；只保存字段名、策略、来源引用、值长度、哈希和脱敏预览。
- fixture 通过只能证明 fixture 覆盖；在真实页面执行前不得声称 live safe fill 已验证。
- 每个 checkpoint 完成后停止，提交证据并等待审核，不连续越过多个 checkpoint。

## Demo 最终验收

演示必须从真实、最新截图开始，并完成以下链路：

```text
岗位列表
  -> 按预算滚动并读取新岗位
  -> Agent 选择一个值得申请的岗位
岗位详情
  -> 读取到明确 reached_bottom 或可解释的安全停止
  -> Agent 根据完整详情作出申请决策
Quick Apply 入口
  -> Gate 放行进入申请流程
申请表单
  -> inventory 当前字段
  -> 自动填写已审核低风险字段
  -> 选择已审核选项
  -> 未知问题暂停并请求人工确认
  -> 继续下一步后重新 inventory
最终审核页
  -> 识别 final submit
  -> Gate 硬阻断
  -> safe_stop
```

最终证据必须同时满足：

- `submit_clicks=0`
- `final_submissions=0`
- 没有未经审核的敏感字段自动填写
- 每次动作使用当前 capture
- 每次成功都包含 effect verification
- Agent 决策、Gate 决定、Operation 结果和 Trace 路径可在面板中查看
- 至少完成 1 次完整 no-submit UAT；之后完成 5 次回归才讨论趋势

---

### Checkpoint 0: 固定基线与验收口径

**Files:**
- Create: `artifacts/benchmarks/generic_quick_apply_demo_manifest_v1.json`
- Create: `tests/test_generic_quick_apply_demo_manifest.py`
- Modify: `CURRENT_STATE.md`

**Interfaces:**
- Produces: `generic_quick_apply_demo_manifest_v1`
- Consumes: 现有导航读取、连续会话、表单 inventory、Gate 和 Trace 合约

- [x] **Step 1: 写失败测试，固定必需指标**

```python
def test_demo_manifest_requires_layered_metrics():
    manifest = load_demo_manifest()
    assert manifest["contract_version"] == "generic_quick_apply_demo_manifest_v1"
    assert manifest["final_submit_forbidden"] is True
    assert manifest["required_metrics"] == [
        "interface_identification",
        "agent_decision",
        "candidate_recall",
        "point_grounding",
        "gate_decision",
        "operation_dispatch",
        "operation_effect",
        "read_completion",
        "form_inventory",
        "safe_fill_effect",
        "dynamic_question_decision",
        "final_submit_guard",
        "full_no_submit_e2e",
    ]
```

- [x] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/test_generic_quick_apply_demo_manifest.py -q`

Expected: FAIL，因为 manifest 尚不存在。

- [x] **Step 3: 创建最小 manifest**

Manifest 必须记录起始 URL、允许动作、禁止动作、用户资料引用、当前简历引用、每层验收条件和输出目录，不保存 PII 原值。

- [x] **Step 4: 运行测试并记录基线**

Run: `uv run pytest tests/test_generic_quick_apply_demo_manifest.py -q`

Expected: PASS。`CURRENT_STATE.md` 必须明确 live safe fill、动态问题和 full no-submit E2E 的当前 attempted 值。

**Checkpoint pass:** 验收标准固定，所有未覆盖项显示 `not_covered`，没有总成功率。

---

### Checkpoint 1: 验证 Agent 能消费一个已审核界面资产

**Files:**
- Modify: `tests/test_agent_evidence.py`
- Modify: `tests/test_navigation_reading.py`
- Modify: `tests/test_navigation_reading_controller.py`
- Modify: `app/learn/agent_evidence.py`
- Modify: `app/agent/navigation_reading.py`

**Interfaces:**
- Consumes: `agent_evidence_context_v1`
- Produces: 只含语义动作的 `navigation_reading_decision_plan_v1`

- [x] **Step 1: 写失败测试，禁止 bbox-only 证据**

```python
def test_agent_rejects_control_without_semantics():
    context = reviewed_context_with_control({"bbox": {"x": 1, "y": 2, "w": 3, "h": 4}})
    with pytest.raises(ValueError, match="semantic"):
        build_navigation_reading_decision(context, goal="open selected item")
```

- [x] **Step 2: 运行相关测试**

Run: `uv run pytest tests/test_reviewed_interface_memory_execution.py tests/test_navigation_reading.py -q`

- [x] **Step 3: 补齐 Agent 可读投影验证**

每个可用控件至少需要 `control_id`、`semantic_name`、`purpose`、`allowed_actions`、`verification_rule` 和 `risk_class`。历史 bbox 只能作为学习证据引用，不进入 Agent 决策输出。

- [x] **Step 4: 重新运行测试**

Expected: PASS。

**Checkpoint pass:** Agent 能说明“当前是什么界面、有哪些可选动作、为何选择该动作”，输出中没有执行坐标。

---

### Checkpoint 2: 单界面当前截图快速重定位闭环

**Files:**
- Modify: `app/api/vision.py`
- Modify: `tests/test_vision_route.py`
- Modify: `tests/test_reviewed_interface_memory_execution.py`
- Modify: `scripts/run_operational_memory_fast_grounding_real_ab.py`
- Create: `tests/test_operational_memory_fast_grounding_probe.py`
- Create: `tests/fixtures/operational_memory_ambiguous_documentation.ps1`

**Interfaces:**
- Consumes: reviewed semantic locator + current screenshot/UIA/OCR evidence
- Produces: current-capture recognition plan with freshness and Gate-ready candidate

- [x] **Step 1: 增加唯一命中、歧义和 stale capture 测试**

```python
def test_fast_grounding_falls_back_when_current_candidates_are_ambiguous():
    result = resolve_reviewed_control_on_current_capture(candidates=two_equal_candidates())
    assert result["status"] == "fallback_required"
    assert result["reason"] == "ambiguous_current_candidates"
```

- [x] **Step 2: 运行目标测试**

Run: `uv run pytest tests/test_vision_route.py tests/test_reviewed_interface_memory_execution.py -q`

- [x] **Step 3: 完成默认关闭的快速路径**

只有当前 UIA/OCR 唯一命中、候选在当前 viewport 内且 Gate 证据完整时，才能跳过完整视觉模型；否则进入现有 OCR + VISTA + rerank 链。

- [x] **Step 4: 真实截图 dry-run**

Run: `uv run python scripts/run_operational_memory_fast_grounding_real_ab.py --dry-run --json`

Expected: 至少一个唯一命中走快速路径，一个歧义样本走完整链；不真实点击。

Evidence: Notepad 和 Python.org 唯一命中使用当前 UIA/OCR 候选并跳过 VISTA；受控 WPF 重复 `Documentation` 控件触发歧义回退并使用完整 VISTA + Gate dry-run 链。三者均未执行点击。WPF 证据只代表受控真实窗口，不代表自然网站歧义已经覆盖。

**Checkpoint pass:** 学习后不是盲目复用坐标，而是能在新截图中更快找到同一语义控件。

---

### Checkpoint 3: 多界面低风险导航闭环

**Files:**
- Modify: `app/agent/continuous_task_session.py`
- Modify: `app/agent/navigation_reading_controller.py`
- Modify: `tests/test_continuous_task_session.py`
- Modify: `tests/test_navigation_reading_controller.py`

**Interfaces:**
- Consumes: current observation + reviewed transition + current recognition plan
- Produces: verified destination observation or `needs_human_review`

- [x] **Step 1: 写失败测试，强制每次导航后重新观察**

```python
def test_verified_navigation_returns_to_observation():
    session = ready_session_with_current_decision("open_detail")
    updated = record_operation_result(session, verified=True, destination_observed=False)
    assert updated["status"] == "waiting_for_destination_observation"
```

- [x] **Step 2: 运行相关测试**

Run: `uv run pytest tests/test_continuous_task_session.py tests/test_navigation_reading_controller.py -q`

- [x] **Step 3: 补齐状态转换**

点击 dispatch 成功不等于导航成功；必须观察目标界面并匹配 `expected_destination_interface`。错误界面、弹窗或登录阻断必须 safe stop。

- [x] **Step 4: 运行 fixture 多界面 replay**

Run: `uv run python scripts/run_navigation_reading_replay.py --manifest artifacts/benchmarks/navigation_reading_replay_v1/manifest.json --out logs/benchmarks/navigation_reading_replay_checkpoint3 --json`

Evidence: `record_action_result` now enters
`waiting_for_destination_observation` and preserves the reviewed expected target
until a fresh observation arrives. A matching observation emits
`destination_observation_verified`; a mismatch emits
`destination_observation_rejected` and `safe_stop`. The recorded two-interface
replay passed both cases and reports Gate, dispatch, effect, and destination
observation separately at
`logs/benchmarks/navigation_reading_replay_checkpoint3/navigation_reading_replay_report.json`.

**Checkpoint pass:** 一条两界面链可复跑，Action、Gate、effect、destination observation 分开报告。

---

### Checkpoint 4: 无限列表滚动与岗位卡片读取

**Files:**
- Modify: `app/operation/reading.py`
- Modify: `app/agent/navigation_reading_live_runtime.py`
- Modify: `tests/test_navigation_reading_live_runtime.py`
- Modify: `tests/test_runtime_contracts.py`

**Interfaces:**
- Consumes: list-region locator, current item fingerprints, scroll budget
- Produces: new-item observations, `no_new_content`, `wrong_scope_detected`, or bounded stop

- [x] **Step 1: 写失败测试，dispatch 与 effect 分离**

```python
def test_scroll_dispatch_without_new_fingerprint_is_not_effect_success():
    result = verify_collection_scroll(before=["a"], after=["a"], dispatched=True)
    assert result["scroll_dispatch_success"] is True
    assert result["scroll_effect_success"] is False
```

- [x] **Step 2: 增加 wrong-scope 回归**

非目标 pane 明显变化时必须输出 `wrong_scope_detected=true` 并停止继续滚动。

- [x] **Step 3: 运行测试**

Run: `uv run pytest tests/test_navigation_reading_live_runtime.py tests/test_runtime_contracts.py -q`

Evidence: the focused plan verification passes `22 passed`. The read batch now
records item fingerprints, new-item observations, scroll dispatch, scroll
effect, and per-capture wrong-scope evidence separately. A dispatched scroll
with unchanged item fingerprints is not effect success; a changed non-target
pane produces a bounded `wrong_scope_detected` failure.

- [x] **Step 4: 运行受控真实滚动 smoke**

Run:

```powershell
uv run python scripts\run_navigation_reading_live_smoke.py `
  --suite configs\demos\navigation_reading_live_v2\suite.json `
  --out logs\smoke\navigation_reading_checkpoint4 `
  --max-steps 18 `
  --json
```

Status: complete on the controlled fixture. The first live attempt exposed a
reusable foreground-activation defect: one failed foreground-thread attachment
prevented the target application thread from being attempted. The loop now
isolates each attachment failure and strict foreground verification remains
intact. A visible Windows `新通知` window still caused the original bound HWND
to fail closed, so the rerun used the framework's own `POST /apps/open` path to
launch and bind a fresh Edge fixture window. Exact-HWND capture then succeeded
without dismissing the notification or bypassing verification.

The final report is
`logs/smoke/navigation_reading_checkpoint4_final2_20260803/navigation_reading_live_smoke_report.json`.
It records 15 actual-model decisions, 13 effect-verified executed actions, one
expected bounded read stop, and final safe stop across hub, incident, policy
modal, updates, and summary. Incident and updates each performed two
effect-verified scrolls, and completed branches were not repeated. Focused
window/navigation verification passes `57 passed`; full offline regression
passes `2407 passed, 1 skipped`. This is controlled fixture evidence, not a
general live-scroll reliability claim.

The later Checkpoint 5 full offline regression remains green at
`2416 passed, 1 skipped`.

**Checkpoint pass:** Agent 能读取当前岗位卡片、滚动后发现新卡片，并按预算停止；不能把 dispatch 写成滚动成功。

---

### Checkpoint 5: 岗位详情完整读取与申请决策

**Files:**
- Modify: `app/operation/reading.py`
- Modify: `app/gate/dataflow.py`
- Modify: `scripts/seek_speed_demo_runner.py`
- Modify: `tests/test_read_region_batch.py`
- Modify: `tests/test_seek_speed_demo_runner.py`

**Interfaces:**
- Consumes: detail container captures
- Produces: latest detail snapshot with terminal state

- [x] **Step 1: 写失败测试，`max_captures` 不算完整**

```python
def test_max_captures_is_not_read_complete():
    report = build_read_report(stop_reason="max_captures")
    assert report["read_complete"] is False
```

- [x] **Step 2: 测试状态分类**

分别断言 `still_reading`、`reached_bottom`、`max_captures`、`no_new_content`、`wrong_surface` 和 `blocked_surface`。

- [x] **Step 3: 运行测试**

Run: `uv run pytest tests/test_read_region_batch.py tests/test_seek_speed_demo_runner.py -q`

- [x] **Step 4: 确保申请决策只读取 latest snapshot**

旧卡片摘要和旧详情不得覆盖当前岗位完整详情。只有最新详情 snapshot 可进入 Agent suitability decision。

**Checkpoint pass:** Agent 的申请判断能引用完整当前详情；读取不完整时不会伪装成完成。

**Verified evidence (2026-08-03):** `read_region_batch_v1` now emits the
canonical read state and completeness separately. Only `reached_bottom` is
complete; `still_reading`, `max_captures`, `no_new_content`, `wrong_surface`,
and `blocked_surface` remain incomplete or blocked. The SEEK decision path
reads that result only from `runtime_detail_snapshot`, and the speed runner
does not call match when the latest detail is incomplete. Focused verification
passed `100 passed`; adjacent contract verification passed `58 passed`; full
offline regression passed `2416 passed, 1 skipped`.

---

### Checkpoint 6: Quick Apply 入口与最终提交语义分离

**Files:**
- Modify: `app/agent/continuous_task_session.py`
- Modify: `app/gate/danger.py`
- Modify: `app/api/action.py`
- Modify: `tests/test_continuous_task_session.py`
- Modify: `tests/test_final_submit_guard_fixtures.py`

**Interfaces:**
- Consumes: semantic action + active flow context
- Produces: `open_apply_flow` allowed decision or final-submit block

- [x] **Step 1: 写上下文测试**

```python
def test_apply_now_entry_is_allowed_but_final_review_is_blocked():
    assert classify_action("Apply now", context="job_detail") == "open_apply_flow"
    assert classify_action("Apply now", context="final_review") == "final_submit"
```

- [x] **Step 2: 覆盖 submit 文案和容器作用域**

覆盖 `Submit application`、`Send application`、`Complete`、`Confirm`、`Review and submit`、sticky footer 和 modal；全局 `Submit search` 不得误报最终提交。

- [x] **Step 3: 运行测试**

Run: `uv run pytest tests/test_continuous_task_session.py tests/test_final_submit_guard_fixtures.py -q`

- [x] **Step 4: 真实入口 dry-run**

只生成当前 recognition plan 和 Gate 决定，不点击。确认操作 taxonomy 是 `open_apply_flow`。

**Checkpoint pass:** 可以安全进入申请流程，同时 final submit 仍由硬规则阻断。

**Verified evidence (2026-08-03):** the execution API now combines selected
target evidence with semantic action and current surface context. `Apply now`
is allowed only as `open_apply_flow` on `job_detail_apply_entry`; the same text
is blocked as `final_submit` on `final_review_submit`. The live navigation
adapter forwards source interface, surface context, and active-flow state to
both dry-run and real execution requests. Focused verification passed `71
passed`; full offline regression passed `2418 passed, 1 skipped`. Step 4 used
the preserved ROI from a real SEEK job-detail page with the current VISTA-4B
model. The selected point `(99, 767)` is inside the visible `Quick apply`
button; Gate returned `semantic_action=open_apply_flow`,
`allowed_action_scope=active_job_detail_apply_entry`, and
`action_executed=false`. The report is
`logs/smoke/checkpoint6_apply_entry_no_click_20260803.json`. This is historical
real-page-pixel coverage, not a live-current website navigation claim.

---

### Checkpoint 7: 通用表单字段清单

**Files:**
- Create: `app/operation/form_inventory.py`
- Modify: `app/api/execute.py`
- Modify: `app/seek/form_inventory.py`
- Create: `tests/test_operation_form_inventory.py`
- Modify: `tests/test_seek_form_inventory.py`

**Interfaces:**
- Produces: `form_question_inventory_v1`
- Consumes: current form/modal scope and current OCR/UIA/vision evidence

- [x] **Step 1: 写字段类型测试**

覆盖 text、email、phone、textarea、radio、checkbox、select、file upload、disabled field 和 final action。

- [x] **Step 2: 写 ownership 测试**

相邻问题中重复的 `Yes/No` 必须归属正确问题；active form 外的控件必须排除；缺少当前 capture 的字段必须 invalid。

- [x] **Step 3: 运行测试**

Run: `uv run pytest tests/test_operation_form_inventory.py tests/test_seek_form_inventory.py -q`

- [x] **Step 4: 抽取通用 Operation 实现**

`app/seek/form_inventory.py` 只保留 SEEK 页面 evidence 转换，字段 grouping 和 ownership 进入通用 Operation。

- [x] **Step 5: 重新运行测试**

**Checkpoint pass:** 当前申请页可以列出完整字段、问题文本、选项、必填状态、局部控件和风险分类，不执行填写。

**Evidence (2026-08-03):** `form_question_inventory_v1` is implemented in the common Operation layer. Focused route and inventory verification passed `9 passed`; adjacent SEEK application, question, answer-plan, replay, and inventory verification passed `75 passed`; the full offline suite passed `2422 passed, 1 skipped`. Repeated options remain bound to their owning question, active-scope exclusions and capture freshness fail closed, and every result records `fill_attempted=false`, `submit_attempted=false`, and `artifact_is_authorization=false`.

---

### Checkpoint 8: 字段策略与 PII 脱敏

**Files:**
- Create: `app/agent/form_question_contracts.py`
- Create: `app/agent/form_answer_planner.py`
- Create: `app/gate/form_policy.py`
- Create: `tests/test_form_question_contracts.py`
- Create: `tests/test_form_answer_planner.py`
- Create: `tests/test_form_policy_gate.py`

**Interfaces:**
- Produces: `form_answer_decision_v1`
- Policy values: `auto_fill`, `derived_with_evidence`, `needs_user_review`, `blocked_sensitive`, `unsupported`, `final_submit`

- [x] **Step 1: 写策略矩阵测试**

姓名、审核后的 email/phone 可 `auto_fill`；salary、relocation、复杂 visa 为 `needs_user_review`；ethnicity、gender、disability、health、criminal history 为 `blocked_sensitive`；file upload 初始为 `unsupported`；最终按钮为 `final_submit`。

- [x] **Step 2: 写无证据拒绝测试**

```python
def test_unknown_question_never_gets_default_answer():
    decision = plan_form_answer(question=unknown_question(), evidence=[])
    assert decision["policy"] == "needs_user_review"
    assert decision["proposed_value"] is None
```

- [x] **Step 3: 写 PII 审计测试**

原始姓名、邮箱、手机号不得出现在 report、Trace、expected/actual 或 stdout JSON。

- [x] **Step 4: 运行测试并实现最小策略引擎**

Run: `uv run pytest tests/test_form_question_contracts.py tests/test_form_answer_planner.py tests/test_form_policy_gate.py -q`

**Checkpoint pass:** 每个字段都有可解释策略和证据来源，未知与敏感问题不会自动回答。

**Evidence (2026-08-03):** The common Agent planner emits `form_answer_decision_v1` and the policy Gate emits `form_action_gate_decision_v1`. Focused verification passed `26 passed`, adjacent inventory/SEEK/final-submit verification passed `55 passed`, and the full offline suite passed `2448 passed, 1 skipped`. Raw PII is absent from the plan report, nested Trace payload, expected/actual projections, and stdout JSON. A policy allow remains `execution_authorized=false` and still requires current grounding plus the real action Gate.

---

### Checkpoint 9: 单个文本字段 fixture 执行与效果验证

**Files:**
- Create: `app/operation/form_fill_executor.py`
- Create: `app/operation/form_fill_verification.py`
- Create: `tests/fixtures/general_form_live_site/index.html`
- Create: `tests/test_form_fill_executor.py`
- Create: `tests/test_form_fill_verification.py`

**Interfaces:**
- Consumes: allowed `form_action_gate_decision_v1` + current recognition plan
- Produces: `form_fill_action_result_v1`

- [x] **Step 1: 写 clear-existing 与输入测试**

要求 `clear_existing=true`，并验证输入后 value hash/length 与批准值一致。

- [x] **Step 2: 写失败效果测试**

dispatch 成功但页面 value 未变化时，`fill_effect_success=false`。

- [x] **Step 3: 运行测试并实现单动作执行**

Run: `uv run pytest tests/test_form_fill_executor.py tests/test_form_fill_verification.py -q`

- [ ] **Step 4: 本地真实 fixture smoke**

在本地浏览器真实填写一个无敏感信息的测试字段，随后观察并验证；不包含最终提交按钮点击。

**Checkpoint pass:** 第一个真实输入动作完整经过 Agent、Gate、Operation、Trace 和 post-observe 验证。

**Partial evidence (2026-08-03):** CP9A/CP9B common contracts are implemented in `app/operation/form_fill_executor.py`. Focused tests pass `12 passed`; adjacent policy/runtime verification passes `46 passed`. Step 4 remains open, so this is not live fixture fill, live safe fill, or end-to-end form evidence.

---

### Checkpoint 10: 下拉、单选和复选控件

**Files:**
- Modify: `app/operation/form_fill_executor.py`
- Modify: `app/operation/form_fill_verification.py`
- Modify: `tests/fixtures/general_form_live_site/index.html`
- Modify: `tests/test_form_fill_executor.py`
- Modify: `tests/test_form_fill_verification.py`

**Interfaces:**
- Produces: verified `select_option`, `select_radio`, `toggle_checkbox`

- [ ] **Step 1: 写失败测试**

覆盖两阶段下拉 `open -> re-observe -> select`、单选、复选、already selected 和重复标签歧义。

- [ ] **Step 2: 实现最小控件动作**

每次选择后重新读取 checked/selected 状态。重复标签无法由局部 question ownership 消歧时停止。

- [ ] **Step 3: 运行测试**

Run: `uv run pytest tests/test_form_fill_executor.py tests/test_form_fill_verification.py -q`

- [ ] **Step 4: 本地真实 fixture smoke**

真实选择一个 radio 和一个 dropdown；保存动作前后截图、Gate 和 effect Trace。

**Checkpoint pass:** 三类常用表单控件都能单步验证，不进行批量盲填。

---

### Checkpoint 11: 动态问题理解与人工确认记忆

**Files:**
- Create: `app/agent/form_question_understanding.py`
- Create: `app/agent/form_answer_policy_memory.py`
- Modify: `app/agent/reviewed_interface_memory.py`
- Create: `tests/test_form_question_understanding.py`
- Create: `tests/test_form_answer_policy_memory.py`
- Modify: `app/web_panel/learning_workflow_review.js`

**Interfaces:**
- Produces: normalized intents and reviewed policy scopes `one_time`, `workflow_class`, `site`, `global_profile`

- [ ] **Step 1: 写同义问法与反向极性测试**

`right to work`、`require sponsorship`、`work without sponsorship` 必须保持不同语义和 polarity。

- [ ] **Step 2: 写负反馈记忆测试**

人工更正后保存 question intent、scope、批准答案引用和 evidence hash，不保存页面坐标。

- [ ] **Step 3: 运行测试并实现**

Run: `uv run pytest tests/test_form_question_understanding.py tests/test_form_answer_policy_memory.py -q`

- [ ] **Step 4: 面板验证**

面板必须显示原问题、归一化意图、拟议答案来源、风险、审核选项；保存后立即刷新 Agent 证据投影。

**Checkpoint pass:** 已知问题可复用经审核答案，未知问题会暂停并让用户决定，不会靠 prompt 猜测。

---

### Checkpoint 12: 多步骤表单状态机

**Files:**
- Create: `app/agent/form_workflow_controller.py`
- Modify: `app/agent/continuous_task_session.py`
- Modify: `app/learn/application_interface_graph.py`
- Create: `tests/test_form_workflow_controller.py`
- Modify: `tests/test_continuous_task_session.py`

**Interfaces:**
- Produces one action: `fill_field`, `select_option`, `continue_next_step`, `request_user_review`, `safe_stop`

- [ ] **Step 1: 写多步骤测试**

覆盖 inventory、部分填写、人工暂停、Continue、进入新步骤重新 inventory、登录阻断、错误 surface、verification failure 和 final review。

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/test_form_workflow_controller.py tests/test_continuous_task_session.py -q`

- [ ] **Step 3: 实现单动作推进**

状态机不假定问题数量和顺序。每次 Continue 后都重新观察当前界面，不允许旧表单字段继续执行。

- [ ] **Step 4: 重新运行测试**

**Checkpoint pass:** 本地多步骤 fixture 可以从第一页走到最终审核页，并由 final-submit guard safe stop。

---

### Checkpoint 13: 面板完整技术演练

**Files:**
- Modify: `app/web_panel/panel.js`
- Modify: `app/web_panel/learning_workflow_review.js`
- Modify: `app/web_panel/interface_workflow_graph.js`
- Modify: `tests/js/learning_workflow_review.test.cjs`
- Modify: `tests/js/interface_workflow_graph.test.cjs`
- Modify: `tests/test_web_panel_route.py`

**Interfaces:**
- Displays: PathGraph、当前带框证据、Agent 决策、Gate、Operation effect、Trace 和 safe stop

- [ ] **Step 1: 写面板流程测试**

要求可从软件流程选择起点、查看当前界面证据、发起 dry-run、查看每层结果、处理中途人工确认并继续。

- [ ] **Step 2: 隐藏开发噪声**

默认不显示原始 JSON、旧 benchmark 控件和无关高级诊断；Trace 仍可按需展开。

- [ ] **Step 3: 运行 UI 测试**

```powershell
node --test tests/js/learning_workflow_review.test.cjs
node --test tests/js/interface_workflow_graph.test.cjs
uv run pytest tests/test_web_panel_route.py -q
```

- [ ] **Step 4: 手工完整操作面板**

使用现有真实学习资产完成：选择流程、选择起点、预览带框图、Agent dry-run、修正一个控件、保存、刷新证据、重新 dry-run。

**Checkpoint pass:** 不看 JSON 也能理解当前状态和失败层，面板操作不会卡死或显示旧证据。

---

### Checkpoint 14: 第一条 SEEK 受控 live safe-fill

**Files:**
- Modify: `scripts/seek_speed_demo_runner.py`
- Modify: `tests/test_seek_speed_demo_runner.py`
- Create: `docs/SEEK_NO_SUBMIT_UAT.md`

**Interfaces:**
- Reuses: generic inventory, answer policy, form executor and continuous session
- Keeps: SEEK extraction as adapter only

- [ ] **Step 1: 运行 GPU/模型/窗口 preflight**

检查 GPU 占用并选择批量；验证目标窗口、当前 capture、用户资料、简历引用、no-submit 开关、Gate fixture 和 Trace 目录。

- [ ] **Step 2: 真实打开 Quick Apply 并 inventory**

进入表单后停止，人工检查字段清单、风险策略和可填写字段。

- [ ] **Step 3: 只填写一个审核后的低风险文本字段**

每次执行前要求用户明确批准 live safe fill。执行后重新观察并验证 value effect。

- [ ] **Step 4: 检查 Trace 与 PII**

要求 Trace 中只有 hash/length/字段名，没有原始值。

- [ ] **Step 5: 运行相关回归**

Run: `uv run pytest tests/test_seek_speed_demo_runner.py tests/test_form_policy_gate.py tests/test_form_fill_executor.py tests/test_final_submit_guard_fixtures.py -q`

**Checkpoint pass:** `live safe fill attempted=1`，效果验证通过，`submit_clicks=0`；不扩大为完整 E2E 结论。

---

### Checkpoint 15: SEEK 单个表单步骤

**Files:**
- Modify: `scripts/seek_speed_demo_runner.py`
- Modify: `tests/test_seek_speed_demo_runner.py`
- Update: `docs/SEEK_NO_SUBMIT_UAT.md`

**Interfaces:**
- Consumes: current step inventory
- Produces: verified next-step observation

- [ ] **Step 1: 在真实表单处理允许字段**

逐字段执行，未知或敏感问题暂停。选择已有简历只在明确识别为已保存文档且用户批准后执行；OS file picker 仍标记 unsupported。

- [ ] **Step 2: 点击非最终 Continue/Next**

Action taxonomy 必须为 `continue_next_step`。Gate 放行后验证新步骤界面确实出现。

- [ ] **Step 3: 重新 inventory 新步骤**

禁止沿用前一步坐标、选项和问题清单。

- [ ] **Step 4: 保存 UAT 证据**

记录每个字段的 policy、Gate、effect、step transition 和 trace path。

**Checkpoint pass:** 一个真实表单步骤从 inventory 到下一步验证完整跑通，仍无最终提交。

---

### Checkpoint 16: 第一条完整 no-submit UAT

**Files:**
- Modify: `scripts/seek_speed_demo_runner.py`
- Modify: `docs/SEEK_NO_SUBMIT_UAT.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Produces: one trace-backed `full_no_submit_e2e` attempt

- [ ] **Step 1: 从岗位列表启动**

读取并滚动首页，选择一个岗位；完整读取详情后由 Agent 决定申请。

- [ ] **Step 2: 进入 Quick Apply**

确认当前岗位和入口，经过 Gate 后进入表单。

- [ ] **Step 3: 逐步骤处理表单**

自动处理审核后的低风险字段；未知问题请求人工确认；每步后重新 inventory。

- [ ] **Step 4: 在最终审核页停止**

识别 final submit，要求 `unsafe_prevented=true`、`real_submit_clicks=0`、`final_submissions=0`。

- [ ] **Step 5: 生成人工可审查报告**

报告按层输出 attempted/passed/failed/not_covered、失败分类、trace、截图和安全停止原因，不输出一个总成功率。

**Checkpoint pass:** 完成 1 次真实列表到最终审核页的 no-submit UAT，或清楚暴露唯一阻断层并安全停止。

---

### Checkpoint 17: 五次回归与一个 holdout 变体

**Files:**
- Create: `scripts/run_generic_quick_apply_demo_benchmark.py`
- Create: `tests/test_generic_quick_apply_demo_benchmark.py`
- Modify: `artifacts/benchmarks/generic_quick_apply_demo_manifest_v1.json`
- Modify: `docs/SEEK_NO_SUBMIT_UAT.md`

**Interfaces:**
- Produces: layered trend report, invalid fixtures, failures and trace paths

- [ ] **Step 1: 写 benchmark integrity 测试**

checksum mismatch、evidence missing 和 stale fixture 进入 invalid，不进入 pass/fail 分母；attempted=0 显示 `not_covered`。

- [ ] **Step 2: 运行五次受控 no-submit**

每次使用不同岗位或不同问题组合。失败必须归因到 evidence generation、Agent decision、candidate recall、grounding、Gate、Operation effect、state verification 或 blocker。

- [ ] **Step 3: 运行 holdout 变体**

选择未用于修正策略的另一条 Quick Apply 表单路径；holdout 结果不反向参与当轮调参。

- [ ] **Step 4: 运行 benchmark 测试**

Run: `uv run pytest tests/test_generic_quick_apply_demo_benchmark.py -q`

**Checkpoint pass:** 至少 5 个 attempted UAT 和 1 个 holdout 有完整分层证据；不使用“90% accuracy”或“SEEK E2E stable”。

---

### Checkpoint 18: Demo 收尾与项目文档同步

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_SUMMARY.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`
- Modify: `docs/SEEK_NO_SUBMIT_UAT.md`

**Interfaces:**
- Produces: one-command start, demo checklist, latest evidence links and known limitations

- [ ] **Step 1: 加入一条启动命令和一条 UAT 命令**

README 最前面说明如何启动 runtime/panel，UAT 命令必须默认 `--no-submit`。

- [ ] **Step 2: 整理面板演示顺序**

演示只保留：软件流程图、当前带框图、Agent 决策、Gate、操作效果、Trace 和人工确认。高级诊断折叠。

- [ ] **Step 3: 运行全部相关测试**

```powershell
uv run pytest tests/test_navigation_reading.py tests/test_continuous_task_session.py -q
uv run pytest tests/test_operation_form_inventory.py tests/test_form_answer_planner.py tests/test_form_policy_gate.py -q
uv run pytest tests/test_form_fill_executor.py tests/test_form_fill_verification.py tests/test_form_workflow_controller.py -q
uv run pytest tests/test_final_submit_guard_fixtures.py tests/test_seek_speed_demo_runner.py -q
node --test tests/js/learning_workflow_review.test.cjs
node --test tests/js/interface_workflow_graph.test.cjs
uv run pytest tests -q
```

- [ ] **Step 4: 运行最终启动检查**

启动 FastAPI 和 panel，检查 health、面板加载、流程选择、证据刷新和 Trace 展开。

- [ ] **Step 5: 记录最后结论**

明确区分 fixture-covered、dry-run-covered、live single-field、live single-step、full no-submit E2E 和 holdout。列出没有覆盖的 file upload、敏感问题和真实 final submit。

**Checkpoint pass:** 用户可以从面板完整展示学习资产如何帮助 Agent 决策并安全完成 no-submit 工作流，所有结论都有可复跑证据。

---

## 推荐执行节奏

| 阶段 | Checkpoint | 目标 | 预计集中时间 |
|---|---:|---|---:|
| A 基础闭环 | 0-3 | 证据可读、当前截图重定位、多界面导航 | 1-2 天 |
| B 读取能力 | 4-6 | 无限列表、详情长读、Apply/Submit 语义 | 1-2 天 |
| C 表单核心 | 7-10 | inventory、策略、文本和选择控件 | 2-3 天 |
| D 动态与多步 | 11-13 | 动态问题、状态机、面板完整演练 | 2 天 |
| E 真实验证 | 14-16 | 单字段、单步骤、完整 no-submit UAT | 1-2 天 |
| F 收尾 | 17-18 | 五次回归、holdout、文档和演示 | 1-2 天 |

合理总量是 8-12 个集中工作日。Checkpoint 9 后已经有第一个真实输入能力；Checkpoint 16 后才有第一条完整 demo 证据；Checkpoint 18 才算阶段性完成。

## 每轮固定汇报格式

每完成一个 checkpoint，只汇报：

- changed files
- 本 checkpoint 的 acceptance evidence
- attempted / passed / failed / invalid / not_covered
- trace path 和 screenshot path
- safety impact
- tests actually run
- remaining blocker
- 是否发生 live fill
- `submit_clicks` 和 `final_submissions`
