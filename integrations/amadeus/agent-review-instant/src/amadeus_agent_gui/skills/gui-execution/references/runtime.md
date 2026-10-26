# Runtime session and receipt contract / 会话与回执合同

## Prerequisites / 使用前提

This resource connector uses an independently installed, operator-started,
authenticated Windows loopback HTTP MCP Runtime. It never launches external
code. The local connection token is distinct from provider API keys. This
Skill supports the existing external API route only; configured model services
receive recognition/review screenshots and task information and may charge for
calls. Input requires explicit task authorization and Runtime opt-in;
`--allow-local-input` also turns automatic risk interception off. Do not change
profiles, thresholds or prompts to bypass a refusal.

本资源连接器使用用户独立安装并启动、带鉴权的 Windows 本机 HTTP MCP Runtime，不会启动外部代码。本机连接密钥与模型 API Key 不同。本 Skill 仅支持原有 external API 路线；已配置模型服务会接收识别／审核截图及任务信息，可能按调用收费。输入须有明确任务授权及 Runtime opt-in；`--allow-local-input` 也会关闭自动风险拦截。不能改 profile、阈值或提示词来绕过拒绝。

Recommend released Runtime 0.1.8. The minimum HTTP/pre-action contract is 0.1.6;
the service must also supply field-review/continue. Runtime 0.1.5 has field
review but no HTTP entry point. This connector does not qualify Runtime 0.1.7
current-Agent mode through Amadeus. Manually inspect the MCP initialization
version, authentication, discovered tools and active schemas before input:
`instant_start`, `instant_status`, `instant_run`, `instant_result`,
`instant_image`, `instant_stop`, and task-plan/original-command status and
review/continue support. Logical names below are Runtime names, not guesses
about Pi's namespaced/hashed tool names. Neither a version marker nor a later
release proves compatibility; no automatic compatibility detector is provided.

推荐已发布 Runtime 0.1.8。最低 HTTP／前置审核合同为 0.1.6，服务还须提供文字结果审核／继续。Runtime 0.1.5 有文字审核但没有 HTTP 入口。本连接器没有通过 Amadeus 核验 Runtime 0.1.7 current-Agent 模式。输入前人工检查 MCP 初始化版本、鉴权、已发现工具及活动 schema：`instant_start`、`instant_status`、`instant_run`、`instant_result`、`instant_image`、`instant_stop`，以及 task-plan／原命令状态和审核／继续支持。下文逻辑名称是 Runtime 名称，不能据此猜 Pi 带命名空间／哈希的工具名。版本号或后续发行不能证明兼容，本包没有自动兼容探测器。

## Start and select / 启动与选择

Keep one live MCP connection and one input owner for the entire Work. Call the
discovered `instant_start` once, then `instant_status` until ready. Vision and
Decision profiles are preconfigured; do not call `prepare_models` or
`learning_*`. A selected target is session state. Prepare known independent
fields together, read healthy pending results promptly, and do not insert
unrelated searches/documentation between action batches.

完整 Work 保持一个活动 MCP 连接和一个输入所有者。发现实际工具后，只调用一次 `instant_start`，再查询 `instant_status` 至 ready。视觉与 Decision profile 已事先配置，不调用 `prepare_models` 或 `learning_*`。选中目标属于会话状态。已知独立字段合并准备，及时读取正常待定结果，不在动作批次间插入无关搜索／文档工作。

For a new application/shortcut explicitly in scope, use the actual approved
path. Read its returned ownership and exact handle/process_id. Example:

对于明确纳入任务的新应用／快捷方式，使用实际已授权路径，读取返回的归属及确切 handle／process_id。例如：

```json
{"request_id":"launch-001","command":{"kind":"launch","path":"C:\\approved-test\\application.lnk","prefer_existing":false},"wait_ms":10000,"images":"none"}
```

For an observed existing window, select its real identities with the shape
`{"kind":"select","handle":123,"process_id":456}`. Example integers are
placeholders, not targets. A pre-existing/operator-prepared window does not
become task-owned. Capture the selected target with **only** `kind`:

对于已观察到的现有窗口，按 `{"kind":"select","handle":123,"process_id":456}` 形状填真实身份。示例整数只是占位符，不是目标。现有／操作员预备窗口不会变成本任务自有窗口。捕获已选目标时，command **只放** `kind`：

```json
{"request_id":"capture-001","command":{"kind":"capture"},"wait_ms":10000,"images":"after"}
```

Do not put handle/process_id in `capture`. Use the original images bound to
`instant_run`/`instant_result`; `instant_image` retrieves available images by
the original request ID. A new capture is a new observation, not replacement
evidence for an older action. Never mix old coordinates with current geometry.
Pi may natively resize a complete bound frame for its model; do not claim that
this is byte-identical original PNG delivery.

