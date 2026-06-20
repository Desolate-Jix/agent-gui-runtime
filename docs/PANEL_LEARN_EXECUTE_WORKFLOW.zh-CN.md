# 面板 Learn / Execute 操作流程

这份说明记录测试面板里两套工作区的实际按钮流程：学习模式负责把界面变成路径图，执行模式负责从路径图里选下一步并执行。打开/绑定、截图、Trace 审计是全局系统工具，两个模式都会保留。

## 0. 全局准备

1. 打开面板：`http://127.0.0.1:8000/panel`。
2. 左侧点 `打开 / 绑定`。
3. 如果目标窗口已经打开，先点 `列出窗口`。
4. 在 `Bindable windows` 里选择目标窗口。
5. 点 `绑定窗口`。

期望结果：

- API 响应 `success: true`。
- 顶部状态显示 `正常`。
- `App ID`、应用名、状态提示会同步到后续学习/执行页面。

如果需要新开应用或 URL：

1. 在 `Launchable apps` 里选择配置好的应用，或填写 `URL`。
2. 点 `打开应用`。
3. 等窗口出现后再点 `列出窗口` 和 `绑定窗口`。

## 1. 学习模式

左侧先切到 `学习模式`。学习模式的目标是生成和校验可复用路径图，不执行真实点击。

### 1.1 整屏理解 / Learn Fast

按钮路径：

1. 左侧点 `整屏理解 / Learn Fast`。
2. 检查 `App name`、`State hint`、`Model profile`。
3. 需要实时截图时保持 `Capture live` 勾选。
4. 点 `快速建图`。

期望响应：

- API 响应 `success: true`。
- 返回界面用途、区域、可操作元素和初版路径图。
- Trace 写入整屏理解阶段。
- 导航路径图卡片出现页面节点和候选控件。

失败时先看：

- API 响应里的 `error.details`。
- Trace 里的模型 raw output 和 parse error。
- 截图是否在窗口稳定之前被抓取。

### 1.2 坐标校准 / Learn Deep

按钮路径：

1. 左侧点 `坐标校准 / Learn Deep`。
2. 点 `深度校准路径图`。

期望响应：

- API 响应 `success: true`。
- 请求语义为 `agent_mode=learn`、`learn_depth=deep`。
- 后端使用最近的 Observe trace，对路径图里的重要子节点做坐标校验。
- 返回每个子节点的 bbox、click point、confidence、role/name 修正、missing/duplicate 修正。
- 生成坐标框 overlay 和 locate trace。

这个阶段不需要用户提供单个目标；它的目标是“校验所有可见路径图控件”。

### 1.3 学习产物回放

按钮路径：

1. 左侧点 `学习产物回放`。
2. 在 `Artifact preset` 选择产物，例如 `SEEK`、`Wikipedia`、`GitHub Issues`、`Python Docs Search`、`Table Directory`。
3. 点 `加载产物`。

期望响应：

- API 响应 `success: true`。
- 响应包含 `contract_version: artifact_replay_load_v1`、`graph_id`、`app_id`、`action_template_count`。
- 页面显示路径图结构摘要、动作表格、skill、安全策略和共享 PathGraph 大图。

这个页面回答：“学习产物里学到了什么？”

### 1.3.1 SEEK 申请证据检查

入口仍在 `学习产物回放` 页面里。

按钮路径：

1. 确认 `Application fill record path` 指向 `logs/smoke/seek_apply_live_92822270_20260620_b/application_fill_record.json`，或换成当前测试 run 的 `application_fill_record.json`。
2. 确认 `Final review audit path` 指向对应的 `final_review_audit.json`。
3. 确认 `Application flow artifact path` 指向对应的 `seek_application_flow_artifact_v1`，例如 `artifacts/seek/learned_seek_application_flow_92822270_20260620.json`。
4. 点击 `加载申请证据`。

期望响应：

- API 响应 `success: true`。
- 响应合同为 `seek_application_evidence_panel_load_v1`。
- 摘要显示 record/audit/artifact 路径、岗位、状态、雇主问题数量、求职信长度、截图数量、action trace 数量、vision trace 数量。
- 当 `audit_decision=pass_stopped_before_final_submit`、`artifact_is_authorization=false`、`final_submit_forbidden=true`、`final_submissions=0` 同时成立时，状态显示 `safe review boundary`。
- 填写字段表格展示默认 resume、cover letter 和每个 employer question 的填写值/证据；如果 employer question 是 `0/0`，这是显式合法状态，不要补造答案。

这个页面回答：“这次站内申请到底填了什么？有没有真的停在最终提交前？”

### 1.4 路径图安全验证

入口 A：

1. 在 `学习产物回放` 点 `带入安全验证`。
2. 面板会切到 `路径图安全验证` 并带入路径图。

入口 B：

1. 左侧直接点 `路径图安全验证`。
2. 填 `Runtime PathGraph path`。

按钮路径：

1. 点 `生成验证计划`。
2. 检查动作表格里只保留安全动作。
3. 点 `Dry-run 下一步`。

期望响应：

