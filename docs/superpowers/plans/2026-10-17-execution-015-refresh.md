# Execution 0.1.5 refresh / 执行版 0.1.5 同版本更新

**Goal / 目标:** Implement the user's selected optimizations: adaptive observation after Enter and overlap of current-result verification with next-step read-only grounding. Release a verified Windows execution package with honest latency evidence. / 实现用户选定的 Enter 后自适应观察，以及当前结果复核与下一步只读定位并行；经验证后发布 Windows 执行安装包和真实耗时数据。

**Authorization / 授权:** The user explicitly selected items 1 and 3 and requested a new release. Continue the existing implementation/test/release workflow without introducing another design-approval round. / 用户明确选择第 1、3 项并要求发布；沿用既有开发、测试、发布授权。

**Latest scope / 最新范围:** The user subsequently requested updating the existing 0.1.5 version, and temporarily hiding learning-mode material. Keep Runtime 0.1.5 and extension 0.0.2; refresh verified artifacts with a dated build identity and checksums. Hide learning entry points in current product/install documentation while preserving source and historical releases. The evidence directory retains its initial `016` name for continuity. / 用户随后明确更新现有 0.1.5 并暂时隐藏学习模式内容；保留 Runtime 0.1.5、扩展 0.0.2，按日期与摘要区分新构建；隐藏当前产品和安装文档中的学习入口，保留源码与历史发布。证据目录初始的 `016` 名称保持不变。

**Architecture / 架构:** Reuse the current adaptive observation and original absolute grace deadline. Extend it only to authenticated completed visual-submit receipts. Add a process-local, single-lookahead grounding service beside the current verifier; consume its result through the existing grounding store and gated action route only after predecessor success. / 复用既有观察与原绝对截止，仅扩展到可认证的已完成视觉提交回执；增加进程内仅预取下一步的定位服务，在前步成功后经既有 grounding store 和动作门禁消费。

**Environment / 环境:** Python 3.11, existing maintained Windows runtime, existing API profiles, existing linked worktree `codex/dev-main-review-resume`. Baseline commit `18cf8ac1912f2b8ffbfb6e7ba32a773b9f334e86` plus the preserved ordinary-click/SSL source candidate. / 沿用维护工作树、解释器和 API 配置；保留上一批普通点击与 SSL 未发布改动。

## Constraints / 约束

- Keep grounding model, image resolution, prompts, Decision rules and risky-action gates unchanged. / 定位模型、分辨率、提示词、Decision 规则和高风险门禁不变。
- Preserve all pre-existing modifications; a verified 20-file archive is in `D:/AgentGUI-Projects/evidence/execution-pipeline-016-20261017/`. / 已有 20 个变更文件已备份并核验。
- Project screenshot/action interfaces only; no Codex native Computer Use. Preserve the named independent Edge profile and all browser data. / 只用项目截图动作接口，禁止原生 Computer Use；保留独立 Edge 资料及全部浏览器数据。
- A stable image chooses observation timing; it does not prove success. Never replay input to repair a failed result check. / 稳定仅决定采图时机，不证明成功；不重放输入修补核验失败。
- Default focus/type waits remain zero. Explicit waits, native conditions, temporal content, learning, local/delegated vision retain their existing contracts. / 聚焦和键入默认等待保持零；显式等待、原生条件、时序内容、学习和本地/委派视觉保留原合同。
- Prefetch never claims input, advances a task or switches a window. Consume only once after authenticated predecessor success; bind the exact plan, attempt, goal, source frame and configuration. / 预取不抢输入、不推进任务、不切窗；只在认证的前步成功后消费一次，绑定计划、尝试、目标、原图和配置。
- Cancel, manual handoff, failure, changed observation, restart or stale identity invalidates a prefetch. Count discarded API calls and retain errors; do not disguise them as a new automatic retry. / 取消、人工接管、失败、换图、重启、身份过期均使预取失效；弃用调用计入费用，不隐式重试掩盖错误。

## Work and checks / 工作与验证

