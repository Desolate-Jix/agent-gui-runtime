# Execution plans without a fixed step count / 执行计划取消固定步数上限

Introduced in execution 0.1.4. The original 0.1.3 installer retains its historical limits; this report preserves the earlier offline evidence and adds the public-client repair and fresh desktop verification. / 执行版 0.1.4 引入本改动。原 0.1.3 安装器保留其历史限制；本文保留早期离线证据，并补充公共客户端修复及全新实机验证。

The user requested removing the initial eight-step batch restriction. Source now requires a nonempty linear plan and validates every declared step without imposing a fixed count. The shared runner no longer rejects caller plans at 256 consumed steps; when its 257-transition scheduling slice is used, it yields and resumes the same run on the next tick instead of reporting failure. The Decision remaining-plan context has no item-count cap; its 64 KiB encoded-byte limit and per-item validation remain. / 用户要求取消首版八步批次限制。当前源码要求非空线性计划并逐步校验，不再限制固定步数。共用运行器不再在调用方计划完成 256 步后拒绝继续；257 次调度批次用尽后让出执行权，由下一次 tick 续跑原 run，不再报失败。Decision 剩余计划摘要不再限制条目数量，仍保留编码后 64 KiB 大小限制与逐项校验。

Duplicate step IDs, invalid actions, stale or mismatched evidence, cancellation, unknown/partial input, host API budgets and per-step timing gates retain their existing semantics. The learned-program backend retains its original loop guard; removing the caller-plan cap does not expand learned-program authority. An accepted long plan is not proof of desktop completion, model accuracy or unlimited resource use. / 重复步骤 ID、非法动作、过期或错配证据、取消、未知／部分输入、宿主 API 预算和单步时间门禁均保持原规则。已学习程序后端保留原循环保护，调用方计划放宽不扩大其权限。长计划准入不等于实机完成、模型准确或资源无限。

## Verification / 验证

- Before the fix, new regressions produced 10 failures and one pass: 9/258-step plans, a 258-item context, the real queue path and the caller runner all exposed the old bounds. / 修复前新增回归为 10 失败、1 通过，分别复现 9／258 步准入、258 项摘要、真实队列与调用方运行器的旧限制。
- After the fix, six focused files passed **185 checks in 11.90 seconds**. These include all three plan schema versions at 9 and 258 steps, a 260-step synthetic runner spanning scheduling ticks, a 12-step real persisted queue using synthetic receipts, and a ninth-step failure that prevents later dispatch. The reviewed-program guard, summary-size budget and allowed-state validation remain covered. / 修复后六个相关测试文件 **185 项检查通过，耗时 11.90 秒**，覆盖三个协议版本的 9／258 步、跨 tick 的 260 步合成调度、使用合成回执的 12 步真实持久队列，以及第 9 步失败后阻止后续派发。已学习程序保护、摘要大小预算和允许状态校验继续覆盖。

Command / 命令：

```text
python -B -m pytest tests/test_task_plan_unbounded.py tests/test_task_plan_contract.py tests/test_task_plan_review_context.py tests/test_adaptive_decision_policy.py tests/test_workflow_runner.py tests/test_task_plan_runner.py -q --tb=short
```

These are offline tests: no desktop input, real model calls, installer build or installed acceptance. They do not establish a new real-world speed result. Historical installed-operation timings are reported separately. / 本轮为离线测试，没有桌面输入、真实模型请求、安装包构建或安装态验收，不构成新的实机速度结果。历史安装版操作用时另行统计。

## Long-plan validation cost / 长计划校验开销

Independent review found that each persisted history row reloaded and revalidated the complete source through `_bound_command`; each v2/v3 validation regenerated all remaining-step summaries. The repair reuses the source already authenticated in the current load, and caches only a successful schema-validation content digest. Every subsequent source read still parses the file, computes the actual canonical plan digest, and authenticates all source/state/target/completion/condition bindings. Changed content cannot hit the old validation digest. No source or state object is cached. / 独立审查发现，每条持久历史都会经 `_bound_command` 重新读取并全文校验来源，而每次 v2／v3 校验又会生成所有剩余步骤摘要。修复后复用本次读取中已经认证的来源，并只缓存结构校验成功的内容摘要；后续仍每次重新解析文件、计算实际计划的 canonical 摘要，核对所有来源／状态／目标／完成条件绑定。内容改变不能命中旧摘要，不缓存来源或状态对象。

