> **2026-10-01 暂停点校准 / Pause checkpoint:** 接管 collector、原 learning_workflow 预览/提交、runtime 失败来源和重复 epoch 链已有源码及离线集成证据。同逻辑请求 ready 回读误停调度已修复（108 项相关检查通过）；两个夹具缺失原命令问题已修复（23 项通过），原失败保留。最终汇总回归中止，完整实机接管尚未通过。下面是上批基础验收记录；当前顺序见[主线重排](../superpowers/plans/2026-10-01-learning-mainline-refocus.md)。 / Public collection/control and ancestry now have offline evidence; final consolidated and live acceptance remain open. Earlier evidence below is historical.

# 学习工作流效果接管基础 / Effect-verified workflow takeover foundation

2026-10-01，开发树 `codex/dev-workflow-editor`；学习源码未发布，版本仍为 `0.1.0-test.8`，正式 v0.1.1 保持独立。/ Learning development remains unreleased and separate from stable v0.1.1.

## 已实现的维护路径 / Implemented maintained paths

- 已结算的直接 `verify_trial_step` 和 `TrialService.prepare` 在观察、幂等命中或写盘前拒绝；旧 session 全部文件原字节、preview 和重复结算保留。/ Settled direct verification and preparation reject before observation or persistence.
- 准入 catalog 增加原 `workflow-observations` JSON 与这些证据、历史读取回执确切引用的 PNG，校验原 SHA、PNG 签名、session 路径、集合和结束字节；不遍历无关资产，保留 4096 文件／64 MiB 限制。原缺少这些证据的准入记录必须重新预览，不回填旧证明。/ Admission now pins referenced business evidence, without backfilling earlier records.
- 原审阅新增 `review_request={request_id, submitted_outputs}`，保留条件改变 verdict 前真实提交的输出；最终有效 outputs、原请求 hash 和幂等语义不变。/ Review preserves the actual submission rather than reconstructing discarded outputs.
- `verify_recovery_history` 重编译原命令，核对原 Trial／program／receipt／terminal／request／PNG，规则结果重新计算；Agent 审核是已记录来源，不是独立准确率证明。/ Historical provenance and rule verification are checked against original evidence.
- `verify_current_effect` 使用独立 `workflow_current_effect.v1` 和新 observation；原动作事实与当前效果分开，未执行或未知事实不改成 True，不制造新 completed receipt。/ Current effect verification never invents a new execution receipt.
- `prepare_recovery_import` 固定原 ready admission、已有 settlement、完整 catalog、原输入／有效上游输出／确切 program，以及新 session 的效果 PNG/envelope；当前仅核对同一个 HWND／PID／创建时间的窗口 incarnation。规则及成功条件失败或不确定不得推进。/ Preparation binds original provenance and fresh-epoch evidence; app recreation and semantic object rebinding remain open.
- `commit_recovery_import` 使用 data-root 级唯一 claim。其 identity 来自原 session／run／step／EID／program SHA，不含新 epoch 或 admission；`prepared → importing → 新 Trial → 原 Runner/active → ready` 保留部分写入。相同请求续接同一运行，其他请求不能重复消费。/ A shared durable claim prevents a second consumption of the same source.
- 新 history 是明确的来源导入事件及当前效果事件，原 EID 留在 source 中；没有新 execution_request_id 或原动作重放。上游值由新 run 正常包装，保留来源。原 Runner 导入只保存状态并等待 `takeover_ready`，显式继续才经原队列生成后续新 EID。/ Imported provenance is distinguished from new execution; original dispatch resumes only explicitly.
- `importing` 时直接 prepare、run/continue 和竞争输入拒绝；尚无新 Trial／Runner 时，原 Trial.start 和 Runtime.admit 也核对 session claim。真实库锁下导入复用已持锁 TrialService，普通调度仍使用原锁。/ Partial imports remain paused even before a runner exists.

