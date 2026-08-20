# Reviewed Workflow Asset v2 设计

## 目标

把现有流程从“审核图可供 Agent 参考”推进为一条可验证的主链：

```text
Learning → Human Review → Semantic Workflow Compilation → Verified Replay → Recovery
```

v2 是新资产，不迁移、不包装、不自动激活任何 v1 memory、旧 PathGraph 或旧运行记录。

## 权威状态

- 人工审核权威源：服务端持久化的 `single_application_workflow_review_v1`。
- 编译权威源：重新从服务器加载的 workflow 文件及其实算 SHA-256；不信任浏览器提交的节点、边或 hash。
- 发布权威源：`runtime_state/reviewed-workflow-assets-v2/registry.json`。
- 执行权威源：当前窗口、当前 capture、当前 grounding、Gate 和 action 后的新 observation。
- 历史截图和 reference ROI 只能作为定位先验，不能授权点击。

## 资产合同

顶层合同为 `reviewed_workflow_asset_v2`：

- `asset_id`
- `application`
- `source_review_lineage`
- `entry_state_id`
- `states[]`
- `transitions[]`
- `safety`
- `lifecycle`

对象以规范 JSON 的 SHA-256 内容寻址。规范化规则固定为 UTF-8、`ensure_ascii=false`、`sort_keys=true`、紧凑 separators；状态、转移、anchor 和 verification rule 按稳定 ID 排序。`created_at`、registry revision 和对象自身 hash 不进入内容 hash。

## Application scope

只接受 `identity_status=resolved` 的应用身份。Web 应用必须声明 canonical origin/domain 和是否允许外站；native 应用必须声明稳定 executable/product identity。禁止把 HWND、PID、当前坐标或临时窗口标题编译进资产。

## Source review lineage

编译必须验证：

- source workflow 文件存在且 SHA-256 与 registry 当前记录一致；
- 至少一个真实界面节点为 `human_approved`；
- 每个可回放源节点满足 `reviewed_by_human=true`；
- `reviewed_revision_hash == current_revision_hash` 且非空；
- 节点 evidence SHA 与当前文件一致；
- edge 语义、目标和安全条件完整；
- 任一 workflow 修改都会产生新的 source hash 和资产 hash。

未学习的 placeholder 可以编译为 `stop_boundary`，但不能提供动作、grounding 或自动执行能力。

## State

State 只保存稳定语义：

- `state_id`
- `source_node_id`
- `state_type`
- `display_name`
- `identity_anchors[]`
- `grounding_profile`
- `allowed_transition_ids[]`
- `availability=reviewed|stop_boundary`

State 中禁止 `click_point`、`actual_point`、`screen_point`、`window_handle`。Reference bbox/ROI 必须标记 `reference_only=true`，运行时必须重新定位。

## Transition

每个 transition 必须包含：

- 稳定 `transition_id`、source/target state；
- `semantic_action`；
- memory/action/element 引用或可审计 locator anchor；
- preconditions；
- expected effect；
- post-action verification；
- recovery policy；
- risk policy。

首个可验证回放里程碑只允许 `open_detail`、`open_apply_flow`、`back`、`close_modal`。`read` 和 `scroll` 需要各自的 effect contract、scope verification 与可信 replay envelope，本轮与 `fill_field`、`continue_next_step` 一样在编译、资产校验和 replay 入口统一 fail-closed，避免把 click-style verifier 错用于读取或滚动。

以下语义及别名永远拒绝自动执行：

```text
final_submit, submit_application, send, confirm, payment, purchase, delete,
open_external_apply
```

## Preconditions

所有可执行转移固定要求：

- 当前 observation 与 capture；
- capture ID、screenshot SHA 和 viewport 一致；
- 当前 target bbox 与 click point；
- click point 位于 bbox；
- confidence 与 score margin 达到策略阈值；
- 当前 source state 唯一解析；
- `POST /action/execute_recognition_plan` 返回允许的 pre-click/Gate 决策；
- real execution 不得复用与当前 capture 不一致的 approved plan。

## Expected effect 与 verification

视觉变化本身不是成功。每条转移至少有一个语义成功规则，例如：

- target state identity；
- same-origin URL；
- 必要 marker/region 出现；
- 指定容器内容变化或到达底部；
- 非目标 pane 保持稳定。

验证必须使用 action 后的新 capture。失败不得推进状态，也不得盲目重复动作。

## Recovery

首版只实现有限、低噪声恢复：

- stale capture：重新 capture 后重新解析；
- target not found：最多一次 fresh grounding；
- post-action failure：只观察当前状态，不重复原点击；
- destination mismatch、foreground change、unexpected origin：立即 safe stop 并返回人工审核；
- recovery 次数固定上限 1。

所有失败输出结构化、非授权的 `recovery_decision_v1`。本里程碑不建立 recovery-feedback 持久化权威层；只有在 server-issued selection、证据绑定、junction-safe publication 和跨进程 single-writer 都被证明后才能增加该层。

## Registry

v2 使用独立目录：

```text
runtime_state/reviewed-workflow-assets-v2/
  objects/<sha256>.json
  registry.json
```

Registry 使用 `expected_registry_revision` CAS。对象不可原地修改；重复发布同一 hash 幂等，语义改变生成新对象和 revision event。

## API 与面板

新增独立 workflow v2 API，不复用单界面 `/memory/reviewed_interfaces/publish`：

- compile：只编译并返回 blocked reasons；
- publish：CAS 激活对象；
- preview：只读投影，永不调用执行 API；
- replay：只接受已发布对象，仍必须经过 current capture、grounding、Gate 和 post verification。

面板复用现有 workflow graph/evidence/step audit，只增加 v2 状态、hash、blocked reason、Compile、Publish 和 Replay Preview，不创建第二套前端权威状态。

当前面板接线和纯离线合成 SEEK E2E 已完成；生产 current-observation capture 与 live execute orchestrator 仍缺失。Preview 不能执行，replay adapter 的每次 action request 只允许一个 attempt。

## SEEK MVP

新合成 fixture 表达：

```text
homepage --open_detail--> detail --open_apply_flow--> apply_entry_stop_boundary
```

必须同站、无 fill、无 upload、无 Continue/Next、无 final submit。该 fixture 用于合同和离线 replay，不含真实求职资料、岗位档案或截图。

## 完成判据

1. 新资产可从当前人工审核 workflow 编译、内容寻址、发布和加载。
2. 旧资产不会被迁移或隐式激活。
3. Offline replay 能解析状态、选择唯一 transition、验证 Gate/operation/post-state，并生成 recovery。
4. Approved plan capture lineage 不一致时不会点击。
5. 面板可显示 compile/publish/preview 状态和 node/edge evidence。
6. 合成 SEEK 三状态路径通过端到端测试，所有危险动作保持 blocked。

当前 1–6 已在纯离线合同范围满足。真实 GUI replay 不属于该完成判据；`read`、`scroll`、fill、upload、Continue 和 final-submit 继续 fail closed，直到生产 orchestrator 和对应 effect contract 完成。
