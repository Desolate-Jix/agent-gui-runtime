# 学习模式设计

更新日期：2026-07-07

## 2026-07-07 更新：学习模式两轮分栏识别流程合同

用户已确认学习模式前半段必须按固定流程推进，不能再围绕单张截图做局部 bbox 修补。权威流程合同记录在：

- `docs/LEARN_MODE_TWO_PASS_PIPELINE_CONTRACT.zh-CN.md`

后续实现、调试和验收必须以该合同为准：

```text
绑定 / 截图
-> 第一次模型调用：整屏分栏
-> 栏精准定位
-> 第二次模型调用：按栏识别内容
   -> 顶栏 / 侧栏 / 底栏：直接编号定位
   -> 中间栏：二次分区后编号定位
-> OCR / 视觉 / 执行定位融合
-> 学习草稿
-> 只读 PathGraph 预览
-> 人工审查 / 修改
```

关键纠偏：

- 第一次模型调用只做上下左右中栏和弹窗/浮层分栏，不编号按钮和卡片。
- 栏精准定位必须覆盖完整视觉栏位；栏之间允许紧贴，不需要保留固定间隔。
- 按钮间距只属于栏内编号/分组策略，不能用来缩小栏 bbox。
- 顶栏、侧栏、底栏在栏内直接编号；中间主内容必须先二次分区，再对子区编号。
- 每次真实界面失败必须先归类为通用流程失败，例如 `region_bbox_too_narrow`、`sidebar_items_missing`、`main_subregion_split_failed`、`card_parent_child_failed`，不能把单图 heuristic 当作主策略。
- 每次开始新识别必须清空当前学习草稿、路径图、界面详情和融合框的旧结果；历史结果只能显示在历史区。
- 不可操作的 review-only 区域也必须进入融合截图审查框；不可执行不等于不显示。
- 进度条必须由证据推进：没有编号图、精准定位、融合结果或 PathGraph 草稿证据时，不能显示完成。
- 每次改识别策略后必须先跑 Apple Music 保护已有较好结果，再跑第二个界面验证通用性；第二个界面暴露的问题必须回到通用 invariant 修复，不能污染 Apple Music 或写成单图补丁。
- Codex 必须目检生成 overlay 后再汇报效果；没有目检时只能说脚本产物已生成，不能说识别变好。

当前 `app.learn.recognition.two_stage` 仍包含 parser / heuristic 驱动的 scaffold，可作为临时 display/review 工具和回归材料，但不能代表最终学习模式主流程。

## 2026-07-03 更新：重做学习模式识别前半段

用户已确认新的方向：执行模式当前完整度较高，不能为了学习模式重构而改变执行模式模型、Operation、Gate、Trace 或 final-submit 安全边界。学习模式要清理的是前半段“整屏理解 + 定位”路径；后半段学习产物分析展示、Learning Draft Review、DraftGraph Preview、PathGraph candidate 和 promotion validation 继续保留。

新设计记录在：

- `docs/superpowers/specs/2026-07-03-learning-recognition-rebuild-design.md`
- `docs/superpowers/plans/2026-07-03-learning-recognition-rebuild-plan.md`
- `docs/LEARN_RECOGNITION_PARSER_AND_GROUNDING.zh-CN.md`

新的学习识别主线：

```text
Capture bound window
-> Observe evidence bundle
-> Parse screen inventory
-> Classify inventory items
-> Select actionable/form-field candidates
-> Build ROI crops
-> Ground locally
-> Restore coordinates
-> Validate evidence
-> Generate learning_template_draft_v1
-> Human review
-> PathGraph candidate
```

关键约束：

- Parser 只是可插拔候选来源，不能授权点击。
- OCR-only 普通文本、标题、段落、代码块、只读卡片默认是 `readable`，不能进入 grounding。
- `semantic_region_only` 中等置信 bbox 默认不能进入点击坐标层。
- Grounding 只处理 `actionable` / `form_field` 候选。
- ROI crop / zoom 后必须保存 coordinate transform，并能 replay。
- Validator 必须检查 OCR/UIA/DOM/OmniParser/vision evidence、point/bbox、screenshot freshness、danger zone、final-submit blocker。
- 学习草稿和 PathGraph candidate 仍然是 display/review-only，不是 Execute 授权。

允许用于学习模式实验的模型限定为 12B 以下或工具型 parser，不覆盖执行模式 profile。候选包括 OmniParser 作为 screen parser、Qwen3-VL 8B 做页面结构理解、UGround 2B/7B 和 GUI-Actor 3B/7B 做 grounding/verifier、ShowUI 2B 做 trial/对比。任何实验都必须记录 raw input/output、model config、screenshot checksum、parsed result 和 failure taxonomy。

