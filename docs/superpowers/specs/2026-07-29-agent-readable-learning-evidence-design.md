# Agent 可读学习证据设计

## 目标

把以下约束提升为核心架构约束：

> 所有学习证据都必须以 Agent 能理解、能据此决策，并能交给 Operation 重新定位为前提设计。学习资产只提供语义和历史证据，不提供执行授权。

现有截图、识别框和 UI hierarchy 主要服务人工审核。它们缺少稳定的内容语义、读取时机、动作意图、目标界面和验证条件，不能直接作为 Agent 的操作记忆。

## 分层职责

- Agent：读取语义证据，拆分任务并选择下一步意图。
- Operation：基于当前截图、OCR、UIA 和视觉定位重新解析目标。
- Gate：在每次真实动作前检查目标、风险、歧义和新鲜度。
- Trace：记录输入目标、证据、候选、决策和动作后验证。
- Workflow / PathGraph：保存界面及跳转关系，但不授权执行。

## Agent Evidence Contract

每个界面证据必须回答：

1. `identity`：当前界面是什么，如何确认。
2. `responsibility`：这个界面承担什么任务。
3. `content`：哪些内容固定，哪些动态，哪些只在需要时读取。
4. `actions`：Agent 可以考虑哪些语义操作。
5. `transitions`：操作成功后预计进入哪个界面或状态。
6. `verification`：如何判断操作成功。
7. `safety`：哪些操作禁止、需要人工确认或必须经过 Gate。
8. `evidence_refs`：原图、融合图和 Trace 在哪里，供审查而非直接点击。

Agent 上下文不包含历史 bbox、click point 或实际坐标。定位信息由 Operation 在当前 capture 上解析。

`agent_evidence_context_v1` 是只读派生投影，权威来源始终是版本化界面资产和人工审核记录。投影不能独立编辑后反向覆盖源资产。`evidence_refs` 只允许作为审计引用，Agent 加载器不得自动展开引用文件并重新注入历史坐标。

动作分类采用 fail-closed：未知动作类型、未知控件绑定和未知 schema 都不能进入 `available_actions`。危险动作别名在归一化后仍进入 `forbidden_actions`，不能通过把 `submit_application`、`confirm_purchase` 或 `place_order` 改写成普通点击绕过 Gate。

## 生命周期

- `recognition_candidate`：只有视觉或 OCR 识别结果。
- `saved_unreviewed`：已保存，但语义尚未人工确认。
- `reviewed`：人已确认框、内容或跳转描述。
- `agent_usable`：满足 Agent Evidence Contract 的最低字段。
- `runtime_verified`：通过 Execute dry-run 或受控动作验证。

旧证据缺少语义时只能进入 `recognition_candidate` 或 `needs_human_review`，不能自动升级成 `agent_usable`。

## 动态内容

动态区域只持久化：

- 区域语义；
- `read_policy`；
- Agent 用途；
- 当前读取方法。

动态值必须来自最新 observe，敏感值只能保留长度、哈希或脱敏预览。历史动态值不能作为当前事实。

## 兼容策略

旧 `ui_hierarchy` 会被投影为只读 `legacy_recognition_candidates`。这些候选帮助人工补语义，但不会自动出现在可执行动作列表。

完整的 `content_descriptors`、人工确认的 controls、工作流 transition 和安全规则才会进入正式 Agent 语义上下文。

## 可用性门槛

`agent_usable` 至少要求：

- 有清晰界面描述；
- 有一个固定身份锚点或当前状态；
- 每个可考虑动作都有语义说明和目标控件；
- 跳转动作有目标界面和成功验证；
- final submit / send / confirm / payment 保持禁止或需要明确人工确认；
- 当前定位与 Gate 仍是强制条件。

缺项必须在 `readiness.missing_fields` 中明确列出。
