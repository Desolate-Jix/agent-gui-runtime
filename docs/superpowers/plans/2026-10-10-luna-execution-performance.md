# Luna API 执行提速实施计划 / Luna API execution performance plan

> **For agentic workers:** Use superpowers:executing-plans for the assigned bounded slice. Reuse the existing Sol ultra sessions; no nested workers. Offline tests completed; the current active goal subsequently authorized low-risk live desktop/API tests. No high-risk actions, publication or installation is authorized by that testing scope.

**Goal:** 普通执行直接使用 `gpt-6-luna` 外部视觉 API，落实已审核的提速项，保留控件扫描与既有输入/审核边界。 / Use direct Luna API grounding and implement the approved performance audit while retaining controls and input/review boundaries.

**Architecture:** 复用 `external_api`、同一宿主/客户端、`input_sequence`、`task_plan` 和 Decision 自动结算。控件按同一新鲜快照批量读取；保留本地模型显式可选路径。 / Reuse the maintained providers, host, grouped input, plan continuation and Decision adoption, with fresh bulk control snapshots and an explicit optional local route.

**Tech Stack:** Python, existing MCP/JSONL client, httpx, Windows UIA, existing pytest contract tests.

**Spec:** [全流程审计](../../verification/EXECUTION_FLOW_PERFORMANCE_AUDIT_20261010.md)及用户最新要求“直接用luna的api识图…优化刚刚提到的，测试向我要申请”。 / Approved audit plus the user's latest direction.

## 约束 / Constraints

- 开发后用户批准离线测试及修复复测；当前active goal进一步批准低风险桌面与真实API测试，复用维护宿主，不改用户凭据。安装及发布另属交付范围。 / The current active goal additionally authorizes low-risk desktop/API checks through the maintained host. Preserve credentials; installation and publication remain separate delivery work.
- 使用现有工作树，保留既有修改。代码注释中文UTF-8，不提交、不删除无关文件。 / Preserve existing work; Chinese UTF-8 comments; no commit or unrelated deletion.
- API定位使用普通Chat Completions，Decision继续判断明确条件，不互相冒充；不把付费API设成所有用户无条件默认。提供明确的Luna配置入口，本次选定路线为API；无密钥明确报错，不静默启动本地模型。 / Distinguish grounding and Decisions; explicit Luna selection without silently imposing paid defaults or local fallback.
- 每次真实输入仍核对窗口、目标、新鲜度；同帧复用不跨输入或模型等待。 / Preserve current-window/target/freshness checks; no stale cross-action reuse.

## 工作划分 / Tasks

1. **视觉路线 / Vision route** — `app/vision/external_grounding_api.py`, `app/api/vision.py`, associated profiles/tests: keep one API client, bounded total request/response processing, original evidence binding; honor explicit input resize and coordinate transforms, including the local optional direct branch. Add regression cases without running them.
2. **输入与固定入口 / Input and caller** — `app/core/input_controller.py`, `scripts/execution_client.py`, `scripts/learning_benchmark_client.py`, component packaging and focused tests: close `pre_input_validator` before actual mouse-down, add an explicit Luna API entry preset, include caller in delivery, retain compact normal output and same-session plan progression. MCP server configuration stays MCP.
3. **批量控件采集 / Bulk controls** — `app/operation/screen_reading/uia_provider.py`, new cache helper and focused tests: integrate native property acquisition with current traversal semantics, rich_text/pattern/graph/popup behavior and freshness. Do not hide COM failures or silently use stale snapshots. Reuse the strict benchmark prototype as reference.
4. **结果链与重复工作 / Verification chain** — `app/judgment/evidence.py`, `service.py`, bounded observation/runtime integration: avoid building upload Base64 during result-only authentication; use existing condition-based early completion where an authoritative condition exists, preserving bounded observation and no input replay. Preserve error evidence and final adoption checks.
5. **集成和文档 / Integration and documentation** — Main statically reviews diffs and updates affected README/developer/state docs, lists exact pending checks and requests approval. After approval, first run offline contracts; only then request/run a bounded fresh real workflow and paid call budget as authorized.

