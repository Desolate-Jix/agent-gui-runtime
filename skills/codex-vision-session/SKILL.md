---
name: codex-vision-session
description: Codex adapter for agent-gui-runtime agent_delegate visual grounding. Reuse one visual subagent with the user's selected model and effort across a continuous GUI task, correlate fresh screenshots and resume the original MCP command. Use only for this runtime's delegated vision route.
---

# Codex 视觉会话适配 / Codex visual-session adapter

这是 Codex 客户端调度适配，不是 MCP 宿主模型服务。仅用于用户选择的 `agent_delegate`；不改变 `local`、`agent_current`、`external_api` 路线，也不切换主 Agent。`delegate_profile` 是客户端标签，不能凭标签声称模型已启动。

## 会话复用 / Session reuse

- 同一连续任务与指定模型复用一个子 Agent。先从当前任务的已知委派记录或 `collaboration.list_agents` 找到已有视觉子 Agent，保留其 ID/规范任务名。已经完成一轮并不代表会话被销毁。
- 用户于 2026-10-08 要求所有工作子 Agent 使用 `ultra`。新建视觉会话使用 `model="gpt-6.1-sol"`、`reasoning_effort="ultra"`、`fork_turns="none"`；其他用户指定模型也须明确支持 `ultra`。当前 Luna 最高支持 `max`，未经用户另行选择并接受该限制，不降档使用 Luna。
- 仅在没有符合指定模型与强度的已有会话时创建一次。此次明确强度调整允许把低强度或强度未知的旧会话替换一次，移交必要的当前任务状态；此后恢复连续复用。修改技能不会热切换旧会话。
- 后续始终 `collaboration.followup_task(target=保留的ID, message=本次定位请求)`，包括上一轮已完成的子 Agent。`send_message` 不会唤醒闲置子 Agent，不能代替续接。
- 一个子 Agent 同时仅一个识图请求；等待它完成再发送下一张图。保留主任务记录中的 `{delegate_profile, model, worker_id, pending_request_id, capture_id}`，跨上下文压缩时一并保留，不把 ID 当作可跨新任务或重启恢复的凭证。
- 原子 Agent 不可用、达到上下文限制或无法续接时明确报告原因，不自动新建、不自动换模型。用户另行要求重建时再处理。

Reuse one known worker ID for the same continuous task, chosen model and effort. The user's 2026-10-08 preference is explicit `ultra`: new visual workers use `gpt-6.1-sol`, `reasoning_effort="ultra"`, `fork_turns="none"`. Luna currently supports only `max`; use it only if the user explicitly chooses and accepts that limit. This preference change permits a one-time replacement of a lower/unknown-effort worker, then use `followup_task` for every later request, including after a completed turn. Keep one outstanding request and preserve its correlation record. Other unavailable sessions remain a blocker, not automatic replacement permission. No main-agent model change or host-managed model service is implied.

## 每次识图与回传 / Per-request grounding

1. 从当前 `awaiting_grounding` 读取 pending `request_id`、`capture_id`、原图路径/哈希/尺寸、目标和 `output_schema`。只提供本次必要数据，不复制无关会话和个人资料。
2. 要求子 Agent 用图像工具实际打开本次原图，返回对应原始请求的结构化结果；不能沿用前图坐标。子 Agent 只读识图，不点击、不执行输入、不派生子 Agent、不自行推进流程。
3. 主 Agent 等待结果并核对当前请求关联信息与 schema；迟到或错配的结果不得提交给新请求。负面或不确定结果如实保留，不编造定位。
4. 对组合命令，先 `grounding_resolve` 回传 pending 请求，再用新的外层 ID `agent_command_continue` 继续原 `command_id`。不重新提交整批，不调用独立 `grounding_execute` 代替组合命令续接。完整参数以实际连接的 MCP 工具契约为准。
5. 下一张图复用相同 worker ID，但使用新的 pending 请求与原图证据。主 Agent 保留独占输入、现场核对与最终结果判断；识图成功不等于动作或用户任务成功。

Each request carries fresh pending/capture IDs and its original image evidence. The worker reads that image and returns structured grounding only. The main Agent correlates the result, resolves and continues the original batch using the connected server contract, then reviews the actual outcome. Never reuse stale coordinates or replay the batch.

## 生效边界 / Loading boundary

安装到 Codex 的个人技能目录后，由技能发现机制在后续任务加载；已有任务可以显式读取本文件应用规则。安装或写入文件不证明现有任务已重新加载技能。通用 MCP 客户端无需实现 Codex 的 collaboration 工具。本适配不宣称已测得速度提升。

Installation makes the skill available for subsequent Codex discovery; an existing task may explicitly read it. File installation alone does not prove live reload. Other MCP clients retain their own orchestration APIs; no speedup is claimed without measurement.
