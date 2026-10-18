## 2026-10-01 当前主线：完整流程与实测收益 / Current journey and benefit priority

本次仅调整计划，开发遵守用户暂停要求。正式 v0.1.1 已独立发布；学习源码未发布、版本不变。下方日期段是历史证据，不再决定当前任务顺序或待批准状态。 / This revision changes planning only; development remains paused, stable v0.1.1 is separate, and dated sections below are historical.

新接管采集/公开控制、runtime 失败来源和重复 epoch 来源链已有源码及持久集成证据。暂停前两个测试夹具错误已修复，additional-boundary/final-green.xml 为 23 passed；原 2 failed 保留。最终汇总回归中止，最新候选完整 GUI 接管及三项收益尚未验收。 / Latest narrow checks pass, including 23 corrected fixture/boundary checks; consolidated and full live/benefit acceptance remain open.

[当前执行计划](superpowers/plans/2026-10-01-learning-mainline-refocus.md)。既有动作、来源和未知事实合同继续有效。 / Existing action and evidence contracts remain in force.

## 2026-10-01 明确新会话准入已接线 / Explicit epoch admission wired

学习开发源码未发布、未改版本；正式 v0.1.1 独立保留。下面原有日期段保留为阶段历史。/ Learning source remains unreleased; stable v0.1.1 remains separate. Earlier dated sections are historical.

新增只读预览与明确准入两个MCP工具。输入 proof固定原目录集合/字节，异步检查原worker/派发/回执，pending Trial复核已有settlement；未知不等于False。发布后的status_admitted严格固定原snapshot与新pointer/宿主身份，只重核旧结算；普通settle不能跨epoch写入。launch_unknown本次proof=False且历史proof另存，工具错误host_launch_attempted=null。普通restart gate不变，new_epoch_ready与workflow_takeover_completed分开，后者仍False。已结算verify在观察/写盘前拒绝。/ New tools and archived checks preserve original input facts and authority boundaries, separating readiness from takeover.

详见 [本轮证据与限制](verification/LEARNING_EPOCH_ADMISSION.md)。/ See the current evidence and limits.

## 2026-10-01 恢复资源基础已验证 / Verified recovery-resource foundation

学习开发树仍未发布、未改版本；正式版 v0.1.1 在独立正式树，保持不变。本轮补 R3 的持久资源拥有权和只读清理证明，没有放宽原 new-session gate，也未实现工作流接管。/ Learning remains unreleased and unchanged in version. Stable v0.1.1 stays in its separate tree. This slice adds durable ownership and read-only cleanup evidence; it does not relax admission or implement takeover.

原 runner 在创建 coordinator 前绑定原 pointer、来源、launcher PID/created、实际 runner PID/create_time_ns 和确切入口/目录，持久化 session-resources.v1。Journal 沿原 FormalModelService、Windows Job 和挂起启动器，在 scope/launch/resume/ready/request/close 边界登记；原四字段策略和累计 cleanup identities 保留，closed_from_phase 不补造缺失启动身份。写盘失败不启动或重放输入，且不丢唯一成员身份。/ The maintained runner pins the original owner and epoch before coordinator creation. Journal writes occur at original model and suspended-launch boundaries, retain the native four-field Job policy and cumulative cleanup identities, and preserve incomplete startup facts after close. Persistence failures cannot launch, replay or discard sole identity evidence.

observe_session_resource_cleanup 只解析同一份原字节并固定 SHA，前后复核原文件和进程 incarnation；owned Job 用原观察器、terminate=False、remove_owned_pid_file=False、三次零观察及专用 PID 文件不存在才能证明。scope_starting/launch_starting 的身份缺口保持 indeterminate；外部服务不被打开 Job 或终止，未决外部请求不通过。本 Job 已退出只证明本地资源，不清除原 pending/票据，不结算业务；input_terminal_settlement_verified/new_epoch_ready 在观察 API 固定 False。/ Read-only proof binds hashes to the same decoded bytes and rechecks identities and snapshots. Owned resources require the original non-terminating observer, stable emptiness and absent PID artifacts. Incomplete launches and unresolved external requests remain indeterminate. Local resource proof never settles input, clears original tickets or admits a new epoch.