90% 目标必须拆成分层指标衡量，例如 `actionable_classification`、`non_actionable_rejection`、`grounding_point_inside_target`、`coordinate_transform_replay`、`pathgraph_candidate_validation`。样本不足时显示 `not_covered`，不能包装成模型准确率、点击成功率或端到端成功率。

当前 benchmark 已开始从纯 fixture-only 过渡到 recorded-output ingestion：manifest 可通过 `recorded_parser_output_path` 加载已有 Learn Fast 模型 trace 派生的 parser 输出，也可通过 `recorded_grounding_output_path` 加载已有 Learn Deep 坐标校准 trace 派生的 grounding 输出。该阶段只证明记录输出可以进入统一 parser / validator / draft 链路，不能证明模型可靠性；`actual_parser_call` / `actual_grounding_call` 仍需后续单独覆盖。

本文记录 `agent-gui-runtime` 的学习模式设计。学习模式必须服务于安全执行和可复盘决策，不能绕过现有点击前闸门，也不能让历史坐标直接替代实时窗口校验。

## 1. 设计目标

学习能力分为两种一等模式：

1. `exploration_learning`：自我探索模式。目标是主动认识一个应用或页面的状态空间。
2. `path_recording_learning`：点击后路径记录模式。目标是把每次真实点击后的状态转移、证据、验证结果记录下来。

现有 `instruction_learning` 不再作为第三条平行主线理解。它更适合作为 `path_recording_learning` 的一个“提升结果”：当某条真实路径被证明稳定、可验证、可复用时，可以从路径记录中生成 `learned_instruction_v1`。

## 2. 模式一：自我探索

`exploration_learning` 用于没有明确单步用户目标时，让 runtime 或上层 agent 安全地认识当前界面。

### 2.1 适用场景

- 新应用首次接入，需要知道有哪些页面、按钮、菜单、输入框和导航路径。
- 已绑定窗口，但用户还没有给出具体点击目标。
- 需要构建一个“应用状态图”，用于后续任务规划。
- 需要找出哪些控件会打开弹窗、切换标签、进入下一页或改变主要内容。

### 2.2 核心循环

```text
bind window
-> observe_screen
-> extract safe action candidates
-> classify risk
-> locate candidate
-> dry-run gate
-> optionally execute low-risk action
-> observe_screen again
-> compare before/after state
-> write state node and transition edge
-> stop, backtrack, or continue within limits
```

### 2.3 输出

自我探索输出的是界面地图，不是可直接复用的点击指令。

建议合同：

- `exploration_session_v1`
- `interface_state_v1`
- `exploration_action_candidate_v1`
- `state_transition_edge_v1`
- `exploration_policy_decision_v1`

建议目录：

```text
artifacts/local-learning/exploration/{session_id}/
  exploration_session.json
  state_nodes/
    {state_id}.json
    {state_id}.png
  transitions/
    {transition_id}.json
  traces/
  overlays/
```

### 2.4 状态节点

`interface_state_v1` 应记录：

```json
{
  "contract_version": "interface_state_v1",
  "state_id": "uuid",
  "app": {
    "app_name": "edge",
    "process_name": "msedge.exe",
    "window_title": "Example - Microsoft Edge"
  },
  "state_signature": {
    "title_signature": "example",
    "ocr_signature": [],
    "uia_signature": [],
    "visual_hash": "...",
    "layout_hash": "..."
  },
  "screen": {
    "image_path": "artifacts/local-learning/exploration/.../state.png",
    "width": 1280,
    "height": 720
  },
  "summary": {
    "screen_summary": "settings page",
    "state_hint": "left settings sidebar and main settings content"
  },
  "controls": []
}
```

### 2.5 探索动作候选

每个候选都要先被分类，再决定是否允许探索。

风险等级建议：

- `safe_dry_run_only`：只允许定位和生成证据，不真实点击。
- `safe_click_allowed`：低风险动作，可在深度限制内真实点击。
- `requires_user_confirmation`：可能改变数据、提交信息、关闭窗口或打开外部副作用。
- `blocked`：删除、支付、发送隐私信息、安装、授权、关闭关键窗口等。

候选字段建议：

```json
{
  "contract_version": "exploration_action_candidate_v1",
  "candidate_id": "uuid",
  "label": "Settings",
  "role": "button",
  "goal": "open settings",
  "risk_class": "safe_click_allowed",
  "risk_reasons": [],
  "evidence": {
    "ocr": [],
    "uia": [],
    "vision": [],
    "bbox": {"x": 10, "y": 20, "w": 80, "h": 32},
    "click_point": {"x": 50, "y": 36}
  }
}
```

