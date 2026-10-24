# 使用当前 Agent（0.1.7）

[English](CURRENT_AGENT_MODE.md) · [执行指南](../EXECUTION_GUIDE.zh-CN.md)

状态：执行版 **0.1.7**，2026-10-24。CLI、配置别名与 `CurrentAgentClient` 已纳入交付制品。源码同连接 7-Zip 20 步通过；独立安装态计算器五次点击、取消负控与清理通过。详见[发布记录](../releases/EXECUTION_017_20261024.md)与[源码实机证据](../verification/CURRENT_AGENT_LIVE_20261024.md)。旧 0.1.6 安装器不包含该新增封装。

## 模式职责

已连接的主 Agent 读取 Runtime 原始截图，逐次定位目标、判断结果；Runtime 绑定截图与请求，检查窗口身份、新鲜度、取消和输入授权，单次派发原动作并返回回执。保持同一持久 MCP 连接，同一时间只有一个桌面输入所有者。

支持的点击闭环无需独立 Runtime 视觉或 Decision API、本地模型权重或视觉子 Agent，仍依赖承载 Agent 的图像能力与模型服务，并消耗相应额度；不代表完全离线或零成本。Runtime 不凭模型名称推断视觉能力，不在路线不可用时静默改用其他来源，也不把截图自动转发给其他模型。

两个主要选择是 **使用当前 Agent** 与 **使用外部模型 API**。既有 `local` 与 `agent_delegate` 路线保留为高级选项。模式选择作用于新会话，不替换已冻结、仍在等待的请求来源。

## 连接并声明能力

使用已准备好的 Windows API／Agent Python 环境，推荐 Python 3.12。首次准备依赖可能下载软件包：

```powershell
.\scripts\setup_instant.ps1 -RecognitionSource agent_current -DataDirectory "D:\AgentReviewInstantData"
```

在 0.1.7 安装目录或对应源码目录启动持久 UTF-8 JSONL 入口：

```powershell
.\.venv-agent\Scripts\python.exe .\scripts\execution_client.py --current-agent --data-dir "D:\AgentReviewInstantData" --client-name "my-agent-client" --client-image-transport supported --client-current-vision supported --allow-actions
```

`--allow-actions` 是明确的输入开关，须与实际操作者授权一致；省略时连接不具备动作权限。客户端能力声明不授予输入。`my-agent-client` 这样的名称只标识客户端，不证明能够看图。

准备动作前，`image_transport` 与 `current_vision` 必须同时为 `supported`。省略时为 `unknown`；`unknown` 或 `unsupported` 仍允许检查状态，但阻止依赖该能力的动作。只有已连接的 Agent 确实能接收并读取原图时，才声明 `supported`。

新入口拒绝混用 `--luna-api`、不同的 `--recognition-source`、`--api-profile`、`--decision-profile`、`--delegate-profile`、`--model-directory`、`--prepare-models` 和 `--administrator`。新适配层仅支持普通权限会话：既有 UAC 桥会重新构建子进程环境，无法保证本模式的 Decision 隔离；旧管理员路线保留。可同时显式给出 `--recognition-source agent_current`。旧的显式 `--recognition-source agent_current` 路线保留，包括可选的 Decision 配置，不自动选择新适配层。省略模式仍默认 `local`，既有 API 路线保持原行为。

## 生成 MCP 条目

以下 0.1.7 便利别名，在当前 Runtime 目录生成 `mcp-config.local.json` 和 `mcp-config.local.toml`：

```powershell
.\.venv-agent\Scripts\python.exe .\scripts\configure_instant_mcp.py --current-agent --python "$PWD\.venv-agent\Scripts\python.exe" --data-dir "D:\AgentReviewInstantData"
```