- API 响应 `success: true`。
- `/execute/available_actions` 返回可验证动作。
- `/execute/step` 返回 `status=planned` 或验证状态。
- `dispatch_low_level_executed=false`，除非你明确勾选低层派发。
- 返回 `path_graph_runtime_state_v1`。
- PathGraph 卡片高亮当前节点、当前动作边和已完成边。

安全验证会过滤 input、Apply、Submit、Delete、Save changes 等写入或高风险动作。

## 2. 执行模式

左侧先切到 `执行模式`。执行模式的目标是让上层 agent 每次调用一步：先看当前状态和可用动作，再选择一个动作执行，然后根据返回结果决定下一步。

### 2.1 当前状态 / 可用动作

按钮路径：

1. 左侧点 `当前状态 / 可用动作`。
2. 检查 `应用名`、`状态提示`、`Runtime PathGraph 路径`。
3. 如果需要让 agent 先看当前屏幕，点 `理解当前页面`。
4. 点 `刷新可用动作`。

期望响应：

- `理解当前页面` 返回当前页面摘要、可见控件和当前状态提示，但不写入学习 PathGraph。
- `刷新可用动作` 返回 `contract_version: available_actions_response_v1`。
- `available_actions.actions[]` 中包含 `action_template_id`、`kind`、`low_level_action_type`、`skill_ref`、`from_state_id`、`to_state_id`、`transition_id`、`allowed/forbidden` 和原因。

这里的动作不只包括点击，也包括 scroll、input、read、filter、sort、table row open 和 guard blocked action。

### 2.2 路径图任务运行

按钮路径：

1. 左侧点 `路径图任务运行`。
2. 填 `Goal`、`Runtime PathGraph path`、`Task template`、`Max items`、`Max steps`。
3. 点 `开始任务`。
4. 每次只点一次 `执行下一步`。

期望响应：

- `开始任务` 会初始化 run summary、timeline、当前状态和 PathGraph 卡片。
- 每次 `执行下一步` 都只调用一个 Execute step。
- 响应包含 `contract_version: execute_step_response_v1`、`path_graph_action_context_v1`、`path_graph_runtime_state_v1`、`low_level_action_type`、`verification.status` 和 `execute_step_trace_path`。
- Timeline 显示 action、skill、low-level action、from/to state、trace。
- PathGraph 同步高亮当前节点、当前 transition、已完成 transition 或失败 transition。

这个页面回答：“agent 连续调用 Execute，一步一步能不能完成目标？”

### 2.3 精准定位

按钮路径：

1. 左侧点 `精准定位`。
2. 填 `Goal`，例如 `点击登录按钮`。
3. 先点 `识别点击预览`。
4. 检查 overlay 和候选坐标。
5. 坐标正确且风险可接受时，再点 `识别执行点击`。

期望响应：

- 预览阶段是 `dry_run=true`，只生成候选、坐标和 overlay，不真实点击。
- 执行阶段必须经过 `pre_click_decision_v1`。
- 真实点击后必须有 post-click verification 和 action trace。

如果 Gate 拒绝，先看拒绝原因、candidate score、bbox/click point 和 fallback plan，不要绕过 Gate。

### 2.4 点击 Gate

按钮路径：

- `识别点击预览`：识别目标并生成预览，不点击。
- `识别执行点击`：识别目标，通过 Gate 后真实点击。
- `坐标点击预览`：使用手填坐标生成预览，不点击。
- `坐标执行点击`：使用手填坐标，通过 Gate 后真实点击。

所有真实点击都必须留下 input goal、截图/OCR 证据、候选、confidence、click point、pre-click decision、post-click verification 和 trace。

### 2.5 输入

按钮路径：

1. 左侧点 `输入`。
2. 填 `Text`、`X`、`Y`。
3. 选择是否 `Click before typing`、`Clear existing`、`Submit Enter`。
4. 默认保持 `Dry run` 勾选。
5. 点 `Type text`。

期望响应：

- dry-run 只生成计划，不真实输入。
- 取消 `Dry run` 后才会真实输入。
- 真实输入前必须确认目标窗口、坐标和输入内容无风险。

## 3. 推荐闭环测试顺序

1. `打开 / 绑定`
2. 切到 `学习模式`
3. 点 `整屏理解 / Learn Fast`
4. 点 `快速建图`
5. 点 `坐标校准 / Learn Deep`
6. 点 `深度校准路径图`
7. 点 `学习产物回放`
8. 选择一个 preset，点 `加载产物`
9. 点 `带入安全验证`
10. 点 `生成验证计划`
11. 点 `Dry-run 下一步`
12. 切到 `执行模式`
13. 点 `路径图任务运行`
14. 点 `开始任务`
15. 连续点 `执行下一步`
16. 检查 PathGraph 高亮、Timeline 和 API 响应。

跑通后说明：学习模式产物能被执行模式消费，执行模式能把每一步结果返回给上层 agent，由 agent 决定下一次调用。

## 4. 模式边界

学习模式负责：“把界面变成地图。”

执行模式负责：“从地图里找下一步并执行。”

后端 Execute API 保持单步，不把连续多步 orchestration 塞进 `/execute/step`。连续任务由上层 agent 或面板 harness 在每次响应后再次调用。