`capture` 不放 handle／process_id。使用 `instant_run`／`instant_result` 绑定的原图，`instant_image` 按原 request ID 取可用图像。新 capture 是新观察，不能替换旧动作证据。不把旧坐标与当前几何混用。Pi 可能原生缩放完整绑定帧再交给模型，不能声称这等于原 PNG 字节相同交付。

## Submit, wait and inspect / 提交、等待与核对

Use a complete `task_plan` when the task calls for one; do not split it to evade
checks. Follow the actual schema, explicit actions/verification and original
run identity. There is no connector step cap; Runtime budgets, evidence binding
and admission apply. `instant_run` accepts `request_id`, `command`, `wait_ms`,
`detail` and `images`; keep receipt waits below the MCP client timeout. A
running start receipt or asynchronous `instant_submit` acknowledgement is not
completion. When pending, follow returned `next` and read `instant_result`
with the **same** outer request ID:

任务需要完整 `task_plan` 时按实际 schema 使用，不拆分来规避检查。保留明确动作／核验及原 run 身份。连接器没有步数上限，Runtime 预算、证据绑定与准入仍适用。`instant_run` 接收 `request_id`、`command`、`wait_ms`、`detail`、`images`，回执等待须低于 MCP 客户端超时。running 启动回执或异步 `instant_submit` 确认不是完成。待定时按返回 `next`，用**相同**外层 request ID 读取 `instant_result`：

```json
{"request_id":"launch-001","detail":"full","images":"both"}
```

For `agent_command.v1`, retain command_id. Read its state under a new outer
request ID; this read-only status request is not a replay. For a review packet,
its `execution_request_id` is the command_id to query. The example value must
be replaced by the real original identity:

对于 `agent_command.v1`，保留 command_id；用新外层 request ID 读状态，这是只读状态请求，不是重放。审核 packet 的 `execution_request_id` 就是要查询的 command_id；示例值须替换为真实原身份：

```json
{"request_id":"status-001","command":{"kind":"agent_command_status","request":{"command_id":"original-execution-request-id"}},"wait_ms":10000,"images":"none"}
```

Inspect `instant_status.task_plan_run` and original start/result receipts until
a terminal outcome or explicit wait. Report completed steps, pending/review/
failure and bound evidence, not merely tool success. `result_unknown`, timeout,
`action_executed=true`, interrupted typing or a missing after image never prove
input did not happen. Preserve original request/run/command IDs; do not resend
input to extend a wait, start a competing plan or use another input route to
hide uncertainty. Cancellation must reach its real terminal state.

检查 `instant_status.task_plan_run` 及原启动／结果回执，直到终态或明确等待。报告完成步骤、待定／审核／失败与绑定证据，不能只报工具成功。`result_unknown`、超时、`action_executed=true`、输入中断或缺少后图不能证明未输入。保留原 request／run／command ID，不重交输入延长等待、不另起竞争计划、不用其他输入路线掩盖未知。取消须到真实终态。

## Main review / 原 Agent 审核

Use the actual packet returned by the active service. A candidate before input
and an already-entered field are different scopes. A handoff/version marker is
not a ticket; do not fabricate hashes, wait IDs, verdicts or recipes.

只使用活动服务实际返回的 packet。输入前候选与已输入字段属于不同作用域，交接／版本标记不是票据；不伪造哈希、wait ID、结论或 recipe。

### Candidate before input / 输入前候选

A genuine `pre_action_review_packet.v1` parks the original job after
authenticated Decision and ordinary-model nonpasses, without claiming native
input. Read `packet.execution_request_id` through `agent_command_status` as
above and wait for that status receipt. Retrieve that successful status
request's bound original **before** image, using its actual request ID:

真实 `pre_action_review_packet.v1` 在已认证 Decision 和普通模型均未通过后暂停原 job，不声称已派发原生输入。按上例通过 `agent_command_status` 读取 `packet.execution_request_id` 并等到状态回执，再以该成功状态请求的实际 request ID 取绑定原 **before** 图：

```json
{"request_id":"status-001","view":"before"}
```

Inspect the original task target, candidate point/box and exact bound image.
Do not replace it with a new capture or treat the locator description as proof.
Copy `caller_controls.review.request` and add only the actual verdict/reason:
success requires a specific visual reason that the candidate satisfies the
task; otherwise record the genuine failure or cancel. Do not ask models again
and again to obtain a pass.

检查原任务目标、候选点／框与确切绑定图像，不能改用新 capture，也不能把定位描述当证明。复制 `caller_controls.review.request`，只添加真实 verdict／reason：success 必须有候选满足任务的具体可见依据，否则记录真实失败或取消。不反复问模型来凑通过。

