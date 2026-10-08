# Optional Decision API / 可选判断 API

2026-10-08，执行 **0.1.2-preview.2** / 学习 **0.1.0-preview.2**。执行与学习共用 `app/judgment`，调用 OpenAI `POST /v1/decisions`（`gpt-6-luna`）。它判断明确条件，不提供点击坐标或动态文本值；视觉定位仍使用当前 Agent、委派 Agent、外部视觉 API 或可选本地模型。 / Execution **0.1.2-preview.2** and learning **0.1.0-preview.2** share the OpenAI Decisions adapter. It checks explicit conditions; grounding and dynamic reading keep their existing providers. Local model weights remain optional.

## Configure / 配置

复制 [配置示例](../../configs/decision-profile.example.json) 到自己的配置目录。API Key 仅放在启动宿主实际可见的 `OPENAI_API_KEY` 环境变量；配置、MCP 参数和管理员连接票据只保存变量名称与文件路径。管理员进程的环境可能不同，缺 Key 会返回 `not_connected`。 / Copy the sample profile. Put the key only in the named environment variable visible to the actual host, including its elevated process. Never put the key in the JSON, command arguments or relay ticket.

为原 MCP 配置生成命令增加 `--decision-profile C:/path/decision.json`，例如： / Add the profile to the existing configuration command:

```powershell
python scripts/configure_instant_mcp.py --recognition-source agent_current --decision-profile C:/path/decision.json --data-dir C:/path/runtime-data --enable-local-input
```

也可给 `start_instant_mcp.py`、`start_instant_mcp_admin.py` 或宿主传该参数，或使用 `AGENT_GUI_DECISION_PROFILE`；显式参数优先。配置改动需要正常关闭并核实原会话已清理，再新开会话。既有正在运行的宿主不会热重载。当前没有判断 API 设置面板；PowerShell 快捷配置脚本还未提供独立参数，请使用上述 Python 配置入口。 / The normal/elevated MCP launcher and host accept the flag, or use `AGENT_GUI_DECISION_PROFILE`; an explicit flag wins. A changed profile requires a clean new session. Existing hosts do not hot-reload. There is no settings UI or dedicated PowerShell-wrapper option yet; use the Python configuration entrypoint.

| Mode / 模式 | Behavior / 行为 |
| --- | --- |
| 无配置或 `off` | 原流程；零新增判断采图、读图、网络或凭据访问。 / Existing behavior with no decision evidence/network/credential work. |
| `shadow`（配置默认） | 调用并记录建议，仍由 Agent 审核，不自动结算。 / Record advice; keep Agent review. |
| `auto` | 只自动采用 `auto_conditions` 中完全一致的条件，且证据、概率和原回执均有效。 / Adopt only exact allowlisted conditions with valid evidence and original receipts. |

默认阈值 0.9/0.1 只是配置起点，未证明已校准准确率。条件满足且错误/危险概率低才算 success；明确不满足可判 failure；冲突、灰区、拒答、超时、坏协议都保留 uncertain 并交回 Agent。`request_cap` 默认 20：普通执行按整个宿主会话计数，学习按每个 run 计数；动作前后共享各自额度。达到上限不再发送，不自动重试。 / Thresholds are provisional, not calibrated accuracy. Conflicting or inconclusive evidence returns to the Agent. The cap counts execution requests per host session and learning requests per run, shared across phases; reaching it stops new dispatches.

## Execution / 执行

只给需要语义核验的单步附加条件，不要求每次动作调用： / Add a check only where a semantic judgment is useful:

```json
{
  "kind": "step",
  "operation": "execute_recognition_plan",
  "request": {"goal": "Open detail for record R-101"},
  "decision_check": {"phase": "after_action", "condition": "The detail view for record R-101 is open."}
}
```

沿用 `instant_run/instant_submit` 的原 `request_id`；Agent 识图路由还需要原有 `vision_capabilities`。`after_action` 复用动作回执的最终截图，一次请求合并“条件满足”和“可见错误”两个独立判断。`operation_succeeded` 仍只表示输入路线结果；`task_effect_verified` 只有通过原执行/截图/条件绑定与认证的自动结果才能改变。影子、不确定及错误不触发重做输入。轮询只读原结果，不重复调用 API。 / Keep the original execution ID and existing vision-capability declaration. Post-action checks reuse the final receipt image and batch two predicates. Input dispatch and verified task effect remain separate. Polling never repeats the paid call or input.

`before_action` 当前仅支持 `step/execute_recognition_plan` 的真实候选派发边界，合并“前提满足”和“危险效果”判断。自动模式下明确列入的条件必须得到有效 success 才能继续原门禁；API 不能自行授权输入。等待期间窗口、图像、目标几何变化即拒绝派发。没有宿主判断 scope 的直接 HTTP 声明会拒绝，不能冒充已经受保护。`input_sequence`、`form_fill`、独立 `grounding_execute` 尚未提供此附加检查。 / Pre-action checks currently cover the recognition-plan step boundary only. A valid automatic success permits continuing the existing gates, never grants authorization. Changed evidence during the wait rejects dispatch. Batch/form-fill/separate-grounding routes are not covered by this new check.

