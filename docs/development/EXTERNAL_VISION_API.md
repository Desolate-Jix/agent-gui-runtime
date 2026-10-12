# 外部视觉 API 接口 / External vision API

## 输入字段范围合同 / Input-field extent contract

输入目标的 `bbox` 必须覆盖整个可见输入字段，包括已有文字区；即使 `goal` 要求点击字段右侧空白等子区域，也不能把框缩成该点击子区。`click_point` 独立选择所要求的可点击子区域，可以偏离框中心。其他 UI 目标仍使用其真实目标框；`grounding.v1` 字段、版本和校验不变。 / For an input target, `bbox` covers the entire visible field, including existing text, even when the goal requests a blank or other clickable subregion. Choose `click_point` independently within that subregion; it need not be the box center. Other UI targets retain their real target boxes. Protocol fields, version and validation are unchanged.

这使同一候选框供后续字段 ROI 使用时能保留可见值，而不将点击区域误当字段范围。修正在外部 grounding 提示词和已有字段描述中，不引入 UIA、全屏裁剪回退、额外请求、重试或阈值调整。本地 48px 点框与既有 bbox 中心路线未改，不声称已修复。 / This keeps the visible value in the downstream field ROI instead of treating the click subregion as the whole field. The external grounding prompt and existing field descriptions clarify the contract without UIA, full-screen fallback, extra requests, retries or threshold changes. The local 48px point box and existing box-center route are unchanged and are not claimed fixed.

Explorer 首验路径实际已输入，但原候选只框住右侧空白，193×53 ROI 漏掉左侧文字，文字 Choice 返回 `condition_not_met`，完整轮数为 0。Main 的相关 6 模块 197 项离线检查通过；后续 4 次只读 API 调用仅为诊断，不授予动作权限，也不改写首败。详见[验收记录](../verification/EXECUTION_STABLE_012_20261012.md)。 / Explorer's first attempt entered the path, but its blank-only box produced a 193×53 ROI that omitted the left-hand text; value Choice returned `condition_not_met`, with zero complete rounds. Main passed 197 related checks across 6 modules. Four subsequent read-only API calls are diagnostic only, grant no action authority and do not replace the first failure.

## 2026-10-11 源码接入统一审核 / Source integration with combined review

新 v3 仍复用此 provider 和当前会话。调用前检查候选审核配置/许可/额度，避免已知不可用时仍付费定位；Luna 定位、可选场景预检、候选判断和输入前核验共用本次执行剩余预算，迟返不派发。默认场景预检关闭，Luna 后进行一次合并候选审核。只在代码/API 模拟边界验证过该组合，不代表本轮真实速度或准确率。 / V3 reuses this provider and session. Review preflight precedes paid grounding; grounding, optional scene probing and candidate adoption share the attempt deadline. Late results cannot dispatch. Default behavior is grounding followed by one combined review. This integration has offline evidence only.

见[源码证据](../verification/VISUAL_EXECUTION_DECISION_FLOW_20261011.md)及[Decision配置](DECISION_API.md)。API 模型名称和密钥配置沿用已有支持格式，本次不查询或改变账户配置。 / See the linked evidence and configuration; existing model/secret configuration is preserved.

用户要求保证 API 接口可跑通执行流程，不把服务商识别准确率作为本轮门槛。`external_api` 现已接入宿主：每步捕获原图，经配置的 Chat Completions HTTP 端点返回 `grounding.v1`，校验截图关联后进入现有公共执行器，回传动作结果与操作后原图。不加载本地模型，不自动挑选服务或切换路线。

The requested scope is API flow connectivity, not provider recognition accuracy. The host now sends each frozen screenshot to the configured Chat Completions endpoint, validates its grounding.v1 response, uses the existing guarded executor and returns the receipt plus after-image. No local model, provider discovery or fallback is involved.

## 配置格式 / Profile format

以下是占位示例，不是可用服务配置。服务商必须明确支持图像输入及 Chat Completions JSON 返回；端点填写完整请求地址，不自动拼接路径。模型 ID 使用该服务实际提供的视觉模型，不能根据主 Agent 的型号推断。

This is a placeholder, not a working service. Configure the complete request endpoint and a provider-supported vision model with Chat Completions JSON output. The main agent's model does not establish API availability.

```json
{
  "protocol": "chat_completions_json",
  "endpoint": "https://YOUR_PROVIDER/v1/chat/completions",
  "model": "YOUR_VISION_MODEL_ID",
  "api_key_env": "AGENT_REVIEW_VISION_API_KEY",
  "timeout_seconds": 45.0,
  "max_completion_tokens": 2048,
  "max_response_bytes": 262144,
  "max_image_bytes": 20971520,
  "max_concurrency": 1
}
```