生成的是标准 `agent-review-instant` 服务器，参数为 `--recognition-source agent_current`；不建立连接、不调用服务、不修改全局 Codex／MCP 设置，也不重载已连接客户端。两种配置均在该服务器的环境中设置 `AGENT_GUI_DECISION_PROFILE=""`，覆盖继承的 Decision 配置；正式维护的 `InstantSession` 与 `DecisionService` 加载器将此空值视为禁用。持久适配层则从自己的子进程环境副本中移除该变量，均不修改父进程／全局环境。合并条目时保留其他服务器，并明确重新连接。生成器不伪造 `ClientVisionCapabilities`，也不启用输入；既有 `--enable-local-input` 仍为明确的宿主输入开关，每个调用方还须通过能力和输入门禁。

新别名在写入任何输出前，拒绝 API、Decision、委派、本地模型参数、`--administrator` 以及不同的显式识别来源。省略别名时，保留旧来源选择、管理员路线、继承 Decision 配置的行为和 `local` 默认校验，不自动选择回退路线。

## 调用流程

`CurrentAgentClient` 继承 `ExecutionClient`，复用其 MCP 连接和回执校验。JSONL 入口提供明确的 `agent_prepare`、`agent_resolve`、`agent_continue`、`agent_status`、`agent_cancel`、`agent_verify` 和 `agent_complete` 动作，分别管理原命令身份、定位请求与截图，以及新的外层控制请求 ID。

以下为消息形状，`123`／`456` 必须替换为本会话发现的实际窗口句柄／进程 ID。逐条检查响应后，才发送依赖它的下一条：

```jsonl
{"request_id":"discover-1","command":{"kind":"discover"}}
{"request_id":"select-1","command":{"kind":"select","handle":123,"process_id":456}}
{"action":"agent_prepare","request_id":"click-1","command":{"kind":"step","operation":"execute_recognition_plan","request":{"goal":"Open Settings","click_kind":"single"}}}
```

后续消息依赖新响应与实际读到的原图，不提前准备坐标：

1. 在同一会话中发现并选择实际目标窗口，检查 ready／status 结果、客户端能力和输入权限。
2. 使用 `agent_prepare` 提交基础点击命令，一次提交原命令并等待其新定位请求。结果仍为 `running`、`pending`、`result_unknown` 或还需图像时，使用 `agent_status`，不重交点击。
3. 只有阶段为 `awaiting_grounding` 且包含 `current_agent.original_image` 时才 resolve。实际读取其 `image_path` 保存的原始 PNG，按 `grounding.v1` 返回定位结果，精确对应 `current_agent.pending_grounding_request_id`、`capture_id` 和 `image_size`；坐标为截图像素。目标不存在、歧义、能力不支持或错误时，如实使用对应状态。
4. 使用 `agent_resolve` 校验结果，再用 `agent_continue` 继续同一原命令；resolve 本身不点击。不能改用独立 `grounding_execute`，也不能重交原点击。
5. 在 `verification_required` 阶段检查动作回执与 `current_agent.verification_image`，再用 `agent_verify` 记录主 Agent 判断（`success`、`failure` 或 `uncertain`）。实际派发输入后，`success`／`failure` 必须将 `evidence.request_id` 绑定到 `current_agent.verification_request_id`，`evidence.sha256` 绑定原结果图摘要；上游提供截图 ID 时，还须以 `evidence.capture_id` 绑定。适配层重验保存的文件与摘要；这只核对证据关联，不证明调用方实际理解了图像，也不授予下一次输入。
6. 判断后再准备下一次新动作，或用 `agent_complete` 标记任务完成。`agent_cancel` 与 `agent_status` 引用已跟踪的原命令。`agent_complete` 仅为本地完成标记；`{"action":"finish"}` 或 EOF 才关闭 JSONL 会话并执行清理，须检查最终 `finished` 事件和 `cleanup_verified` 结果。

回复包括顶层 `status` 与 `current_agent` 会话快照，后者含 `phase`、`connection_active`、`capability_status`（`eligible` 或 `unavailable`）、原命令／当前／pending 请求 ID、截图信息、`verification_image`／`verification_request_id`、客户端能力、输入权限、核验和完成状态。`eligible` 只代表声明满足条件，不证明实际识图；返回的 `receipt` 保留原 Runtime 精简回执。应使用结构化 ID，不凭传输成功标志推断任务完成。