### 2.6 安全规则

- 默认先做 dry-run，不真实点击。
- 真实探索点击必须仍走 `POST /action/execute_recognition_plan`。
- 不能使用 `POST /action/execute_confirmed_point` 作为自主探索捷径。
- 每次真实点击前必须有截图、候选、bbox、点、gate 结果和 pre-click decision。
- 每次真实点击后必须重新 observe，并记录状态是否改变。
- 探索必须有深度限制、动作数量限制、时间限制、回退策略和黑名单。
- 遇到疑似提交、删除、支付、发送、授权、关闭窗口、文件操作、隐私输入，一律拒绝或请求用户确认。

## 3. 模式二：点击后路径记录

`path_recording_learning` 是被动学习。它不主动选择动作，而是在每次真实点击后，把“为什么点击、点了哪里、点前点后发生了什么、是否验证成功”记录成路径图。

### 3.1 适用场景

- 用户或 agent 正在执行一个真实任务。
- 每次点击都已经通过 gated action API。
- 需要保留完整轨迹，方便复盘、回放、稳定性评估和后续学习。
- 需要把成功路径提升为可复用指令或测试样本。

### 3.2 核心循环

```text
before action:
  current state snapshot
  goal
  recognition plan
  pre-click decision

execute action:
  selected click point
  action trace

after action:
  post screenshot
  verification
  new observe result
  state diff

write:
  path event
  transition edge
  evidence bundle
```

### 3.3 输出

点击后路径记录输出的是真实执行轨迹。

建议合同：

- `runtime_path_graph_v1`
- `path_click_event_v1`
- `verified_transition_v1`
- `learning_promotion_candidate_v1`

建议目录：

```text
artifacts/local-learning/path-runs/{run_id}/
  path_graph.json
  events/
    {event_id}.json
  screenshots/
    before_{event_id}.png
    after_{event_id}.png
    diff_{event_id}.png
  crops/
  traces/
```

### 3.4 点击事件

`path_click_event_v1` 建议字段：

```json
{
  "contract_version": "path_click_event_v1",
  "event_id": "uuid",
  "run_id": "uuid",
  "timestamp": "2026-06-07T00:00:00Z",
  "from_state_id": "state_a",
  "goal": {
    "original": "点击设置",
    "model": "Click Settings"
  },
  "target": {
    "label": "Settings",
    "bbox": {"x": 10, "y": 20, "w": 80, "h": 32},
    "click_point": {"x": 50, "y": 36},
    "coordinate_source": "pre_click_decision_v1.selected_click_point"
  },
  "decision": {
    "allowed": true,
    "reasons": [],
    "candidate_id": "candidate_settings",
    "confidence": 0.91
  },
  "execution": {
    "action_executed": true,
    "dry_run": false,
    "approved_plan_id": "..."
  },
  "verification": {
    "passed": true,
    "methods": ["screenshot_diff", "semantic_post_click_verification"]
  },
  "to_state_id": "state_b",
  "artifacts": {
    "recognition_trace_path": "logs/traces/vision/...",
    "action_trace_path": "logs/traces/actions/...",
    "before_image_path": "...",
    "after_image_path": "...",
    "diff_image_path": "..."
  }
}
```

### 3.5 与路径图的关系

路径图必须由结构化事件确定性生成。

AI 可以：

- 翻译节点标签。
- 总结页面状态。
- 总结失败原因。

AI 不能：

- 发明节点。
- 发明边。
- 发明点击点。
- 发明验证结果。
- 把未验证点击升级为成功路径。

## 4. 从路径记录提升为指令学习

当某条点击后路径记录满足稳定条件时，可以生成 `learned_instruction_v1`。

### 4.1 提升条件

至少满足：

- 真实点击执行成功。
- 点击后验证通过。
- 目标与用户意图一致。
- 当前窗口身份可校验。
- 点击点在目标 bbox 内。
- 点前/点后截图、trace、crop、diff 都存在。
- 不属于危险动作或外部副作用动作。

更高质量的提升条件：

- 同一 goal 重复成功多次。
- selected point 漂移小。
- OCR/UIA/视觉证据稳定。
- post-click verification 稳定。
- 不依赖单次偶然坐标。

### 4.2 指令学习资产

```text
artifacts/local-learning/instructions/{learned_instruction_id}/
  learned_instruction.json
  source_path_event.json
  path_graph.json
  source_window.png
  pre_action.png
  post_action.png
  diff.png
  target_crop.png
  context_crop.png
```

`learned_instruction_v1` 应保存：

