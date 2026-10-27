---
name: gui-execution
description: Execute an explicitly authorized Windows GUI task through the connected external-API Runtime route, preserve original request and evidence identities, handle review without replaying input, and verify owned-window and host cleanup.
---

## English

Read `references/runtime.md` before using the connected Runtime. Discover its
actual tools and schemas; Pi names may be namespaced or hashed, so never invent
a tool name. This Skill supplies no tools, authority, executor, learning mode or
shell route. Connector 0.0.7 supplies installation and execution guidance;
publication, independent store approval and installed GUI execution are separate
results. Historical 0.0.4/0.1.6 controlled Pi evidence is a separate result.

Use only the existing external API route. Recommend separately installed
Runtime 0.1.10; minimum 0.1.6 supplies the HTTP/pre-action contract, and the active
service must supply field review/continue. Runtime 0.1.5 has no HTTP entry point.
Runtime 0.1.7 current-Agent mode is not qualified through Amadeus here. Manually
check MCP initialization version, actual tools/schemas, authentication and
review/cleanup capabilities; neither a version number nor a later release
establishes compatibility. The 0.1.6 protocol floor does not qualify all later
0.1.x versions. No automatic compatibility detector is provided.

Keep one Runtime MCP connection and one input owner for the complete authorized
Work. The operator independently installs and starts the authenticated loopback
daemon. The connector never launches Python, chooses executable paths, supplies
provider keys or changes profiles. The local connection token is not a model
API key. Screenshots/task information can reach the configured model services,
whose calls may cost money. Confirm task scope and Runtime input opt-in:
`--allow-local-input` enables input and turns automatic risk interception off.
Start the host once, wait for ready, launch/select the intended window, use
current bound observations, submit the task and inspect original receipts. A
launch or asynchronous acknowledgement is not task success. Prepare known
independent fields together and read healthy pending batches promptly; do not
insert unrelated searches or documentation between them.

For pending, unknown, timeout, interrupted input or unavailable images, retain
original request/run/command IDs and inspect their state. Never replay possibly
executed input under a new ID or resubmit to extend a wait. At a genuine
`pre_action_review_packet.v1` or `field_review_packet.v1`, read
`agent_command_status` with `command_id=packet.execution_request_id` under a new
outer request ID and `images=none`. Retrieve that status request's bound image with
`instant_image`: `view=before` for a candidate, `view=after` for entered text.
Inspect the exact bound evidence against the task, copy
`caller_controls.review.request` and add only the actual verdict/reason. Then
separately use the returned continue recipe. Review alone performs no input.
Pre-action continuation retains the original job/candidate and requires a fresh
target-region check and existing hard gates before one dispatch. Field
continuation does not retype; any submit suffix still needs normal gates and
verification. With no genuine resumable ticket or a stale candidate, stop and
report. Do not manufacture hashes, wait IDs, success or a restart/replay.

