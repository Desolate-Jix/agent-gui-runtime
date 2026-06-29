# GUI Agent Runtime 分层架构

Last updated: 2026-06-29.

## 核心判断

执行模式不是 Workflow-first，而是 Agentic Loop-first。

陌生网页或软件里，下一个界面通常不可预测，所以系统不能依赖预写完整流程才能行动。默认执行闭环是：

```text
用户对话
-> Agent 理解目标并决定下一步意图
-> Operation observe 当前界面
-> Agent 基于当前界面继续判断
-> Gate 审核真实动作
-> Operation 执行
-> Trace 记录证据
-> 重新 observe
```

Workflow / PathGraph 是学习出来的可复用流程资产。有匹配资产时，Agent 可以选择它来加速和约束执行；没有资产时，Agent 继续动态探索。

## 五个核心层

### Agent

Agent 是对话入口和决策中心。

Agent 负责：

- 理解用户自然语言目标。
- 拆分当前任务。
- 管理、修改、版本化 prompt。
- 根据当前屏幕和任务历史决定下一步意图。
- 做内容判断，例如岗位是否匹配、表单答案是否可靠。
- 在权限、信息或安全边界不清楚时输出 `ask_user_required`。
- 选择已有 PathGraph；没有 PathGraph 时走动态探索。

Agent 不负责：

- 直接点击。
- 直接输入。
- 绕过 Gate 授权危险动作。
- 把旧截图坐标当作当前授权。

Prompt 是 Agent 层的一等资源：

```text
GET /runtime/agent_prompts
GET /runtime/agent_prompts/{prompt_id}
GET /runtime/agent_prompts/{prompt_id}/versions
GET /runtime/agent_prompts/{prompt_id}/versions/{version}
GET /runtime/agent_prompts/{prompt_id}/diff?from_version=...&to_version=...
POST /runtime/agent_prompts/{prompt_id}/versions
POST /runtime/agent_prompts/{prompt_id}/rollback
```

Prompt 模板以 `agent_prompt_template_v1` 存在于 `artifacts/agent_prompts`。保存和回滚都会写成新版本文件并写 trace，不覆盖 base 模板。当前默认模板包括：

- `job_suitability_full_jd_v1`：完整岗位详情审核。
- `agent_next_action_agentic_loop_v1`：Agentic Loop 下一步动作意图判断。

Human Review / Approval 不单独成层。它是 Agent decision 的一种输出：

```json
{
  "schema": "agent_decision_v1",
  "decision": "ask_user_required",
  "reason": "当前动作可能进入外部申请系统",
  "question": "是否允许继续打开站外申请页面？",
  "risk_level": "medium"
}
```

### Operation

Operation 是 framework 的操作能力层。它负责看和做，不负责业务判断。

Operation skills 包括：

- `observe_screen`
- `locate_element`
- `click_target`
- `type_text`
- `scroll_region`
- `read_region`
- `read_full_page`
- `detect_form`
- `bind_window`
- `verify_change`

Operation 输出的候选动作必须带证据，例如 `capture_id`、`viewport_size`、`source`、`bbox`、`click_point`、`freshness`。

代码入口：

```text
app/operation/
  skills.py
```

`GET /runtime/operation_skills` 返回基础 framework skill catalog；`GET /runtime/operation_skills?app_id=seek` 返回 SEEK profile skill 到通用 Operation skill 的映射。

当前迁移到 Operation 入口的实现包括：

- PathGraph available actions：`app.operation.path_graph`
- PathGraph step plan：`app.operation.step`
- visual asset matching：`app.operation.visual_asset_matching`
- long-read region batch：`app.operation.reading`
- UI diff verification：`app.operation.verification`
- region click execution：`app.operation.region_click`
- MouseTester semantic verification：`app.operation.mousetester`

旧 `app.execute` 兼容包已删除；新代码必须直接引用 `app.operation.*`。

### Gate

Gate 是动作安全层。它不判断任务价值，只判断动作现在能不能安全执行。

Gate 负责：

- 当前窗口验证。
- 坐标新鲜度验证。
- 目标 bbox 和 click point 验证。
- 候选目标歧义检测。
- 动作 taxonomy：`open_detail`、`open_apply_flow`、`fill_field`、`continue_next_step`、`final_submit`。
- scoped danger detection。
- final submit / send / confirm / payment 硬拦截。
- 任务级 policy 检查。

代码入口：

```text
app/gate/
  candidates.py
```

当前迁移到 Gate 入口的通用合同包括：

- action candidate freshness / target-at-point validation：`app.gate.candidates`
- bound window matching：`app.gate.window`
- action taxonomy：`app.gate.actions`
- scoped final submit / danger detection：`app.gate.danger`
- scroll safe point / precondition / effect validation / scope：`app.gate.scroll`
- latest detail snapshot dataflow：`app.gate.dataflow`
- contextual OCR normalization：`app.gate.ocr`

新的安全合同调用必须直接走 `app.gate.*`。

### Trace

Trace 是证据层，负责记录、审查、回放和学习输入。

Trace 记录：

- 用户目标。
- Agent prompt、prompt version、结构化输出。
- 当前截图、OCR、UIA、DOM、视觉理解。
- Operation 候选和执行结果。
- Gate allow/block 决策。
- 动作前后证据。
- 失败原因和回放输入。

Replay 不单独成层，它是 Trace 的能力。Trace 是证据，Replay 是用证据验证新 prompt、新 Gate、新 Operation skill 是否退化。

