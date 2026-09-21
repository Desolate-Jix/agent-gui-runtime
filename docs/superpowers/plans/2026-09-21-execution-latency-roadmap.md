# 执行模式优化计划 / Execution-mode optimization roadmap

**日期 / Date:** 2026-09-21

**状态 / Status:** 待执行的阶段计划，不代表已实现或已发布。接口细节在各阶段开始时基于当前代码确定；本文件不是可直接照抄的代码补丁。 / Planned phases, not implemented or published; finalize interfaces against current code at the start of each phase.

**目标 / Goal:** 保持 Agent 决策、框架执行的边界，在真实任务成功率不下降的前提下，减少命令之间的停顿和不必要等待。 / Reduce inter-command gaps and unnecessary waits without regressing real-task success; Agent decides, framework executes.

**基线 / Baseline:** test.4 + 未发布输入框聚焦修复。754 项源码测试通过；有限样本字段聚焦/输入 4/4，不代表总体可靠性。窗口重新启动的观察/归属问题仍未修复。 / test.4 plus unreleased field-focus fix; 754 source tests passed, four bounded field interactions passed, relaunch observation/ownership issue remains open.

## 范围与原则 / Scope and constraints

- 保留现有单步接口和默认行为；组合操作是可选能力，不强迫其他 Agent 改用。 / Preserve existing single-step APIs/defaults; grouped operations are optional.
- 本轮不开发学习模式、新模型组合、自动风险审批或推测点击；不借优化之名移除现有契约。 / No learning mode, extra models, new risk-approval system or speculative clicks; preserve existing contracts.
- 焦点/文字/页面条件检测是执行正确性与等待逻辑，不是重新堆叠风险策略。 / Focus/text/readiness checks serve correctness and waiting, not a new risk-policy layer.
- 不使用站点固定坐标、旧截图或模拟页面代替真实验收。测试窗口和数据独立，模型只读复用。 / No fixed site coordinates, stale captures or mock-page acceptance; isolate test windows/data and reuse model weights read-only.
- 框架报告动作派发、观察与条件是否满足；任务成功仍由 Agent 判定。 / Report dispatch, observation and condition satisfaction separately; Agent judges task success.
- Codex 完成单元/契约、真实单项、同会话连续回归后，才将同一冻结候选交 AionUi 独立验收。 / Codex finishes unit/contract, live individual and continuous tests before AionUi tests the same frozen candidate.

## P0：稳定性与可比较基线 / Stability and comparable baseline

- [ ] 核对原始启动回执、进程及窗口归属链，修复“窗口已开却报告 unavailable、随后不能正常收尾”的公共问题；先加复现测试再修，禁止靠重复启动掩盖。 / Reproduce and repair the common launch/ownership failure; never hide it by relaunching.
- [ ] 保留首次失败，验证正常启动、延迟出现窗口、复用浏览器进程、连续关闭/重开及清理。 / Retain first failures and cover delayed windows, shared browser processes, repeated close/reopen and cleanup.
- [ ] 记录统一时间线：请求发送、接收、排队、识别、输入派发、等待、截图、回执收到、下一请求发送。框架无法观测的 Agent 推理时间标 unknown，不把调用间隔全算模型耗时。 / Add correlated timestamps; label unobservable Agent inference time unknown rather than attributing all gaps to it.
- [ ] 基准运行期间不穿插读代码、写文档和长篇进度说明；开发调试时间另记。 / Keep development work outside timed acceptance runs.

**验收 / Exit:** 已知启动故障关闭；能复核一条完整时间线和同会话收尾，首次成功与恢复成功分开统计。 / Close the known launch defect and produce an auditable timeline with cleanup and separate first-attempt/recovered success.

## P1：减少往返——最小短组合 / Reduce round trips with a bounded group

- [ ] 复用现有识别、填写、按键执行路径，先只提供“定位并聚焦 → 填写/替换 → 可选 Enter → 观察”这一类有限组合，不新增平行执行器。 / Reuse existing primitives for focus/type/optional Enter/observe; do not build a second executor.
- [ ] Agent 显式给出目标、文字和是否 Enter；不让框架自行推断跨页面下一步，不把字段 Enter 默认为已授权业务提交。 / Agent supplies target/text/Enter intent; no inferred cross-page actions or implicit business submission.
- [ ] 每个子动作保留独立回执和时序，组合返回完成步骤、停止步骤、部分执行情况及最终截图；异常中断不回滚已产生副作用、不自动重放整组。 / Keep substep receipts, partial completion and stopping reason; no imaginary rollback or automatic group replay.
- [ ] 测试点击未聚焦、文字未匹配、弹窗、焦点切换、目标退出、半途断连/超时与重新读取回执；不因重连再次派发输入。 / Cover focus/text failures, dialogs, target changes, timeout/disconnect and receipt recovery without redispatch.

**验收 / Exit:** 搜索小任务从多轮 Agent 决策缩为一个组合请求及结果判定；准确性和错误诊断不下降，单步接口回归通过。 / Fewer decision round trips with intact correctness, diagnostics and single-step compatibility.

## P2：按条件等待与精简回执 / Condition-based waiting and compact replies