已结算 Trial 的直接 cancel、Runner cancel/resume 和原 ticket admit 均在写入或放行前拒绝；原 session JSON、preview 和重复结算保持。Main 最终相关源码回归 498 passed。全新原 InstantSession 的两次正常退出、一次硬终止均完成无输入生命周期验证：两次正常 cleanup_verified=True；硬终止的原 normal cleanup=False，独立资源证明=True，但 start(new_session=True) 仍以 previous_session_not_resolved 拒绝。610 个 app/scripts Python 文件在实测前后哈希相同，11 条原进程身份均已退出。/ Settled controls reject mutation and admission while retaining evidence and idempotence. Main passes 498 related checks. Two normal stops and one abrupt stop use fresh original sessions with zero input. Abrupt-stop resource evidence does not forge normal cleanup or bypass the existing restart gate. All 610 frozen source files and 11 original process identity observations are verified.

原挂起 model wrapper/Job helper 的实际无窗口测试子进程另验证成功启动与登记失败不 resume，两者真实收尾通过；它是 stdlib 等待进程，不是视觉模型、外部 API 服务或学习 GUI 验收。首轮探针错误地把 venv launcher 和实际解释器当作同一 PID，原失败目录与脚本保留；修正为原 Job 成员关系后用第二个全新目录复测通过。源码合同首次失败、夹具目录/锁/超时错误和 Main 原字节绑定失败均与复测分开保留。/ Real suspended-launch boundaries and cleanup also pass with a windowless stdlib fixture, not a vision provider or GUI-learning acceptance. Initial launcher/interpreter assumptions and fixture/contract failures remain separate from successful reruns.

仍待：资源证明与原终态/结算共同约束的新宿主 admission、固定程序/新窗口/新 capture 的明确接管与当前效果核验、活动工作流弹窗及完整同候选连续恢复/收尾，随后独立实机验收。正式人工审核 C、R4 匹配收益、R5 实测优化和 R6 第三方迁移仍未完成；模型总调用/token 与省模型、准确率、速度收益仍未知。历史 session-02 没有此清单，不补写、不把本轮证明移植给旧记录。/ Admission, explicit effect-verified takeover, dialog scope and full same-candidate recovery remain open before independent live acceptance. Reviewed C, matched benefits, measured optimization and third-party transfer are unfinished; usage and benefits remain unknown. Old sessions are not backfilled with new evidence.

合同 / Contract：docs/superpowers/specs/2026-10-01-recovery-resources-design.md；计划 / Plan：docs/superpowers/plans/2026-10-01-recovery-resources.md。证据 / Evidence：D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-recovery-admission-01/main-final-contracts.xml、main-resource-lifecycle.json、main-resource-scope.json、main-owned-identity-audit.json。

# 中断事实与只读恢复 / Interruption facts and read-only recovery

2026-10-01，开发分支源码状态；未发布、未改版本、未替换安装候选。/ Development-source status; no release, version change or installed-candidate replacement.

## 2026-10-01 本候选新鲜实机证据 / Fresh physical evidence for this candidate

全新窗口与数据根在同一原会话完成教学填写、事件/原图核对、同源合成、程序保存和规则正常复用，再完成第三次填写及原宿主硬终止。未读取历史学习资产，所有输入沿原运行时门控，未提交或按 Enter。正常面板连接原数据，核对/明确结算/刷新/重开均已实测；业务核验保持 null，输入不重放。/ Fresh data and an owned window establish live teaching, original-event review, synthesis, program saves and rule reuse, followed by a third fill and host termination. Input uses the original gate without submission or Enter. Ordinary-panel settlement and reopening preserve unknown task effect and forbid replay.