Cancellation must settle to a real terminal state; a disconnect is not
cancellation or cleanup. Close only task-launched windows using their returned
handle/process identity, resolve save dialogs only for an authorized choice,
and verify `window_closed`. Keep pre-existing/operator-prepared windows unless
their closure is explicitly in scope. Call `instant_stop`, then poll until
`host_alive=false`, `pending_ids=[]`, `cleanup_verified=true` and no unresolved
cleanup error. Only then release the native HTTP owner. If an old owner is
unresolved, inspect its original receipts and cleanup diagnostics. If the
original connection is lost, retain evidence and stop for operator recovery.
After Pi disconnects or encounters an owner conflict, both
`instant_recovery_preview` and `instant_recover_session` are operator-only;
Pi must not use them to take over the old session or workflow. Main's
bound-image review/continue path in the original live session remains available
under its existing contracts. Do not steal ownership, repeatedly
reconnect/restart, or delete queues, locks or session records. Report task
outcome separately from cleanup. Runtime 0.1.10 adds settlement of proven
rejected `task_plan` controls and successful `observe` requests. Rejections
require original durable before-dispatch proof; error strings alone are
insufficient. Successful observation requires bound original capture and ledger
evidence. Settlement of `recover` and `resume_pre_dispatch` remains unqualified.
Consult the [settlement recovery guide](https://github.com/Desolate-Jix/agent-gui-runtime/blob/instant-v0.1.10/docs/RUNTIME_018_SETTLEMENT_RECOVERY.md)
for retained evidence and the maintained operator entry point.

Disabling/removing the connector releases the Host connection only; it does
not stop/uninstall the independently running Runtime or delete its data. Finish
cleanup before disabling/removing. Connector 0.0.7 updates guidance and metadata;
Runtime fixes are delivered separately. 0.0.3/0.0.4/0.0.5/0.0.6 connection settings
need no migration and input gates and permissions do not change.

## 简体中文

使用连接的 Runtime 前先读 `references/runtime.md`。发现实际工具与 schema；Pi 名称可能带命名空间或哈希，不能猜工具名。本 Skill 不提供工具、授权、执行器、学习模式或 shell 路线。连接器 0.0.7 提供安装与执行指引；作者发布、独立商店批准及安装态 GUI 执行分别记录。历史 0.0.4／0.1.6 受控 Pi 证据单独记录。

仅使用原有 external API 路线。推荐独立安装的 Runtime 0.1.10；最低 0.1.6 提供 HTTP／输入前审核合同，活动服务还须提供文字结果审核／继续。Runtime 0.1.5 没有 HTTP 入口。此处没有通过 Amadeus 核验 Runtime 0.1.7 current-Agent 模式。人工核对 MCP 初始化版本、实际工具／schema、鉴权及审核／清理能力；版本号或后续发行不能证明兼容。0.1.6 的协议起点不表示所有后续 0.1.x 版本均已具备资格。本包不提供自动兼容探测器。

完整授权 Work 保持一个 Runtime MCP 连接和一个输入所有者。操作员独立安装并启动带鉴权的本机 daemon；连接器不会启动 Python、选择可执行路径、提供模型密钥或改 profile。本机连接密钥不是模型 API Key。截图／任务信息可能发送给已配置模型服务，服务调用可能收费。确认任务范围及 Runtime 输入授权：`--allow-local-input` 启用输入，同时关闭自动风险拦截。宿主只启动一次，等待 ready，启动／选择目标窗口，使用当前绑定观察，提交任务并检查原回执。启动或异步确认不是任务成功。已知独立字段提前合并准备，及时读取正常待定批次，不在其间插入无关搜索或文档工作。

待定、未知、超时、中断输入或图像不可用时，保留原 request／run／command ID 并检查状态。可能执行过的输入不能换 ID 重放，也不能为延长等待而重交。真实 `pre_action_review_packet.v1` 或 `field_review_packet.v1` 出现时，用新外层 request ID 和 `images=none` 调用 `agent_command_status`，`command_id=packet.execution_request_id`。随后用 `instant_image` 取该状态请求绑定图像：候选看 `view=before`，已输入文字看 `view=after`。对照任务检查确切绑定证据，复制 `caller_controls.review.request`，仅添加实际 verdict／reason，再单独使用返回的 continue recipe。审核本身不输入。前置继续保留原 job／候选，派发一次前须通过新截图的目标区域核对及既有硬门禁；文字结果继续不重输，后续 submit 仍须普通门禁及核验。没有真实可续票据或候选已过期就停报。不伪造哈希、wait ID、成功或重启／重放。

取消须结算到真实终态；断线不等于取消或清理。仅按返回 handle／process 身份关闭本任务启动的窗口，仅处理已授权选择的保存对话框，并核对 `window_closed`。保留原有／操作员预备窗口，除非其关闭已明确纳入任务。调用 `instant_stop`，查询至 `host_alive=false`、`pending_ids=[]`、`cleanup_verified=true` 且没有未解决清理错误，之后才释放原生 HTTP 所有者。旧所有者未结算时读取原回执和清理诊断；原连接丢失时保留证据并停止，交操作员恢复。Pi 断线或遇到 owner 冲突后，`instant_recovery_preview`、`instant_recover_session` 两个工具仅限操作员使用，Pi 不得用它们接管旧会话或工作流。原活动会话中 Main 对绑定图像审核／继续的路径仍按既有合同保留。不抢占、不反复重连／重启、不删除队列、锁或会话记录。任务结果与清理分别报告。Runtime 0.1.10 新增证据完整的拒绝 `task_plan` 控制及成功 `observe` 请求的结算；拒绝须有原始持久化派发前证明，错误字符串本身不足为据，成功观察须有绑定的原截图及账本证据。`recover`、`resume_pre_dispatch` 的结算仍未具备资格。保留证据及正式维护的操作员入口见[结算恢复指南](https://github.com/Desolate-Jix/agent-gui-runtime/blob/instant-v0.1.10/docs/RUNTIME_018_SETTLEMENT_RECOVERY.md)。

禁用／移除连接器只释放 Host 连接，不停止／卸载独立运行的 Runtime，也不删除它的数据。先完成清理再禁用／移除。连接器 0.0.7 更新指引与元数据，Runtime 修复单独交付；0.0.3／0.0.4／0.0.5／0.0.6 连接设置无需迁移，输入门禁及权限不变。
