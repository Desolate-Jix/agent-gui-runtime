## 2026-10-08 当前接入 / Current integration

开发源码已接通 `app/judgment/DecisionService`：OpenAI Decisions 适配器、非秘密配置、证据绑定、持久防重派、执行前后检查及学习 Trial 结算共用同一服务。`app/core/outcome_judgment.py` 的旧可选接口继续保留兼容测试；下方“尚未接入”的段落属于历史记录，不再描述当前源码。已发布安装包尚未更新。 / Development source now shares DecisionService across execution checks and learning settlement, with the OpenAI adapter, evidence binding and durable dispatch protection. The old OptionalJudgment interface remains for compatibility; the unconnected-state descriptions below are historical. Released installers are unchanged.

本地图像成功不调用 API；没有配置时沿原路线。配置默认 shadow；auto 只用于完全匹配允许清单的审核条件，错误和不确定保留 Agent。原回执与任务效果分开，重复读取不重复网络请求。API usage/timing 保存在服务结果；现有 caller_reported 计量保持独立，不据此宣称全量 Agent 节省。 / Local image success is zero API, absent configuration preserves existing behavior, shadow remains the configured default, and auto adoption is explicit. Service usage/timings are factual; caller-reported totals remain separate.

配置、请求示例与边界见 [Decision API](development/DECISION_API.md)，本轮证据见 [验证记录](verification/DECISION_API_INTEGRATION.md)。 / See the current integration guide and verification report.

## 2026-10-01 历史维护接入位置 / Historical integration positions

本轮执行代码归层保留以下真实合同，不新增重复判断协议或执行器。`OptionalJudgment` 目前仅有离线合同测试，没有生产自动调用、供应商适配器、设置 UI 或公共判断 HTTP 端点。/ Execution cleanup preserves these existing contracts, without duplicate judgment protocols or executors. Optional judgment still has no production invocation, provider adapter, settings UI or public judgment endpoint.

| 边界 / Boundary | 当前保留与以后接线 / Current contract and future wiring |
| --- | --- |
| 决策模型 / Judgment model | `app.core.outcome_judgment.JudgmentProvider.judge` 与 `OptionalJudgment.evaluate`，execution/learning 共用。disabled/not_connected 在证据工厂之前返回；不采图、不探网、不增加供应商等待。/ Shared execution/learning contract; inactive states short-circuit before the evidence factory. |
| 执行核验 / Execution verification | 原动作回执之后，经 Verifier/Instant agent_review 的原图与窗口身份构造证据。未来建议独立于 action_executed，不能把派发成功当任务成功、改输入事实或自动重试。/ Future evidence comes from original post-action verification, with verdict separate from input facts and no automatic retry. |
| 学习观察 / Learning observation | `app.execution.local_direct_step.LocalDirectStepMixin.execute_local_step(..., learning_context=None)`；事件只含原 event_id/command_sha256，经原 Jobs 冻结、owner learning_capture_scope 和输入前 observe_learning_target。不从 UI 或判断结果旁路输入。/ Original frozen tickets and owner scope provide pre-input learning evidence through the same route. |
| 学习工作流 / Learning workflow | `WorkflowRuntime` 为原 Runner 注入 submit_command/read_result/verify_step/settle_failed。将来判断进入 `_verify`/verify_trial_step 的原核验链，保留 Trial 的终态、EID/run/step/window/scope 绑定与幂等；通用 verdict 不能直接替代完整核验结果或冒充人工审核。/ Future advisory judgment joins original verification and Trial settlement, retaining identity and idempotency checks. |
| 调用计量 / Telemetry | 原 `learning_workflow.record_model_call` 只收实际调用记录；缺失为未知，记录不推进步骤、不证明全量主 Agent 用量。/ Original caller telemetry remains factual, partial and separate from step progression. |

后续薄 adapter 自己处理凭据、图像读取、供应商协议和有界网络期限；原证据 builder 校验实际文件哈希、新鲜度及窗口/进程身份。当前引用格式校验不提供这些实时保证；同窗口合同也未覆盖“关闭子弹窗后观察父窗口”，该扩展需沿原所有权合同单独实现。超时/错绑/错误回复保持 uncertain，无自动重派。导航 choice_id 模型和视觉坐标 grounding 继续使用各自语义。/ The later adapter owns transport deadlines and protocol mapping; an original-evidence builder must prove content, freshness and identity. Cross-window dialog/parent evidence remains open. Errors stay uncertain without replay; navigation and grounding retain separate semantics.