密钥只设置在启动调用进程的本机环境中，不写入 JSON、仓库、聊天或示例脚本。启动后更改环境变量需要重启对应调用进程。外网地址要求 HTTPS；HTTP 仅接受 loopback。禁止 URL 内凭证、查询参数和重定向；不会自动寻找其他密钥或服务。

Keep the key only in the launching process environment, never in profiles, repositories, chats or example scripts. Restart the calling process after changing its inherited environment. Remote endpoints require HTTPS; HTTP is loopback-only. Embedded credentials, query parameters and redirects are rejected. No credential/provider discovery occurs.

## 开发接口 / Developer interface

`app/vision/external_grounding_api.py` 提供 `load_api_grounding_profile(path)` 和 `ChatCompletionsGrounder(profile)`。通过上下文管理器释放连接；`ground(request_id=..., capture=..., goal=...)` 接受真实冻结截图元数据，返回严格的 `grounding.v1` 和耗时/用量信息。它只请求定位，不执行鼠标键盘，不判断任务成功。

The module exposes a profile loader and context-managed grounder. Pass a frozen capture, goal and request ID to obtain validated `grounding.v1` plus timing/usage metadata. This adapter only requests localization; it neither dispatches input nor judges task success.

- `capture` 必须包含 `capture_id`、`image_path`、`sha256`、`image_size{width,height}`；读取原 PNG，核对大小和摘要，不发送任意目录或历史记录。 / Validate and send only the referenced original PNG, not directories or history.
- 截图会发送给所配置服务。是否允许发送由调用方在使用前确认；不要默认发送私人页面、凭证或账户信息。 / Calling the adapter transmits the screenshot to the configured service; establish consent and data scope first.
- JSON 状态、候选框和点均绑定请求及原图；`evidence_source=api_visual`，不会冒充本地 OCR 或 Agent 目视证据。 / Results remain bound to the request/image and explicitly identify API visual evidence.
- 回执记录请求模型、返回模型、可用 token 用量和本地耗时；不推断服务商计费或实际底层型号。 / Metadata is reported, not inferred billing or backend-model proof.
- 不重试；调用方必须区分 `api_key_missing`、`api_authentication_failed`、`api_access_denied`、`api_rate_limited`、`api_timeout`、`api_network_error`、`api_busy` 和格式/截图错误。公开错误不包含响应正文、Authorization 或底层异常链。 / Explicit, non-retrying errors omit response bodies, credentials and exception chains.

## 启动与调用 / Startup and calls

### Luna 持久调用入口（未发布源码） / Persistent Luna caller (unreleased source)

