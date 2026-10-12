# Adaptive Decision review implementation plan / 主动审核实施计划

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` with the project's proportional implementation loop. Tasks use checkboxes and evidence below. No automatic commit, publication, dependency installation or desktop input from workers.

**Goal:** Validate accurate continuous execution, selective Main review and optional workflow reuse, with measured reductions in ordinary Main involvement and task time. / 验收准确的连续执行、按需主 Agent 审核与可选工作流复用，实测降低常规介入和整任务耗时。

**Architecture:** Version the shared Decision policy and derive outcome before routing. Preserve original receipts, review/continue waits and exclusive input ownership; use immutable successor plans after terminal cancellation. / 判断与路由分离，复用原票据和运行器，后续计划不改旧历史。

**Tech Stack:** Python, Pydantic, SQLite/DPAPI, httpx, existing Qt workbench and pytest. No new dependencies. / 沿用已有依赖。

**Spec:** `docs/superpowers/specs/2026-10-09-adaptive-decision-review-design.md` (user approved 2026-10-09).


## 2026-10-10 当前发布主线（审查后调整） / Current release plan after scope review

本节是当前执行顺序；下方历史“下一步／待批准／待测”不再驱动工作。按用户最新要求，已完成默认主动审核及无 API 备选的限定源码调整与离线验证，751 项通过；未恢复整批桌面验收、付费调用、构建或发布。已有同范围测试及修复复测批准保留，不重复申请。 / This section controls current work. The latest user instruction authorized the bounded default-routing source/offline slice, now verified by 751 tests; the broader desktop/paid/build/release batch has not restarted. Existing same-scope approval remains effective.

**新默认 / New default:** v2/auto/proactive/adaptive，API 可选；无配置/off 使用本地核验和原 Main。旧配置/冻结会话保留。此改动在 Candidate02 之后，Candidate02 只作为既有功能证据；下一次集中冻结需包含默认入口变化，再做相关最终验收。详见[源码证据](../../verification/DEFAULT_ADAPTIVE_ROUTING_20261010.md)。 / New defaults follow the diagram with an optional API, retaining explicit/legacy policies. Candidate02 predates this slice; the next consolidated freeze must cover the changed entry defaults.

**目标 / Goal:** 常规稳定步骤由 Runtime 连续执行；Decision 同次判断结果与是否需要 Main，异常交回已有 Main 会话，审核后精确续接或只重规划剩余步骤。学习是独立可选组件，生成可审核、可修改、可变参复用的工作流。以准确性、真实 Main 介入和整任务耗时验收，不以测试数量或 API 参与次数验收。 / Runtime executes ordinary stable steps; Decision assesses outcome and intervention together, returning exceptions to the existing Main for exact continuation or suffix-only replanning. Optional learning produces reviewable, editable, parameterized workflows. Acceptance concerns accuracy, actual Main involvement and task time.

### 已有证据与边界 / Existing evidence and limits

| 已完成 / Complete | 证据及不能推导的结论 / Evidence and limit |
| --- | --- |
| 主动审核、取消/恢复、有限观察、模板配置和执行/学习/UI 接线的源码联调 / Integrated source | [Main 冻结组合](../../verification/CONDITION_TEMPLATES_SOURCE_20261010.md)：1319 passed / 1 skipped，1059 个源码/翻译文件一致。不是实机或收益验收。 / Offline only, not live or benefit acceptance. |
| Candidate02 已冻结并有两场 7-Zip 实机记录 / Frozen candidate and bounded live runs | [实机记录](../../../.superpowers/sdd/2026-10-09-adaptive-live/CANDIDATE02_MAIN_LIVE.md)：单项及同窗连续操作、原 wait 审核/续接、manual observe A/B/重放、已知输入后取消和清理；Decision off，API 0。A/B 像素相同，不证明动态加载或主动审核收益。 / Off-mode evidence does not prove adaptive benefits or changing-screen loading. |
| 原真实事件学习审核、双参数草稿保存和跨连接重开 / Offline learning persistence | [学习记录](../../../.superpowers/sdd/2026-10-09-adaptive-live/CANDIDATE02_LEARNING_OFFLINE.md)：三步、两项图像规则、两个程序修订保留；全部步骤仍 pending，变参实机复用及本库 EXE 编辑重开未验收。 / Pending draft, not a live-reuse pass. |
| 较早真实对照 / Earlier comparison | [对照记录](../../verification/ADAPTIVE_REVIEW_LIVE_20261009.md)：Main 审核 3 对 3，没有减少；后续源码修复尚无同口径新对照。 / No measured reduction; later source benefits remain unknown. |

### 剩余顺序及完成条件 / Remaining sequence and completion checks

1. **P0：真实执行闭环，复用 Candidate02 / Real execution closure on Candidate02.** 在既有获批范围内补齐真实外部浏览器公开文档检索、详情、返回与动态内容，以及 7-Zip 弹窗、中断恢复。覆盖普通自动继续、成功但需 Main、失败/冲突/未知转 Main、原 wait 续接、旧运行终止后仅启动剩余计划；不得新建主会话或重复已完成输入。先完成无需新增付费的部分；当前候选的付费 Decision、真实 loading 正例单列待证，不能用 off 或模拟结果替代。 / Cover ordinary continuation, successful-result escalation, failure/uncertainty, original-wait resume and suffix-only replanning in actual applications. Complete unpaid coverage first; real Decision/loading remain separate open items.
2. **P0：可选学习最小可用闭环 / Optional learning usability.** 使用本轮新采集库，从工作台普通入口审核 pending 草稿、修改规则/参数、保存并关闭重开，再换本轮临时数据复用；固定步骤与动态输入分离，完整本地图像证明零 API，变化或歧义按策略交 Main。没有固定目标规则时先走现有正式 grounding 路径，保留动态读取的 Agent 审核，不宣称全部脱离模型。源码入口为 `app/learning_memory/workflow_trial.py`、`workflow_execution_strategy.py`；`target_memory` 是可选项。 / Validate review/edit/reopen and changed inputs through the maintained path; optional target recipes are not a prerequisite. Explicit Agent-assisted reads stay visible.
3. **P1：同口径准确性与收益对照 / Matched accuracy and benefit evaluation.** 按 spec §12 比较 A 已发布 preview.3、B 当前 adaptive、C 同候选 always_main；任务、模型/截图配置和结果判据一致，交替次序，普通/变化/异常分开。记录首次整任务完成率、错误自动放行、漏交、不必要接管、真实 Main 次数、Decision 调用/token，以及整任务时间；冷/热启动分开，给出样本量、median/p95 和原始失败。采集/本地验证/API/Main 耗时单列，嵌套时间不重复相加，脚本回调不冒充真实 Main 推理。额度不足时明确“对照未完成”，不降级发布门槛。 / Use matched tasks/configuration and independent outcome criteria, reporting actual accuracy, involvement, usage and latency; insufficient budget means incomplete evidence.
4. **P1：同候选独立验收与交付 / Same-candidate acceptance and delivery.** Main 完成相关单项、连续流程及清理并修复复测后，复用 Sol ultra 独立验收同一冻结候选。Candidate01 的安装/UI 记录保留其原范围，不转计 Candidate02。主链通过后再集中完成最终双组件独立安装、兼容/升级、语言切换、卸载保留用户数据与依赖检查，并同步 README/发布说明；不因观察器或文档改动反复打包，不自动提交或发布。 / Independent acceptance follows Main on the same payload; final delivery checks and documentation follow mainline closure, without ritual builds or automatic publication.

**本版门槛 / Release gate:** 确定性合同通过；冻结标注集无已知错误放行、漏交及取消/所有权回归；相对基线首次完成率不下降，常规 Main 介入和整任务耗时实测下降。若收益不成立，基于失败证据调整条件或路由并定向复测，不能靠增加模型调用或放宽门禁称为完成。有限样本无错误不代表所有实际任务必然成功。 / Preserve the approved accuracy and measured-benefit gate; fix evidenced routing defects rather than adding calls or weakening controls. Finite samples are not universal guarantees.

P0 还须保留已批准 P2 的有效原生不匹配接续、模板/条件/策略与预算显示、有限 loading、旧版本及固定引用兼容。API 异常和限额耗尽必须形成真实、可恢复的等待，不能冒充成功；以已有合同证据加必要集成检查验证，不为制造故障额外花费。 / P0 retains approved P2 functionality and compatibility. Provider errors and exhausted budgets must produce truthful recoverable waits, verified through existing contracts and necessary integration without unnecessary paid fault injection.

**P2 后置 / Deferred:** 无名、同 ID 重叠控件的固定目标提案增强单独保留，不再作为重冻候选或发布的前置条件；它限制固定定位提案，不等于所有学习复用失败。仅当普通维护路径实测暴露阻断主线的错误，才按公共合同定位、最小修复、窄回归及相关实机复测处理。其余泛化学习能力、新 UI 扩展和领英运营本轮不扩展。 / Defer unnamed-control recipe support and unrelated expansion; promote only an observed mainline blocker, with a shared-contract repair and targeted checks.

**当前资源边界 / Resource boundary:** 付费额度 12/12 已用完（43,665 input / 0 output tokens）；追加最多 4 次的询问尚未获答复，不调用新付费请求，也不把可能的 4 次当成充分统计样本。保留已有候选、原失败和回执；无需重做已有效覆盖的项目，仅补缺口及受源码修复影响的回归。 / Paid allowance is exhausted and the pending extension is not authorization or sufficient statistical evidence. Preserve existing evidence and rerun only gaps or affected paths.

## Global constraints / 全局约束

**历史授权记录（本批已获批准） / Historical authorization record; batch approved:** 用户已明确批准本批测试。Main 正在运行已列明的 7 文件离线回归，随后进行 Edge Python 文档的 asyncio/pathlib 搜索、详情、返回、同会话连续操作和维护清理；同范围修复与复测已批准，无需重复申请。本次同步尚未收到 Main 结果，不新增通过结论。 / The user explicitly approved this batch on 2026-10-10. Main is running the specified seven-file offline regression, followed by Edge searches for asyncio/pathlib in Python documentation, detail/back navigation, continuous operations in the same session and maintained cleanup. Repairs and reruns within that scope are approved without another request. Results have not been received for this update; no new pass claim is recorded.

**历史授权限制（已被上述批次批准替代） / Historical approval restriction, superseded for this batch:** 此前“继续代码开发，测试向我要申请”及“待测试批准”是当时状态，保留为历史；不再阻拦已批准的本批测试和同范围修复复测。下方此前运行结果仍为历史证据，不自动证明当前源码。 / Earlier source-only and approval-pending statements remain historical. They no longer block this approved batch or its repairs/reruns. Earlier run results remain historical evidence and do not automatically validate current source.

Current acceptance ledger: `.superpowers/sdd/2026-10-09-adaptive-live/PROGRESS.md`. Existing same-scope testing/repair approval remains effective; the current goal is paused. New paid allowance, unrelated scope and publication are separate. Historical results prove only their recorded candidates. / 本批同范围测试和修复复测批准有效，当前目标暂停；新增付费、无关范围和发布另论，历史结果只证明原候选。

- Worktree `C:/Users/DesolateJix/.codex/worktrees/decision-api/agent-gui-runtime`, branch `codex/dev-decision-api`, baseline `5689d337`.
- Preserve v1 behavior, exact original evidence and frozen policy; new features require explicit v2 configuration. English default, Chinese selectable. / 保留兼容、证据、冻结策略和双语。
- No native Codex Computer Use. Main serializes desktop acceptance through maintained interfaces; workers perform assigned offline work before same-candidate independent acceptance. / 禁止原生 Computer Use；Main 用维护接口串行验收，独立实机验收在 Main 通过之后。
- No network inference from workers, no keys, no input replay, no parallel input owner, no automatic package/release/version bump. / 不读凭据、不擅自付费、不重放、不自动发布。
- The earlier clean interpreter no longer exists. Current tests use `D:/agent-gui-runtime/.venv/Scripts/python.exe`; missing MCP 2.1.1 and PySide6 6.11.2 were added, with before/after package manifests. `uv pip check` passed; the 196-case environment regression passed after installation completed. / 旧独立环境已不存在，本轮复用现有模型环境补齐缺依赖，记录安装前后清单和环境回归。
- Codegraph index was unavailable in this worktree during design; scoped source search is used. / 当前定向读取源码。

## Review focus / 复核重点

1. A successful outcome with high review probability must pause before suffix input. / 成功也能主动接管。
2. Disabled predicates differ from missing requested answers; conflict detection precedes disposition. / 未请求不等于缺失。
3. Cancel/late results, stale reviews and repeated successor requests cannot create input. / 取消、过期和重复请求不生成新输入。
4. Learning's complete local image success stays zero-call in adaptive mode. Explicit always_main pauses even on local success without a paid check; policy edits require a new reviewed revision. / adaptive 本地快速路径保留；显式逐步审核零调用暂停，编辑产生待审修订。
5. Provider failure, shadow/off configuration and exhausted budget produce truthful waits, not false success. / 异常和关闭状态不冒充成功。

## Task 1 — Shared v2 Decision policy / 共用判断协议

Files: `app/judgment/{profile,service,evidence,openai_decisions}.py`, narrowly scoped helper(s), `tests/test_decision_service.py`, `tests/test_openai_decisions.py`, new adaptive-policy tests.

Interfaces: extend `DecisionService.evaluate` and `validate_result` with optional `review_context` (frozen task/step/suffix context). Preserve omitted v1 semantics. V2 results include `disposition`, `review_scope`, `reason_codes`, `enabled_predicates`; `adopted` is false for proactive Main review. Consumer code must gate on authenticated result plus disposition, not verdict alone.

- [x] Implement and verify success+review, conflicting answers, disabled/missing predicates, always_main/off/shadow, replay and authentication. / 已实现并通过离线回归。
- [x] Implement and verify the v2 profile and strict three-predicate core provider with outcome-before-routing; Task 5 adds the optional loading predicate in the same request. / 核心三谓词已验证，Task 5 在同一请求内增加可选加载谓词。
- [x] Preserve v1 digest/saved-result compatibility and add readonly budget reporting; verify both offline. / 兼容路径及只读预算报告已离线验证。
- [x] Run provider/service/configuration regressions: the initial 198-case group was included in the core 649-case milestone; current source is covered by Task 6. / 初期定向和核心组合通过；当前源码以 Task 6 为准。

## Task 2 — Plan handoff and successors / 执行计划交接

Files: `app/execution/task_plan_{contract,verification,backend,admission}.py`, narrow review/successor helper(s), `scripts/learning_benchmark_client.py`, plan tests.

Interfaces: v2 service context from Task 1; `review_packet.v1` bound to original wait/execution/receipt/evidence and immutable source. `successor_request_id` links a new plan/run to terminal parent and a consumed lineage generation; repeated logical requests return the original successor.

- [x] Implement and verify proactive success stopping suffix, original review/continue, provider errors, stale packets and cancelled late replies. / 已实现并通过离线回归。
- [x] Implement and verify bound review-packet and existing-client handoff; retain original input facts and review identity. / 已实现并验证原输入事实和审核身份保留。
- [x] Verify successor logical/transport replay, parent state, conflicting plans, consumed generations and active-run preservation. / 后续计划相关离线回归已通过。
- [x] Write durable lineage admission using existing queues/ownership; reject unknown effects and identical completed-parent commands conservatively. / 源码已写，含保守重复命令限制。
- [x] Run plan contract/runner/verification/client regressions: original 1 failure/202 passes; fixed cached receipt ID; 204 passes, then included in final combination. / 首败保留，修复及组合通过。
- [x] Repair ordinary final Decision/Agent cancellation during backend validation; retain original input/ticket, normal cancellation settlement and read-only settled replay. Worker RED2 failed/2 passed→12 passed; Main's current source integration below covers the repair. / 普通最终取消竞态已修复，保留原事实、正常取消结算与已结算幂等读回，首次失败和Main联调分开记录。

## Task 3 — Learning adoption and editor / 学习核验与编辑

Files: `app/learning_memory/{decision_verification,runtime_verification,workflow_verification,workflow_program,workflow_rules_editor}.py`, corresponding offscreen/recovery tests and existing translation files if needed.

Interfaces: consume authenticated v2 disposition from Task 1 and pass relevant immutable program/step context. Ordinary image success skips Decision. Add condition and Main-review policy editing using existing immutable revisions and review invalidation.

- [x] Verify success+review pauses, image success makes no call, unsupported outputs remain blocked, policy/condition edits require review, and context changes fail recovery. / 相关离线回归已通过。
- [x] Implement and verify eligibility/context/routing, condition editor and English/Chinese translations using existing patterns. / 已实现并通过双语离屏验证。
- [x] Generate both `.qm` files after approval: 1198 finished entries each, zero unfinished. / 双语翻译生成通过。
- [x] Run learning Decision/recovery and offscreen editor checks: 148 passed, included in final combination. / 148 项及最终组合通过。

## Task 4 — Main integration, public docs and diagram / 集成与文档

Files: `app/execution/decision_check.py`, `app/instant_mcp.py`, `app/core/decision_configuration.py` only where integration requires; configuration examples, README, `docs/development/DECISION_API.md`, `docs/development/TASK_PLAN.md`, local ignored state notes.

- [x] Implement and verify direct-step review-context/authentication integration; retain pre-action revalidation. / 已实现并通过离线回归，保留动作前复核。
- [x] Add the approved Mermaid diagram to README; distinguish verified source, unfinished slices and published preview.3. / 已同步图和当前阶段边界。
- [x] Make new profiles/caller guidance default to v2 auto/adaptive; retain the exact old profile as the legacy example and verify missing/off API plus explicit/frozen policy compatibility. Main's related 751-test combination passed; the default change is not yet packaged. / 新默认入口及无 API 路径已离线验证，旧样例/策略保留；默认值更改尚未打包。
- [x] Run core impacted contracts: Main 649 passed in 37.51 s; original client regression and fix retained. Task 6 records the later final source combination. / 核心阶段组合通过，首败保留；后续最终组合见 Task 6。

## Task 5 — Bounded observation and semantic continuation / 有界观察与语义接续

Requires Tasks 1–3 to pass. Introduce explicit append-only observation/assessment rounds and current packet/evidence revision checks; do not retrofit fresh screenshots into the old after-only receipt. Respect spec limits: max 2 extra observations, max 2 paid requests per step, proposed 12-second whole-verification budget, no repeated input. Native fallback requires distinguishing valid mismatch from bad evidence first.

- [x] Confirm maintained read-only observation entry and define its exact binding before implementation: `capture_memory_observation(recipe=None)` on the existing serial input owner, without focus/input or imported `image_path`. / 已确认原维护截图入口和同一 owner。
- [x] Write and run cancellation, deadline, evidence-revision, missing-output and no-replay tests; preserve RED and repaired results. / 负例已执行，首败保留。
- [x] Implement the automatic declared-loading slice through the shared runner/client and original input owner; its historical freeze passed Main's862-case/1-skip group. Later native continuation has separate current-source evidence below; the old result does not cover later repairs. / 自动加载切片保留旧862项时点证据，原生续接及后续修复另计当前源码，不转计历史。
- [x] Implement explicit v2 native semantic continuation with strict options, complete maintained-timeout qualification, original false recheck/receipt preservation, final-search binding, backend revalidation and zero-call local/always_main/off paths. Worker final204 passed including130 native cases; Main756-pass/1-skip current integration is recorded in Task6. / 原生显式接续与负例已实现并离线联调通过，保留首次失败；不代表新候选实机。
- [x] Implement durable manual read-only `observe`, original wait/owner/window, persistent claims, append-only v3 evidence, recovery/cancellation/shared limits and public replay images. Offline integration and Candidate02's bounded A/B/replay-A journey passed; images were identical, so changing-screen validation remains open. / 人工观察源码及 Candidate02 限定实机链通过，首败保留；A/B 同图，不算动态画面验收。
- [x] Finish versioned typed-template shared service/profile/execution/learning/UI wiring and frozen-source revalidation: Main 1319 passed / 1 skipped. Candidate02 is built; full live template/changed-input acceptance remains in the current release sequence. / 类型模板共享服务、profile、执行/学习/UI 接线及冻结源码联调已完成；实机变参等按当前主线补证，不再重复开发接线。

### Task 5 current slice contract / 本切片固定合同

- The prerequisite queued-cancel defect is fixed and separately verified: its first real-queue offline test failed, the corrected boundary set passed 8 cases, and the related combination passed 212. A queued cancel is observed without consuming it; normal host control still settles cancellation. This is not atomic interruption of OS input. / 前置取消首败、修复和回归均保留，原宿主负责正式结算取消。
- Explicit v2 `agent_judgment`, or explicitly opted-in `native_condition` with fully valid maintained-timeout evidence, enters the common semantic path with `decision_condition`; `wait_policy={loading_condition, completion_excludes_loading}` enables its existing bounded-observation slice. Native controls require the decision condition. V1 stays unchanged. `still_progressing` is requested only for declared after-action loading checks. / 共用分支现接收显式v2判断和合格原生超时；其他原生控制项不得脱离判断条件生效，追加观察仍须声明wait_policy，v1不变。
- `observe` means uncertain outcome and no adoption. Shadow mode only suggests observation. Danger, Main-review requests, invalid evidence and contradictory declared states take priority. Complete local success retains its existing zero-call path. / 观察不代表成功，不削弱审核与危险判定。
- Persist the first verification start and operation claims. The12-second scheduling/adoption budget includes initial Decision time. Owned HTTP now has a separate absolute monotonic network deadline; native COM, cold initialization and local persistence are not hard-real-time operations. Schedule at most two additional captures at0.5 and1.5 seconds after entering observation, skipping missed slots with at most one capture per tick on the existing runner. / 原运行器跨tick调度，逾期槽跳过；自有HTTP已有网络总截止，原生COM、冷初始化及落盘不声称硬实时。
- Each step permits the initial assessment and at most one paid assessment on different new evidence. At most 8 steps implies at most 16 such requests per run; the existing service-wide budget still applies. Identical pixels do not justify a paid retry. Repeated status/ticks cannot replay captures or requests; an unresolved persisted operation claim requires review. / 单步最多两次付费，重复读取与未决记录不触发重试。
- Freeze optional `assessment_context` with round 0–2, original receipt SHA, input evidence-set SHA, elapsed milliseconds and remaining timeout. Round 0 uses `[after]`; later assessment uses `[after, observation]` with separate paths/capture IDs and matching complete window birth identity. The helper validates original image size/window rectangle, cancellation and remaining budget before and after the owner call. / 新图独立保存，原 after 不替换；窗口与预算每次复核。
- Input evidence hashes exclude the assessment being generated. Separate artifact references and a final packet hash cover assessment and ledger records, avoiding a circular digest. Review uses the latest round/revision; the client polls during `observation_pending` and only invokes the existing Main callback when review is actually required. / 输入摘要与结果证据分开，旧轮次审核不可采纳。
- Automatic loading, strict native-timeout continuation, public manual observe and typed-template wiring are complete in source/offline integration. Manual observe requires completed original input with action_executed=True, excludes read_text=False, shares two automatic/manual attempts including failed/unknown captures and has a separate12-second adoption deadline without hard-interrupting synchronous capture. Original after/assessment round remain fixed; only the current packet can be reviewed, older authenticated images remain readable. Candidate02 has bounded manual-observe live evidence; full live acceptance and benefits remain open. / 自动加载、原生续接、人工观察及模板接线源码联调完成；手动只支持completed+true、排除read_textFalse，共享两次含失败/未知，独立12秒采用期限不硬中断同步截图。原after/轮次不改，仅最新包可审核、旧认证图可读；Candidate02 有限定人工观察实机证据，完整实机与收益仍待验收。

## Task 6 — Acceptance / 验收

- [x] Current source freeze: 1319 passed / 1 skipped, unchanged 1059 source/translation files; Candidate02 built from that freeze. / 当前源码冻结与内部候选构建完成。
- [x] Candidate02 bounded 7-Zip single/continuous/manual-observe/cancel/cleanup and offline learning persistence checkpoints; limits are listed in the opening evidence table. / 限定实机和离线学习保存重开完成，不转计为完整验收。
- [ ] Complete the remaining real execution and optional-learning journeys listed in the current P0 sequence, including actual adaptive routing evidence. / 完成当前 P0 缺口，含真实主动审核效果。
- [ ] Meet the approved matched accuracy/Main-involvement/latency gates, followed by same-candidate independent and final delivery validation. / 按当前 P1 完成对照、独立验收和交付验证。

### Earlier verification checkpoints / 较早验证记录

- [x] Main's manual+pure-template frozen integration:1008 passed/1 skipped out of1009, zero failures/errors; XML91.700s/stdout91.74s/wall92.968s;1048 Python-file hashes unchanged. Only the symlink-directory case skips for permission. Includes the96 pure-module cases, excludes subsequent template wiring; zero paid requests/desktop actions/packages. The review-found replay-image P2 retains RED1 failed/1 passed and repair86 passed; bounded re-review closed. [Result](../../../.superpowers/sdd/2026-10-09-adaptive-live/manual-source-integration/result.json), [XML](../../../.superpowers/sdd/2026-10-09-adaptive-live/manual-source-integration/pytest.xml). / 人工观察＋纯模板冻结联调通过；原首败保留，不覆盖后续模板接线或新候选实机。

- [x] Earlier post-Candidate01 native-source freeze:756 passed/1 skipped out of757, zero failures/errors, XML80.769s;1040 Python-file hashes unchanged. The symlink-directory case skips for permission. Zero paid requests/desktop actions/packages. Its bounded native review found no specific P1/P2; this earlier freeze does not validate later manual work. [Historical evidence](../../verification/ADAPTIVE_P2_SOURCE_20261010.md), [result](../../../.superpowers/sdd/2026-10-09-adaptive-live/p2-source-integration/result.json), [XML](../../../.superpowers/sdd/2026-10-09-adaptive-live/p2-source-integration/pytest.xml). / 此前原生源码冻结成绩保留历史，不转计后续manual或新候选实机。

The source-only notes immediately below describe earlier checkpoints; preserve them and their failures. Current-source evidence above does not rewrite Candidate01 or prior source freezes. / 紧接下方源码待测文字为此前时点记录，保留原失败；当前联调不倒改Candidate01或旧冻结证据。

**2026-10-10 源码修复，待测 / Source repair, untested:** 独立学习包的回执校验反向导入执行器，静态上会命中构建 forbidden。现已将原输入请求模型与纯目标校验提取到 `app/core/input_sequence_contract.py`、`app/core/control_target_contract.py`，执行端保留原导入入口；未放宽打包排除或校验规则。已补兼容与实际源码收集回归用例，尚未运行；此前255/43项不验证本次提取。详情：`.superpowers/sdd/2026-10-09-adaptive-live/input-contract-boundary/SOURCE_CHANGE.md`。 / A shared receipt reader imported the forbidden executor into standalone learning collection. The original strict request model and pure target validator now live in shared core modules with legacy re-exports. Build exclusions and validation rules remain unchanged. Written compatibility/source-collection regressions await approval; prior 255/43 results do not cover this extraction.

**Reader 源码收拢 / Reader source completion:** Value/Text 分歧修复及回归用例已写入，限定静态独立审阅无阻断发现；Main 已核对报告和关键源码。已绑定、明确可写、非密码且范围 owner 一致的 Edit/既有 ComboBox 可用 Value 作全文替换与精确回读依据；分歧禁用选区与追加，双读同时比较两种模式，异常/身份检查保持。诊断仅增加 field_reads sidecar，旧 v1 snapshot shape 保持。Main 255 passed / 4.61s 是暂停前结果，不是本轮复测；真实 Edge 尚待批准后验证，不宣称搜索已恢复。 / The implemented slice has no blocker in bounded independent source review, inspected by Main. Writable, non-password, same-owner bound fields use Value for full replacement/readback; disagreement disables selection/append, both pattern summaries participate in double reads, and existing identity/error checks remain. Diagnostics are sidecars without changing v1 snapshot shape. The 255-case Main run predates the pause; real Edge recovery remains unverified.

- [x] Main inspected source/diffs and ran 31 files: 862 passed, 1 symbolic-link permission skip, 107.05 s, exit 0. This proves that recorded offline freeze and supersedes its core-only 649 milestone. Later live-found field, no-dispatch and budget repairs have separate Main groups of 374, 252 and 203; do not transfer the old 862 result to a later frozen candidate or sum overlapping groups. See the current live evidence document. / 862证明当时冻结源码；后续实机修复分别有374/252/203项Main定向回归，不把旧冻结成绩转计新候选，也不累加重叠组。
- [x] Verify MCP contracts plus actual client, queue, runner and authenticated provider/service code in offline integration using mocked HTTP and desktop boundaries; include the maintained capture helper rather than only adapter replacements. / MCP合同、真实客户端/队列/运行器/认证服务和正式采集链均有分层离线联调；HTTP及系统边界模拟。
The remaining acceptance work is tracked once in the current P0/P1 sequence and Task6 checklist above; these historical groups do not replace it or create duplicate tasks. / 剩余验收只在当前 P0/P1 及 Task6 清单跟踪，历史组合不替代验收，也不重复生成待办。

### Real application acceptance outline / 真实软件验收纲要

The cases below and same-scope repairs/reruns already have approval. This plan-only turn keeps execution paused; upon resumption, do not request that approval again. Additional paid allowance remains separate. Preserve valid completed evidence and use fresh data/connections and maintained interfaces for remaining cases. / 以下范围及同范围修复复测已经批准；本轮仅改计划、保持暂停，恢复时不重复申请。新增付费额度单列；保留有效证据，剩余验收使用新数据、连接及维护接口。

| Case / 场景 | Intended coverage / 核验内容 |
| --- | --- |
| External browser, public documentation search and detail navigation / 外部浏览器公开文档检索与详情 | Real dynamic results, loading indicators, side navigation and return navigation. Judge the requested document identity, not merely a visible page. Changed or unexpected content must pause the suffix. / 覆盖真实异步页面，核对目标文档而非仅页面出现；计划外内容暂停。 |
| Installed 7-Zip, new temporary multi-level files / 已安装 7-Zip 与新建多层测试目录 | Select/open/read/back across the same session, an About dialog, normal cancellation during a declared wait, resumption and cleanup. No deletion or overwrite of existing user data. / 同会话状态累积、弹窗、取消恢复与清理，只使用新建测试数据。 |
| Learning replay of the newly collected real 7-Zip journey / 本轮真实软件学习与复用 | Learn/review/save/reopen, replace this run's parameter values, retain local image success with zero API, and require Main on a real scope change. / 学习审核保存重开，替换本轮参数，图像成功零 API，范围变化交 Main。 |

Record first-attempt task success, wrong automatic passes, unnecessary Main handoffs, duplicate input/request counts, original input effects, cleanup, captures and paid calls. Keep end-to-end elapsed time separate from capture/local verification/provider/Main time; report only measured samples and retain all failures. Compare the same candidate and equivalent tasks with and without adaptive review before making efficiency claims. / 分开记录准确性、介入、重复、副作用、清理及分层耗时；同候选同口径对照，不从离线速度推导实机收益。

## 历史 P2 源码检查点（不作为当前待办） / Historical P2 source checkpoint

重新对照已批准spec §4、§6–8、§12：自动loading、显式原生超时语义接续及人工只读observe已源码实现并离线联调通过，仍不能代表完整P2。类型模板共享服务/profile/执行学习runtime/UI现已接通并完成单列冻结离线组合；付费实测不是唯一剩余项。 / Automatic loading, explicit native-timeout continuation and manual read-only observe are implemented and integrated offline, without completing approved P2. Typed-template shared service/profile/execution/learning/UI wiring is now covered by a separate frozen offline integration. Paid validation is not the sole remaining item.

1. **源码完成 / Source complete:** 普通Decision/Agent最终取消门禁、学习分支上下文、HTTP总截止已修复并纳入Main当前联调，首次失败保留。 / Final cancellation, learning-context and HTTP-deadline repairs are included in Main's current source integration, with first failures retained.
2. **源码完成 / Source complete:** `native_condition`显式v2语义续接已通过离线联调；仅完整维护路径超时可进入共用Decision，全部观察/身份/时间/原after绑定重核，最终backend再次校验。坏证据、未知输入及错窗零调用；完整本地证明零API，always_main/off语义保留，尚无新候选实机验收。 / Explicit v2 native-timeout continuation is integrated offline with complete original-proof checks and backend revalidation. Invalid evidence, unknown input and wrong windows make no call; local success stays free and review/off semantics are retained. New-candidate desktop acceptance remains pending.
3. **源码完成 / Source complete:** 人工只读observe已复用原wait/owner/窗口接通持久claim、恢复、取消、共享限额、v3链和公共图像/客户端。v3原after及assessment_round保持，包revision/证据摘要使旧审核失效；相同逻辑请求不重截图，未知采集不重派。A→B→重放A的图像P2保留首败并修复，不回退当前B审核；尚无新候选实机证明。 / Manual observe now wires durable claims, recovery/cancellation/shared limits, v3 ancestry and public image/client delivery on the original wait/owner/window. Original after and assessment round stay unchanged; packet/evidence revisions invalidate stale reviews. Logical or unknown captures never repeat. The replay-image P2 retains RED and is repaired without rolling current B back; new-candidate live acceptance remains pending.
4. **源码完成 / Source complete:** 类型模板共用配置/服务、执行/学习运行时、恢复与双语编辑器已接通；Main完整冻结组1319通过/1跳过，详细首败与修复见[模板源码证据](../../verification/CONDITION_TEMPLATES_SOURCE_20261010.md)。新候选实机验收仍待进行。 / Typed-template configuration/service, execution/learning, recovery and bilingual editing are integrated; Main's frozen group records1319 passed/1 skipped. Linked evidence preserves failures and repairs; new-candidate live acceptance remains open.
5. P2 源码闭合后再冻结新候选，进行新内容真实单项/连续测试、同候选独立验收和同口径收益评估。Candidate01 的已通过安装/桌面证据保留为历史，不覆盖此后源码修复。 / Freeze a new candidate after P2 source closure, then validate fresh single/continuous journeys, independent acceptance and comparable benefits. Candidate01 evidence remains valid only for its frozen source.

本批测试批准继续有效；新增付费额度仍独立待答复。未进行版本升级、提交或发布。 / Existing test approval remains valid; additional paid allowance is separately pending. No version bump, commit or publication.

## 2026-10-10 Candidate01 检查点（历史） / Candidate01 checkpoint (historical)

此前installed01改名/保存revision3→4、仅step-1.title变化及installed03正确预检后重开/public read/31库hash通过，三次运行正常清理。installed02预检失败后Main未按exit code阻止启动，以及之前执行卸载exit0/complete=false均保留原件；该生命周期检查点hash不改。 / The earlier save/reopen checkpoint retains its31-file library and normal cleanup, together with the caller preflight failure and original incomplete root-removal assertion. Its evidence remains immutable. [Lifecycle](../../../.superpowers/sdd/2026-10-09-adaptive-live/INSTALLED_LIFECYCLE_CHECKPOINT.md).

新增同版本包替换检查：旧执行/学习→Candidate01四命令exit0/verified，payload 546/349→557/981，各组件内未知fixture及本次独立外部30库hash保留；没有跨版本或schema迁移。升级后执行依赖7.065s passed（既有LIGHT，Qt/input/host=false），GUI en-US三页offscreen/正常close 1.668s。两维护卸载exit0/verified后各仅保留fixture、原卸载器、retained marker共3文件，外部/另一组件不变，无强删。 / Same-version replacement passed four check-install commands, preserving unknown fixtures and this separate30-file library. Existing-interpreter dependency and offscreen GUI probes passed; two maintained uninstalls retained only three expected files per component without forced removal. These are not cross-version/schema, fresh-environment or live-desktop results. [Upgrade checkpoint](../../../.superpowers/sdd/2026-10-09-adaptive-live/UPGRADE_CHECKPOINT.md).

Sol同冻结候选的限定独立桌面验收已通过：新Temp check安装，改名保存、英→中→英、界面库/流程图查看、同库重开和两次正常关闭；10次门控click、1次clear/type，31库hash及旧版本/pin保留，API0。Main复核关键原图和数据，并在维护卸载前重算127原件引用/64原图/8安装元数据；卸载后254外部文件不变，学习临时目录移除，执行未知空目录和卸载记录按合同保留。观察器首败与原回执保留，不把人工效果改写为自动effect。 / The bounded independent journey passed on the same frozen candidate, including bilingual UI, title-only save, exact reopen and two normal closures. Main reviewed key images/data and rehashed the evidence before maintained cleanup; external data and prior versions remain intact. Preserve observer failures and automatic effect facts. [Main closeout](../../../.superpowers/sdd/2026-10-09-adaptive-live/INDEPENDENT_MAIN_CLOSEOUT.md).

真实loading/observe正例及新审核上下文的远程效果/收益仍待验证；本次check证据不等于当前候选normal安装、跨版本/schema迁移或新机器依赖验收。安装器/设置/依赖11文件的22项字节比较相等，已有preview.1安装的registry/shortcut仅做了只读观察，不倒写历史。批准有效；付费仍12/12余0，追加最多4次额度尚待答复；冻结产品、版本、公开下载不变，正式目标未完成。 / Real observe and revised-context benefits remain open. Check-mode evidence does not establish normal installation, migration or fresh-machine dependencies. The 22 exact contract comparisons and current installed-state observation retain their own scope. Testing approval stands; additional paid allowance is pending, with no product or release change.

## 2026-10-10 UI08时点记录（历史） / UI08 checkpoint (historical)

UI08 的27份请求已正常收尾；Main确认同窗英文→中文菜单/库→英文、反馈条目与Candidate 1选择、双截图比较和dialog关闭的限定流程通过。12个动作各一次click，自动effect_verified=false保持，效果明确归Main看图。024关闭后即时采集失败保留，025/026确认root恢复；663源码、3工具与30库文件hash核对一致。证据：[UI08_CLOSURE](../../../.superpowers/sdd/2026-10-09-adaptive-live/UI08_CLOSURE.md)。 / Main confirmed the bounded 27-request bilingual and feedback comparison journey with cleanup. Each of 12 actions records one click; automatic effect remains false and visual confirmation belongs to Main. Preserve024's capture failure and025/026 recovery; source/tool/library hashes match at the recorded checkpoint.

身份接线修复Main11模块380passed/6.90秒（XML6.877秒），不累加历史组；UI06/07首败原件不改，尤其UI06/016原null与UI07严格false proof分开。context441仅离线，实际远程收益未知；loading/observe正例、当前冻结候选安装/升级与同候选独立验收仍未完成。批准有效，付费新增0，预算12/12余0；未构建/提交/发布。 / Main's identity repair passed380 offline cases, separately from prior groups. Earlier failures and original unknown/false facts remain intact. Positive loading/observe, actual context benefit, installed/upgrade and independent acceptance remain open. Approval stands; no paid call was added, budget stays12/12 with zero remaining, and no build/commit/release is claimed.

## 此前结果（历史） / Earlier results; historical

当前批次已批准；control_target初始输入前proof已修，RED12/62→74、Main300/15.38s、Decision二次变化48/5.37s，6文件只读审阅无阻断。旧9失败/283过保留为修前原件，unknown/已点击语义保持。 / The approved proof repair is verified; prior failures are historical and input semantics remain unchanged.

chrome Sol86/2.20s、Main26文件634/19.19s离线通过；Edge11纠正Main格式请求后六合法命令/Main核验/清理通过，first_attempt_clean=false、四次automatic effect仍false。两次返回未先full，不推广非匹配观测为收益；首次调用方错误保留。 / Corrected-request bounded live use and cleanup passed with manual effects and the caller failure retained; no generalized benefit claim.

7zip-06 的真实 Decision 非空后缀审核门槛已通过。字段内部聚焦语义及尺度已修：经验证的普通聚焦默认1024整图，显式配置及原输入门禁保留；Main15模块397项/13.87秒通过。640实机首败保留；新根focus-resolution-live-02与adaptive-03在同一冻结源码下均完成三步及清理。两组Main审核均3次，差0；原命令wall为14.910/15.119秒，后组另有两次Decision共3.685秒，不宣称提速或准确率提升。当前预算12/12余0、43665 input tokens。下一步补齐审核上下文丢失的步骤/参数语义并做离线合同验证，不通过降低阈值掩盖不确定。真实loading/observe、最终双语/隔离安装及同候选独立验收仍未完成；下载仍preview.3。 / The real nonempty-suffix review gate passed. Verified ordinary field focus now preserves its intent and defaults to a 1024px full image, retaining explicit settings and input gates; Main passed 397 cases in 13.87s. Keep the initial 640px live failure. Two fresh runs completed all three steps and cleanup on identical frozen source. Both required three Main reviews, a zero reduction; original command walls were 14.910/15.119s, with two additional Decision calls taking 3.685s in the adaptive route. No speed or accuracy gain is established. Usage is 12/12, none remaining, with 43,665 input tokens. Next repair missing scoped step/parameter context and verify offline without lowering thresholds. Real loading observation, final bilingual/isolated installation and same-candidate independent acceptance remain open; published downloads remain preview.3.

随后完成v2审核上下文修复：步骤摘要保留ID、动作、参数名、flags及验证条件，隐藏输入值；超长在入队前拒绝，空allowed_states明确为未声明额外状态。Main相关441项离线通过（main-review-context-integrated.xml），未调用真实API；不把修前3对3结果转计新投影的效果。旧v2证据保持冻结，新投影不混入旧运行；v1保持原合同。下一步验证真实审核收益与loading观察，再完成最终双语/隔离安装和同候选独立验收。 / A subsequent v2 context repair preserves step IDs, actions, parameter names, flags and verification conditions while hiding input values, rejecting oversize before queueing and clarifying empty allowed_states. Main passed 441 related offline cases without real API calls. The earlier three-versus-three result does not measure this new projection. Keep old v2 evidence frozen and use new runs for the changed projection; v1 retains its contract. Real review benefit and loading observation, followed by final bilingual/isolated installation and independent same-candidate acceptance, remain open.

**Edge12真实加载检查 / Real loading check:** API validated=true，三项概率0、still_progressing=0.36，failure/review_required、adopted=false；未observe/未追加capture，加载门槛仍未通过。原输入completed/action=true，单条trial-exec，随后cancelled/pending=null及维护清理成功；不盲复试或降阈值。Edge12完成时预算 **7/12余5，27052 input tokens**；Edge05–11新增0，Edge12新增1。 / The real check was validated but did not enter observation; original input and successful cancellation/cleanup remain distinct. One added call brings the batch to seven of twelve, five remaining.

## Progress and evidence history / 进度与证据历史

Entries below preserve historical stages, including superseded approval/test notes; they are not active instructions. Current priority and evidence boundaries are in the opening release section, with source completion tracked in Tasks 1–6. / 以下是历史时点而非当前指令，包括已被替代的授权/待测文字；当前顺序和证据边界以开头发布主线为准，源码完成项见 Task 1–6。

- 2026-10-09: user approved the detailed design and requested the README diagram. Implementation started from clean tracked baseline; prior private `.superpowers/` and `artifacts/` remain untouched. / 用户已批准，开始实施。
- Scope discipline: no ritual commits or full-suite legacy migration. Feature implementation and source acceptance do not silently publish a release. / 按项目规则定向验证，不自动发布。
- User subsequently required test approval. All three workers confirmed no test/compile/API/desktop run had started; Main has also run none in this development slice. Continue source/test-file writing and static reading only; request a concrete verification batch after source integration. / 三名工作者与Main尚无测试执行，完成源码后申请具体批次。
- Source checkboxes above mean written and inspected as text, not verified behavior. Current batch is Tasks 1–4 core plus condition/policy editor, not the entire design. v2 auto/always_main is explicit; shadow/off preserves routing, and step policy cannot weaken the host. Static integration corrected skipped-result authentication, immutable program context on recovery, zero-call incompatible plan/profile behavior, and readonly successor replay. / 勾选仅代表源码，不代表运行通过；本批不含全部后续设计。
- Approval proposal: offline Decision/provider/config/receipt and direct-step contracts; task-plan runner/client/review/successor integration; learning recovery/rules and Qt offscreen; generate `.qm` from the two edited `.ts` files. Use temporary data, synthetic credentials and mock HTTP only. No real API, desktop input, packaging or installation in that batch. Fix/retest only its affected paths after approval. / 下一申请批次限定离线测试与翻译生成。
- Final readonly review found reservation ownership and logical-ID collision windows. Source now checks reservations even with a terminal active parent and rejects an occupied child ID before consuming the parent generation; new regression files describe both failure windows. Worker `git diff --check` returned 0, which is only a text-format check. No collection, imports, compilation or behavioral test has run. / 最后静态修订已补预留所有权及 ID 碰撞；仅有文本检查，不是运行通过。
- Following explicit offline approval, Main's final combined run passed 649 cases. The compatibility first failure and precise fix remain in `docs/verification/ADAPTIVE_REVIEW_OFFLINE_20261009.md`. All prior source-only entries above describe the earlier stage. No live desktop or real API test ran. / 后续授权后离线组合通过，前述未测试记录为历史阶段。
- User strengthened release acceptance: use real complex applications and workflows, not only custom demos. LinkedIn release-content operation is a later runtime business case, with draft approval before publication; it does not replace this development mainline or start an automation now. / 用户要求复杂真实验收；领英为后续业务场景，先审核稿件，本轮不做运营。
- Current frozen source: automatic declared-loading observation, queued cancellation and late-adoption checks are implemented. Main's 31-file final run passed 862 cases with one OS-permission skip; see the verification record for primary-path metadata, budget and damaged-evidence failures and fixes. No source changes followed that run; final edits synchronize documentation only. / 当前源码冻结后最终组合通过，随后仅同步文档，没有实机、真实API、打包或发布。
