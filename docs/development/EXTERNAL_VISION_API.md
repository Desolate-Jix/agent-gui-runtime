# 外部视觉 API 接口 / External vision API

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

将上方配置另存为绝对路径 JSON。密钥在启动 MCP 的进程环境中设置，配置只保存变量名。管理员宿主从其自身环境读取密钥；UAC 桥不把密钥写进票据或转存。修改配置或环境后需重启连接。

Save the profile as an absolute JSON path. Set its named secret variable in the process launching MCP. Elevated hosts read their own environment; UAC tickets never contain the key. Restart the connection after configuration/environment changes.

```powershell
python scripts/start_instant_mcp.py --data-dir D:/AgentReviewData/api-fresh --recognition-source external_api --api-profile D:/AgentReviewConfig/vision-api.json --allow-local-input
```

也可用 `scripts/setup_instant.ps1 -RecognitionSource external_api -ApiProfile D:/AgentReviewConfig/vision-api.json` 安装轻量运行依赖并生成配置，不需要本地权重。配置生成不调用服务；宿主启动检查配置和密钥是否存在，不能把它当成服务商连通性证明。

The setup script supports external_api and ApiProfile with the lightweight runtime and no local weights. Configuration generation makes no provider call; startup validates the profile and credential presence, not provider connectivity.

使用 `instant_run` 的 `step/execute_recognition_plan`、`desktop_click`、`input_sequence` 或 `form_fill`；沿用 `agent_command.v1` 回执和 `agent_command_status` 查询。API 会在同一命令的每次定位时自行请求，无须客户端调用 `grounding_resolve/agent_command_continue`，也不要重发原批次。`agent_command_cancel` 请求停止；已派发输入不会撤回。HTTP 返回后、派发前再检查取消、窗口身份、截图新鲜度及目标边界。

Use the existing step/desktop-click/input-sequence/form-fill commands and agent_command_status. Each localization runs automatically through the API; clients do not resolve or continue API grounding manually. Cancellation remains cooperative and never rolls back dispatched input. Existing live identity, freshness and geometry checks remain required.

API 只定位，不自动判断整项任务成功。`read_text` 仍返回原图交调用方读取；动作后原图与回执由主 Agent 核对。`recognition_calls` 在完整及精简回执中保留服务商返回模型、用量、耗时；`api_request` 表示请求阶段。缺少密钥、鉴权失败、限流、超时、畸形输出或目标缺失均明确报错，零自动重试，不退回 VISTA 或 Luna。

The API localizes targets rather than judging task success. read_text remains original-image handoff to the caller. The main agent reviews after-images and receipts. Full/compact receipts retain provider model, usage and timing in recognition_calls plus api_request phase. Missing credentials, authentication/rate/timeout errors, malformed output and absent targets stop without retry or fallback.

## 验收边界 / Acceptance boundary

- v0.1.0 源码与隔离候选各 2040 项通过；真实 STDIO 无大模型环境的启动、清理与重连通过；回环 HTTP 配合原生窗口完成本方及独立 Agent 的真实单项、两轮填写、弹窗与异常恢复和清理。测试服务定位测试控件，不证明供应商视觉能力。详见 [验收记录](../verification/V010_RELEASE_ACCEPTANCE.md)。 / 2040 checks passed per source/bundle suite; model-free STDIO startup, cleanup and reconnect passed. Main-agent and independent loopback-HTTP native journeys covered single actions, two form rounds, dialogs, error recovery and cleanup. The fixture grounds test controls; it does not establish provider vision accuracy.
- 尚不验证或保证任意服务商在线兼容性、识别准确率、速度、费用，或管理员进程可继承密钥。Chat Completions 图像 JSON 协议是接入前提，不代表所有 OpenAI-compatible 服务都可直接使用。 / No claim is made for arbitrary provider compatibility, accuracy, latency, cost or elevated-process secret inheritance. Conformance to the image/JSON protocol is required but does not guarantee all OpenAI-compatible providers work.

API 截图数据边界与错误处理要求见上文；本版实测状态以验收记录为准。 / Screenshot-data boundaries and error handling are specified above; consult the acceptance record for this release's test status.
