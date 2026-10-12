# 启动判定与截图前失败结算 / Startup and pre-capture settlement

2026-10-12 源码修复，未发布；不更改 Decision 阈值，不清理浏览器资料与缓存。 / Unreleased source repair; Decision thresholds and browser data/cache remain unchanged.

## 故障与根因 / Failure and invariant

原失败目录：D:/AgentReviewAcceptance/native-focus-geometry-20261012-empty-repeat-02。
选窗内层 focused，但外层 failed、operation_succeeded=false，错误 capture_window_occluded。旧调用驱动仅按 focused 提交后续计划。输入又在 _CoordinatorProxy.execute_local_step 的 capture_current 处失败，此时尚未创建 grounding 请求或调用动作路由；原回执 dispatch_attempts 为空，session 没有 runtime-output，Decision used=0。异常被统一记成 unknown，取消无法结算。无法由这些证据确定实际遮挡窗口或认定用户切窗。

The driver ignored an outer selection failure. The subsequent capture failed before grounding/model/input dispatch; generic exception handling lost this known no-input boundary. The incident has no local-direct-step report. The actual occluding window remains unidentified.

必须成立：只有完整成功、目标绑定的选窗结果才能启动；运行时能证明未派发的失败应正常结算，已经派发或证据不完整的动作仍不得推断为未执行。 / Invariants: complete target-bound selection precedes startup; proven pre-dispatch failure settles without treating unknown or started input as unexecuted.

## 通用修复 / Shared fixes

- scripts/execution_startup.py 复用 ExecutionClient，要求 returned、operation_succeeded=true、terminal、原选择 ID、正确进程实例、允许的截图及文件 SHA 一致，才提交原计划一次。失败保留 selection 回执，不重试。
- agent_command_jobs 在真实 pre-grounding capture 异常边界生成 pre_grounding_capture_failure.v1 回执，记录原请求、目标身份/几何、关闭状态、未创建 grounding/未开始派发和摘要。仅捕获这一边界的 CaptureVisibilityError；身份无法核验则保持未知。
- input_sequence、receipt_action、recognition_dispatch、input_sequence_partial 使用共同的只读验证器。认证零输入失败可取消并释放新计划准入；损坏证明、后续 capture/route 异常仍保持 unknown。没有修改 local_direct_step 的更晚派发边界。

The shared startup adapter and runtime receipt readers apply to any supported window, not a Google-specific workaround. The pre-grounding receipt authenticates the original no-dispatch boundary within existing receipt ownership/file binding. It grants no action/replay authority.

## 离线验证 / Offline verification

旧启动判断复现：9 failed / 2 passed；修复后 startup/client：35 passed。真实代理结算新回归先为11 failed / 2 passed，修复后13 passed。Main 最终整合15个相关模块：**283 passed in 19.86s**；包含真实 AgentCommandJobs、同步/异步队列取消→cancelled→新计划准入、无重放、证明篡改、更晚派发异常、现有输入/空框和截图归属。Worker 的122项与 Main 重叠，不相加。

Main command: D:/agent-gui-runtime/.venv/Scripts/python.exe -B -X utf8 -m pytest -q tests/test_execution_startup.py tests/test_execution_client.py tests/test_pre_capture_failure_settlement.py tests/test_agent_command_jobs.py tests/test_agent_command_dispatch_attempts.py tests/test_agent_command_action_review.py tests/test_task_plan_queued_cancel.py tests/test_recognition_no_dispatch.py tests/test_recognition_dispatch_boundary.py tests/test_visual_empty_input.py tests/test_visual_empty_partial.py tests/test_visual_input_no_uia.py tests/test_input_sequence_focus_partial.py tests/test_input_sequence_visual_focus_partial.py tests/test_capture_window_ownership.py --tb=short --junitxml=.superpowers/sdd/2026-10-12-startup-settlement/main-regression.xml

证据：.superpowers/sdd/2026-10-12-choice-runtime/startup-{red,green}.xml；.superpowers/sdd/2026-10-12-startup-settlement/main-regression.xml。

## 真实运行 / Live result

**没有完整通过。** 同一保留 Edge profile：D:/AgentReviewAcceptance/current-step-decision-20261012-1791764425288/edge-profile。

1. native-focus-geometry-20261012-startup-fixed-03：新选窗判定通过；自动输入 Google 网址、按 Enter 并确认首页。点击搜索框后，after_click Choice 返回 evidence_insufficient，空框内容选 empty；在键入 java 前交回 Main。原输入明确 failed，仅 focus 已执行。Decision 7次。
2. Main 查看原始截图，确认普通空框和展开的建议列表，显式新建剩余两步计划；同一窗口、同一 profile，原失败留存。native-focus-geometry-20261012-startup-remainder-04 再次在相同焦点审核返回 evidence_insufficient（内容 uncertain），仍未键入 java、未打开结果链接。Decision 2次。此次续接为 Main 接管，不计全自动通过。

Both live selections passed. Google navigation succeeded, but the search-field focus check requested Main twice before typing. One explicit Main-reviewed remainder was attempted without replaying the URL or typed text. Both failures settled as failed, not unknown. The complete Google→java→first-result flow remains unverified on this candidate. Nine Decision requests in total.

两个宿主 cleanup_verified=true；原测试窗口经身份核验正常关闭，未强杀、未删除 profile/cache。实际 pre-grounding capture 故障本轮没有再次出现，该修复的异常路径证据来自离线注入，不能用新的焦点失败冒充实机截图异常修复验证。

Evidence: D:/AgentReviewAcceptance/native-focus-geometry-20261012-startup-fixed-03/{flow-result.json,host-cleanup.json,isolated-browser-cleanup.json,final-summary.json}; D:/AgentReviewAcceptance/native-focus-geometry-20261012-startup-remainder-04/{main-review.json,flow-result.json,host-cleanup.json}. The live runner uses scripts.execution_startup.run_selected_plan; it treats review_required/failed as non-success.

## 风险与下一步 / Safety and next step

身份、几何、截图可见性、点击门禁、原输入认证、取消和无自动重放不变；此修复不放宽提交/发送/确认/支付动作。不是删掉截图遮挡检查，也不宣称该检查误拒已解决。

当前后续重点是 Decision 输入前焦点证据与提示词的专项核对；先用这两次留存图分析再决定修改，不能调整阈值或反复实机抽样来掩盖失败。此前单次3/3成功及随后截图失败都保留，连续可靠性仍未通过。

Safety gates remain intact. Next investigate the retained focus evidence and Decision question; do not relabel repeats as success or change thresholds to conceal the failure. Earlier success and subsequent failures remain separate.
