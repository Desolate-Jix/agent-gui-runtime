> **2026-10-01 当前顺序已调整 / Current priority supersedes earlier sequencing:** [学习主线重排计划](2026-10-01-learning-mainline-refocus.md) 为当前执行入口。先完整流程与六对诊断试采，再限定恢复、扩大实测。原目标、技术合同、未完成完整验收及首次失败保留；旧“待确认”和“下一步”只代表当时状态。本轮仅改计划，开发继续暂停。 / Follow the refocused plan; retain original targets and evidence. Historical pending approvals are not current blockers, and implementation remains paused.

# Recovery resources Implementation Plan / 恢复资源实现计划

> **For agentic workers:** Follow the existing code-implementation loop. Execute the approved R3 work using bounded Sol tasks and Main integration; user instructions preserve authorization and do not require ritual commits or new worktrees.

**Goal:** 持久资源拥有权，使异常退出后的观察、admission 和明确工作流接管可验证；完整恢复仍须真实任务与收尾。/ Make crash ownership, admission and explicit takeover verifiable.

**Architecture:** 原清单与原 report 分开；同一 Journal 注入原 coordinator/model service，原挂起启动 helper 在 resume 前登记身份。原恢复证据不复活原 worker，接管永不消费旧 commands。/ Separate evidence, inject the journal into maintained launch boundaries, and never revive workers or consume old queues.

**Tech Stack:** Python 3.11, UTF-8 JSON atomic snapshots, psutil, existing Windows Job helpers, pytest.

**Spec:** docs/superpowers/specs/2026-10-01-recovery-resources-design.md

## Global constraints / 全局约束

- 开发树 codex/dev-workflow-editor；不发布/改版本/复制正式树/安装依赖/新执行器。
- 中文最小注释，原字节与未提交改动保留；进程观察不得按名称 kill。
- 外部服务与目标应用不纳入可终止范围；业务结果/用量未知不补造。
- 正式恢复验收用新窗口/数据/连接，不复用历史学习资产。

## Review focus / 审查重点

- 任意原控制修改 settlement 或 ticket：写入前拒绝，并保持 preview 幂等。
- inventory 写盘失败或 launch_started 无持久 PID：不启动/不标清理成功。
- Job 空但原身份仍活、PID 复用或 AccessDenied：严格观察，不终止外部进程。
- 原 snapshot/来源/路径/epoch 漂移：拒绝证据与 admission。
- 新宿主重复消费旧输入或未经当前效果核验推进：拒绝，独立队列和新 EID。

## Task 1: Settled control guards / 原结算控制保护

Files: app/learning_memory/workflow_trial.py, workflow_runner.py, workflow_runtime.py; tests/test_workflow_recovery_control_guard.py.
- [x] 保存直接 Trial cancel、Runner cancel/resume、原 ticket admit 的原持久化失败。
- [x] 最小守卫在任何写盘/放行前拒绝 recovery_settlement；status 保持只读。
- [x] Main 复核全 session 字节、原 preview 与同 ID 结算幂等及相关回归。

## Task 2: Durable resource journal / 持久资源清单

Files: app/execution/session_resources.py; tests/test_session_resources.py.
Interfaces: SessionResourceJournal(session_dir, *, recognition_source, host_identity, runner_identity); register_model(resource_id, *, scope_name, pid_file); begin_model_scope(resource_id); model_scope_acquired(resource_id, policy); begin_model_launch(resource_id); model_process_created(resource_id, identity); model_ready(resource_id, *, ownership, member_identities); model_request_started(resource_id, request_id); model_request_finished(resource_id, request_id); model_cleanup_members_observed(resource_id, identities); model_closed(resource_id); mark_ready(); read_session_resources(session_dir); decode_session_resources(session_dir, raw).
- [x] 写失败合同：UTF-8 严格结构、不可变 epoch/路径/owned/member 身份、开始/完成请求同 ID、重复注册/关闭后不可重开、写盘失败保留上一原快照。
- [x] 复用 json_snapshot 原子写，session-resources.v1 独立文件及 RLock。
- [x] Main 核对不会根据空列表或未知 phase 推断完整清理。

## Task 3: Original launch integration / 原启动接线

