# 视觉能力前置拒绝与恢复证明 / Vision admission rejection and recovery proof

更新 / Updated: 2026-10-03。源码候选 `codex/dev-workflow-editor`；正式 v0.1.1、已选 UI v14 未改，未打包发布。 / Source candidate only; stable v0.1.1 and accepted v14 UI are unchanged, without packaging/publication.

## 失败与公共契约 / Failure and shared invariant

1. **失败 / Failure:** T13 的 `t13-teach-select-n42` 缺少视觉能力声明，在创建 worker 前返回 `AgentCommandError/capability_unknown`。原回执没有正式零输入证明，之后 `instant_recovery_preview` 返回 `session_input_synchronous_unknown`。 / Missing capability declarations reject the first T13 command before worker creation, but its plain error lacks formal no-input evidence and blocks epoch admission.
2. **根契约 / Invariant:** 已知的前派发拒绝必须在原响应中留下可核验的阶段和零输入事实；错误字符串和 worker 缺失不能证明输入终态。 / Known pre-dispatch rejection needs bound stage/no-input evidence; error text or an absent worker cannot prove terminal input state.
3. **修复位置 / Fix:** `AgentCommandJobs.start` 仅在能力路由前置拒绝处抛 `AgentCommandVisionAdmissionError`；`run_local_step_session.preserve_input_admission_rejection` 持久化 `vision_admission_rejection.v1`；`inspect_session_input_terminal` 严格消费。 / The shared admission producer, original response writer and terminal-input consumer implement the contract.
4. **跨应用 / Beyond one app:** 这是当前 Agent 与委派识图的公共准入，适用于所有应用，不依赖 7-Zip 的名称或坐标。 / Shared current/delegated-Agent admission is independent of application names or coordinates.
5. **回归 / Regression:** 真实 RED 22 failed/1 passed → 首次 GREEN 23 passed；加入负例后，Main 最终九个相关文件 166 passed / 4.50s。不是实机恢复验收，也不与此前 66/39 项相加。 / Actual RED precedes the repair; Main's final nine-file 166-check run is source/contract coverage, not physical recovery acceptance or an added historical total.
6. **安全影响 / Safety:** 命令 SHA、原会话识图来源/profile、原能力声明、拒绝阶段、严格 false 和无 worker 都必须匹配；原来源与报告快照进入前后一致核验。旧字符串、伪造、来源漂移、已可用路由、有效 memory 例外和未知派发仍拒绝。没有放松点击、提交或发送门禁。 / Exact original binding and recomputed unavailable routing remain mandatory; legacy/unbound/changed/eligible/unknown evidence fails closed without changing action gates.

## T13 原实机结果 / Original T13 live result

全新 N42 四步教学、六事件审核（含两个原失败）、合成回交、普通工作台参数与结果规则编辑、Agent 审核、三版保存重开通过。首次编辑 QA 未先完成合成回交而失败，原错误和正常清理保留，另次编辑通过；不是产品草稿加载故障。第一次复用的 `ensure_selected` 通过原生已选/非编辑证明零输入。 / Fresh teaching, six-event review including two failures, synthesis handoff, ordinary edits/review/versioning/reopen and no-input selected-row reuse pass. The first editor QA omits synthesis completion and fails; preserve that caller failure/cleanup separately from the corrected pass.

原第二步实际双击完成后，`run(mode=single)` 接收原 pending，紧接 `instant_stop`；最终规则已用新截图中的 `manifest-N42.txt` 结算，Trial 到 step-3、runner 为 single_complete、ticket=null。原 host 82732 与 runner 105232 消失。终态恢复预览拒绝 `workflow_recovery_original_ticket_mismatch`；旧原能力错误再阻止 epoch 准入。不能把宿主正常停止、单步规则通过或新宿主 ready 记为原流程接管通过。 / The completed second action is adopted and immediately stopped. Final saved-rule verification settles it from a fresh image, advancing to step three with no ticket; original host/runner are absent. Terminal recovery refuses the missing original ticket, and the legacy capability error blocks epoch admission. These facts do not accept takeover.

旧 T13 回执未被补写或改成成功；本次源码修复不追溯赋予旧字符串证明。后续从真实可观察的待处理边界复验，按原计划保留弹窗、同窗口结果、剩余动作和收尾出口；收益继续未知后置。 / Preserve original failures without retroactive proof. Fresh testing must use an observable pending boundary and retain modal, same-window effect, remaining-action and cleanup gates; benefits remain unknown/deferred.

新候选的真实维护 MCP 已复验 `vision_admission_rejection.v1`：缺少能力声明的请求保留 failed/capability_unknown、未创建 worker，公共终态检查确认 input_terminal_settlement_verified=true。新维护连接正常 stop/disconnect、exit 0；这是接口生产者与零输入证明的复验，不是完整 P3 恢复。原测试 7-Zip 仍打开：客户区截图不含标题栏/菜单，新协调器没有原 launch 所有权，未猜坐标、未强杀。原连接与窗口完整收尾仍待。 / Fresh maintenance MCP on the new candidate verifies the typed pre-worker rejection and known no-input terminal proof. The new connection stops/disconnects normally with exit zero. This accepts the producer/proof path only, not complete P3 recovery. The original test-owned 7-Zip remains open: the client viewport omits caption/menu and the new coordinator lacks original launch ownership. No coordinate guess or forced kill occurs; full original-client/window cleanup remains open.

[Main MCP 原证据 / Main live proof](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-recovery-13-host-stop/cleanup-01/live/main-live-proof.json)

## 原证据 / Original evidence

- [Main 最终源码回归 / Final source regression](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-recovery-13-host-stop/main-vision-fix-review.json)
- [原停止事务 / Original stop transaction](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-recovery-13-host-stop/live-01/replies/t13-adopt-stop.json)
- [原终态预览拒绝 / Terminal preview rejection](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-recovery-13-host-stop/main-stop-terminal-preview.json)
- [旧原件仍严格拒绝 / Legacy record remains rejected](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-recovery-13-host-stop/main-old-proof-recheck.json)

修复后的完整 MCP/实机恢复及 T13 测试窗口正常清理仍待。 / Post-fix complete MCP/live recovery and normal T13 window cleanup remain open.