- [ ] 从便宜且可验证的焦点/字段值检测开始；识别能力不可用时明确说明，不将无法读取当作匹配成功。 / Start with cheap verifiable focus/value checks; unavailable evidence is not success.
- [ ] 聚焦和文字输入使用短等待；导航按明确观察条件有界轮询，保留最大超时。预期状态未出现时，即使画面不动也不能宣布就绪。 / Short waits for focus/type, bounded navigation polling; visual stability alone is not readiness.
- [ ] 不把一次 VLM 推理放进高频轮询；UIA 或局部像素/OCR检测按成本限频。DOM 不成为必须新增的浏览器依赖。 / Avoid VLM polling; rate-limit local checks and do not introduce a mandatory DOM dependency.
- [ ] 正常回执给摘要、关键耗时和原图引用；详细诊断另存且随时可读。原始截图不降质，返回摘要与证据必须绑定同一请求。 / Compact replies retain original-image access and request-bound diagnostics.
- [ ] 覆盖慢加载、持续动画、缓存快速响应、无变化但动作正确，以及观察不完整。 / Cover slow loads, animation, fast cached pages, correct no-change actions and incomplete evidence.

**验收 / Exit:** 少等无意义的固定时间，但无过早截图被误报成功；精简输出不破坏其他 Agent 的读取方式。 / Less fixed waiting without premature success or client incompatibility.

## P3：优化剩余识别成本 / Optimize remaining recognition cost

- [ ] 按新时间线排序瓶颈，再决定是否消除同一请求内的重复截图/识别、重复准备模型及重复等待；不同状态的截图不得为省时混用。 / Profile before removing redundant work; never reuse evidence across changed states.
- [ ] 保持模型常驻选项；仅在后端真实支持且实测有收益时评估缓存。不加入第二/第三模型或猜测执行。 / Keep model residency configurable; assess supported caching only with evidence, no extra models or speculative actions.

**验收 / Exit:** 报告总耗时与分项收益，不能只用某个模型阶段变快冒充端到端提速。 / Demonstrate end-to-end improvement, not just faster inference.

## 对照测试与交付 / Comparative testing and delivery

- [ ] 固定三类真实流程：Google 搜索 → B 站搜索 → 首个视频；Google Maps 搜地点并更换地点；新记事本填写、替换、撤销及不保存收尾。 / Use real web search/video, Maps search replacement and Notepad edit/undo/discard flows.
- [ ] 每项先做单项，再在同一会话连续运行；基线/优化版交替，初轮每种模式每类流程至少 5 次。冷启动单列，热运行不混入模型加载；发生干扰的轮次单列而非删除。 / Alternate baseline/optimized modes with at least five initial runs per flow/mode; separate cold/warm and interrupted runs.
- [ ] 统计端到端耗时、中位数/最慢值、Agent 往返数、首次成功、恢复成功、误操作、部分执行和清理。小样本不声称稳定 p95 或总体成功率。 / Track latency, round trips, first/recovered success, misoperations and cleanup; no population or stable-p95 claims from small samples.
- [ ] 若出现新增误操作、无法诊断的部分执行或清理失败，停止发布，修复后完成相关单项与连续回归。 / New misoperations, opaque partial execution or cleanup failures block release pending regression.
- [ ] Codex 通过后冻结一个候选交 AionUi；要求返回原始请求、错误码、失败步骤、截图引用、耗时及清理情况。失败先由 Codex 修复/复验，再交独立复测。 / Freeze one Codex-validated candidate for AionUi; require reproducible error and cleanup evidence.
- [ ] 累计改动通过后集中构建一次，更新中英 README、Agent 指南、契约和限制，检查独立包依赖。保留当前发布版作为回退，不为每个小改动打包。 / Consolidate builds, bilingual docs and isolated dependency checks; retain the current release for rollback.

## 存储控制 / Evidence retention

本轮建议上限：每类流程保留最近 3 个成功轮次的完整原图/详细日志；此外保留每个尚未关闭缺陷的首次失败和修复后证据对。其他成功轮次保留小型时序摘要与哈希，完整证据是否已清除必须标明。删除前核对唯一失败证据、活动会话及发布验收引用；不是按数量盲删。 / Proposed cap: retain the latest three full successful runs per flow, plus first-failure/fixed evidence pairs for open defects; keep compact summaries for other successes. Verify references and unique evidence before any deletion.

## 顺序与暂停点 / Order and pause point

**P0 → P1 → P2 → 对照复验 → 按瓶颈决定 P3 → AionUi → 候选交付并停下给用户检查。** 不以提速推迟稳定性修复，也不把本轮扩展成学习模式重构。 / Stabilize, group, wait/compact, compare, profile-driven optimization, independent acceptance, then deliver and pause for user review.

## 研究依据 / References

- [OSWorld-Human §4.2](https://arxiv.org/html/2506.16042v1#S4.SS2)：同一观察下确定的动作可分组，不代表本项目已有提速数据。 / Group actions determined by one observation, not a measured speedup for this project.
- [Playwright actionability](https://playwright.dev/docs/actionability)：借鉴条件等待，不照搬 DOM，也不把可操作性当任务成功。 / Borrow condition waiting, not DOM dependencies or success claims.
- [Agent-X](https://arxiv.org/abs/2605.10380)：模型内部优化后置，论文倍率不直接套用。 / Defer inference optimization; published multipliers do not transfer automatically.