Files: app/vision/model_service.py, app/core/model_server.py, app/desktop_review/single_step_coordinator.py, scripts/run_local_step_session.py; new focused integration tests.
- [x] co/ModelService 可选 resource_journal，旧无 journal 调用不改变语义。
- [x] 原 model wrapper 增可选 before_resume 回调；有回调但无显式 owned scope 拒绝；透传至原 spawn_process_in_scope。
- [x] 原 scope/child/ready/request/close 边界使用 Task 2；登记失败不得 resume、输入或静默 fallback。
- [x] runner 读原 pointer 并核对自身/launcher/入口/目录，启动原 co 前建 Journal，ready 后 mark_ready；无输入实际启动/退出及持久清单验证。

## Task 4: Recovery observation, admission and takeover / 恢复观察与接管

- [x] 只观察 service 固定 pointer/report/inventory 原字节，原 process incarnation 与每个 owned scope，累积身份及专用 PID；缺证据拒绝。
- [x] 明确 new-session 接口同时要求恢复资源证明和旧输入原终态/结算；原正常 start gate 不放宽，不改原 report，不消费旧队列。/ Explicit admission is implemented with resource and original-input proofs, preserving the ordinary start gate.
- [ ] 接管固定原程序/票据和新 host/window/capture，观察当前业务效果、明确消费原动作，再生成后续新 EID。
- [ ] Main 新鲜实机完整任务、连续中断/弹窗/恢复/收尾通过后，同冻结候选交独立验收。

Task 4a/4b 已完成；Task 4c 内部 primitives 已通过离线持久集成，公开采集/接管与真实完整流程仍未完成；不以资源或新宿主 ready 证明冒充工作流接管。/ Tasks 4a/4b are verified. Task 4c internal primitives pass offline persistent integration; public collection/takeover and complete live workflows remain open.

### Task 4a: Read-only proof / 只读资源证明

Files: app/execution/session_resource_recovery.py; tests/test_session_resource_recovery.py.
API: observe_session_resource_cleanup(session_dir, *, timeout_seconds=1.0).

观察预算保持原 helper 的有限正超时合同（0 < timeout_seconds <= 10），不把 0 偷换成正数或无限等待。/ Keep a finite positive observation budget; never silently replace it.

- 固定原 pointer/report/session-resources 原字节 SHA、来源、launcher PID/created 与 runner PID/create_time_ns；原进程仍活、身份不可观察或文件漂移直接拒绝。/ Pin original bytes and process incarnations; reject live owners, unobservable identities or changed evidence.
- 无模型或 registered 尚未开始 scope 可观察为无模型资源；scope_starting 未持久化策略、launch_starting 未登记主 PID 必须 indeterminate，closed_from_phase 保留同样限制。/ An incomplete launch remains indeterminate even after close.
- owned scope_acquired/launch_registered/ready 复用原 observe_process_scope_cleanup，terminate=False、remove_owned_pid_file=False、listener_ports=[]、累积两组身份、连续三次零观察；专用 PID 文件残留仍不通过。/ Observe owned resources without terminating or unlinking anything; require stable emptiness and absent PID file.
- external 不查询/终止其 Job 或监听器；未决请求仍 indeterminate。外部空闲服务可保留。/ Leave external services alone; unresolved external requests block proof.
- 返回 session_resource_cleanup.v1 的独立观察结果，resources_cleanup_verified 与 input_terminal_settlement_verified/new_epoch_ready 分开；后两者在此 API 固定 False。此 API 不写任何文件、不消费队列、不创建宿主。/ Resource proof alone cannot admit or take over a workflow.
- Main 先失败合同再最小实现，验证原快照原字节不变、PID 复用、未知阶段、残留/权限失败、漂移和 no-kill；之后做新数据原宿主实际正常退出与异常退出的无输入观察。/ Verify contracts and fresh no-input host lifecycles before extending admission.

### Verified evidence / 已核验证据

Main 最终相关回归 498 passed（main-final-contracts.xml）。原 InstantSession 两次正常退出/一次异常退出，均为全新会话、agent_current、无模型清单及零输入；正常清理通过，异常资源观察通过但旧正常清理与新会话 gate 不改变。原 wrapper/Job 另用实体 stdlib 等待进程测试正常启动和登记失败不 resume，真实视觉模型测试为 0。610 个冻结源文件相同，11 条原进程身份已退出。/ Main verifies 498 checks, three fresh original host lifecycles and two real suspended-launch boundary cases. Scope fixtures are not vision models or learning GUI acceptance.

首轮 source/fixture/原字节绑定失败与第二目录复测分开保存；所有观察不回填历史 session-02。/ Preserve first failures separately and do not backfill older sessions.

Evidence root: D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-recovery-admission-01.

### Task 4b: Explicit epoch admission / 明确新会话准入

