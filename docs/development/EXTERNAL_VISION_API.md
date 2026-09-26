# 独立视觉 API 预留接口 / Reserved external vision API

test.8：仅交付预留适配器，未接入执行宿主 / Reserved adapter shipped in test.8; not wired to the execution host

用户目前没有独立 API，本版保留配置、传输适配和契约检查，不要求提供密钥，不把付费服务实测作为本版发布前置条件。`--recognition-source external_api` 仍明确拒绝启动；配置文件存在不代表该路线已启用。当前 Agent 和指定视觉子 Agent 路线不需要这个额外 API。

The operator has no independent API. This version reserves configuration, transport adaptation and contract checks, without requiring credentials or a paid-provider test. The host still rejects `external_api`; a saved profile does not enable it. Current-agent and delegated-agent routes do not require this additional API.

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

## 已验证与未验证 / Verification boundary

24 项隔离协议测试覆盖请求图像、UTF-8、模型配置、结果关联、畸形输出、拒绝/截断、超时/限流、并发占用与释放、错误脱敏，以及非法端口、NUL 路径和损坏 PNG。使用模拟 HTTP transport，没有调用付费服务。

Twenty-four isolated protocol checks cover image requests, UTF-8, configuration, correlation, malformed/refused/truncated responses, timeout/rate errors, bounded concurrency and sanitized failures, including invalid ports/paths and corrupt PNGs. Tests use a mock HTTP transport, not a paid provider.

**未验证：** 任意具体服务商的图像兼容性、准确率、速度、价格；API 路线的 MCP 启动和真实点击。后续有服务后先验证协议，再接入统一候选/执行链，不能把此适配器直接算作完整 API 执行模式。

**Not verified:** provider compatibility, accuracy, latency, price, API-mode MCP startup or real clicks. Validate a real provider before wiring the shared candidate/execution route; this reserved adapter is not an operational API execution mode.