已发布本地操作路线的自动风险策略仍关闭。新 before-action 路径只在显式检查且服务启用时保留现有作用域内 final-submit/send/confirm/payment 禁止项；不把全局搜索框里的 “Submit search” 当最终提交。这不是全产品安全保证，也不改变未配置判断的原路线。 / The published local route still has automatic risk interception off. This opt-in boundary additionally respects existing scoped prohibited-action classifications; it does not apply a global keyword filter or imply universal safety coverage.

## Learning / 学习

在正常草稿保存与审核流程中，为步骤设置： / Save and review an explicit step condition through the existing program workflow:

```json
{"verification":{"kind":"agent_judgment","decision_condition":"The detail view for record R-101 is open."}}
```

可同时保留原 `image_check`：本地图像匹配成功仍零 API；只有证据完整、重新计算一致的 `image_not_matched` 才进入语义判断，复用最后一帧，不另采一次。没有图像规则的显式语义检查通过维护接口采集新图；未配置、关闭或缺 Key 的首次语义检查直接返回 Agent。修改条件生成新程序版本，必须重新审核；当前未增加 UI 专用编辑控件。 / Keep an optional local image check. Local success stays zero API; a proven semantic mismatch can reuse its final frame. Pure semantic checks capture through the maintained interface. Changes require review of a new pinned version; there is no dedicated UI field yet.

动态文字读取、输出变量、坏图、错窗、陈旧证据和取消/恢复冲突不会由“是/否”替代。自动采用经过原 Trial 结算，核对 run/step/execution/窗口/证据；不能伪装人工审核，单独声明的 Agent 成功断言仍需满足。已有条件会在图像规则编辑时保留，不会因修改阈值或关闭图像核验而静默丢失。 / Predicates do not extract dynamic output or override invalid evidence, cancellation, recovery or separate Agent assertions. Automatic adoption uses the original Trial settlement and binding checks. Editing or disabling image checks preserves an existing semantic condition.

## Evidence, timing and limits / 证据、耗时与限制

- 同一服务复用 HTTP 连接；没有重试、重定向或自动换模型。超时配置约束 HTTP 各阶段与排队等待，并非包含本地 I/O 的全流程硬截止。 / Persistent HTTP client, no retries/redirects/provider switching; the timeout is not a hard end-to-end deadline.
- 请求只上传当前步骤明确绑定的 1–2 张图；校验路径位于所属 session、文件 SHA256 和窗口进程身份。启用即会把这些图与条件发往 OpenAI。 / Only bound, verified session images and conditions are uploaded to OpenAI.
- `session/judgments/decisions.sqlite3` 保存发送标记和 Windows DPAPI 认证结果；崩溃/未知发送状态保留，不因重开重新付费。认证结果不代表模型判断必然正确。 / Durable dispatch markers and DPAPI-protected results prevent automatic repeat dispatch after reopening; authentication does not prove semantic accuracy.
- 会话冻结非敏感配置；恢复时核对原条件、回执、截图与认证账本，仅读取原证据，不需要 Key，不重新调用 API，也不修改来源会话。缺失或篡改的记录拒绝恢复。 / Recovery validates the original condition, receipt, image, frozen nonsecret profile and authenticated ledger without a key, new API call or source-session writes; missing or altered evidence is rejected.
- 回执区分 `elapsed_ms`、`http_elapsed_ms` 与服务端 `openai-processing-ms`（若提供），另含实际 tokens 与供应商 request ID。`elapsed_ms` 包含本地准备和发送标记，但在最终结果加密/落盘前结束；完整判断耗时须在 `evaluate` 调用外计时。各层时间有包含关系，不能相加；没有服务端时长就记未知，不把整个网络时间称为推理时间。 / Record service/client/server timings separately. Service elapsed includes preparation and the dispatch marker but stops before final result encryption/persistence; time the evaluate call externally for complete judgment latency. These nested timings must not be added together; unknown server time stays null.
- 集成检查见 [源码验证记录](../verification/DECISION_API_INTEGRATION.md)，本轮新数据实机流程、时间对照和安装范围见 [preview.2 验收](../verification/DECISION_API_RELEASE_ACCEPTANCE_20261008.md)。限定样本包含 API 灰区后交回 Agent 的情况；不能外推通用准确率、尾延迟或总 Agent token 收益。 / See integration and release evidence for bounded fresh GUI cases, timing comparisons and installed scope. A real gray-zone result required Agent review; the sample does not establish general accuracy, tail latency or total Agent usage savings.

协议依据：[OpenAI Decisions guide](https://developers.openai.com/api/docs/guides/decisions)。 / Protocol reference: the official Decisions guide.
