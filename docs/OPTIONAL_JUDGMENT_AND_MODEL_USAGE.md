# 可选决策判断接口 / Optional outcome judgment contract

v0.1.1 预留 `app.core.outcome_judgment.JudgmentProvider` 与 `OptionalJudgment`。供应商未接入，正式执行不会自动调用判断模型；现有外部视觉 API 定位路线继续使用原协议。`enabled=False` 或未连接 provider 会在证据工厂前返回，不采图、不读证据、不联网、不增加供应商等待。/ The shared outcome contract is reserved but unwired. Existing visual grounding is unchanged; inactive judgment returns before evidence creation or transport.

- 请求绑定原 execution_request_id、明确条件、capture/hash/window 引用；learning 模式还要求原 run_id/step_id。/ Requests bind the original execution and capture evidence; learning additionally requires run/step identities.
- 回复回显请求哈希，严格 true/false/null 映射 success/failure/uncertain，可选真实概率和用量；不估计缺失值。/ Strict bound replies map to an advisory verdict, with actual optional probability and usage only.
- 图像不能静默降为纯文本，超时或协议错绑保持 uncertain，禁止自动重试、改写 action_executed 或获得输入权限。/ Images cannot silently degrade to text; errors remain uncertain without retry, altered input facts or authority.

后续薄供应商 adapter 负责凭据、图像读取、协议映射及有界传输期限；原证据 builder 负责实际图片哈希、新鲜度和窗口/进程身份，当前引用格式校验不证明这些实时事实。判断应接入原动作回执之后的核验链；未来学习应保留自己的原票据、审核及结算绑定，不能把通用 verdict 直接写成工作流成功。/ A later adapter owns transport, while an original-evidence builder must prove content, freshness and identity. Judgment joins post-action verification; future learning must retain original tickets and settlement bindings.

本版未提供供应商配置 UI、公共判断 HTTP 端点、生产求值接线或学习产品。ModelUsage 只是严格用量格式，未知保持 null；这不证明全量 Agent 用量。真实供应商连通、识别准确率、延迟和费用未认证。/ No provider settings, public judgment endpoint, production invocation or learning product is added. Unknown usage stays null; live-provider quality and cost are unverified.