本轮选用普通 `gpt-6-luna` 识图，复用 [Luna profile](../../configs/vision-api-openai-luna.example.json) 的 `OPENAI_API_KEY` 环境变量引用，不把密钥写进命令或仓库。官方 [Luna API 文档](https://developers.openai.com/api/docs/models/gpt-6-luna)列出图像输入及 Chat Completions 支持。该路线不加载 VISTA/OCR；Decision profile 是另一个可选结果判断配置。API推理级别保持供应商默认，不能把 Codex 工作子Agent的 ultra 设置冒充 API 的设置。 / Use the regular Luna image endpoint with an environment-variable key reference. No local VISTA/OCR startup is required; Decisions remain independently configured. API reasoning stays at the provider default, separately from coding-worker effort.

```powershell
python scripts/execution_client.py --data-dir D:/AgentReviewData/luna-session --luna-api
```

这是调用方 JSONL 程序：保持一个 MCP 连接，逐行提交命令、等待原票据，并在 `{"action":"finish"}` 后正常清理；不是MCP server，不能用它替换MCP配置里的服务器命令。执行真实动作仍需显式 `--allow-actions` 及当前任务授权。`--luna-api` 与冲突的识别来源/profile组合应拒绝；不改变未选择它的用户默认配置。常规步骤使用 `input_sequence` 与 `task_plan.v2` 的 `until_wait`，不要拆成逐动作 Main 往返。 / This JSONL caller keeps one MCP connection; it is not a replacement MCP server. Real actions require explicit enabling and task authorization. Use grouped input and plan continuation to reduce caller round trips.

程序调用应使用持久的 UTF-8 stdin/stdout 管道，不要通过交互式 PTY 粘贴长 JSON 行。本机 Windows PTY 实测把超过510字符的单行截断，分块写入也无效；原始管道验证过完整中文载荷。调用方可持有同一个子进程并逐行写入 JSON，保持现有 MCP 会话和原票据。该限制来自测试终端链路，不是计划长度合同。 / Use persistent UTF-8 stdin/stdout pipes for programmatic calls. The tested Windows PTY truncated lines above 510 characters even when written in chunks; raw pipes preserved the complete Unicode payload. Keep one child process and write JSON lines without recreating the MCP session. This is a measured terminal-path limitation, not a plan-length limit.

本轮复审的三项问题已修复并完成[647项离线组合](../verification/LUNA_EXECUTION_FIXES_20261010.md)，1项完整构建按范围排除；没有API-selected实机点击、真实识图准确率或本轮速度收益证明。既有安装版继续使用下方明确的 `external_api` 启动方式。 / The repaired candidate passed 647 offline tests with one full build excluded. Real-model accuracy and live speed remain unverified; existing installers retain the explicit external API startup below.

若需要 Decision 自动核验，还须传入已有、范围已批准的 `--decision-profile`；Luna识图选项本身不会启用判断API或批准条件。计划中的完成条件必须与该profile允许的条件/模板一致，否则交原Main审核。普通回执默认紧凑输出，保留原 `request_id`；可通过 `instant_result` 的 `detail="full"` 获取完整诊断。 / Decision adoption separately requires an approved profile and matching allowed conditions/templates. Grounding selection grants neither. Compact progress preserves original receipt identities; explicitly request full details when needed.

JSONL不传递原生MCP图片块。`instant_image`或显式请求带图的`instant_result`会把原PNG字节保存在`<data-dir>/caller-images/<client-uuid>/<sha256>.png`；`image_delivery`返回`status="saved"`、绝对`image_path`、`sha256`、`mime_type`、`bytes`和`source_content_index`，紧凑回执也保留。上游摘要不符、图片块缺失或路径越界明确拒绝，不把base64写入JSONL。 / JSONL saves exact PNG bytes under a per-client directory and returns file references, hashes and source block indices, including in compact receipts. It rejects mismatched evidence and unsafe paths rather than claiming an image block was delivered.

普通命令的`total_timeout`约束首次调用、状态查询和原回执等待；发送后超时返回`result_unknown`及原票据的只读恢复入口，不重发动作，也不表示业务命令已取消。从未发出的请求在零预算下返回`not_submitted`且不生成图片/回执引用；已发出的同ID请求仍保留未知状态。当前MCP 2.1.1会取消RPC等待，连接可继续使用；若取消通知写队列堵塞，SDK清理可能另等约5秒，因此此预算不是硬实时保证。 / Ordinary calls share one wait budget. Timeout after dispatch preserves the original receipt and never replays the action. Zero-budget unissued requests are not submitted; existing IDs retain unknown state. MCP cancellation concerns the RPC wait, not the durable action; blocked cancellation writes can add roughly five seconds of SDK cleanup.

源码API传输复用单会话连接池，连接数与 `max_concurrency` 一致，空闲保留60秒；图片准备、网络及解析共用 `timeout_seconds` 总预算，超时不重试。CPU图片/JSON处理只能在阶段边界拒绝迟到结果，不冒称硬中断。通用profile的可选 `max_image_edge` 省略时仍为 `null`；Luna示例及 `--luna-api` 默认入口现显式设为1600。仅较大图像按比例缩小、不放大小图；请求中的image_size使用实际提交尺寸，返回几何先按该尺寸校验，再按实际两轴比例回映原截图。原截图/hash及供Decision使用的原图保持不变。 / The pooled transport retains idle connections for60 seconds and applies one budget without retries. Generic profiles still default resizing off; the Luna example selected by `--luna-api` explicitly limits the longest edge to1600. Larger images shrink without upscaling smaller images. Prompt dimensions match submitted pixels; output geometry is validated there and restored by actual per-axis ratios. Original captures/hashes and Decision image resolution are preserved.

共享HTTP传输在非200响应收到头后关闭正文流，保留状态和响应头供视觉API/Decision分类；401/429不再因错误正文慢、过大或压缩而变成解析/超时错误。200响应仍受原编码、字节上限和总预算限制。 / Non-200 responses preserve status and headers without buffering their bodies; success responses retain the existing encoding, size and deadline limits.

将上方配置另存为绝对路径 JSON。密钥在启动 MCP 的进程环境中设置，配置只保存变量名。管理员宿主从其自身环境读取密钥；UAC 桥不把密钥写进票据或转存。修改配置或环境后需重启连接。

Save the profile as an absolute JSON path. Set its named secret variable in the process launching MCP. Elevated hosts read their own environment; UAC tickets never contain the key. Restart the connection after configuration/environment changes.

```powershell
python scripts/start_instant_mcp.py --data-dir D:/AgentReviewData/api-fresh --recognition-source external_api --api-profile D:/AgentReviewConfig/vision-api.json --allow-local-input
```

也可用 `scripts/setup_instant.ps1 -RecognitionSource external_api -ApiProfile D:/AgentReviewConfig/vision-api.json` 安装轻量运行依赖并生成配置，不需要本地权重。配置生成不调用服务；宿主启动检查配置和密钥是否存在，不能把它当成服务商连通性证明。

The setup script supports external_api and ApiProfile with the lightweight runtime and no local weights. Configuration generation makes no provider call; startup validates the profile and credential presence, not provider connectivity.

使用 `instant_run` 的 `step/execute_recognition_plan`、`desktop_click`、`input_sequence` 或 `form_fill`；沿用 `agent_command.v1` 回执和 `agent_command_status` 查询。API 会在同一命令的每次定位时自行请求，无须客户端调用 `grounding_resolve/agent_command_continue`，也不要重发原批次。`agent_command_cancel` 请求停止；已派发输入不会撤回。HTTP 返回后、派发前再检查取消、窗口身份、截图新鲜度及目标边界。

Use the existing step/desktop-click/input-sequence/form-fill commands and agent_command_status. Each localization runs automatically through the API; clients do not resolve or continue API grounding manually. Cancellation remains cooperative and never rolls back dispatched input. Existing live identity, freshness and geometry checks remain required.

API 只定位，不自动判断整项任务成功。`read_text` 仍返回原图交调用方读取；动作后按所选核验路线结算，合格本地证明或已认证Decision可连续推进，否则由原主Agent审核。`recognition_calls` 在完整及精简回执中保留服务商返回模型、用量、耗时；`api_request` 表示请求阶段。缺少密钥、鉴权失败、限流、超时、畸形输出或目标缺失均明确报错，零自动重试，不静默切换识别来源。 / Grounding does not establish task success. Result adoption follows local/Decision/Main verification; failures remain explicit without automatic retry or provider switching.

The API localizes targets rather than judging task success. read_text remains original-image handoff to the caller. The main agent reviews after-images and receipts. Full/compact receipts retain provider model, usage and timing in recognition_calls plus api_request phase. Missing credentials, authentication/rate/timeout errors, malformed output and absent targets stop without retry or fallback.

## 验收边界 / Acceptance boundary

- v0.1.0 源码与隔离候选各 2040 项通过；真实 STDIO 无大模型环境的启动、清理与重连通过；回环 HTTP 配合原生窗口完成本方及独立 Agent 的真实单项、两轮填写、弹窗与异常恢复和清理。测试服务定位测试控件，不证明供应商视觉能力。详见 [验收记录](../verification/V010_RELEASE_ACCEPTANCE.md)。 / 2040 checks passed per source/bundle suite; model-free STDIO startup, cleanup and reconnect passed. Main-agent and independent loopback-HTTP native journeys covered single actions, two form rounds, dialogs, error recovery and cleanup. The fixture grounds test controls; it does not establish provider vision accuracy.
- 尚不验证或保证任意服务商在线兼容性、识别准确率、速度、费用，或管理员进程可继承密钥。Chat Completions 图像 JSON 协议是接入前提，不代表所有 OpenAI-compatible 服务都可直接使用。 / No claim is made for arbitrary provider compatibility, accuracy, latency, cost or elevated-process secret inheritance. Conformance to the image/JSON protocol is required but does not guarantee all OpenAI-compatible providers work.

API 截图数据边界与错误处理要求见上文；本版实测状态以验收记录为准。 / Screenshot-data boundaries and error handling are specified above; consult the acceptance record for this release's test status.


## 2026-10-12 Luna 坐标对照 / Luna coordinate comparison

2026-10-12：Luna 默认 profile 已设置 `max_image_edge:1600`，复用既有显式缩图和按实际宽高回映；每次定位仍只调用一次模型。真实同图对照中，原尺寸复现尺度偏移，缩图后地址栏两次回映点为(1224,60)/(1225,59)，右侧小按钮点为(2446,180)。174项相关离线检查通过；共4次Luna API请求、零桌面输入，尚未验证点击或完整浏览器流程。自定义profile及已运行宿主不自动改变，需新连接加载；安装器未更新。 / The Luna default profile now sets `max_image_edge:1600`, reusing explicit resize and actual-dimension coordinate restoration with one model call per localization. Same-image API comparisons reproduced the original scale mismatch and restored address-bar points to(1224,60)/(1225,59), plus a right-side button to(2446,180).174 related offline checks passed; four Luna requests, no desktop input or full-flow acceptance. Custom profiles/running hosts do not change automatically; reconnect to load. Installers are unchanged.

1600是本次验证的输入策略，不是对服务端内部尺寸规则的保证。缩图会损失小字/小目标细节；本次仅验证同一截图内两个目标，不宣称通用准确率或整流程提速。原图地址栏请求HTTP6.098s，对照缩图5.337s、默认复测5.498s；样本不足以证明稳定速度增益。见[完整证据](../verification/VISUAL_EXECUTION_DECISION_FLOW_20261011.md)。 /1600 is a tested input policy, not a guarantee of provider internals. Downsampling loses fine detail. Two targets in one saved image do not establish general accuracy or end-to-end speed; HTTP samples6.098/5.337/5.498s are not a latency benchmark.
