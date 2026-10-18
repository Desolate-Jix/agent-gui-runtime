# 学习模式限定恢复验证 / Bounded learning recovery verification

## 当前范围 / Scope

用户接受 v14 工作台外观后，继续学习主线。本轮仅修复原会话输入终态证明，并验证新教学、普通规则编辑、保存重开、同窗口弹窗与宿主中断后的接管。沿用原 MCP、Trial/Runner、门控执行器；不改正式 v0.1.1、不打包、不提交或发布。 / The accepted v14 shell stays unchanged. This slice repairs original-session terminal proof and validates teaching, ordinary editing, persistence and bounded recovery using maintained components. The stable release and distribution are unchanged.

学习源码：`<LEARNING_WORKTREE>`，分支 `codex/dev-workflow-editor`。证据根目录：`<EVIDENCE_ROOT>/20261002-learning-mainline-01/continued-learning-v14`（下文 B）。v17 冻结 `B/source-freeze-v17.json` 的 873 个源码文件；v17r2/r3 使用同一冻结候选和各自全新数据根，不读取旧学习资产。 / Preserve the dirty learning tree. The retries use the same 873-file candidate with separate fresh roots and assets.

## 故障、共同修复与安全边界 / Incidents, common repairs and safety

1. **失败 / Failure**：v14 的 `teach-find` 在另一命令活动时被拒绝，原失败没有零派发证明，恢复预览拒绝 `session_input_synchronous_unknown`。**约束 / Invariant**：只有确定未派发的输入才能结算为 false。**位置 / Location**：`scripts/run_local_step_session.py` 的专用 `AgentCommandAdmissionError` 和 `app/execution/session_input_terminal.py`。**通用性 / Why common**：所有输入来源共用活动命令门控。**回归 / Regression**：`test_agent_busy_recovery_proof.py`，RED 后 GREEN。**安全 / Safety**：仅精确原 `input_admission_rejection.v1`、无 worker、input_attempted/action_executed 都严格 false 才闭合；普通字符串失败仍拒绝，不重放输入。 / A dedicated pre-dispatch rejection receipt preserves actual zero-dispatch facts; unstructured failures remain unknown.

2. **失败 / Failure**：合法多步输入的定位 continue 对应早期点击，终态 worker 最后回执已经是后续键盘动作；旧单派发关联无法证明该点击。**约束 / Invariant**：完整有序的批次回执应能关联唯一原派发。**位置 / Location**：同一 `session_input_terminal.py`。**通用性 / Why common**：同时覆盖 input_sequence/form_fill。**回归 / Regression**：`test_agent_continue_terminal_proof.py`；独立 Sol 审查发现重复认领与重复 native step_id 两个负例，Main 先 RED 后修复。**安全 / Safety**：完整批次与 dispatch_attempts 的顺序、操作、action、唯一 receipt/native ID、末尾回执必须一致；同一次派发不能被两个 grounding 认领，缺失和未知继续拒绝。 / Valid early grounding dispatches can be proven from the entire original batch; duplicate ownership, missing evidence and unresolved dispatch stay blocked.

3. **失败 / Failure**：v16 Main 误查不存在的 command_id，真实只读 `AgentCommandError("command_unknown")` 被恢复检查拒绝 `session_input_control_binding`。**约束 / Invariant**：只读缺席查询的失败不应伪装成未决输入，也不能证明任何输入成功。**位置 / Location**：同一终态检查器；producer `dispatch_agent_command → AgentCommandJobs.get` 仅校验并读取快照。**通用性 / Why common**：适用于任何 Agent 状态查询。**回归 / Regression**：`test_agent_status_unknown_recovery_proof.py`，1 failed/17 passed 的 RED 后最终 18 passed。**安全 / Safety**：仅合法精确 status 查询、专用 failed/error、被查 command/worker 均不存在、无结果/动作/观察回执、retry=false 才记 `unknown_command_readonly`；continue/cancel、实际存在输入及未知派发均不放行。 / A strictly read-only absent-command query is settled as a failed query, never as business success or permission to replay.

## 原尝试不能改记成功 / Retained attempts

