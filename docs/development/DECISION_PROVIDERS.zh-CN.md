# 配置 Decision 与普通模型复核服务

[English](DECISION_PROVIDERS.md) · [返回首页](../../README.zh-CN.md)

**源码更新，版本仍为 0.1.3。** 已发布的执行 0.1.3 安装包仍使用固定 OpenAI 地址和 Luna 模型。这些配置需要更新后的源码；本轮不改版本号和学习组件。

Decision 与普通模型复核现在可以分别配置接口地址、模型 ID 和密钥环境变量。视觉定位仍使用独立的[视觉 API 配置](EXTERNAL_VISION_API.md)，替换其中一层不会改变其他层。

## 如何配置

复制完整的[服务配置示例](../../configs/decision-profile.providers.example.json)，修改下方六个连接字段，通过现有 `--decision-profile` 参数传入文件路径。示例保留视觉执行的 Choice 策略，使用两个明确的密钥变量名，不包含密钥值。

| 层级 | 接口地址字段 | 模型字段 | 密钥环境变量名字段 |
| --- | --- | --- | --- |
| Decision | `endpoint` | `model` | `api_key_env` |
| 普通模型复核 | `ordinary_review_endpoint` | `ordinary_review_model` | `ordinary_review_api_key_env` |

示例中的连接字段为：

```json
{
  "endpoint": "https://api.openai.com/v1/decisions",
  "model": "gpt-6-luna",
  "api_key_env": "DECISION_API_KEY",
  "ordinary_review_endpoint": "https://api.openai.com/v1/responses",
  "ordinary_review_model": "gpt-6-luna",
  "ordinary_review_api_key_env": "REVIEW_API_KEY"
}
```

这段仅展示连接字段，不是完整执行策略。请使用链接中的完整配置，保留 `decision_format: "choice"` 和 `ordinary_review: "on_reject"`。让启动 MCP 的进程能够读取这些环境变量。两个变量可以存放相同或不同的密钥；不要把真实密钥写入 JSON。视觉定位 API 的密钥在其视觉配置中另行设置。

## 默认值与兼容范围

- 旧配置无需修改。Decision 默认使用 `https://api.openai.com/v1/decisions`、`gpt-6-luna`、`OPENAI_API_KEY`。普通复核默认使用 `https://api.openai.com/v1/responses` 和 `gpt-6-luna`；省略 `ordinary_review_api_key_env` 或设为 `null` 时，沿用 Decision 配置的 `api_key_env`。
- 明确指定的复核密钥缺失时，不会借用主判断密钥。Decision 已通过的检查仍可继续；确实需要复核时，返回 `ordinary_review_unavailable` 交主 Agent 处理，不发出第二次 API 请求。
- 地址必须是完整请求 URL，不会自动补路径。远程地址要求 HTTPS；明文 HTTP 仅支持 `localhost`、`127.0.0.1` 和 `::1`。URL 不得包含凭证、查询参数或片段。仍不跟随重定向，也不自动重试。
- 两层均使用 `Authorization: Bearer` 认证。Decision 服务须兼容现有 **Decisions 协议**，包括 Choice／predicate 答案和用量字段。普通复核服务须兼容 **Responses 协议**、图像输入和现有单选项输出格式，请求仍包含 `reasoning.effort: "none"`、`max_output_tokens: 32`、`store: false`、`service_tier: "default"`。普通 Chat Completions 接口不能直接替换。
- 返回的模型 ID 必须与配置完全一致，并满足现有响应格式。若模型别名返回了不同的实际 ID，需要兼容适配；格式错误或模型不符的结果不会被采纳。
- 流程仍是 **Decision → 未通过时普通模型复核一次 → 仍未解决则返回原主 Agent**。本次不改变提示词、阈值、裁剪图、动作门禁、超时策略和请求预算。自定义复核的回执会标明配置的复核模型。

## 如何生效

完成或明确停止当前任务，正常关闭其运行时会话，再用修改后的配置启动新会话；若 MCP 启动配置有变化，还需重新连接客户端。配置按会话冻结：修改文件不会热更新运行中的宿主，也不会悄悄重判旧请求。接口、模型和密钥变量名的变更会绑定到新配置；密钥值不会写入配置快照或结果。

## 验证范围

离线 HTTP 模拟覆盖独立路由与密钥、返回模型校验、默认请求内容不变、公开 CLI 配置、冻结配置重开及认证恢复不重复派发。这些检查不证明第三方服务的实际兼容性、准确率、速度或 token 收益。现有 0.1.3 性能数据只描述原 OpenAI 配置。