- [x] Inspect current call paths and preserve existing changes. Codegraph transport is unavailable; use targeted source reads. / 已核对调用链并备份；Codegraph 连接不可用，使用定向源码读取。
- [x] **Enter observation:** modify `local_direct_step.py`, `input_sequence.py`, `task_plan_adaptive_grace.py`; add `test_input_sequence_adaptive_observation.py`. First demonstrate missing behavior, then verify early success, original-deadline final observation, unchanged image, delayed transition, cancellation and forged/nested receipt rejection. / 先复现缺失行为，再覆盖早图成功、原截止补查、同图、迟到变化、取消和嵌套回执伪造。
- [x] **Read-only lookahead:** add `TaskGroundingPrefetch` in `app/vision/task_grounding_prefetch.py`; integrate `task_plan_admission.py`, `task_plan_verification.py`, and the original `agent_command_jobs.py` consumption path. / 增加只读预取服务并接入复核与原消费入口。
  - Interface: optional verifier prefetch hook; one process-local future; `prepare → ground → resolve`, followed by release after persisted predecessor success and consume/claim in the next job. / 可选复核钩子、单个进程内 future；前步落盘成功后才放行后步消费。
  - Test real synchronization with fake HTTP/desktop boundaries: grounding starts while assessment is blocked; no input before success; one HTTP/consume; cancellation, late responses, stale frames, wrong goal, failure, restart, timeout and malformed output. / 用可控 HTTP/桌面边界验证真实并发顺序及各类失效，无提前动作或重复请求。
- [x] **Main integration and review:** run affected contracts together, independently inspect the actual diff and fix relevant findings. Freeze source hashes before live runs. / 主端合并验证并独立审阅实际差异；实测前冻结源码摘要。
- [x] **Live acceptance:** Main runs fresh low-risk Notepad, 7-Zip and Edge flows with consecutive use, cancellation/recovery and owned-window cleanup. Record first failures separately. Compare complete step duration and actual action intervals; log prefetch overlap, calls and tokens including discarded work. / 主端完成新数据多应用连续测试、取消恢复和归属窗口收尾；分别记录完整单步、真实动作间隔、并行区间及全部用量。
- [x] **Delivery:** retain execution version 0.1.5, build one frozen candidate after source verification, validate isolated package dependencies and installed behavior, then request independent acceptance of the same candidate. Main completed Notepad/Edge twice each; independent Sol completed 7-Zip twice on the same payload, including owned-window/host cleanup. / 保留执行版 0.1.5；源码通过后集中构建，验证隔离依赖和安装态；Main 完成记事本及 Edge 各两轮，独立 Sol 使用同载荷完成 7-Zip 两轮及窗口、宿主收尾。
- [x] **Documentation focus:** temporarily hide learning-mode entry points from English/Chinese product and setup pages, and focus the active roadmap on execution. Keep learning sources, shared dependencies and historical release assets. / 暂时隐藏中英文产品及安装页面的学习模式入口，当前路线集中执行模式；保留学习源码、共享依赖和历史发布资产。
- **Publish (final status and asset checks are recorded in the release notes) / 发布状态及附件核验以发布说明为准:** synchronize English/Chinese README and affected architecture/current-state notes; commit and integrate with main without overwriting unrelated edits; update `instant-v0.1.5` with dated refresh notes, source identity, checksums and verified assets. Preserve a verified copy of replaced release artifacts. Verify remote files and downloadable asset digests. / 同步中英文及受影响文档，保护无关变更合入 main；更新 `instant-v0.1.5`，标注刷新日期、源码身份与摘要，先保存被替换资产的已核验副本，再核验远端文件与下载摘要。

## Reporting boundaries / 报告边界

Old samples are comparison evidence, not new-version acceptance. Do not claim a four-second operation target without new measurements. Distinguish a single complete operation from adjacent action intervals, API latency and whole-plan time. Keep failures and unmeasured areas explicit. / 历史样本仅作对照，不能替代新版本验收；未测得前不宣称达到四秒。区分完整单步、相邻动作间隔、API 耗时和完整计划时间，保留失败及未知项。
