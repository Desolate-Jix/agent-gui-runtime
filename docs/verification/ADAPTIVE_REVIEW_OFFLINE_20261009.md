# Adaptive review offline verification / 主动审核离线验证

Date: 2026-10-09 (Pacific/Auckland). Worktree: `C:/Users/DesolateJix/.codex/worktrees/decision-api/agent-gui-runtime`; branch `codex/dev-decision-api`; base `5689d33738e75b722de7433454b2cc2661fd07da`. This is an unreleased source milestone, not live acceptance. / 这是未发布源码阶段结果，不是实机验收。

The user first required source-only development, then authorized tests that do not operate the computer while they use it. All runs below used temporary data, synthetic credentials, mocked HTTP and `QT_QPA_PLATFORM=offscreen`. No real desktop capture/input, paid API, installation or packaging occurred. / 授权范围为不操作桌面的测试；使用临时数据、模拟 API 和 Qt 离屏，没有实机、付费请求、安装或打包。

**Final frozen-source result: Main ran 31 files, 862 passed and 1 skipped in 107.05 s, exit 0.** The skip is the real symbolic-link test without OS permission; a separate resolved-path escape regression passed. Evidence: `main-p2-combined.xml`. This includes the core, automatic declared-loading observations and the fixes below; only documentation changed afterwards. / **最终源码：Main运行31文件，862通过、1项因符号链接权限跳过，107.05秒，exit 0。** 包含本轮自动观察和修复，之后仅同步文档，不把历史分组相加。

## Results / 结果

| Batch / 批次 | Result / 结果 | Evidence / 证据 |
| --- | --- | --- |
| Main: provider, policy, configuration, receipt and direct-step contracts | 198 passed, 8.94 s, exit 0 | Main command output; included again in final combination |
| Main: MCP protocol | 99 passed, 5.06 s, exit 0 | Main command output; included again in final combination |
| Task-plan adaptive first run | 36 passed, 4.93 s, exit 0 | `task2-adaptive-first.log` |
| Task-plan/client compatibility first run | **1 failed, 202 passed**, 12.94 s, exit 1 | `task2-plan-client-compatibility.log` |
| Client receipt fix, targeted | 2 passed, 0.73 s, exit 0 | `task2-client-receipt-fix.log` |
| Task-plan/client compatibility after fix | 204 passed, 13.22 s, exit 0 | `task2-plan-client-compatibility-fixed.log` |
| Learning, recovery, editor and i18n first run | 148 passed, 15.25 s, exit 0 | `learning-first.log` |
| Main: core cross-module combination before follow-up observation changes | **649 passed**, 37.51 s, exit 0 | `main-combined.xml` and Main command output |
| English and Chinese translation generation | Both exit 0; 1198 finished / 0 unfinished each | `learning-lrelease-en.log`, `learning-lrelease-zh.log` |
| Observation runtime/client compatibility | 252 passed, 41.02 s, exit 0 | `task5-plan-client-compatibility-first.log` |
| Main: final source across 31 files | **862 passed, 1 skipped**, 107.05 s, exit 0 | `main-p2-combined.xml` |

All named logs are local under `.superpowers/sdd/2026-10-09-adaptive-review/offline-tests/`. Groups overlap; do not add their counts. The 649-case command is the consolidated core count at that point, not acceptance of later changes. / 分组存在重叠，不相加；649 是当时核心组合数，不转计后续变更。日志位于上述本地目录。

## Failure and fix / 首败与修复

- **Failure:** while a v1 plan control remained pending, the cached `start_receipt` lost its original request ID (`None` instead of `original-start`). / 旧计划等待控制回执时，缓存回执 ID 丢失。
- **Root contract:** optional successor transport metadata must not erase a normal plan's durable start receipt. The cached binding included `start_transport_request_id=None`, so `dict.get(key, default)` did not use its default. / 缺省字段存在但为 None，导致默认值未生效。
- **Fix:** `scripts/learning_benchmark_client.py::_plan_result` uses a nonempty original transport ID when present, otherwise the original start ID. This applies to all callers, not a website-specific patch. / 公共客户端修正，既保留旧计划 ID，也保留后续计划首次传输 ID。
- **Regression:** reran the original failing pending-control case and added a real runner/client successor cached-receipt case; then reran the full related group and final combination. No test was removed or loosened. / 原首败和新增后续计划用例均复测。
- **Safety:** receipt projection only; no action authorization or input gate was relaxed. The initial failing run remains recorded separately. / 仅回执投影修复，不放宽动作门禁，首败保留。

The default whitespace check also reported retained CRLF in `.ts` files as trailing whitespace. A one-command CRLF-aware check passed; no persisted Git setting or source line endings were changed. This was a text-format diagnostic, not a failed runtime case. / 另有 CRLF 文本检查误报，按原换行检查通过，未改持久配置。

## Queued-cancel prerequisite / 排队取消前置修复