Submit review through the actual `task_plan` recipe. Review records Main's
judgment and performs no click. Then use the **separately returned**
`caller_controls.continue.request`, retaining the original run/wait. It resumes
the original job/candidate after a fresh target-region check and existing
input, identity, geometry, visibility and cancellation gates. A changed/expired
candidate stops. Do not restart, replan or synthesize approval to repeat it.
Original model nonpasses remain separate from Main's one-use approval.

按真实 `task_plan` recipe 提交审核，审核仅记录 Main 判断，不点击。之后使用**单独返回**的 `caller_controls.continue.request`，保留原 run／wait。原 job／候选须通过新截图的目标区域核对及既有输入、身份、几何、可见性、取消门禁后才继续。候选变化／过期就停止，不重启、重规划或合成批准来重做；原模型未通过结果与 Main 一次性批准分别保留。

### Entered field value / 已输入文字

A genuine `field_review_packet.v1` reviews text already entered after an
authenticated dual-model rejection; the original execution is still pending.
Read `packet.execution_request_id` through a new `agent_command_status` as
above. After that status receipt, use its real request ID with
`instant_image(view="after")`:

真实 `field_review_packet.v1` 在已认证双模型拒绝后审核已经输入的文字，原执行仍待定。按上例用新 `agent_command_status` 读取 `packet.execution_request_id`，状态回执完成后，用其真实 request ID 调用 `instant_image(view="after")`：

```json
{"request_id":"status-001","view":"after"}
```

Do not request an image directly on the unfinished execution, replace the bound
after image with a new capture or replay text. Inspect the evidence bound to
`caller_controls.review.request`, copy it and add only actual verdict/reason;
do not add wait_id to review. Review only records Main's judgment. Separately
submit the returned continue recipe for the original run/wait; the live thread
resumes without retyping. Parameter recipes are not action authorization.

不能直接向未完成执行取图、用新 capture 替换绑定后图或重输文字。检查 `caller_controls.review.request` 绑定证据，复制并仅添加真实 verdict／reason，不在 review 添加 wait_id。审核只记录 Main 判断；再单独提交返回的 continue recipe 续原 run／wait，活动线程不重输。参数 recipe 不是动作授权。

Field review only confirms entered text. A submit suffix still needs its fresh
target/candidate, normal input gates and result verification; field review does
not prove search/submission success or bypass final-submit restrictions. If
there is no genuine resumable review/continue recipe, retain the original
failure and stop/report. Do not invent a ticket, restart/replay, relabel success
or create a successor to repeat input. This package does not repair Runtime or
claim new installed acceptance of its review behavior.

文字结果审核只确认已输入内容。submit 后缀仍须新目标／候选、普通输入门禁及结果核验；文字审核不证明搜索／提交成功，也不绕过最终提交限制。没有真实可续审核／继续 recipe 时保留原失败并停报，不伪造票据、重启／重放、改标成功或另造后继来重输。本包不修复 Runtime，也不声称新安装态审核行为验收。

## Recovery / 恢复

If HTTP is unreachable, check the independently started service console,
loopback port and `/mcp` path. For 401, compare the private local tokens; do not
substitute a provider key or expose secrets in logs. Host/Origin rejection
requires a direct native MCP connection to `127.0.0.1`, not a proxy/browser.
Missing tools/contracts require manual version/schema review before new input,
not an invented fallback. Do not change running configuration until original
input and cleanup have settled.

HTTP 不可达时核对独立服务控制台、本机端口及 `/mcp` 路径。401 时核对私下保存的本机密钥，不用模型密钥替代，也不在日志暴露密钥。Host／Origin 拒绝时须原生 MCP 直连 `127.0.0.1`，不用代理／浏览器。工具／合同缺失时先人工核对版本／schema，再考虑新输入，不能虚构后备路线。原输入与清理未结算前，不更改运行配置。

A timeout/disconnect is not cancellation. If the original connection is still
usable, inspect original receipts and use its actual cancel/status recipe,
then wait for terminal settlement. An owner conflict or cleanup gate must be
resolved through the original live Work. Inspect `cleanup_pending` diagnostics,
resolve its specific blocker, then retry `instant_stop` for cleanup only and
poll. If the original connection is unavailable, retain evidence and stop for
operator/maintainer recovery; a new Work is not the old owner. Never steal
ownership, repeatedly reconnect/restart, delete queues/locks/session records or
replay unknown input to bypass a gate.

超时／断线不等于取消。原连接仍可用时，检查原回执，使用其真实 cancel／status recipe 并等到终态。owner 冲突或清理门禁须经原活动 Work 处理。读取 `cleanup_pending` 诊断，解除具体阻塞后调用 `instant_stop` 只重试清理，再查询状态。原连接不可用时保留证据，停止并交操作员／维护者恢复；新 Work 不是旧 owner。不抢占、不反复重连／重启、不删除队列／锁／会话记录、不重放未知输入来绕过门禁。