原 acceptance 的 running/False 不被改写；原 worker completed/True 的原字节证据可读，顶层诊断保留已知 True。结算前后 command/response/worker、runner、pointer/report 和 library JSON 字节保持；Trial 除新增 recovery_settlement 外相同，history/outputs/pending 不变。同 preview/ID 重复不写新事实，不同 ID 拒绝。/ Stale acceptance bytes remain intact while bound terminal-worker facts preserve known True. Only the Trial settlement is added; original evidence and scheduling state remain unchanged. Repeated settlement is idempotent and conflicts are rejected.

Main 相关源码 245 passed。独立观察到全部已登记进程退出、fixture 退出 0 和 HWND 消失；原正常 cleanup_verified=False、new_epoch_ready=False，close 返回 benchmark_cleanup_not_verified。外部硬杀脚本在实际 runner 已终止、launcher 自动退出后报告 NoSuchProcess，其 killed=False 不是真实进程存活证明；原失败保留，未修改报告来冒充正常退出。/ Main passes 245 checks. Recorded process exits and fixture closure are observed, but original normal-cleanup and readiness flags remain false. The external kill adapter's absent-launcher failure is retained; report fields are not forged.

证据 / Evidence：D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-terminal-live-01/main-final-live-audit.json、main-fixed-contracts.xml、session-02/recovery-proof/summary.json、session-02/recovery-proof/panel-reopened-cjk.png、session-02/cleanup.json。首轮身份/任务归属失败、调用方候选引用及能力层级错误、首次离屏字库限制保留。此证据不覆盖活动工作流弹窗、新宿主接管、完整 R3、人工审核 C、公平收益或独立实机验收。/ Initial client/probe/caller/font failures remain preserved. Full recovery, dialog scope, takeover, reviewed C, comparative benefits and independent live acceptance remain open.

## 已实现 / Implemented

`app/vision/agent_command_jobs.py` 的 memory、视觉 grounding 和非 recognition 原生调用共用持久化 attempt 边界。每次调用前保存单调 `index`、`operation`、`status=started`、此前动作事实和当次未知事实；这次保存失败则不会调用输入层。原调用返回后，原回执、观察、动作事实、`status=returned` 和关闭派发标志在同一个 JSON 快照发布。异常保存 `unknown`，保存失败保留未关闭的 `started`。/ Memory, visual and non-recognition dispatch share a durable attempt boundary. Start must persist before the coordinator call. Original receipt, observation, action fact, returned outcome and closed flag publish together. Errors remain unknown; failed outcome publication retains the open attempt.

| 持久化状态 / Persisted state | 可以证明 / Proven fact | 不能推断 / Not implied |
|---|---|---|
| `started`，无返回回执 / no receipt | 原调用边界已经开始；可能输入 / call boundary began; input is possible | `action_executed=False`、可重试 / no input or safe replay |
| `returned` + 同快照原回执 / original receipt in same snapshot | 该次原调用回执中的 True/False/未知 / this attempt's actual True/False/unknown | 整个任务成功、业务结果正确 / task success or verified effect |
| `unknown` | 原调用异常，结果不能确认 / call failed with uncertain outcome | 没有输入、可以重跑 / no input or safe replay |

累计 True 不会降为 False 或未知；没有此前未知时，当次明确 False 可以保留已知 False。记录 attempt 不创建新执行器、输入许可或重试路径。磁盘状态不复活线程。/ Cumulative True is never downgraded. A known False return remains False when no earlier uncertainty exists. Attempts grant neither input authority nor retries, and persisted state does not revive threads.

`InstantSession.result` 对**已退出宿主的非终态 Agent 接收回执**，保留原 `result` 和原回执文件，另返回 `persisted_worker_evidence`：原 command ID、文件路径、原字节 SHA-256、保存状态和动作字段。请求与原命令、原接收回执、worker ID/合同必须一致；冲突明确拒绝。/ For nonterminal Agent acceptance receipts after host exit, `result` preserves the original result/file and adds saved-worker evidence with original ID, path, exact-byte hash, state and action field. Original command, acceptance and worker identities must match.