本批预检将判断合同列为维护依赖，验证默认零证据/零调用与 learning 异常清理；352 项相关检查与隔离入口检查通过，未测试真实供应商连通或准确率。现有宿主未重载。/ The contract is explicitly checked as a maintained dependency. Source/isolation checks pass, without live-provider or accuracy claims or existing-host reload.

# 可选判断接口与调用方计量 / Optional judgment and caller telemetry

2026-09-30，开发源码，尚未打包发布。两项均可脱离实机独立验证。 / Development source only, not packaged or released; both slices support isolated verification.

## 调用方用量 / Caller telemetry

`learning_workflow` 新增 `action=record_model_call`，沿用原 MCP 命令、会话和存储锁。原执行回执或草稿整理回复必须已存在；记录只写计量，不执行输入、不完成核验、不推进工作流。它不是自动获取 Codex 内部调用的探针。只有调用方实际拿到逐调用记录时才提交；没有记录则省略调用，不用交接次数、工具次数、等待时长或估算 token 代填。 / The existing command/session/lock accepts supplied per-call records after the original execution or synthesis reply exists. This records telemetry only, without input, verification or workflow advancement. It cannot inspect hidden Codex calls. Never substitute handoffs, tool calls, waits or estimates for actual telemetry.

示例为格式演示，不是实测数据；所有身份须替换为当前运行及供应商实际值。 / Illustrative format only; replace identities and measurements with actual records.

```json
{
  "kind": "learning_workflow",
  "request": {
    "action": "record_model_call",
    "scope": {
      "kind": "workflow",
      "run_id": "original-run-id",
      "step_id": "original-step-id",
      "execution_request_id": "original-execution-request-id"
    },
    "model_call": {
      "provider": "actual-provider",
      "model": "actual-model",
      "call_id": "actual-provider-call-id",
      "source": "agent_current",
      "phase": "verification",
      "status": "success",
      "usage": {"input_tokens": 11, "output_tokens": 3},
      "elapsed_ms": 12.5
    }
  }
}
```

- `source`：`agent_current|agent_delegate|external_api|local`；`phase`：`planning|grounding|verification`；`status`：`success|failure|timeout|cancelled`。失败的实际尝试也单独保留。 / Failed actual attempts remain separate records.
- `usage` 必填，可为 `null`；非空时必须有非负整数 `input_tokens`、`output_tokens`，可选 `total_tokens` 不小于两者之和。缺总数但两个分项均已知时才求和。`elapsed_ms` 可缺省或为 `null`；它只是调用方给出的单次耗时，不写进本地单调时钟。 / Usage is required but nullable; complete components can be summed. Optional duration never enters the local monotonic timeline.
- 草稿整理替换 `scope` 为 `{kind:"synthesis",synthesis_id,source_sha256,reply_request_id}`，`phase` 必须为 `planning`。绑定确切的完成或纠错回复；`synthesis_status` 返回独立汇总。 / Synthesis binds an exact completion/correction reply, with planning-only telemetry returned by synthesis_status.
- 每个供应商调用只归属一个原始范围；同一会话内 `(provider, call_id)` 相同且内容相同可幂等重交，内容或归属不同即拒绝。记录位于 `session/caller-model-calls/`。 / One original scope per provider call, idempotent identical submissions, conflicting payloads rejected.
- 普通 `status.metrics.caller_reported` 和 `synthesis_status.metrics.caller_reported` 标注 `coverage=caller_reported_partial`、`independently_verified=false`。不合并进 `observed`，防止与已有运行时 API 计量重算；整个任务的 `total_model_calls/total_usage` 仍为 `null`。没有记录时保持旧字段形状。任一选中记录缺用量/耗时，相应聚合保持未知。 / Caller summaries remain separate from observed metrics and cannot prove whole-task totals. Missing records preserve the old shape; incomplete usage/duration remains unknown.
- 写入和汇总复核原回执身份、记录内容哈希及原回执文件哈希。变更、损坏或丢失显示调用方计量 `unavailable`，保留原件，不改变执行事实。哈希校验不是供应商真实性认证。恢复原件后可重读；不可重新派发输入来修复计量。 / Identity and content/source hashes detect changed or missing records, without authenticating provider claims. Restore evidence and reread; never replay input to repair telemetry.