`{"action":"agent_status"}` 读取已跟踪动作。将本次 `grounding.v1` 对象作为 `result` 提交给 `agent_resolve`，等待 `grounding_ready` 后，使用 `{"action":"agent_continue"}`。结果图缺失时保持 `verification_required`，继续只读状态，不重放输入。`{"action":"agent_verify","verdict":"uncertain"}` 不要求图像，仍阻止后续输入。已证明 `action_executed=false` 的失败／取消可据回执判断；`success` 不能把 failed／rejected 执行转为成功。实际任务完成且终态判断已接受后，发送 `{"action":"agent_complete"}`，再发送 `{"action":"finish"}` 并检查清理。prepare／resolve／continue／status／cancel 可给出可选外层 `request_id`；省略时适配层分配新 ID 或回读已跟踪的 pending 回执。回执仍 pending 时，显式 status ID 必须匹配原 pending ID。verify／complete 不接受外层请求 ID；不能替换已冻结定位结果内的身份。

传输结果为 pending 时读取原请求 ID。等待到期不等于取消，也不证明未输入；不得重发输入延长等待，未知输入不得重放。页面导航、滚动或布局变化后，应使用新截图，不复用坐标。

新适配层的输入入口限定为受管理的基础点击流程。兼容的底层消息仅有 `discover`、`select`、`capture`、`read_text` 与 `instant_status`／`instant_result`／`instant_image`；`select` 要求动作权限，且仅限空闲或已核验的动作阶段。本地 `read_text` 仍有自己的 OCR 依赖，不能替代主 Agent 实际读取原图。其他底层输入、原始定位／控制或计划消息会被拒绝，不会绕过流程转发。既有命令仍可通过原来的明确路线使用，不表示它们已进入新适配层支持范围。

## 能力矩阵

本表分别记录代码合同、适配层与验收状态。“离线”指 schema、状态／回执校验或模拟连接检查，不意味着承载 Agent 可脱离服务运行。源码实机覆盖 7-Zip 基础点击 20 步；独立安装态覆盖计算器五次点击与取消，均不能扩展为其他动作或 Amadeus 验收。

| 能力 | 现有底层协议 | 新当前 Agent 适配层 | 离线检查范围 | 新适配层实机 |
| --- | --- | --- | --- | --- |
| 点击 | `step/execute_recognition_plan`、Agent 定位及原命令明确续行 | 支持基础点击闭环：原图→resolve→continue→调用方判断 | 能力准入，请求／截图／图像绑定，状态与防重放检查 | 源码：7-Zip 同连接 20 步；安装态：计算器五次点击均通过 |
| 按键 | `step/press_key`，保留既有按键／请求合同及目标门禁 | 未提供受管理输入入口 | 核对既有合同，不算适配层验收 | 未跑 |
| 滚动 | `step/scroll`，保留当前目标与输入门禁 | 未提供受管理输入入口 | 核对既有合同，不算适配层验收 | 未跑 |
| 文字替换 | 显式 `step/type_text`，或兼容的原生／legacy `input_sequence`，含清空与结果检查 | 未提供受管理输入入口 | 核对既有请求与默认路线合同 | 未跑 |
| 组合填写 | `input_sequence`；有界 `form_fill` 按自身门禁支持最多 32 个已声明字段 | 未提供受管理输入入口 | 核对既有合同，不宣称端到端无 API | 未跑 |
| v1 线性计划 | 既有点击／输入／读文字计划及原 Main 审核语义 | `agent_prepare` 不接受 | 核对既有计划合同 | 未跑 |
| v2 线性计划 | 兼容无 Decision／原生证明与明确 Main 审核；语义自动采用另有服务要求 | `agent_prepare` 不接受 | 核对既有计划与默认路线合同 | 未跑 |
| v3 线性计划 | 既有视觉／Decision 动作审核路线；点击／输入预检要求合规 Decision auto 配置 | 未扩展无 API v3 | 核对既有预检，保留拒绝边界 | 未跑 |
| 跨窗口 | 有窗口发现／选择；计划及续行仍绑定原宿主／目标 | 无自动跨窗工作流 | 核对绑定合同，不算跨窗验收 | 未跑 |
| 断线／重启恢复 | 有原回执只读回读及实验性、证明门控的新 epoch 恢复；不重放旧命令，不自动接管工作流 | 不保证重连或宿主重启续跑 | 仅回执／防重放边界，不算重启验收 | 未跑 |
| 管理员／UAC | 旧路线保留明确的管理员桥接入口 | 不支持，在连接／生成输出前拒绝 | 检查拒绝边界及普通会话 Decision 隔离的有效加载 | 未跑 |

