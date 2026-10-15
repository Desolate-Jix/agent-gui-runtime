# 普通Luna复核时限修复 / Ordinary Luna review deadline repair

2026-10-14，未发布源码。范围为复核的可用时间、总截止和诊断，不承诺模型永远判断正确或网络永不超时。 / Unreleased source; this repairs timing and diagnostics, not model accuracy or network availability guarantees.

## 已确认原因 / Confirmed causes

旧配置使两层共享8秒：首轮Decision HTTP已用1.897秒，两级服务在8.015秒结束。调用方尚余48.225秒，真正紧约束是本地共享8秒。旧超时记录把排队、HTTP及收到有效回答后的迟到都记为同一个三字段错误，已返回的usage/provider ID还会丢失，**无法事后认定首败具体属于哪一阶段**。 / The shared local deadline was tighter than the caller budget. The original record cannot distinguish queue, transport and late-result expiry, so the precise historical phase remains unknown.

离线复现还确认：普通首层payload即使声明0.2秒，准备已经耗0.3秒，旧适配器仍以完整8秒派发；未传HTTP绝对总截止。普通review路径已读剩余时间，但仍受primary的8秒总预算及provider默认8秒上限挤占。 / A separate reproduction proves that plain primary requests ignored the supplied remaining budget and omitted the absolute HTTP deadline. The secondary lacked a complete independent allowance.

证据 / Evidence: `D:/AgentGUI-Projects/evidence/ordinary-review-timeout-20261014-01/initial-audit.json`。

## 修复 / Repair

- 新维护示例显式设 `ordinary_review_timeout_seconds: 12`；primary仍是8秒。复核进入时获得自己的12秒额度，包含账本、准备和排队。它是上限，不是固定等待。 / The explicit secondary cap is12s; primary remains8s. Neither is a mandatory wait.
- `request_budget_seconds`、assessment和temporal的原总截止继续约束两层；每个阶段都取较短的剩余量。旧字段缺省或null保持原共享预算及配置序列化摘要，不自动修改已冻结会话。 / Outer deadlines always dominate. Omitted/null secondary caps preserve legacy profile serialization and shared behavior.
- 两路provider均扣准备及排队，向维护HTTP transport传 `extensions.total_deadline`，整个网络交换按单调截止取消；无自动重试。 / Preparation, queuing and the complete HTTP exchange consume the same stage deadline; no automatic retries.
- 超时记录可带固定phase/code及已知usage、HTTP/server时间和provider ID；未知用量仍是null。收到晚答、结算锁或持久化期间越界也不采用；认证回读必须保持相同结果。 / Fixed diagnostics preserve known measurements without exception text. Late responses and settlement cannot authorize continuation; replay remains authenticated without redispatch.
- `target_check`提示词版本升至 `decision_prompt.target_check.v2`，不会把旧问题缓存当作新问题结果。 / A prompt-version bump separates old cached assessments.

CPU截图/图片准备和同步持久化只能在边界检查期限，不能宣称这些操作在到点时被硬中断。网络不可用、拒绝、复核不通过或超时均交原Main，不绕过动作门禁。 / Synchronous CPU and persistence work are checked at boundaries, not hard-interrupted. Unresolved results return to the existing Main.

## 验证 / Verification

新增最小回归先RED：13失败、9通过；修复后22项通过。首批范围回归326通过/9失败，9项为旧测试要求网络阶段重开完整时间或让迟到结果成功；调整独立阶段夹具、剩余预算断言及冷客户端余量后335项通过。首次失败ID和理由保留在 `first-regression-failures.json`，没有改记为首次通过。 / Initial regression failures and fixture corrections are retained separately.

Main最终独立运行受影响上下游：**368 passed in18.43s**。未跑整个仓库，也不替代安装版/桌面验收。 / Main's affected-scope verification passed368; this is not the entire repository or installed/desktop acceptance.

```text
D:/agent-gui-runtime/.venv/Scripts/python.exe -X utf8 -m pytest tests/test_ordinary_review_time_budget.py tests/test_luna_choice_review_provider.py tests/test_ordinary_review_cascade.py tests/test_decision_http_deadline.py tests/test_decision_service.py tests/test_decision_choice.py tests/test_adaptive_decision_policy.py tests/test_openai_decisions.py tests/test_target_check.py tests/test_grounding_target_check_wiring.py tests/test_ordinary_review_input_consumers.py -q
```

真实API诊断复用首败历史图，全部使用修后真实Decision→普通Luna，无桌面动作、无强造首层回复。 / Real API replay used both actual model stages, with no synthetic primary answers or desktop input.

| 样本 / Sample | 普通复核 / Secondary | HTTP | 两级墙钟 / Wall | 判断结果 / Classification |
|---|---|---:|---:|---|
| 正确地址栏1 / Correct field1 | completed | 2.393 s | 4.519 s | 两层均误拒→Main / Both reject incorrectly |
| 同图重复2 / Same image repeat2 | completed | 2.370 s | 4.517 s | 两层均误拒→Main / Both reject incorrectly |
| 同点错误目标 / Wrong target | completed | 2.599 s | 4.338 s | 两层均正确拒绝→Main / Both reject correctly |

三次复核均正常返回、没有超时，读回及关闭重开没有新增API请求，源码前后摘要一致。但**正例2/2仍误拒，复核可用不等于判断准确**；这张图仍作为难例保留，不把完成状态当作任务成功。新Decision短提示词在另一保留集改善的结果见[提示词选型](TARGET_CHECK_PROMPT_20261014.md)。 / Three secondary calls completed without timeout and authenticated replay issued no calls. Both positive repeats still failed semantically; availability is not accuracy.

真实诊断共6个返回请求，4,487输入/21输出token；证据位于 `D:/AgentGUI-Projects/evidence/ordinary-review-timeout-live-20261014-01`，含profile、来源、源码摘要、assessment及summary。12秒只是可配置额度，3次正常返回不证明永不超时。 / Six responses used4,487 input and21 output tokens. The configurable cap is not an availability guarantee.

## 通用故障合同 / Reusable runtime contract

1. Failure：正确地址栏在输入前被拒，复核超时，任务停下。 / The fallback was unavailable within its budget.
2. Root invariant：每阶段必须使用真实剩余时间，复核不得被首层耗时隐式挤占；外层总截止不可刷新；迟到结果不可续行。 / Respect stage and outer deadlines without adopting late results.
3. Fix location：公共judgment service/provider/profile及安全超时记录，不是浏览器专用适配。 / Shared runtime judgment layer.
4. Why not app-only：任意Windows应用的同图复核和其他Decision请求都获得一致预算与诊断。 / Applies to all callers, not one site.
5. Regression：假钟、排队、真实本机HTTP/慢流、账本、迟到计量、重开及原请求防重派覆盖；保留真实首败及复测。 / Deadline, metadata, persistence and replay coverage.
6. Safety impact：不改阈值/裁剪，不增加自动重试、输入权限或终提交范围；失败继续交Main。 / Existing action and final-submit gates remain unchanged.