The added regression failed before the fix, then passed with content/target/empty-plan tampering still rejected. A separate six-file integration group covering MCP, admission, adaptive review, queued cancellation, goal completion and caller controls passed **197 checks in 18.67 seconds** after the final backend change. Together with the core group this is **382 distinct checks across 12 selected files**, not a full-suite result. / 新回归在修复前先失败，修复后通过，且实际篡改计划、目标或改为空计划仍会被拒绝。最终后端修改后，另六个文件覆盖 MCP、准入、主动审核、队列取消、最终目标与调用方控制，**197 项检查通过，耗时 18.67 秒**；与核心组共 **12 个选定文件、382 项不重复检查**，不冒充全量测试。

Using the exact same local script with real TaskPlanRuntime/TaskPlanBackend and synthetic receipts in new temporary sessions: / 使用完全相同的本地脚本、真实 TaskPlanRuntime／TaskPlanBackend、合成回执及新临时会话：

| Steps / 步数 | Before flow / 修复前流程 | After flow / 修复后流程 | Full schema validations before → after / 全文结构校验次数 |
| --- | ---: | ---: | ---: |
| 10 | 2.843108 s | 0.949263 s | 1,911 → 3 |
| 20 | 15.344259 s | 1.717956 s | 6,611 → 3 |

These are one local before/after sample per size, including offline scheduling and filesystem work, not real GUI/model latency or a general speed guarantee. The completed 20-step status read changed from 21 full validations to zero, while still rereading and authenticating the source. Review confirmed the original repeated-validation defect is closed. / 每种长度只有本机前后各一次样本，包含离线调度和文件处理，不代表真实 GUI／模型延迟或通用速度保证。20 步完成后的状态读取从 21 次全文结构校验降为 0 次，仍重新读取并认证来源。独立复核确认原重复校验缺陷已闭合。

Historical GUI operation breakdown: [installed timings](EXECUTION_OPERATION_TIMINGS_20261015.md). / 历史真实 GUI 的各操作耗时见该独立报告。
## Public client completion and fresh desktop evidence / 公共客户端结算与全新实机证据

The first real ten-step 7-Zip run completed in the backend, but the public client still rejected completed plans above eight steps and reported an unknown result. This first failure is retained; it is not an end-to-end pass. The repair removes only that upper bound from `LearningBenchmarkClient._plan_snapshot`, while preserving positive-integer, history-size, all-success and original-binding checks. / 首次真实十步 7-Zip 任务已在后端完成，但公共客户端仍拒绝八步以上的完成回执，报告结果未知。原失败保留，不算端到端通过。修复仅移除 `LearningBenchmarkClient._plan_snapshot` 的固定上限，正整数、历史数量、全部成功及原绑定校验保留。

`tests/test_execution_client_unbounded_plan.py` exercises the actual ExecutionClient polling path with a fake MCP boundary: 9/10/258-step completion failed before the repair, while 18 malformed/binding cases were already rejected. All 21 pass after repair; five related modules pass 140 checks. These overlap the earlier groups and must not be added to 382 as a distinct total. / 新回归使用真实 ExecutionClient 轮询路径和模拟 MCP 边界：修复前 9／10／258 步完成三项失败，18 项畸形或错绑拒绝已通过；修复后 21 项全过，相关五模块 140 项通过。它们与早期组存在重叠，不得与 382 相加冒充不重复总数。

With the repaired frozen source and new test data, a different 12-step 7-Zip folder/archive navigation task completed automatically in 131.8980933 s. A four-step continuation in the same window completed in 46.3820546 s. All 16 results passed without Main intervention; the owned window and host closed normally. The sequence used 32 Decision and 16 grounding calls, no ordinary review, and 126,868 API tokens. This is navigation inside a fixture ZIP, not compression or extraction. / 修复后的冻结源码使用全新数据，以不同的十二步 7-Zip 目录／压缩包导航任务自动完成，耗时 131.8980933 秒；同窗口四步续用 46.3820546 秒。16 个结果均无 Main 接管通过，本轮窗口及宿主正常关闭。共 32 次 Decision、16 次定位，无普通复核，126,868 API tokens。这是预制 ZIP 内导航，不是压缩或解压。

These source runs do not by themselves prove installed or independent acceptance. Exact versions, first failures, timings and release-boundary status are kept in the [multi-application report](MULTI_APP_EXECUTION_20261015.md). / 源码实测本身不证明安装态或独立验收；确切版本、首次失败、耗时及交付状态见[多应用报告](MULTI_APP_EXECUTION_20261015.md)。