- **Failure:** a cancel arriving through the real command queue during mocked Decision evaluation was not consumed until the synchronous tick returned. The original step settled and the runtime prepared its successor. The existing busy queue prevented successor input; no live input was performed and no mis-click is claimed. / 取消已排队但尚未消费时，原步骤提前结算并准备后缀；已有队列门禁挡住实际派发。
- **Root contract:** cancellation checks must include valid unconsumed same-run controls, not only the backend's already-applied cancellation state. / 核验与最终入队须看到同运行尚未消费的取消。
- **Fix location:** `task_plan_cancellation.py` provides a shared read-only queue check at verification boundaries and final enqueue. The original control path remains responsible for settling cancellation; it does not rewrite receipts or grant input. / 公共层只读检查，正式取消仍沿原控制处理，不做应用特例。
- **Regression:** first reproduction **1 failed in 0.53 s** (`task2-queued-cancel-red.log`); same case after repair **1 passed in 0.50 s**; boundary set **8 passed in 1.43 s**; related 7-file combination **212 passed in 23.97 s** (`task2-queued-cancel-compatibility.log`). Main inspected the actual implementation and tests. / 首败、定点与组合均保留，不与649相加。
- **Safety limit:** this blocks new dispatch at those boundaries, rather than atomically preempting already-started OS input. A cancel after the original step has settled retains that original completion and blocks the suffix as known zero input. / 不声称能原子抢占已开始的输入，原副作用按事实保留。

## Reproduce / 复现命令

### Follow-up observation component checks / 追加观察组件检查

These component results do not by themselves verify the full runner/client observation loop. / 以下组件通过不等于完整运行链已通过。

- Judgment worker: final policy/provider/service/configuration/receipt group **184 passed in 4.03 s**. The first missing-interface/predicate runs and later huge-integer rejection failure were repaired and retained in `TASK5_JUDGMENT_HANDOFF.md`; Main also ran an intermediate provider/direct integration group (**248 passed**, `main-p2-provider.xml`) before the last boundary additions. / 判断组件已通过，Main 中途组合不冒充最终集成结果。
- Capture worker: first missing-helper test failed; a separate original-path reuse regression also failed before the primary path was repaired. Main then ran `tests/test_task_plan_observation_capture.py tests/test_memory_observation.py`: **63 passed, 1 skipped in 0.73 s, exit 0**, `main-p2-capture.xml`. The skipped real symbolic-link case lacked OS permission; a separate resolved-path escape regression passed. / 两次首败均保留；真实符号链接测试因权限跳过，路径出界逻辑另有覆盖。
- Capture checks use the real maintained capture function with mocked screenshot/window dependencies, confirming `focus_window=False`, no full UIA scan, separate immutable PNG bytes, original-image preservation, owner execution, cancellation and late-return refusal. No desktop pixels were read. / 维护入口联调用模拟依赖，不读取真实桌面。

The exact component commands and original logs are local under the same evidence directory. Main's final combination above includes the integrated observation runtime and the last repairs below. / 上方Main最终组合已覆盖集成运行链及下方最后修复。

Two further primary-path defects were found before live use. / 实机前又发现两项主路径缺口：

1. **Provider budget:** remaining timeout was computed before acquiring the provider lock, so getter waiting could allow a request after the budget expired. The new mock-HTTP reproduction failed with one send after expiry. The service now acquires the provider before recomputing remaining time from the original start; the final 184-case group includes the fix. The durable reservation remains truthful and no automatic retry was added. / 获取 provider 的锁等待未扣时，可能预算到期仍发请求；已先复现，再改为取得 provider 后扣减同一预算，未加重试。
2. **Original capture geometry:** `ScreenshotService` did not expose the actual capture's `window_rect` or `image_size`, so strict follow-up validation could not consume normal production receipts. `tests/test_capture_observation_geometry.py` first returned **2 failed, 1 passed** (`main-capture-geometry-red.xml`). The shared capture result now includes pixel dimensions and the window rectangle from the binding already checked before/after capture; ROI dimensions remain separate. It never substitutes pre-action or later geometry. The related six-file group passed **53 cases in 2.31 s, exit 0** (`main-capture-geometry-green.xml`). This is a common screenshot metadata fix, not a test-app adapter or relaxation of capture checks. / 正式回执缺几何使追加观察无法使用；公共截图输出补充当次已核对的位置和真实图像尺寸，ROI独立，不猜补旧证据，不放宽门禁。

3. **Final adoption timing:** authentication and subsequent source/queue checks could finish after the last budget check. Offline clock regressions reproduced this. The common observation validator and backend now check after synchronous validation and immediately before admission; a late candidate is retained, with a separate budget-review artifact, rather than adopted or overwritten. `task5-service-final-admission-first.log` retained 4 failures/3 passes (one budget defect plus three fixture/legacy-expectation errors); the repaired targeted group passed 7. No input gate was weakened; elapsed budgets cannot rewrite original effects. / 最终认证及后续读取可能耗尽预算；公共结算前再次检查，迟到候选保留并另存审核，不覆盖原件、不放行后缀。夹具错误与产品预算缺陷分别记录。
4. **Damaged original evidence:** deleting/changing the original after image during an observation wait caused validation to fail before the observation driver, leaving `observation_pending=true` and repeated polling. The runtime now terminates automatic observation with a diagnostic and stops automatic ticks; it cannot manufacture a success-review packet from invalid evidence. The damaged-image and final source-read budget group first returned **3 failed, 1 passed**, then **4 passed in 3.68 s** (`task5-damaged-after-final-source-red.log`, `task5-damaged-after-final-source-green.log`). These shared-runtime regressions apply to any target application and preserve the original ticket with zero new input. / 原图缺失或被改时前置核验异常曾留下持续等待；公共运行器现结束自动观察并诊断，保留原票据、零新增输入，不伪造坏证据成功包。