Files: app/execution/session_input_terminal.py, app/execution/session_epoch_admission.py, app/instant_mcp.py; focused contract tests. Main owns epoch decisions/integration; Sol may implement the pure input inspector. No release or extra executor.

APIs: InstantSession.preview_recovery(); InstantSession.recover_session(request_id, preview_sha256); corresponding instant_recovery_preview and instant_recover_session MCP tools. Input inspector: inspect_session_input_terminal(session_dir, library_root), returns session_input_terminal.v1 with catalog_sha256/files/commands/workflow_settlements/input_terminal_settlement_verified; no writes or input.

- 预览在原 inactive epoch 内组合 Task4a 与全部旧输入原终态/工作流结算，固定原文件目录集合与字节 SHA、pointer/config/library 及原资源。异步 worker 必须终态且无 started/unknown 派发；同步输入需原回执明确动作事实；不能把 response 存在或 failed 当未输入。/ Preview composes resource and original-input evidence, not acceptance alone.
- 原活动 pending Trial 必须经原 WorkflowTerminalRecovery.status 重新核验已有 settlement；零旧输入可准入空新会话，但不冒充已完成工作流。旧目录原字节不改、不复活旧 worker、不消费旧 queue。/ Pending trials require validated settlement; empty sessions do not imply workflow success.
- 保存 data-root/recovery-admissions/<request_id>.json，固定预览 hash、旧 session/原 pointer/证明、配置与预分配新 session；先 prepared，再 launch_started，原创建宿主函数回调存 host_created，原 pointer 发布后 pointer_published，实际 ready 及新 journal/进程身份核对后 ready。/ Persist a bounded launch transaction and verify readiness from the new maintained host.
- 正常 start gate 保持；只抽取原配置/新宿主启动维护函数供新入口复用。创建前写盘失败不得 Popen；launch_started 且 PID 未登记保持启动未知，任何 ID 不得自动再次创建。host_created 可核对原身份/确切入口和当前 pointer 后完成同一发布；已发布同 ID 只回读同一新宿主。/ No second spawn after an uncertain launch; idempotence never replays commands.
- 外部 API/模型配置仍按原操作员启动配置核验；新 session 不继承旧 target/commands/worker。new_epoch_ready 只表示新宿主可用，workflow_takeover_completed 固定 False。/ Readiness is not workflow takeover.
- Main 红/绿：未知/非终态/漂移/未结算拒绝，prepare 写失败零创建，创建后与发布后异常同 ID 零重复，普通 gate 不变；随后全新数据原宿主中断→明确恢复→再次连续恢复→正常收尾的无输入测试。已结算 verify 的先采集后拒绝缺口同批修复。/ Preserve first failures and verify live continuity before takeover.

Evidence root: D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-epoch-admission-01.

接管 Task4c 仍要求新宿主当前窗口/新 capture/原效果核验、仅新账本消费旧 step 和跨 epoch 唯一接管索引；不能通过普通 verify/continue 修改旧 session。/ Task4c remains a distinct effect-verified, uniquely indexed takeover transaction.

### Task4b checked implementation / 本轮已验证实现

- [x] 原输入终态 inspector、只读稳定 preview、原 launcher 明确准入及两个公共 MCP 工具；普通 start gate 保持。/ Original evidence inspection and explicit launcher admission are wired.
- [x] prepared/launch_started/host_created/pointer_published/ready 持久事务；unknown 不重建且不冒充当前资源/输入证明。/ Persisted stages preserve uncertainty and prevent duplicate creation.
- [x] 发布后原 settlement 经严格准入记录只读重核；原 status/preview/settle 不取得跨 epoch 权限。/ Archived verification remains read-only.
- [x] 原已结算 verify 在观察、核验和写盘前拒绝；Main 最终相关合同与启动/来源回归 482 passed。/ The settled-verification guard and related regression pass.
- [x] live-03 全新原 InstantSession 三轮硬终止→明确恢复，第三轮真实 pointer 写失败后同宿主恢复，最终 cleanup；全旧目录前后 SHA 及 612 项 source freeze 保存。/ Fresh host continuity, interrupted publication and full source/old-file evidence pass.
- [x] 真 STDIO 两个新工具完整调用、九工具常规探针及最终清理。/ Public recovery calls and normal protocol smoke pass.

所有实机均空模型清单、零 GUI 输入；pending 工作流结算的跨 epoch 重核为持久合同测试。不得据此勾选完整 R3 GUI 工作流、模型推理或收益验收。首次 fixture/SDK/协议失败与修复后结果分开保留，详见 docs/verification/LEARNING_EPOCH_ADMISSION.md。/ Lifecycle and contract checks do not establish live pending-workflow takeover, inference or benefits.