省略 `field_evidence_mode` 时，公开输入入口可能采用默认视觉输入；该路线及 v3 视觉点击／输入审核仍要求已启用的 `decision_profile.v2`、auto 模式、合规条件与预算。本模式不放宽这些检查，不把请求暗改为 `legacy`，也不承诺所有 v3／默认视觉组合输入均可无 API。参见[视觉输入](VISUAL_EXECUTION_INPUT.md)和[任务计划](TASK_PLAN.md)。

## 证据与限制

[2026-10-24 源码实机](../verification/CURRENT_AGENT_LIVE_20261024.md)在同一持久 MCP 连接完成 7-Zip 20 步原图→resolve→continue→后图→verify。另测错 hash 拒绝、不确定判断封锁、complete 后封锁，以及 awaiting_grounding 取消到真实 cancelled／action_executed=false；清理验证通过。未配置独立视觉／Decision 服务或提供其密钥。承载 Agent 仍使用自身模型服务；独立安装态使用实际 installed-root CLI 及 -I/-B：计算器 C → 1 → + → 2 → = 显示 3，每帧由 Agent 读取原图核验。动作后取消保留 completed／action_executed=true 并阻止下步；另一个定位等待取消达到 cancelled／action_executed=false，晚续行被拒。两个宿主均确认清理，684 项安装载荷运行前后摘要全同，原生卸载通过。[发布记录](../releases/EXECUTION_017_20261024.md)保留实测安装器身份与最终仅文档重包边界；源码 20 步不写成安装态 20 步。

早期配置别名及既有 API／Decision／启动兼容检查通过 43 项离线测试，适配层另有 40 项模拟检查；这是先前检查快照，不能与本轮回归数量相加。当前回归及制品范围以[发布记录](../releases/EXECUTION_017_20261024.md)为准。

实现依据：[客户端适配层](../../scripts/current_agent_client.py)、[CLI](../../scripts/execution_client.py)、[配置生成器](../../scripts/configure_instant_mcp.py)、[能力协商](../../app/vision/recognition_source.py)、[定位结果校验](../../app/vision/grounding_contract.py)、[公开输入默认值](../../app/execution/public_input_defaults.py)及 [Decision 预检](../../app/execution/action_review.py)。

后续验收继续保留原始失败与每步截图／请求／回执关联，目标缺失、歧义、未知输入及断线恢复未因此获得全面验收。执行耗时、调用方空档和测得的用户等待分开；承载 Agent token／额度不可观测时标记未知。本轮不证明提速、成本节省比例或通用成功率。学习保持暂停，模型阈值和输入门禁未改动。

## Amadeus 与更新边界

Amadeus 0.0.4 wheel 保留固定 `instant-v0.1.6` URL 和既有 API 路线 Skill；本轮没有新当前 Agent 模式的 Amadeus 实测。HTTP 协议保持兼容时，Runtime 补丁无需重新导入未变化的扩展。自动检查、下载或切换尚未实现，见 [Amadeus 策略](AMADEUS_UPDATE_STRATEGY.md)与 [Runtime 策略](RUNTIME_UPDATE_STRATEGY.md)。