`worker_status=result_unknown` 表示尚无 worker 终态；`terminal_available` 仅表示原终态文件可读，**不是已结算工作流**。顶层 `action_executed` 保留已知 True，其余未决事实为 null；诊断文件中的旧 False 不证明完整命令未输入。仍为 `operation_succeeded=null`、禁止自动重试；不再建议向死宿主发送新的状态控制命令。活宿主的原轮询流程不变。/ `result_unknown` lacks a worker terminal outcome; `terminal_available` does not settle a workflow. The projection preserves known True and otherwise keeps unresolved input null. It is a diagnostic, not a replacement execution receipt. Live polling is unchanged.

普通运行面板在只读重开后持续标注“宿主未运行”“已保存状态”；非终态提示输入可能已发生，并保持执行、继续和取消按钮禁用。刷新和回读不入队、不改变原账本。/ The ordinary panel labels saved state after host exit, warns about unresolved input, and keeps action controls disabled. Reads and refreshes do not enqueue or rewrite the ledger.

## 原终态显式结算 / Explicit original-terminal settlement

`WorkflowRunClient.preview_recovery(run_id)` 只读核对原 active runner/pending、固定程序与步骤、EID、command/acceptance/worker 原字节 SHA，以及 pointer/report 中的原宿主与 runner。原宿主和实际 runner 均不得仍在执行；runner 只有 PID 时，PID 复用也保守拒绝。只支持已保存的异步 `agent_command.v1` 真终态；`started`/`unknown` dispatch 保持未决，不生成失败或正常完成时间。/ Preview validates original active/pending tickets, pinned program/step, original IDs and byte hashes, and persisted host/runner identity. Both execution processes must be inactive; a live reused runner PID is conservatively refused. This slice supports saved asynchronous worker terminal evidence only; unresolved dispatch stays unresolved.

`settle_recovery(preview, request_id=...)` 是独立记忆库短事务，不经过 control/submit，也不启动宿主。记忆库独占锁与原 runner 锁覆盖读改写；三个原文件哈希和 trial 状态摘要必须仍吻合。单个原子 trial 写入增加 `recovery_settlement`，同 ID/同预览重复幂等，不同 ID 或证据冲突拒绝。原 pending、history、outputs、runner 文件、原回执与完成时间不变。/ A separate workspace transaction holds existing workspace/runner locks and revalidates all hashes and trial state. One atomic trial commit adds recovery settlement, idempotent for the same ID/preview and rejecting conflicts. It neither queues commands nor changes the original ticket, history, outputs, runner, receipts or finish times.

结算只证明原动作事实。累计 True 保留；结果核验和业务成功仍为 null。原 Runner drive 与 Trial review 保持 `recovery_paused`，不转分支或产生下一票据。普通面板“核对已保存结果→结算已保存结果”可审计展示 True/False/未知，刷新重开仍只读；失败保留原恢复 ID/预览。进程退出证据明确 `resources_cleanup_verified=False`，不能拿它启动新宿主。/ Settlement records action facts only; known True survives and task verification remains unknown. Scheduling and review stay paused with no next ticket. The panel exposes preview/settlement and idempotent recovery identity, while reads remain read-only. Inactive execution processes do not establish resource cleanup or new-host readiness.

## 本批证据与界限 / Evidence and limits

