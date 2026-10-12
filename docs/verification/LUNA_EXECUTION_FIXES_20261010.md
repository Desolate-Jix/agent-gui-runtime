# Luna 执行复审修复 / Luna execution review repairs

日期 / Date: 2026-10-10. 分支 / Branch: `codex/dev-decision-api`.

用户在[三项复审发现](LUNA_EXECUTION_REVIEW_20261010.md)后要求“修”，本轮沿已批准的离线范围修复。保留上轮源码、历史通过记录和首次失败原件。Codegraph未初始化，采用限定源码与调用链检查。 / The user authorized repairs to the three findings within the existing offline scope. Historical results and first failures are retained; scoped source inspection replaces the unavailable index.

## 修复合同 / Repaired contracts

| 原故障 / Failure | 根合同与修复 / Invariant and repair | 范围与回归 / Scope and regression |
|---|---|---|
| JSONL纯图片报缺失，混合响应丢图却声称included / Image-only failure and false mixed-image delivery | ExecutionClient接收原PNG，核对上游SHA后保存在数据根的独立客户端目录；返回saved、绝对路径、SHA和上游块索引，compact也保留 / Save exact PNG bytes with verified hashes and honest file-delivery metadata | MCP返回解析增加扩展点，学习基准原解析保持；所有截图来源共用，非网站补丁 / Shared caller adapter; pure/mixed responses, hash, byte limit and real directory-junction escape tests |
| 普通命令MCP等待超出总预算 / Unbounded ordinary-command waits | 首次调用、原票据回读及worker状态查询使用同一剩余预算；超时保留未知与原ID，不重发动作 / Bound each await; retain the original receipt and no-replay recovery | 适用于所有普通命令。未发请求零预算不提交；已发同ID零预算不覆盖原输入事实 / All ordinary commands; both unissued and previously issued zero-budget cases |
| 401/429被慢/大/压缩正文掩盖 / Error bodies mask known HTTP status | 共享transport收到非200头后关闭正文流，保留状态与头；200继续原限制 / Preserve non-200 headers/status without body buffering; retain success-body bounds | 视觉API与Decision共用，非供应商特判；模拟流及127.0.0.1真实HTTP覆盖 / Shared visual/Decision transport; mock streams and real loopback HTTP |

输入授权、坐标门禁和业务取消逻辑不因这些修复放宽；未知结果不转成成功。没有修改特定网站适配器。 / These fixes do not loosen input authorization, coordinate gates or business cancellation; unknown results never become success.

## 验证记录 / Verification

命令统一使用`D:/agent-gui-runtime/.venv/Scripts/python.exe -B -X utf8 -m pytest -p no:cacheprovider`。 / All pytest runs use this interpreter and these options.

| 检查 / Check | 实际结果 / Actual result | 原件 / Evidence |
|---|---|---|
| HTTP新增回归修前→修后 / New HTTP regressions | 14 failed → 14 passed；相关5模块168 passed / Related five-module group passed 168 | [api](../../.superpowers/sdd/2026-10-10-luna-fixes/api/) |
| 调用器新增回归修前→修后 / New caller regressions | 最终RED 15 failed、无skip → GREEN 15 passed；相关4模块122 passed / Final RED without skips; related four-module group passed 122 | [caller](../../.superpowers/sdd/2026-10-10-luna-fixes/caller/) |
| 真实MCP SDK离线集成 / Real SDK offline integration | 3/3挂起路径可在同连接回读，原动作仅提交一次、无遗留waiter / Three suspended paths recover on the same connection with no replay or leaked waiter | [SDK证据](../../.superpowers/sdd/2026-10-10-luna-fixes/cancellation/benchmark_sdk_result.json) |
| Main最终24模块组合 / Main final 24-module group | **647 passed / 1 deselected / 148.33s**；0失败、错误、跳过，1085个源码/测试/配置SHA前后一致 / No failures, errors or skips; unchanged 1085-entry source snapshot | [完整命令及结果](../../.superpowers/sdd/2026-10-10-luna-fixes/run-01/) |

最终组合沿用上轮21模块并加入`test_execution_client_transport.py`、`test_api_flow.py`和`test_openai_decisions.py`；以`-k "not real_payload"`排除完整载荷构建，组件仅检查依赖及临时源码副本。Main另行复跑真实SDK正常/堵塞取消两项，退出码0。 / The final group extends the previous 21 modules with these three, excluding full payload construction. Main also reran both real-SDK cancellation probes successfully.

调用器中途组合曾120通过、2失败：旧测试用零预算模拟已发送pending，调整为亚毫秒正预算后受Windows计时精度影响。最终用首次假回执显式消耗预算的fixture保持原pending/不重发断言，122项通过；所有中途日志保留。路径越界测试起初因符号链接权限跳过，随后使用临时目录内真实Windows junction验证，最终无此跳过。 / Intermediate caller runs retained two timing-fixture failures. Explicit first-response budget consumption preserves the original pending/no-replay assertions. A Windows junction removes the initial symlink-permission skip. Original logs remain intact.

## SDK取消边界与未验证内容 / Cancellation boundary and remaining limits

本机固定依赖MCP 2.1.1的`wait_for`取消会发`notifications/cancelled`、移除RPC waiter并中断当前RPC handler；服务端已同步提交的业务命令仍由宿主继续处理。客户端返回`command_cancelled=false`，只读恢复原ID。独立AnyIO内存传输验证正常取消约31ms，若取消通知写队列堵塞则另等SDK固定约5秒清理（独立实测5.047秒，Main复跑5.032秒）；`total_timeout`不是硬实时上限。 / Cancellation affects the RPC wait, not the durable action. Same-session recovery works. A blocked cancellation write can add about five seconds of SDK cleanup; this is not a hard real-time deadline. [独立证据 / Independent evidence](../../.superpowers/sdd/2026-10-10-luna-fixes/cancellation/sdk_cancellation_result.json)，[Main复跑 / Main rerun](../../.superpowers/sdd/2026-10-10-luna-fixes/run-01/sdk/sdk_cancellation_result.json)

本轮只用合成PNG、临时目录、FakeSDK、内存流和回环HTTP。未操作桌面、使用真实密钥、调用付费API、启动执行宿主、构建完整交付包、安装或发布。真实模型准确率、实际桌面速度、UIA提供者行为及安装版仍待另行批准验收；离线修复通过不代表这些项目通过。 / Synthetic data, fake SDKs, memory streams and loopback HTTP only. Live accuracy, desktop latency, UIA provider behavior and installed delivery remain unverified and require separately approved acceptance.