- 新会话输入 catalog 排除会演进的 Trial/Runner，保留原命令、回执、业务观察和引用 PNG；准备时固定字节，提交中原队列锁阻断新入队和 Runtime.admit。准备后已返回的竞争输入也使观察失效，不允许接管。/ Pin the original input catalog and serialize admission with the maintained queue lock.
- effect_files 必须恰为实际 envelope 与 PNG 的路径/SHA；发布 ready 前复核旧 catalog、新输入及 effect 字节。ready 同 ID 只读回读原运行及后续 history，不要求旧现场图仍有效。/ Recheck pinned evidence at publication; completed retries read state without replaying old observations.

内部维护 API 不等于公开接管工具：当前 MCP 仍为上批九工具；原宿主的新截图采集入口、业务对象重绑定和完整连续接管尚待接线。/ These internal primitives are not a public takeover endpoint; maintained live collection and complete continuity are unfinished.

## 实际验证 / Actual verification

Main：相关 `pytest` **466 passed，21.43s**，见 `main-final-contracts.xml`。单项回归覆盖原控制／观察／规则／历史／Trial／Runner／Runtime／catalog／admission／MCP；不是新增 443 个测试，也不是完整 GUI 任务验收。/ This is an overlapping related regression set, not a GUI acceptance claim.

`tests/test_workflow_recovery_import.py` 使用真实 MemoryWorkspace、原 Trial／Runner／终态结算／epoch admission、上游历史和落盘 PNG；进程身份及 Popen 为边界模拟。三处真实原子写入故障注入（Trial、Runner active、claim ready）保留 importing，原文件字节不变，同 ID 续接同 run，零派发；显式原 continue／tick 只排新下游 EID，并正常完成合成合同流程。/ Persistent integration checks use real maintained storage and simulated OS boundaries; they do not launch a GUI host.

首轮失败保留：直接守卫的 RED、纯效果接口 35 failed、历史接口 23 failed、Runner 接口 6 failed、catalog 10 failed、实际审阅提交 3 failed、session guard 有效 RED 4 failed／1 passed。导入的 contract RED 9 failed；真实库锁首次 5 failed／9 passed，经主路径复用修复后 14 passed。目录／简化协议／测试错误的首轮记录另存，不计产品首次成功。/ Red-phase, fixture and real lock failures remain separate from corrected runs.

竞争输入 RED 4 failed／1 passed、最后证据漂移/幂等 RED 4 failed；初次修复相关检查 43 passed／2 failed（首次拒绝创建锁文件），补快速拒绝后 45 passed。最终 11 项边界检查通过，最后验图注入按真实 Trial 导入调用栈定位；首次失败未改记通过。/ Concurrency and final-evidence failures remain separate from the corrected boundary checks.

证据根：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-takeover-01`。本轮没有真实 GUI 输入、视觉模型、供应商 API、外部 Agent 实机验收、打包或发布。/ No live GUI, model, provider, independent live acceptance, package or publication occurred in this slice.

## 未完成及下一顺序 / Open work and order

1. 原宿主内实时采集、绑定当前业务对象、时间与窗口漂移校验，再公开可读的接管入口；不能让调用方任意写 envelope 充当现场观察。/ Wire maintained live collection, semantic scope and freshness before exposing takeover.
2. 跨再次中断的来源链与 runtime 失败历史；当前 history validator 明确拒绝 `runtime`／已有 `recovery_import` 来源。旧失败／不确定记录若缺原实际提交凭据也拒绝，不补造。/ Close repeated-epoch and runtime-origin provenance without inventing lost history.
3. 新数据、新窗口、真实完整学习工作流；同会话累计状态、活动弹窗、中断、恢复、最终清理，本方修复／复测后再交同冻结候选独立实机验收。/ Complete main fresh live acceptance before independent testing.
4. 人工审核 C、R4 匹配收益、R5 实测优化和 R6 第三方迁移；模型总调用、token、准确率和速度收益仍未知。/ Complete the planned benefit and transfer stages; no benefit is claimed yet.