## 重点审查 / Review focus

- API缺密钥、限流、畸形输出和超时不得触发本地服务或重复收费调用。 / Missing keys, rate limits, malformed output and timeouts must not trigger local fallback or duplicate requests.
- 缩放后的bbox/point必须回到原图，缺失/歧义拒绝输入。 / Resized points and boxes must return to original pixels; absent/ambiguous results reject input.
- 缓存不改变ControlView、rich_text、pattern、可见性和节点关系，不跨观察复用。 / Cache preserves control/text/pattern/graph semantics within one observation.
- validator在鼠标按下前执行；失败不得落下输入。 / Validator failure before mouse-down prevents input.
- 自动继续不越过真实review wait；条件未知不会被等待超时变成成功。 / Automatic continuation preserves review waits and never converts timeout/unknown to success.

## 状态 / Status

- [x] 审计和本轮实施范围已明确 / Audit and requested scope established.
- [x] 实现并静态审阅各分片 / Implement and statically review slices.
- [x] 同步文档并提出具体测试申请；见[源码检查点](../../verification/LUNA_EXECUTION_SOURCE_20261010.md) / Synchronize docs and prepare concrete test approval; see source checkpoint.
- [x] 获批准后完成离线验证，保留组件旧断言首败及复测；[577项组合记录](../../verification/LUNA_EXECUTION_OFFLINE_20261010.md) / Complete authorized offline verification, retaining the obsolete component assertion failure and rerun.
- [x] 按后续复审修复图片交付、普通调用总预算及非200状态保留；最终[647项组合通过](../../verification/LUNA_EXECUTION_FIXES_20261010.md)，SDK取消清理上限另行记录 / Repair the three subsequent findings, verify 647 tests and document SDK cancellation-cleanup limits.
- [ ] 另行申请并完成真实API、Windows控件语义和连续桌面用时/准确率验收 / Obtain approval for real API, Windows provider semantics and continuous desktop accuracy/latency acceptance.

## 2026-10-11 授权与当前验证 / Current authorization and verification

后续active goal已明确批准低风险桌面与真实API测试；上面的另行申请条款是历史阶段记录。源码实机现已完成两轮Google→Bilibili五步闭环（各含一次Main审核）、自动加载观察、Python文档目标缺失拒绝及显式恢复。继续按同一模型/profile/窗口比较2000ms与500ms采图宽限，分别记录实际端到端耗时、付费调用、Main等待与首次失败；不降低结果阈值。公开图片入口新发现agent_command嵌套终态图解析遗漏，先修复回归，再冻结同会话ABBA对比。 / The later active goal authorizes scoped low-risk desktop and real API tests. The earlier approval requirement is historical. Two full requested flows, automatic loading, and documentation refusal/replanning are verified. Next repair the newly exposed nested terminal-image delivery defect, then compare 2000ms and 500ms grace in a frozen same-session ABBA trial without changing result thresholds. Record end-to-end time, paid calls, Main waits and first failures separately.


## 2026-10-11 最终源码验证检查点 / Final source verification checkpoint

本轮保留原图解析、纯证据依赖拆分和预算测试fixture修复，相关Main回归197+114通过；6行provider提示因12次预注册诊断中的正例退化已撤回。调用方显式Searching/Search finished条件经2次shadow区分后，在最终文档实机成功observe→continue。 / Retain image/evidence repairs and the fixture fix, with311 focused passes; reject the regressing provider prompt. Explicit visible loading/completion conditions passed two advisory probes and the final live recovery.

同一冻结会话完成视频5步（4 Decision+1 Main）和文档4步（全Decision、26.196秒），正常清理且10项源哈希一致。视频42.467秒返回需审核、254.416秒才闭合；播放时间性判断与Main接管仍是待优化项。默认等待未改；完整ABBA、独立冻结候选实机及安装交付未完成。详见[证据与计时范围](../../verification/LUNA_RENDER_GRACE_20261011.md)。 / Both real tasks and cleanup completed, with unchanged frozen source. Video takeover remains costly; controlled comparison and installed acceptance remain separate pending milestones.