新增原终态结算证据 / New settlement evidence：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-terminal-settlement-01`。

- 最新候选 `main-final-source.xml`：216 passed，包括实际持久项目和原 reader 的依赖闭合。首次缺少 `load_graph_revision` 的预览入口缺陷及修复见 `red-history.json`；改用现有完整记忆库短事务。/ The final candidate has 216 passing source checks, including persisted-project dependencies without replacing the reader. The simplified preview facade failure and workspace-transaction fix remain recorded.
- `hardkill-commit-02/summary.json` 与 `main-final-audit.json`：原子写前/后两个实际子进程硬终止、原恢复 ID 幂等重试及两个 Qt 离屏重开均通过，原字节、历史、输出和分支保持。合成 worker/project 的隔离探针真实 GUI 输入为 0，不能作为实机学习、完整 R3 或收益证据。/ Two real commit-process terminations, original-ID retries and offscreen reopenings preserve the original evidence. Synthetic workers/projects do not establish physical input, full R3 or empirical benefits.
- `main-source.xml`：825 passed、1 skipped，属于持久项目缺陷修复之前的扩展检查，不冒充最终候选结果。原离屏图字体限制、独立审计漏项目适配的失败均保留；没有重放输入。/ The earlier 825-pass, one-skip expanded check predates the dependency fix. Initial font and auditor-fixture limitations remain preserved; no input was replayed.

证据根目录 / Evidence root: `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-process-recovery-01`。

- Main 合并源码合同见 `main-integrated-final.xml`。worker 及 Main 的红阶段、写盘失败、审查发现和修复记录分别保存；重叠测试不累加。/ Main integrated contracts and retained red/fix evidence are separate; overlapping counts are not added.
- `hardkill-after-rerun/summary.json`：三条路径 × 三个中断点，9 个真实子进程硬终止后只读回读通过，原 ID/原字节不变、没有重派。coordinator 是效果文件替身，**真实 GUI 输入为 0**。`hardkill-before/` 在原实现上重现失败。首次 `hardkill-after/` 失败是审计路径分隔符 KeyError，原报告保留，修正外部审计后复测。/ Nine actual process terminations exercise coordinator test doubles, not desktop input. The original implementation fails; the first auditor path-key error remains preserved.
- `hardkill-panel/summary.json`：两个已硬死亡进程的新客户端及真实 Qt 面板离屏重开通过，原等待 ID 和账本保持，按钮禁用。/ Two actual Qt panels reopen killed-process records offscreen without changing the original wait or ledger.
- R2 的两个完整实机任务及正常清理是上一批证据，不能代替本批更改后的真实输入/连续回归。没有证明硬死亡后透明续跑、恢复清理证明、新宿主启动、正式人工审核 C 或模型收益。/ Earlier physical runs do not validate this candidate's live input paths. Transparent recovery, cleanup reconstruction, new-host startup, reviewed C and comparative benefits remain unverified.

## 下一步与边界 / Next steps and boundaries

原终态只结算源码已接入；下一步使用全新自建低风险窗口完成本候选真实单项、中断、原结果核对及完整收尾，再补独立资源清理证明与明确新宿主接管。未知派发仍保留未决状态，不伪造失败回执或正常 `finished_at`；新宿主不读取或消费旧 commands。完整 Main 连续验收通过后，才交同一冻结候选作外部实机验收。/ Source settlement is connected. Next validate this candidate with a fresh owned window, real single-operation/interruption checks and cleanup, then separate cleanup proof and explicit new-host takeover. Unknown input remains unresolved and old commands are never consumed. Independent physical acceptance follows complete Main continuous coverage on the same frozen candidate.

弹窗按原步骤声明逻辑窗口范围，在原 ticket 内解析唯一所属窗口，并重新核对 PID/创建时间/owner；不允许竞争 `select` 绕过 admit。关闭弹窗后的父窗口观察须单独记录执行窗口与观察窗口及事先 owner 关系，不能把父截图冒充弹窗的 after，也不能重放 Close。此为后续方案，当前程序/编辑 UI 尚无该窗口范围字段。/ Dialogs will use declared per-step scope and the original ticket, with fresh identity/ownership checks. Parent observation must preserve separate execution and observation identities. This scope and editor field are planned, not implemented.