The final runtime group also covers real authenticated service/provider code against MockTransport, the shared runner/client, automatic completion versus one Main callback, explicit original-wait continuation, old-review rejection, unknown durable claims, slot skipping, profile/window/owner drift and cancellation during captures or assessments. The production capture helper is exercised with mocked native/screenshot boundaries; no model-accuracy or desktop claim follows from these checks. / 最终联调覆盖认证服务、原运行器/客户端、两种结算、旧包拒绝、未决记录、观察槽和取消等；系统边界模拟，不冒称实机或模型准确率通过。

### Core milestone command / 核心阶段命令

Use the existing clean interpreter with UTF-8 output and `QT_QPA_PLATFORM=offscreen`:

```powershell
& 'D:/agent-gui-runtime/.superpowers/sdd/2026-09-13-formal-release/.venv-clean-desktop/Scripts/python.exe' -B -X utf8 -m pytest -q --tb=short --junitxml=.superpowers/sdd/2026-10-09-adaptive-review/offline-tests/main-combined.xml tests/test_adaptive_decision_policy.py tests/test_decision_service.py tests/test_openai_decisions.py tests/test_decision_configuration.py tests/test_decision_receipt.py tests/test_execution_adaptive_review.py tests/test_execution_decision_check.py tests/test_execution_decision_closure.py tests/test_instant_mcp.py tests/test_task_plan_contract.py tests/test_task_plan_runner.py tests/test_task_plan_verification.py tests/test_task_plan_client.py tests/test_task_plan_adaptive_review.py tests/test_learning_benchmark_client.py tests/test_workflow_decision_adaptive.py tests/test_workflow_decision_verification.py tests/test_workflow_decision_recovery.py tests/test_workflow_rules_editor.py tests/test_workflow_runtime_verification.py tests/test_workflow_verification.py tests/test_workbench_i18n.py
```

## Limits and next stage / 边界与下一阶段

This verifies deterministic core source contracts and offscreen editing, including real service/runner/queue integration against mock HTTP. It does not measure model accuracy, real API latency, Main handoff time, desktop stability or task benefit. / 本批验证确定性源码与离屏编辑，不证明模型准确率、真实延迟、桌面稳定性或收益。

Automatic observation for explicit loading conditions is included in this final result. Public manual observation, template binding and valid native-mismatch semantic continuation remain future slices. Subsequent source changes need their own checks; these results must not silently count as their acceptance. / 自动声明加载状态的观察已覆盖；人工追加观察、模板绑定及有效原生不匹配接续仍待后续，不转计本批成绩。

### Final 31-file command / 最终31文件命令

With the same clean interpreter, UTF-8, `PYTHONDONTWRITEBYTECODE=1` and Qt offscreen environment:

```powershell
& 'D:/agent-gui-runtime/.superpowers/sdd/2026-09-13-formal-release/.venv-clean-desktop/Scripts/python.exe' -B -X utf8 -m pytest -q --tb=short --junitxml=.superpowers/sdd/2026-10-09-adaptive-review/offline-tests/main-p2-combined.xml tests/test_adaptive_decision_policy.py tests/test_decision_service.py tests/test_openai_decisions.py tests/test_decision_configuration.py tests/test_decision_receipt.py tests/test_execution_adaptive_review.py tests/test_execution_decision_check.py tests/test_execution_decision_closure.py tests/test_instant_mcp.py tests/test_task_plan_contract.py tests/test_task_plan_runner.py tests/test_task_plan_verification.py tests/test_task_plan_client.py tests/test_task_plan_adaptive_review.py tests/test_learning_benchmark_client.py tests/test_workflow_decision_adaptive.py tests/test_workflow_decision_verification.py tests/test_workflow_decision_recovery.py tests/test_workflow_rules_editor.py tests/test_workflow_runtime_verification.py tests/test_workflow_verification.py tests/test_workbench_i18n.py tests/test_task_plan_queued_cancel.py tests/test_task_plan_observation.py tests/test_task_plan_observation_capture.py tests/test_task_plan_observation_capture_integration.py tests/test_capture_observation_geometry.py tests/test_capture_window_ownership.py tests/test_owned_popup_foreground.py tests/test_local_step_timings.py tests/test_memory_observation.py
```

Before a release, validate real complex applications and continuous sessions, not only custom demos. The user's future LinkedIn workflow is a target business journey: collect release evidence, prepare a draft, obtain the user's approval, then publish and verify without duplicates. It is queued for later runtime use; no LinkedIn operation or recurring automation was started in this batch. / 发布前需真实复杂软件连续验收；领英是后续 runtime 业务场景，稿件先审核再发布，本批未启动领英操作或定时任务。
