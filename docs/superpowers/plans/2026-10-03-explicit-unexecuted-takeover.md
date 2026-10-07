# Explicit unexecuted-step takeover / 明确继续未执行步骤

## Scope / 范围

Extend the existing P3 recovery path after T16 exposed a cancelled grounding ticket with no input. The stable release v0.1.1 and accepted UI v14 remain unchanged. This slice changes source recovery contracts and offline coverage; it is not a live or release acceptance result.

扩展既有 P3 恢复路径：T16 的原识图票据取消且尚未输入。正式版 v0.1.1 与已选 UI v14 不变。本片只补源码恢复合同及离线回归，不记为现场或发布验收。

## Decision / 设计决定

- `takeover_preview` accepts optional `resolution`: omitted or `adopt_success` preserves existing successful-effect adoption and v1 marker bytes; `resume_unexecuted` is explicit and produces a strict v2 marker with that resolution. Commit inherits the decision from the exact preview SHA and accepts no separate decision override.
- Only a settled original `cancelled` worker with false action facts, explicitly false dispatch-in-progress, an empty dispatch-attempt list, no last execution and no pending grounding qualifies. Original acceptance, worker, settlement, pinned program, history and source catalog remain unchanged and are revalidated.
- Current native observation must be complete, bound to the original window and checked by the saved deterministic rule. Resume requires `failure/observed_value_conflict`; success uses the existing adoption choice; uncertainty, agent-only judgments and unsupported observation rules remain blocked.
- Import only verified upstream history/outputs. Keep the interrupted step as the new current step, with no pending ticket and no invented success/output for that step. Empty upstream prefixes are allowed only for this v2 resolution.
- Preserve the same source-only exclusive claim identity across choices. Preview and commit reobserve; incomplete commits revalidate; ready retries remain read-only. Commit pauses at `takeover_ready`; explicit continue produces fresh execution and capture identities through the existing gated runner.

- `takeover_preview` 新增可选 `resolution`；省略或 `adopt_success` 保持既有成功效果接管与 v1 记录。明确选择 `resume_unexecuted` 才生成带处置字段的严格 v2 记录。提交只继承确切预览 SHA 的处置，不能另外改选。
- 仅接纳已结算的原 `cancelled` worker：动作事实均为 false、派发中明确为 false、派发尝试为空、没有末次执行及待识图任务。原准入、worker、结算、固定程序、历史和文件目录保留并重新核验。
- 新原生观察必须完整、绑定原窗口并使用已保存的确定性规则。继续只允许 `failure/observed_value_conflict`；当前效果成功仍走原接管选择；不确定、纯 Agent 判断或不支持的观察继续阻止。
- 仅导入已验证上游历史和输出。新运行停在原中断步骤，pending 为空，不给该步骤添加成功记录或输出。零上游仅在本 v2 处置中允许。
- 两种选择共用原来源的独占 claim。预览和提交重新观察，未完成提交复核，ready 重试只读。提交暂停在 `takeover_ready`，明确继续后才经现有门控执行器生成新的执行与截图身份。

## Execution / 执行步骤

1. Create isolated fresh offline cancellation fixtures and capture failing tests before implementation.
2. Add the resolution/marker contract, primary zero-input proof and recovery-state reconstruction; bind public preview, replay and ancestry validation.
3. Run new and affected recovery, runner, public, history and session checks; retain failures and rerun results separately. Inspect actual diff and a bounded independent source review.
4. Synchronize public documentation and progress evidence. Keep native P3 continuation, modal handling, cleanup and final delivery open until actually validated.

1. 创建全新隔离取消夹具，先记录未实现时的失败测试。
2. 补处置/记录合同、原零输入证明、恢复状态重建，并闭合公开预览、回读和祖先历史核验。
3. 运行新增及受影响恢复、调度、公开入口、历史和会话检查；首次失败与复测分别保留。检查实际差异并作有界独立源码审阅。
4. 同步公开文档和进度证据。原生 P3 续跑、弹窗、清理与最终交付在实证前继续未完成。

## Limits / 限制

No raw desktop input, forced application termination, old-session ledger rewriting, cached-MCP hot reload, automatic retry, version bump, packaging, commit or publication. Ordinary workbench recovery-choice UI is a later integration item, not represented as complete by this API/source slice.

不使用原始桌面输入、强制终止应用、改写旧账本、热重载旧 MCP、自动重试、改版本、打包、提交或发布。普通工作台的恢复选择入口是后续接线项，不以本片 API/源码完成冒充已完成。

### Verified guard and result / 已核验守卫与结果

For v2 ticket-free resume/advance, rebuild actual source and new history even if its length or runner seen values have changed. Bind seen/count to verified consumed steps, compare the exact initial trial when no new history exists, and reject terminal runners retaining waits before resume can reactivate them. Existing normal post-execution history remains valid, and ready commit rereads remain read-only without a second library lock.

v2 无新票据的 resume/advance 始终重建原来源与真实新增历史，不能因历史长度或 runner seen 改变而跳过。seen/count 绑定核验 consumed，尚无新历史时精确比较初始 trial；终态遗留 wait 在 resume 重激活之前拒绝。正常新执行历史仍有效，ready 提交回读仍只读且不二次开库锁。

The source slice is implemented. Main passes 374 related checks before the last terminal-only repair; its final 125 direct checks pass, including all 65 new checks, without adding totals. Original T16 no-input replay preserves 163 files. Ordinary workbench choice wiring, live pending-ticket continuation/dialog/full cleanup and final delivery remain open.

本源码片已实现。最后终态窄改前 Main 374 项相关检查通过；最后 125 项直接回归通过（包含全部 65 项新增），不累加。原 T16 零输入只读复验保留 163 文件。普通工作台选择接线、实机原票据续跑/弹窗/完整收尾与最终交付仍待。


Lifecycle update / 生命周期更新：原窗口/PID 已退出；原支持结束请求已签名发送一次，原 helper 不产生该请求 reply，短轮询 timeout 保留，随后 cleanup_verified=true、driver exit 0。只读核验原 host/PID/创建时间和 runner 原创建时间已结束；104732 已复用，首次 PID-only 断言失败及修正诊断分别保存，未触碰其它进程。原 pending 票据仍 cancelled/action=false，不把清理改记为任务完成。证据 / Evidence: `unexecuted-original-cleanup.json`, `unexecuted-cleanup-audit-pid-first-failure.json`, `live/identity-absent.json`, `live/cleanup.json`, `live/driver-exit.json`. The original connection now closes normally without hot reload or rewriting task success; the reused runner PID belongs to a different creation time. Full live takeover remains unverified.