## 共用判断位置 / Shared judgment extension

`app/core/outcome_judgment.py` 提供 `JudgmentProvider` 与 `OptionalJudgment`，供后续执行/学习结果核验复用。当前仅预留可测试的程序接口：尚未接到运行时的自动结算、设置面板或供应商网络适配器。未增加供应商名称、模型 ID、API 价格或准确率假设。 / A testable programmatic extension is reserved for execution and learning outcome checks. Runtime settlement, settings UI and a vendor transport are not connected; no vendor/model/pricing/accuracy assumptions are made.

`OptionalJudgment()` 默认关闭；关闭或没有 provider 时，在调用 `request_factory` 前返回 `disabled/not_connected`，不采图、不读图、不访问网络、不增加等待。原规则与 Agent 核验路径继续使用。 / Disabled or unconnected evaluation returns before evidence creation, with no captures, image reads, network calls or new waits; existing rule/Agent checks remain available.

接入后的契约 / Contract for a future adapter:

1. 输入确切 `request_id`、`mode=execution|learning`、`execution_request_id`、待核验的 `condition` 和 1–2 份证据。学习模式还须 `run_id/step_id`。证据含 `capture_id/sha256/window_id/role`，以及 `image_ref` 或 `text`；同一窗口、不重复采集 ID、恰好一份 after 证据，可选一份 before。 / Bind the exact request, execution, condition and evidence; learning also binds run/step, with one current after frame and optional before frame in the same window.
2. 适配器接收规范化载荷及 `request_sha256`，返回同一哈希、严格布尔值或空值 `answer=true|false|null`、可选真实概率和用量。映射为 `success|failure|uncertain`；字符串“yes”和整数 1 均拒绝，不从答案编造概率。 / Echo the request hash and return a strict boolean or null, with optional actual probability/usage; no inferred confidence.
3. 图像证据不能交给仅支持文本的 provider 并静默丢图。请求/回复不匹配、协议失败或服务超时不能变成成功，且不自动重试。接口只给建议，始终 `authorizes_action=false`；它不定位坐标、不替代动作确认。 / Image input cannot silently degrade to text. Bound reply validation, no automatic retry, and advisory results only; no grounding or action authorization.
4. 将来的适配器负责网络超时、凭据、图像读取和供应商协议映射；超时抛 `TimeoutError`，服务/协议失败抛 `OSError/ValueError`。此同步接口不强制中断挂死的任意 provider；编程错误继续显式抛出。当前只校验引用绑定，不读取图片证明实际哈希/实时性；接线时仍需原采集和新鲜度校验。 / The future adapter owns transport deadlines, credentials, image loading and protocol mapping, using the documented exception contract. The synchronous interface cannot interrupt a hung implementation; programming errors propagate. Reference validation does not prove actual file content or live freshness.

## 验证与边界 / Verification and limits

相关自动检查覆盖原 MCP 请求校验与学习控制入口、真实格式的合成回执/草稿、幂等和错绑、缺计量、损坏证据、关闭零采集/零调用、严格回复和超时，以及原运行、报告和核验路径。完整命令与结果在本轮[验收记录](verification/LEARNING_WORKFLOW_BENEFIT.md)。 / Isolated checks cover maintained entrypoints, synthetic source receipts, idempotency, binding, missing/corrupt telemetry, inactive providers, strict replies and existing workflow compatibility; see the acceptance record for commands/results.

这不证明真实 API 连通、模型准确率、全量主 Agent token、实机加速或学习收益。当前代码未加载到旧宿主，也未形成新发布包。 / These checks do not prove live API connectivity, model accuracy, complete agent usage, physical speed or learning benefits; existing hosts/packages have not been updated.