- `p3/live-01`（v14）：原宿主中断与输入终态结算成功，准入预览失败；未接管/未执行剩余步骤，逻辑清理未通过。物理所属进程已退出；307 个原 JSON 在修复后只读复查未改，不能据源码修复重评分。 / Recovery admission failed and logical cleanup did not pass; later read-only checks do not change its live result.
- `p3/live-02`（v15）：仅准备、未教学或输入任务；源码审查发现负例后停止，原正常清理通过，不算 P3 尝试通过。 / Preparation-only, normally cleaned, without acceptance credit.
- `p3/live-03`（v16）：六步教学含末事件补收，普通三版保存重开通过；同期 Main 弹窗改变队列导致离屏队列等同断言失败，初始基线未落盘，精确归属证明未知。同窗口弹窗和限定中断成功，误查状态后准入预览失败；未接管/未执行 step6，逻辑清理 false，物理所属进程已退出。修复后 284 个原 JSON 只读不变，终态检查器通过只作源码复查。 / Persistence is verified, but concurrent queue equality and full recovery failed; the preserved original records remain unchanged.
- `p3/live-04`（v17）：Main 首次 Open grounding 回复在真实按钮上方；原输入 completed/action=true，但未打开详情，紧接读取也无详情，两个学习审核结论为 failure。新截图后的新 Open/Read 成功，原八事件全部保留；普通控件明确修订断边并保存 pending→Agent reviewed，三版重开不变、队列 70 条无变动。恢复预览成功，但 Main 在首次准入 `pointer_published/new_epoch_ready=false` 后过早选窗；接管拒绝 not_ready，再读同一准入拒绝 new_host_not_empty。未接管/未跑 step6；新宿主正常 cleanup=true、pending=[]、host_alive=false、夹具退出0。 / Caller grounding and admission-order mistakes are preserved. The second failed admission must not be treated as completed takeover.

- `p3/live-05`（v17r2）：六步教学、普通三版保存重开、57 条完整队列无变动、R-451 新详情填写、弹窗、限定中断、终态结算、同一准入读到 ready、接管预览/提交均通过。Main 在恢复输入接受回执尚未消费时查询工作流，原 `state_rejected/command_pending` 指向 `instant_result`；debug 客户端却把拒绝当异常并停止宿主，step6 原 worker cancelled/action=false，未执行最后核验。正常 cleanup=true、夹具退出0，不算完整通过。 / The original refusal and cancelled final step remain failed acceptance. Debug transport incorrectly tore down the host instead of preserving the protocol reply; normal cleanup does not make the task complete.

## 当前新现场 / Current fresh rerun

`p3/live-06`（v17r3，同源候选）：Main 六步首次教学 R-372 / `detail-6dc60e68866c` 成功，原六事件无 pending；两项刻意拒绝保持 failed。普通入口保存原版、语义 pending 版、Agent reviewed 版并重开；58 条完整命令队列原字节不变、持久标题 UTF-8 通过。保存程序 `task-program-5559f19ca8499f237fd4d0eadd616bc2589dcf721aece7fb6030c1d7b0c0486a`；保存 JSON SHA `81aad58f87dd2e35d83926bf32b731e922bf3953d24ae6f4c0097ce9200596b2`。 / Fresh teaching and ordinary three-version persistence pass, with truthful Agent review and an unchanged 58-command queue.

同一 PID 77872/HWND 212077646/创建时间的自建窗口中，弹窗打开/关闭通过；换编号 R-467，原新图读取 `detail-9e40901b9178`，step5 按输出填写 completed/action=true。Runner 认领后只中断确切所属宿主；原终态结算保留 task_effect=null、retry=false，原 Trial.status 仍为 pending，recovery_settlement.status 为 recovery_paused。公开恢复预览 SHA `9998d23c792018dc3af91d429ce48e4e5cfefdbf38ba272be174fa76d1128764`，同一逻辑 `p3-v17r3-epoch-admission` 从 pointer_published 读到 ready 后才选窗。fresh effect 验证当前字段值，接管只导入 step1–4 的历史、以当前效果闭合 step5；显式继续后仅执行原 step6 `trial-exec-4f942356810d1eb2b5bac0e28475367c`，Main 消费原 instant_result 再查 worker，completed/action=true，原图 Matches current detail。Agent 审核及使用真实等待 ID 的最后继续后，新 Trial/Runner completed、wait/pending=null；正常 stop cleanup_verified=true、pending_ids=[]、host_alive=false、夹具退出0。 / The original Trial remains pending with a recovery_paused settlement; only the new takeover run completes. Bounded recovery and cleanup pass without replaying the fill.

