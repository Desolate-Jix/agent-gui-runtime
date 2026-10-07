## 实装回归补充 / Installed regression update

Main N10 135审核首步后，136直接取消立即runner=cancelled、pending/wait/active为空，未派发第二步；原命令/回执/Agent状态字节SHA和输入队列前后一致，137回读终态、138capture准入。随后同程序两轮参数各两步completed，182/183宿主停止并cleanup_verified。Sol N11同冻结131直接取消也立即终态，原文件和工作流队列不变，后续准入及甲乙完整运行、清理通过，未发布；此前N7首失败保留。 / Native reviewed cancellation settles immediately without next dispatch or receipt/queue mutation. Subsequent parameter runs and verified cleanup pass; independent direct cancellation, subsequent admission, parameter runs and cleanup also pass.

详见[新候选验收](LEARNING_PREVIEW_NATIVE_ACCEPTANCE.md)。以下为源码修复及最初阶段原件。 / See the candidate record; the source-repair and first-stage records follow.

# 学习工作流取消生命周期 / Learning workflow cancellation lifecycle

## 故障与共同合同 / Failure and shared invariant

独立 N7 实装验收中，Agent 成功审核当前步骤后，Trial 已清空 pending 并转至下一步，但运行器尚保留原 execution ticket。公开 cancel 将 Trial 变为 cancelled，运行器却仅按 ticket 存在保持 cancel_requested，后续输入被 workflow_run_active 拒绝。原 261–263 回执保留为首次失败；264 使用原 wait 的继续调用才结算，且没有新派发。B2 后续测试被暂停，不计完整通过。 / During fresh installed acceptance, Agent review cleared the Trial's pending item before the runner reconciled its original ticket. Cancel ended the Trial but left the runner active, blocking later input. Preserve the original failure and the no-input settlement through the original wait; B2 is incomplete.

可复用合同：取消返回的 Trial 已通过审核且没有待处理项时，只能结算与历史末项 execution_request_id 和 step_id 均匹配的原票据；不得根据票据存在误判仍在执行，也不得将未审核、未知或不匹配的输入视为已结束。 / Cancellation must settle only the original ticket matching the reviewed Trial's latest execution and step identities with no pending item. Unreviewed, unknown or mismatched input remains unresolved.

## 修复与安全 / Repair and safety

`app/learning_memory/workflow_runner.py` 消费原 Trial.cancel 的真实返回值，以既有 _reviewed_ticket 和 _settle_reviewed 结算原票据。没有调用下一步调度，也没有修改原 receipt、history、outputs 或输入队列。恢复暂停、cancel ID 冲突、未审核执行以及异票据门禁继续有效。公共运行器修复适用于所有维护应用，而非 7-Zip 专用补丁；没有放宽提交、发送、确认或付款限制。 / The shared runner consumes the actual Trial cancellation snapshot and reuses its matching-ticket settlement. It does not dispatch the next step or rewrite receipts, history, outputs or queued input. Recovery and unresolved-input gates remain unchanged; this is application-independent.

## 验证状态 / Verification status

新增 `tests/test_workflow_cancel_reviewed_runner.py` 使用真实 TrialService、WorkflowRuntime、原命令队列与持久回执，隔离桌面边界。覆盖成功/失败/不确定的外部审核、即时取消、同 ID 幂等、不同 ID 冲突、关闭重建状态、后续新运行，以及未审核和异票据仍拦截。测试不操作桌面。 / Regression uses real Trial/runtime/queue components with the desktop boundary isolated, covering reviewed outcomes, idempotency, persistence, subsequent runs and unresolved-ticket guards.

纠正最初将只读 capture 用于输入门禁断言的测试字段后，新增回归 RED 为 3 failed / 1 passed，失败即 trial cancelled 而 runner cancel_requested；修复后相关 5 文件 60 passed，3.20s。原 RED、纠正和最初 59 项 GREEN 日志均保留。 / After correcting an initial test-only command-kind mistake, the new regression failed on the observed lifecycle defect. The repair passed 60 related checks; all earlier results are retained.

实际命令使用既有 Python，`-I -B -X utf8` 从当前维护树导入 pytest，运行： / The existing interpreter ran pytest in isolated UTF-8 mode against:

```text
tests/test_workflow_cancel_reviewed_runner.py
tests/test_workflow_runner.py
tests/test_workflow_runtime.py
tests/test_workflow_trial.py
tests/test_workflow_cancelled_trial.py
```

证据为本轮私有根 L 中 `cancel-reviewed-runner-red.xml`、`cancel-reviewed-runner-red-corrected.xml`、`cancel-reviewed-runner-green.xml`、`cancel-reviewed-runner-green-boundaries.xml` 和独立 N7 原回执；不随公开载荷交付。执行 source06 和学习 GUI04 实际冻结归档均包含旧共同模块，本修复不会热加载。新冻结、Main 单项/连续原生回归、Sol 同候选复验和发布尚未完成。 / Private evidence retains original receipts and regression reports. Both earlier frozen components include the old module; new frozen/native/independent acceptance and publication remain pending.