代码入口：

```text
app/trace/
  actions.py
  recorder.py
```

`record_trace_event()` 把 `trace_event_v1` 写入现有 bounded trace writer。
`app.trace.actions` 负责执行动作 trace 的写入策略，包括 `write_policy.trace=false` 时不写主 action trace，以及把 `execute_recognition_plan` 规范成 `execute_mode_plan_preview` 或 `execute_mode_click`。`app.api.action` 只保留薄包装，真实策略源头在 Trace 层。

### Workflow / PathGraph Asset

Workflow 和 PathGraph 是同一类东西的不同具体程度：

```text
Workflow = 抽象流程骨架
PathGraph = 带状态、证据、skill、Gate 条件和验证规则的具体 Workflow
```

它不是执行模式的必需入口，而是可复用资产。

PathGraph 应记录：

- states
- transitions
- state detectors
- operation skill bindings
- gate requirements
- success conditions
- failure conditions
- trace evidence

学习模式的目标就是从人工演示、Agent 探索和历史 Trace 中学习 PathGraph。

## 两种执行形态

### 陌生界面

```text
observe
-> Agent 判断下一步
-> Gate 审核
-> Operation 执行
-> Trace 记录
-> observe
```

这个形态不要求预先知道下一屏是什么。

### 已知界面

```text
Agent 选择匹配 PathGraph
-> PathGraph 给出候选 state / transition / skill
-> Operation 生成当前候选
-> Gate 审核
-> Operation 执行
-> Trace 记录
```

PathGraph 是导航资产，不是动作授权。每一步仍然必须基于当前观察和 Gate 决策。

## Profile 位置

具体网站或软件不应该进入主架构。它们应该进入 App Profile。

App Profile 负责记录：

- app_id 和显示名称。
- 可用 Operation skills。
- 必须遵守的 Gate contracts。
- Agent prompt requirements。
- Trace requirements。
- 已学习 PathGraph / interface map / visual asset / skill asset。
- 禁止动作和用户确认边界。

SEEK、GitHub Issues、Python Docs Search、Windows 软件都应该是 profile，而不是主架构本身。

Profile 现在是 runtime 一等资源：

```text
GET /runtime/architecture
GET /runtime/app_profiles
GET /runtime/app_profiles/{app_id}
GET /runtime/operation_skills
GET /runtime/operation_skills?app_id=seek
GET /runtime/gate_contracts
GET /runtime/gate_contracts?app_id=seek
```

面板不再只通过路径显示 profile。学习产物回放页会根据 PathGraph 的 `app_id` 调用 runtime API，显示对应 profile 的执行模型、Operation skills、Operation 层映射、Gate contracts、Gate 层模块、Workflow assets、Learning assets 和 policy。

## 面板表达

本地面板需要按同一套架构表达 PathGraph。

Navigation Path / PathGraph 卡片显示 Agentic Loop 条带：

```text
Agent -> Operation -> Gate -> Trace -> PathGraph asset
```

GraphNode 详情必须说明：

- 执行模型是 Agentic Loop-first。
- PathGraph 是导航资产，不是动作授权。
- 真实动作仍需重新观察并通过 Gate。
- 当前图对应的软件 Profile，例如 `artifacts/app_profiles/seek_app_profile_v1.json`。

Artifact Replay 页还需要显示 App Profile 摘要。加载 SEEK PathGraph 时，面板会自动填入 `seek`，调用 `/runtime/app_profiles/seek`，并展示 full-JD Agent review、final submit forbidden、外部 ATS ask_user_required 等 profile policy。

同一页面还需要显示 Agent Prompt 查看/编辑器。加载 `job_suitability_full_jd_v1` 后，面板展示变量、输出合同、安全说明和完整 prompt 模板；同时可以列出版本、加载选中版本、对比 diff、保存新版本或把旧版本回滚成一个新版本。

这样用户在看学习产物时不会把 PathGraph 理解成硬编码脚本，也不会把旧坐标或旧截图误认为可直接执行的动作授权。

## 目录目标

```text
app/
  runtime_architecture/
    contracts.py

  agent/
    prompts.py
    decision_engine.py

  operation/
    skills.py

  gate/
    candidates.py
    actions.py
    contracts.py
    danger.py
    scroll.py
    dataflow.py
    ocr.py
    window.py

  trace/
    actions.py
    recorder.py

artifacts/
  app_profiles/
    seek_app_profile_v1.json
  templates/
    app_profile_template_v1.json
```

当前阶段先落合同和 profile 资产，不强行搬迁既有模块。

## 迁移顺序

1. 让 README 和架构文档先回到通用 runtime 叙事。
2. 增加 `runtime_architecture` 合同，固定五层边界。
3. 把 SEEK 经验注册成 app profile。
4. 同步面板 GraphNode/PathGraph 展示，让学习产物按 Agentic Loop-first 语义呈现。
5. 逐步把 `app.seek` 中可复用能力拆到 Operation skill、Gate contract、Trace audit。
6. 用第二个网站或 Windows 软件验证：陌生界面先走 Agentic Loop，跑过后学习 PathGraph。

## 不变安全原则

- Prompt 可以改，输出合同不能乱。
- PathGraph 可以指导，不能授权危险动作。
- Apply / Quick Apply 是 `open_apply_flow`，不是 final submit。
- Final submit / send / confirm / payment 默认硬阻止。
- 任何真实点击必须有当前截图证据、候选证据、Gate 决策和执行后验证。