## Owned-window and host cleanup / 自有窗口与宿主收尾

After input settles, close only a task-launched window using the exact
handle/process_id from its launch receipt. Example numbers are placeholders:

输入结算后，仅按启动回执的确切 handle／process_id 关闭本任务启动的窗口；示例数字只是占位符：

```json
{"request_id":"close-001","command":{"kind":"close_launched_window","handle":123,"process_id":456},"wait_ms":10000,"images":"after"}
```

No `request.ownership` field is required. Preserve the original launch identity.
If `window_close_pending` exposes an owned modal, inspect the current dialog
through select/capture; closing does not authorize Save/Discard/Confirm. Act
only on a choice explicitly in scope. Missing after evidence can mean the
window closed: inspect the original receipt and verify disappearance rather
than repeating a click. Verify `window_closed` for each owned window. Do not
close unrelated/operator-prepared windows unless explicitly authorized.

不需要 `request.ownership` 字段，保留原启动身份。`window_close_pending` 显示自有模态框时，通过 select／capture 查看当前对话框；关闭请求不授权保存／丢弃／确认，只执行明确在范围内的选择。缺后图可能因为窗口已关，应读原回执并核对消失，不能重复点击。逐一核实自有窗口 `window_closed`；没有明确授权就不关闭无关／操作员预备窗口。

Call `instant_stop`, then poll `instant_status` until `host_alive=false`,
`pending_ids=[]`, `cleanup_verified=true` and no unresolved cleanup error.
`cleanup_pending`/stop acknowledgement is not terminal cleanup. Host cleanup
does not prove application closure. Only after these conditions release the
native HTTP owner so another Work can initialize. A transport disconnect is
not task success, cancellation or cleanup; reopening a Pi conversation does
not resume the old live MCP connection.

调用 `instant_stop`，查询 `instant_status` 至 `host_alive=false`、`pending_ids=[]`、`cleanup_verified=true` 且没有未解决清理错误。`cleanup_pending`／stop 确认不是清理终态，宿主清理不证明应用已关。满足这些条件后才释放原生 HTTP owner，使其他 Work 初始化。传输断线不是任务成功、取消或清理；重开 Pi 对话不会恢复旧活动 MCP 连接。

Report task success/failure/unknown, original IDs and evidence, assistance or
recovery, owned-window closure and host cleanup separately. Disabling/removing
the connector releases the Host connection only; it does not shut down or
uninstall the external Runtime or delete its data. Finish cleanup first; stop
the independent daemon deliberately afterward if desired. Do not delete
browser profiles, cookies, history, sessions or retained extension data.

分别报告任务成功／失败／未知、原 ID 与证据、协助／恢复、自有窗口关闭及宿主清理。禁用／移除连接器只释放 Host 连接，不停止／卸载外部 Runtime，也不删除它的数据。先完成清理，如需停用独立 daemon 再明确关闭。不要删除浏览器 profile、cookie、历史、会话或保留的扩展数据。

## Evidence boundary / 证据边界

Connector 0.0.5 changes documentation/disclosure and metadata only; existing
0.0.3/0.0.4 connection settings need no migration, and permissions/input gates
do not change. It is author-published and pending independent store review.
[Controlled installed Pi evidence](https://github.com/Desolate-Jix/agent-gui-runtime/blob/instant-v0.1.6/docs/verification/MAIN_PRE_ACTION_REVIEW_20261023.md)
belongs to connector 0.0.4/Runtime 0.1.6; new 0.0.5/0.1.8 installed GUI acceptance
remains pending. Read the separate [0.0.5 author validation record](https://github.com/Desolate-Jix/agent-gui-runtime/blob/amadeus-extension-v0.0.5/docs/verification/AMADEUS_CONNECTOR_005_20261026.md)
for the exact scope of packaging/protocol checks. These layers do not establish
independent approval, unattended accuracy or performance.

连接器 0.0.5 只改文档／披露与元数据；既有 0.0.3／0.0.4 连接设置无需迁移，权限／输入门禁不变。本版为作者发行，独立商店审核待完成。[受控安装态 Pi 证据](https://github.com/Desolate-Jix/agent-gui-runtime/blob/instant-v0.1.6/docs/verification/MAIN_PRE_ACTION_REVIEW_20261023.md)属于连接器 0.0.4／Runtime 0.1.6；新 0.0.5／0.1.8 安装态 GUI 验收仍待完成。打包／协议检查的确切范围见单独的 [0.0.5 作者验证记录](https://github.com/Desolate-Jix/agent-gui-runtime/blob/amadeus-extension-v0.0.5/docs/verification/AMADEUS_CONNECTOR_005_20261026.md)，这些层不证明独立批准、无人准确率或性能。