保留调用方错误：Main 在 commit 辅助进程写完本地回执前启动 continue helper，FileNotFoundError 发生于提交前，未派发输入；等原 commit 结束后才用原 wait_id 继续。它不是产品输入失败，也没有用新输入替代。debug r3 对带原 response 的 BenchmarkCallError 保留并返回原 failed/rejected 回执；无 response 的传输异常仍抛出，不自动重试。真实 r2 原拒绝的窄检查逐值相等、原文件字节不变。 / A pre-submit helper ordering error is retained separately. The debug conduit now preserves original protocol refusals without retry or input fallback.

## 检查和限制 / Checks and limits

Main：`PY -m pytest tests/test_agent_status_unknown_recovery_proof.py tests/test_agent_continue_terminal_proof.py tests/test_agent_busy_recovery_proof.py tests/test_session_input_terminal.py tests/test_agent_command_protocol.py tests/test_session_epoch_admission.py tests/test_workflow_terminal_recovery.py tests/test_workflow_takeover_public_recovery.py -q --junitxml=B/main-recovery-v17.xml`，**151 passed / 7.64s**。更早的 133 项集合重叠，不相加；本轮没有跑全套旧测试。 / The 151 focused checks pass; overlapping earlier runs are not additive and the legacy full suite was not run.

Main 实际运行 `PY B/v17r3-driver/audit_r3.py`，11 项只读审计全部 verified：原教学 worker、三版/队列、873 源码 SHA、故障原 raw SHA、结算/接管、准入调用顺序、六步历史/无填写重放、原读取截图 SHA/动态值、正常清理、5 个确切进程身份退出、保留调用方错误。报告 `B/v17r3-driver/audit-r3-result.json` 固定所读证据 SHA。原客户端顺序追加 `mcp/calls.jsonl` 中 starting/ready 准入为行索引129/131，选窗133；证明调用顺序而不声称时间戳或以 mtime 推断。首次审计脚本错误期待 commit.status=takeover_ready、judged_by=recovery_current_effect，并假设 inbox 时间字段，三项 unproven 保存为 audit-r3-result-first.json；核对原 producer/字段后仅修审计器，未改原任务证据。 / Main executes the narrow audit and checks original sequential MCP records, exact field contracts and process identities. Initial audit assumptions remain preserved separately from the corrected read-only check; the live records were not rewritten.

本轮审核者都是 Agent，human_review=false；未做第三方应用迁移、真人审核、同候选独立完整实机验收或交付包检查。离屏截图的中文 glyph 显示方框，持久中文文本仍 UTF-8；该截图不证明原生字体可读性。限定故障只覆盖“已经完成的手动填写由 Runner 认领后，原宿主中断”，不覆盖任意自动输入派发中途崩溃。三项收益未采新对照，完整模型调用/token 仍未知；不把工具数或等待数当模型计量。 / Review attribution, offscreen font limitations, bounded fault timing and unmeasured benefits remain explicit. Third-party, human, independent live and delivery acceptance remain open.

恢复顺序必须是：确认原终态且不重放 → 原公开恢复预览 → 使用同一 durable admission request_id/hash 读取到 phase=ready/new_epoch_ready=true（此前不能选窗或派发命令） → 重新选同一 PID/HWND/创建时间的窗口 → fresh effect preview → commit → 显式 continue 剩余步骤 → 完整清理。 / Confirm terminal facts, reuse the same admission identity until ready, then select, freshly verify effects, commit, explicitly continue and clean up. A starting host is not ready admission.
