# 单界面资产、动态内容与类规则设计

## 目标

把 Learn Mode 固定为一条通用、可人工修订、可组成多界面流程、可由 Agent 安全试跑的资产生成链：

```text
识别单界面
→ 人工修正框、语义和内容类型
→ 保存到软件级界面库
→ 识别下一个界面
→ 人工或 Agent 建议建立操作连线
→ 编译 Agent 上下文
→ fresh observe + Gate + Operation 单步试跑
→ Trace 验证目标界面
```

SEEK、浏览器视频网站和音乐软件只是验证样本，不得进入通用契约字段名。

## 核心资产

### SingleInterfaceAsset

每个界面是独立、可复用的主资产：

- `interface_id`
- `application_identity`
- `display_name`
- `surface_type`
- `state_signature`
- `evidence`
- `fixed_anchors`
- `dynamic_slots`
- `controls`
- `regions`
- `verification_rules`
- `blockers`
- `review`

截图、编号图、融合图和人工修订图由该界面独占。保存时不得复用其他节点的证据。

### InterfaceTransition

界面跳转单独保存：

- `transition_id`
- `source_interface_id`
- `source_control_id`
- `operation`
- `target_interface_id`
- `preconditions`
- `success_conditions`
- `failure_conditions`
- `risk_level`
- `review_status`
- `verification_evidence`

人工连线是事实来源。Agent 自动连线只能是 `suggested`，人工接受后才能成为 `human_confirmed`。

### ApplicationInterfaceGraph

软件级路径图只引用界面和转换 ID，不复制单界面内容。它是可复用资产和审阅视图，不是执行授权。

### LiveObservation

动态值只存在于当前捕获：

- `capture_id`
- `interface_id`
- `observed_at`
- `dynamic_values`
- `read_failures`
- `freshness`

长期资产保存“字段含义和读取方法”，不得把学习时的动态文本当作当前事实。

## 固定与动态内容

每个区域或控件增加：

- `content_behavior`
  - `fixed_structure`
  - `fixed_label`
  - `dynamic_value`
  - `dynamic_collection`
  - `user_input`
  - `ephemeral`
  - `sensitive_dynamic`
  - `ignore`
- `agent_usage`
  - `identity_anchor`
  - `action_target`
  - `decision_signal`
  - `display_only`
- `read_policy`
  - `on_interface_match`
  - `on_demand`
  - `never`
- `agent_description`

默认策略是按需读取。界面匹配只读取固定锚点；任务决策需要时才读取动态字段。

## Agent 上下文

Agent 不直接读取编辑器 JSON，而读取编译后的：

```json
{
  "contract_version": "agent_interface_graph_context_v1",
  "application_identity": {},
  "current_interface": {},
  "identity_anchors": [],
  "latest_dynamic_values": {},
  "available_actions": [],
  "reachable_interfaces": [],
  "verification_rules": [],
  "blockers": [],
  "execution_contract": {
    "current_capture_required": true,
    "fresh_grounding_required": true,
    "historical_coordinates_forbidden": true,
    "gate_required": true,
    "post_action_verification_required": true
  }
}
```

历史 bbox 只用于定位先验和人工审阅。真实动作必须重新截图、重新定位并经过 Gate。

## 面板

### 左栏

- 软件选择器；
- 该软件的界面缩略图库；
- 软件级分支路径图；
- 新增界面、连接界面、返回全部路径。

### 中栏

- 原图、模型图、融合图、人工修订图；
- 拖动、缩放、添加、删除框；
- 点击路径节点原子切换该节点自己的证据；
- 不显示上一节点残留。

### 右栏

- 界面名称、类型和审核状态；
- 框的名称、角色、Agent 描述；
- 固定/动态类型、Agent 用途和读取策略；
- 可用操作和目标界面；
- 转换验证、安全级别和试跑状态。

路径图复用 Execute Mode 的画布语言：平移、缩放、选中、分支、节点详情和状态颜色。学习节点使用截图缩略图，不复用 Execute 授权状态或历史点击坐标。

## 类规则

类规则采用两层 Adapter：

1. Host Adapter：`browser`、`native_window`；
2. Content Adapter：`chat`、`mail_workspace`、`media_player`、`employment_workflow`、`generic`。

`employment_workflow` 是跨网站和跨宿主的求职任务类规则，不是 SEEK 专用规则。它内部区分岗位列表、岗位详情、申请表单、申请复核以及 mixed/ambiguous 状态。浏览器只作为 Host Adapter；站点名称和 URL 不足以激活求职规则。

模型输出页面类别和结构信号；程序必须用当前截图的 OCR/UIA/视觉拓扑验证。应用名只能是弱证据。

类规则只能提供：

- 候选召回先验；
- 容器/项目父子关系约束；
- 重复列表、媒体卡片、播放器控制、浏览器外壳、岗位卡片、申请字段和申请复核的验证规则；
- 错误候选抑制；
- 缺失候选补召回策略。

类规则不得：

- 复用旧截图几何；
- 直接生成点击点；
- 放宽 Gate；
- 根据应用名强行套用；
- 未经回归和人工批准进入生产。

人工修正先进入候选规则注册表。只有跨同类样本通过、反例无退化、人工批准后才可激活。

## 验收

1. 单界面可独立保存、加载、修订并按软件归档。
2. 固定和动态内容可由模型建议、人工覆盖。
3. 动态值只来自最新捕获，历史值不参与当前决策。
4. 两个界面可通过人工选择控件和操作建立转换。
5. 路径图支持分支、返回和循环，并展示截图缩略图。
6. Agent 上下文能唯一表达当前界面、最新信息、可用动作和目标界面。
7. 至少一条低风险转换完成 fresh grounding、Gate、Operation、Trace 单步验证。
8. 多个求职网站的列表、详情、表单和复核样本优于 generic 基线，普通表单、电商列表和结账复核反例不误激活。
9. 原有九界面回归无新增污染。
10. final submit、send、confirm、delete、payment 仍不可授权。