### Task4c internal primitives / 明确接管内部基础

Files: app/learning_memory/workflow_verification.py, workflow_recovery_history.py, workflow_recovery_import.py, workflow_trial.py, workflow_runner.py, workflow_runtime.py; focused effect/history/import/claim/race tests.

- [x] verify_current_effect 纯核验新现场效果，保留 source_action_executed True/False/null，不制造 completed/action_executed 回执；原 verify_step 行为保留。/ Pure current-effect verification preserves original action facts without inventing an execution receipt.
- [x] 原历史 provenance 核对固定 program/inputs、上游 outputs、原 command/receipt/terminal 与 Agent 请求或 rule envelope/PNG；来源不支持或实际提交缺失时拒绝。/ Verify original provenance and upstream outputs; reject unsupported origins or unavailable submitted values.
- [x] data-root/workflow-takeovers 唯一 claim 固定原 session/run/step/EID/program，先预占再 importing→新 Trial→原 Runner 暂停导入→ready；同 ID 只读，失败保留原阶段，不重派旧 EID。/ A source-stable claim reserves consumption before paused successor-ledger import; retries preserve the same run without replay.
- [x] prepare 固定新输入目录与 effect/envelope/PNG 原字节；commit 与原 queue/admit 共用锁，竞争写入和来源漂移拒绝；partial claim 在尚无 Trial/Runner 时也阻止竞争输入。/ Pin the successor input catalog and effect bytes; serialize commit with the original queue/admission gate and reject races.
- [x] Main 阶段相关回归 466 passed / 21.43s，含最终边界 race 11；证据 main-final-contracts.xml。原首次失败、真实库锁重入失败和修复后结果分别保留。/ The recorded phase regression passes 466 checks, including 11 race cases; first failures remain separate.

当前仅支持同窗口 incarnation；上述为离线持久集成，OS/launcher 边界模拟，未证明真实 GUI 接管、收益或完整连续恢复。learning 未发布、不改版本，stable v0.1.1 保持独立不动。/ Support is limited to the same window incarnation. Offline persistent integration with simulated OS/launcher boundaries does not establish live GUI takeover, benefits or full continuity; learning remains unreleased and stable v0.1.1 is unchanged.

Evidence root: D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-takeover-01.

### Task4c remaining acceptance / 明确接管剩余验收

- [x] 原 learning_workflow 公开接管控制与原 collector 已接线并有离线检查；完整实机验收仍在下项。/ Public controls and maintained collection are wired and contract-tested; live acceptance remains open.
- [ ] 语义业务对象与窗口新实例绑定；不得以同窗口身份推断跨应用实例等价。/ Semantic business-object and new-window-instance binding.
- [x] runtime 失败及重复 epoch/import 来源核验已有持久集成证据（ancestry/final-green.xml，93 passed）；不等于完整实机恢复。/ Persisted runtime/ancestry checks pass; this is not live acceptance.
- [ ] 全新同应用真实连续任务、活动弹窗、异常恢复与最终收尾；Main 完整单项/连续通过后，同冻结候选独立实机验收。/ Fresh complete live continuity, dialogs, interruption recovery and cleanup, followed by independent acceptance of the same frozen candidate.
- [ ] R4/R5/R6。/ R4/R5/R6 remain open.

以下保留原接管目标顺序；内部基础完成不等于整项 Task 4c 通过。/ Preserve the original target sequence; completed primitives do not complete Task 4c.

1. 读取固定原 admission、program、Trial、ticket 与 settlement；当前新宿主保持 empty/无竞争输入。/ Bind the original provenance to the admitted successor.
2. 原新宿主选择当前目标、采集新 capture，调用原 read_spec/verification 核验 pending 原动作的当前效果；失败/不确定不推进、不重发。/ Verify the current effect using fresh maintained evidence.
3. 仅写新 epoch Trial/Runner 与来源记录；固定原参数、有效上游输出及确切程序，跨 epoch 唯一消费索引先持久预占再提交；磁盘或并发未知不得再次消费。/ Create a new ledger with pinned inputs and uniquely claimed provenance.
4. 完成新内容完整任务、活动弹窗、同会话状态累积、中断与最终清理；Main 单项与连续通过后再同冻结候选独立实机验收。/ Full live workflow acceptance precedes independent acceptance.
