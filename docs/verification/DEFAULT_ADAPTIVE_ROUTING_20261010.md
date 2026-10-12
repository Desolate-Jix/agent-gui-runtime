# Default adaptive routing / 默认主动审核路由

2026-10-10，用户明确流程图是核心默认逻辑，同时保留无 Decision API 的使用路径。此记录仅覆盖当前源码与离线验证，未操作桌面、读取真实 Key、请求付费 API、重打候选或发布。 / The user made adaptive orchestration the default while retaining operation without Decision. This checkpoint is source/offline only: no desktop, real key, paid call, new candidate or release.

## Changed / 变更

- `configs/decision-profile.example.json` 与 `decision-profile.adaptive.example.json` 均采用 `decision_profile.v2`、`auto`、`proactive_review=true`、`review_policy=adaptive`。原 v1 样例逐字保留为 `decision-profile.legacy.example.json`，供已发布 preview.3 使用。 / Both new examples select adaptive auto; the exact old example remains available for published preview.3.
- `app/judgment/profile.py` 对明确 v2 且省略 mode 的新配置采用 auto。明确 shadow/off/always_main、v1 配置和原冻结快照保持原策略；文件仍须声明协议版本，内部无版本构造保留 v1 兼容。条件/模板批准、学习草稿审核和输入门禁不改变。 / Explicit v2 files default to auto when mode is omitted; legacy and explicit policies retain their meaning. Approval and input contracts are unchanged.
- 当前 MCP 工具说明及主调用样例推荐 `task_plan.v2`；单步默认继承宿主 adaptive，仅显式 always_main 可收紧。学习入口继续使用已有 learned 策略，不另建执行器。 / New caller guidance recommends v2 and inherited adaptive review; learning keeps the existing runner.
- 无配置或明确 off：完整本地证明继续，其余保留原 wait 交 Main；Key 存在本身不启用服务。缺 Key、API 故障、预算耗尽保留明确诊断和审核，不自动成功或重放。 / Missing/off profiles retain local verification and original-Main review. Credentials alone do not enable Decision; failures remain explicit waits.

## Verification / 验证

- 新增真实配置加载/冻结、正式 TaskPlanRuntime/队列/回执、正式 DecisionService/provider 的离线联调；只有 HTTP 与桌面边界使用合成数据及 MockTransport。覆盖成功自动排下步、成功但需 Main、原票据审核续接、无配置/off、本地证明、缺 Key、未批准条件、明确旧策略。 / Tests use maintained configuration, runner, queue and provider code with mocked external boundaries.
- 最初 **6 failed / 9 passed**，其中一项是测试错误地把“缺 Key 的持久尝试计数”当成零；核对现有账本合同后改验“不发 HTTP、状态读取不增加计数、原输入不重发”。纠正后 **5 failed / 10 passed**，准确暴露旧样例/v2 默认 shadow。保留两个 RED XML。 / The first RED includes one incorrect test assumption; the corrected RED isolates default-routing failures without changing the ledger contract.
- 修复后新增组 **15 passed / 3.02s**；Main 16 文件相关组合 **751 passed / 68.14s**，exit 0，无跳过或失败。不累加重叠组，也不替代历史 1319/1 冻结或实机收益证据。 / Focused and integrated runs passed; overlapping counts are not summed or transferred to another freeze.
- 最终统一 MCP server 总说明后，实际 `list_tools()` 回读两个入口的新默认说明及三份配置加载通过；MCP 相关复测 **99 passed / 4.65s**，不与组合相加。见 [effective defaults](../../.superpowers/sdd/2026-10-10-default-adaptive/effective-defaults.json) 和 [MCP XML](../../.superpowers/sdd/2026-10-10-default-adaptive/mcp-final.xml)。 / Effective tool discovery/profile loading and the affected MCP rerun passed after the final metadata change.
- 完整组合命令：`D:/agent-gui-runtime/.venv/Scripts/python.exe -B -X utf8 -m pytest -q tests/test_decision_default_routing.py tests/test_decision_configuration.py tests/test_decision_service.py tests/test_adaptive_decision_policy.py tests/test_decision_template_service.py tests/test_execution_decision_check.py tests/test_execution_adaptive_review.py tests/test_task_plan_adaptive_review.py tests/test_task_plan_native_semantic.py tests/test_task_plan_condition_templates.py tests/test_workflow_decision_adaptive.py tests/test_workflow_decision_verification.py tests/test_workflow_decision_recovery.py tests/test_workflow_condition_templates.py tests/test_decision_status_snapshot.py tests/test_instant_mcp.py --junitxml=.superpowers/sdd/2026-10-10-default-adaptive/integrated.xml`。
- 证据 / Evidence: [corrected RED](../../.superpowers/sdd/2026-10-10-default-adaptive/red-corrected.xml), [GREEN](../../.superpowers/sdd/2026-10-10-default-adaptive/green.xml), [integrated XML](../../.superpowers/sdd/2026-10-10-default-adaptive/integrated.xml)。首轮 RED 和限定改动前原件位于同目录。 / The same directory retains the initial RED and scoped before-images.

## Remaining / 剩余

Candidate02 与既有安装包保持原载荷，本次默认配置解析及调用说明更改尚未进入冻结交付候选。后续集中冻结时验证新默认入口；未变更功能可复用已有证据。真实主动审核复杂连续流程、同口径准确性/介入/耗时对照和最终同候选独立验收仍待；12/12 付费额度已耗尽，本轮新增 0。 / Candidate02 and installed payloads are unchanged. Validate new defaults on the next consolidated freeze; real continuous adaptive acceptance, benefits and final independent acceptance remain open, with no new paid allowance consumed.