- 原始 goal 和模型侧 goal。
- app/window/state signature。
- target bbox、click point、coordinate source。
- OCR/UIA/vision evidence。
- 来源 path event。
- 来源 trace。
- 验证结果。
- 复用约束。

复用仍然必须：

- 验证 goal。
- 验证 app/window。
- 验证窗口尺寸或尺寸 bucket。
- 验证点击点边界。
- 最好重新截图并做图像/OCR/结构签名匹配。
- 执行后继续做 post-click verification。

## 5. 两种模式如何协同

```text
exploration_learning
  主动发现状态和候选动作
  输出 interface map
  低风险动作可形成 transition edge

path_recording_learning
  被动记录真实任务点击
  输出 verified runtime path graph
  成功稳定路径可提升为 learned_instruction_v1

instruction reuse
  从 verified path 中派生
  只能在实时校验通过后复用
```

建议统一使用同一套状态节点和边：

- `state_id`
- `state_signature`
- `transition_id`
- `from_state_id`
- `to_state_id`
- `source`: `exploration` / `execution` / `instruction_reuse`
- `confidence`
- `verification`

这样探索地图、真实路径、指令复用不会成为三套互不兼容的数据。

## 6. API 草案

第一阶段可以先只做文档和数据落盘，不急着加完整 API。

后续 API 可分为：

```text
POST /learning/exploration/start
POST /learning/exploration/step
POST /learning/exploration/stop
GET  /learning/exploration/{session_id}

POST /learning/path_runs/start
POST /learning/path_runs/{run_id}/events
GET  /learning/path_runs/{run_id}
GET  /learning/path_runs

POST /learning/promote_instruction
GET  /learning/instructions
GET  /learning/instructions/{id}
```

最小可实现切片：

1. 在每次 `execute_recognition_plan` 真实点击后写 `path_click_event_v1`。
2. 写 `path_graph.json`。
3. 面板 Trace 或导航路径图能打开该路径记录。
4. 再做 `promote_instruction`，从已验证 path event 生成 `learned_instruction_v1`。

## 7. 验收标准

自我探索模式第一阶段：

- 只 dry-run。
- 能从 `observe_screen` 生成候选动作列表。
- 能对候选动作打风险标签。
- 能生成 `interface_state_v1`。
- 不真实点击任何危险动作。

点击后路径记录第一阶段：

- 每次真实点击都有一条 `path_click_event_v1`。
- 事件包含 before/after、trace、gate、point、verification。
- 未验证点击不会标成成功。
- 路径图能从事件确定性生成。

指令提升第一阶段：

- 只允许从 verified path event 提升。
- 提升记录能定位回来源 path event。
- 复用失败时回到普通识别流程，不静默点击历史坐标。

## 8. 当前建议的下一步

当前第一步 MVP 先把整屏理解变成路径图入口：`POST /vision/observe_screen` 返回 `screen_map_v1`，前端现有导航路径图卡片直接消费 `screen_map.candidates`，从 Observe 阶段就能看到当前状态、候选动作、风险等级和预期效果。

之后再实现 `path_recording_learning` 的最小落盘，因为它不会改变 agent 的决策能力，只增强审计和学习素材。

建议顺序：

1. 在 `observe_screen` 中生成 `screen_map_v1`。
2. 让现有路径图卡片从 `screen_map.candidates` 渲染候选动作。
3. 定义 `path_click_event_v1` schema。
4. 在 `execute_recognition_plan` 成功真实点击后写事件。
5. 把现有面板导航路径图保存格式对齐到 `runtime_path_graph_v1`。
6. 做 MouseTester 一次真实成功点击，确认事件完整。
7. 再考虑 `exploration_learning` 的 dry-run 原型。
## 2026-06-07 更新：Observe Path Map Trace

第一步 MVP 现在不只是在 Observe 页面生成 `screen_map_v1`，也会把同一份地图保存在 observe trace 里。`/panel/inspect_trace` 会把它解析成 `Path Map` 阶段，Trace Inspector 详情里可以直接看到路径候选、候选框 bbox、click_point 观察证据和原始 JSON。

这仍然不是可执行点击路径。`screen_map` 只负责“当前界面有哪些可能的路”；真正点击前仍然需要 `locate_target` 精准定位和 `execute_recognition_plan` 的 Gate。

## 2026-06-07 更新：Sectioned Screen Map

`screen_map_v1` 现在会先划分页面区域，再把候选动作挂到区域上。典型区域包括 `page_header`、`promo_strip`、`main_content`、`lower_content` 和 `floating_overlay`。如果整屏视觉模型只返回顶部导航控件，runtime 会从高置信 OCR 正文文本补充 `ocr_text_actions`，让正文卡片和按钮先进入地图，后续再由 `locate_target` 精准确认。
