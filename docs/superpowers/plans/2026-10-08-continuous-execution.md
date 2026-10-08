# Continuous Execution Implementation Plan / 连续执行优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Follow explicit project/user choices; do not create ritual worktrees, per-task agents, approvals or commits.

**Goal:** 主 Agent 一次提交短计划，可靠定位与充分核验支持的步骤自动连续完成；降低真实任务耗时，同时保留原输入与恢复约束。 / Submit once and automatically advance sufficiently grounded and verified steps, reducing end-to-end latency without weakening input or recovery contracts.

**Architecture:** 给现有 WorkflowRunner 注入可选运行后端和固定步骤读取接口；学习程序保留原 MemoryWorkspace/TrialService 默认路径，临时计划使用独立 session-local 来源。共享队列、AgentCommandJobs、串行 owner、原动作门禁、图像和 Decision 服务。 / Add backend and pinned-step ports to the existing runner; retain the learned-program default and provide a separate session-local caller-plan backend over the same execution stack.

**Tech Stack:** Python, Pydantic, existing Instant MCP and Windows UIA, maintained screenshot/action interfaces, existing image matcher, optional `app/judgment` Decision service; pytest. No new paid provider, local weights or GUI framework dependency.

**Spec:** [连续执行提速设计 / Design](../specs/2026-10-08-continuous-execution-design.md). Read both documents before implementation.

## 2026-10-09 发布授权与当前状态 / Publication authorization and current state

用户已授权完成本轮发布、同步进展后关机。版本为 execution `0.1.2-preview.3` / optional learning `0.1.0-preview.3`，标签 `learning-v0.1.0-preview.3`；学习包已纳入修改后的 shared runner/readers。Main 与独立 Sol 的短计划源码验收通过，Main 新安装版执行 smoke/B/C/取消审核/弹窗及学习保存/重开/原版本保持/关闭也通过。首次 adapter 与 PowerShell worker 漏包零输入失败独立保留；39 项回归后仅重建 E，G 不变。最终安装独立验收、发布及下载核对按[发布记录](../../verification/CONTINUOUS_EXECUTION_RELEASE_20261009.md)，旧 preview.2 与稳定 v0.1.1 保留，远期 checkbox 不变。 / Main passed scoped installed journeys after retained zero-input failures; the release record owns final installed-independent/publication status without completing the broader plan.

## 2026-10-08 初期授权与执行记录 / Initial authorization and execution

用户已授权本轮 API、本地及桌面测试，不再逐次申请；此前“先不测试”限制已被覆盖。先用同一 OpenAI Key 对普通 Luna 外部视觉路由做有界准确性与延迟评估，随后恢复本地识图；Decision 仍为可选核验。 / The user now authorizes API, local and desktop testing, superseding the earlier deferral. Evaluate ordinary Luna grounding with the existing key, then retain local grounding as the default; Decisions remain optional.

- 复用原工作树；三项有界 Sol Ultra 工作：外部视觉适配/评分、临时运行器合同回归、客户端 run_plan。 / Reuse the checkout with bounded adapter, runner and client work.
- Codegraph 当前工作树未初始化；本轮使用限定 rg 与源码读取。 / Current checkout has no Codegraph index.
- 本轮验收素材为新创建 Record Desk 三个布局、12 个识图案例；图像由项目 ScreenshotService 采集，真值由 Qt 控件几何独立给出。没有使用旧学习截图或资产。 / Fresh captures and independent widget truth only.
- 工作器初始运行器兼容检查报告 51 项通过；尚非完整计划验收。 / Initial worker compatibility checks report 51 passing; not complete acceptance.
- 初期不提交、发布或改版本；2026-10-09 用户已授权发布，当前范围见上方新记录。 / The initial no-publication boundary was superseded by the later explicit release authorization.

## Global Constraints / 全局约束

- 用户已授权本轮离线、真实 API 和本地桌面测试，覆盖此前“先不测试”。下方尚未勾选的完整验收项仍未闭合；历史发布通过数不能计入本轮。 / Current authorization supersedes the earlier test deferral; unchecked acceptance items remain open and historical release results do not cover this slice.
- 短计划源码限定验收及 Main 新安装版流程通过，整体远期计划未完成；版本为 execution `0.1.2-preview.3` / learning `0.1.0-preview.3`，最终验收/发布状态见上方记录，旧 preview.2 保留历史。 / Scoped source and Main installed acceptance passed; final verification/publication remains governed by the release record.
- 工作树 `C:/Users/DesolateJix/.codex/worktrees/decision-api/agent-gui-runtime`，分支 `codex/dev-decision-api`，基线 `766032860e5d8351b6edd7e3eb862ff9b1f188d7`。复用现工作树，保留 `.superpowers/` 等既有未跟踪内容。 / Reuse the existing checkout; preserve unrelated work.
- CodeGraph 在当前工作树未初始化；实施定位以当前工作树源码为准，使用限定范围 rg。 / CodeGraph is not initialized for this checkout; scoped source searches are used.
- 学习安装可选；不创建假审核、单节点假学习图或自动修改已发布学习版本。 / Learning remains optional; no fabricated review or silent revision changes.
- 原队列、唯一输入 owner、`POST /action/execute_recognition_plan`、窗口/候选 freshness、可写性与原回执继续有效；Decision 成功不授予权限。 / Keep the original owner, gate, freshness, editability and receipt semantics.
- 默认模型/强度不变；Codex 原生 Computer Use 禁用；真实测试只用项目维护接口、新数据、新采集，保护浏览器资料。 / Preserve model/effort and use only maintained desktop interfaces with fresh data.
- 待决、未知、部分输入不自动重派；网络/模型错误不能由静默换 provider 掩盖。 / Never replay uncertain input or silently switch providers.
- UTF-8、中文最小代码注释、中英同步维护文档；初期只实现的边界已由上方发布授权更新，不扩大到未授权的私有证据、模型或凭据上传。 / Keep UTF-8/bilingual maintenance and the explicit release scope; private evidence, models and credentials are not release assets.

## 2026-10-08 开发记录 / Implementation ledger

| Area / 范围 | Source status / 源码状态 | Evidence still needed / 待验证 |
| --- | --- | --- |
| P0 timing + field diagnosis | browser03 正确聚焦、填写及原生读回通过，14.153 秒，未提交搜索 / Browser03 focus, typing and native read-back passed without search submission | Production timing collection and wider field coverage / 生产计时采集及更多字段覆盖 |
| P1 shared runner | continuity02 取消与原 wait 审核续接两场景通过，A 不重放；notice01 显式恢复及独立 fresh 三组通过 / Final-candidate cancellation, retained-wait continuation and explicit popup recovery passed independently | Wider runtime coverage / 更多运行场景 |
| P1 verification | 两次真实 Decision 结算；BC02 40/40 独立业务效果正确，Decision off / Decision evidence retained; 40 final-candidate native effects match the independent oracle | Broader predicates, dynamic outputs and learned references / 更多结果条件、动态输出及学习引用 |
| P2 target/caller costs | BC02 20/20 runs；B/C 中位 6502.2987/2069.75995 ms，降幅 68.1688% / Final matched native-target comparison passed within the measured scope | Browser preparation scans, cold 3/configuration, 100 scheduler transitions and real Main baseline / 浏览器准备扫描、冷启动及真实 Main 基线仍待 |
| P3 acceptance | 本方与独立 Sol 的源码短计划验收通过，Main 新安装流程通过，原失败保留 / Scoped source and Main installed journeys passed | Broader plan unfinished; final release status in the release record / 远期计划未完成，最终发布状态见发布记录 |

**2026-10-09 台账补充 / Ledger update:** 原报告确认最终候选 `continuity02`、`notice01`、`BC02` 及独立 Sol fresh 三组均通过，包括正常清理与同冻结产品源码核对。本轮短计划源码里程碑验收完成，Main 新安装流程通过，最终发布状态见上方记录；下方远期计划保持未完成。 / Main and independent Sol passed the scoped frozen-candidate live acceptance, including cleanup and source consistency. This source milestone and Main's scoped installed journeys passed; the release record owns final status, and the broader plan remains unfinished.

- 普通 Luna API 仅在 3 张全新夹具图上做 12 次分类/几何评估，12/12 通过；端到端中位 2937.394 ms、最大 5118.273 ms，原 usage 共 19,087 tokens。没有执行任何 API 返回点击点；评估已停止，后续本地定位，不能据此宣称通用准确率或真实 API 动作通过。 / The bounded 12-request image evaluation passed; no returned point was executed, and the API evaluation is now stopped. Evidence: `D:/AgentReviewAcceptance/ordinary-luna-vision-20261008-01/summary.json`.
- browser03 完成 `focus/type/check_input`，25 字符测试值与原 SHA 的 UIA 读回一致，Main 核对原 PNG；14.153 秒、未 Enter/提交搜索，正常关闭与宿主清理、运行中源码冻结均通过。browser01/02 的拒绝保留原失败身份，不改记首次成功。 / Browser03 passed the scoped write/read-back and cleanup after retained earlier refusals. Evidence: `D:/AgentReviewAcceptance/browser-field-acceptance-20261008-03/report.json`.
- **旧候选 BC01：** 同模型、本地定位、相同任务/布局与 absent→stable 原生验后；10 对分为两个 5 对同会话 block，交替顺序，两布局。20/20 runs、40/40 业务输入正确，callback 0，API/Decision off，清理和起止 SHA 一致；B 中位 6528.871 ms、C 中位 2057.443 ms，C 的 20 次识图推理均 skipped。只证明本夹具明确原生目标的收益，模型准备/冷启动及清理不在 `run_wall_ms`，不推广为 Main 模型收益。 / BC01 proves scoped native-target savings, not cold-start or Main-model savings. Evidence: `D:/AgentReviewAcceptance/native-plan-matrix-bc-01/report.json`.
- **旧候选 AB01：** 10 对、20/20 runs 和 40/40 业务输入正确，清理与起止 SHA 一致；A 中位 6525.081 ms、B 中位 6611.686 ms。A 是零思考脚本逐步调用维护接口，不是真实 Main 模型基线；此组未显示编排直接提速，Main 总推理时间/token 仍未知。BC01/AB01 均早于最终派发身份及取消边界补强，不能替代最终候选复测。 / AB01 shows no raw scheduling gain against a zero-thinking script; both old-candidate comparisons remain separate from final-candidate acceptance. Evidence: `D:/AgentReviewAcceptance/native-plan-matrix-ab-01/report.json`.
- continuity01 首次取消停在 `cancel_requested`、旧 wait 与原 A 票据保留，oracle 只有 A；客户端误返回审核 handoff，宿主又停掉取消结算 tick，清理通过但 case 失败。两层已分别修复；联合客户端/运行器/核验/合同 167 passed，Main 窄回归 132 passed，批次重叠不累加。合法 review 返回 `continue_required`，原 wait 显式 continue 后才推进；取消过渡只读轮询，超时不冒称取消完成。 / The original failure is retained; repaired control boundaries passed scoped overlapping regressions, followed by the separate final-candidate evidence below.
- **最终候选 continuity02：** 同宿主/夹具两场景通过；cancel 保留 A 的唯一原输入，B 未发生；另一新 case 的脚本 oracle 审核返回 `continue_required`，使用原 wait ID 显式续接 B，A 未重放。各场景只有 1 次有意审核等待 callback；清理与起止源码 SHA 一致。脚本审核不计作 Main 模型审核。 / Both same-session cancellation and explicit original-wait continuation passed without replay. Evidence: `D:/AgentReviewAcceptance/native-plan-continuity-02/report.json`.
- **最终候选 notice01：** Show notice→取消原计划→明确选择同 PID/birth 的新 Notice→gated Close→重新选择原窗→新 case 的新 C 计划完成 A/B，四个输入和独立 oracle 一致。Close 原回执为 `returned_observation_unavailable`，原 `action_executed=true` 与 `notice_closed` oracle 证明关闭，未重放；正常清理与源码冻结通过。公开 owner HWND 仍未知；只验证显式选窗恢复，不宣称原计划自动跨窗继续。 / Four explicit inputs and independent effects passed; unavailable dialog post-observation remains visible in the original receipt. Evidence: `D:/AgentReviewAcceptance/native-plan-notice-01/report.json`.
- **最终候选 BC02：** 10 对、20/20 runs、40/40 效果正确；B/C 中位 6502.2987/2069.75995 ms，中位耗时降幅 68.1688%；各对节省中位 4350.9142 ms、降幅中位 67.7351%。B 范围 6315.6136–7699.8159 ms，C 范围 2057.7367–2182.8397 ms；C 20 个步骤均 skipped 视觉推理，API 0、callback 0、Decision off，两 block 清理正常且源码冻结。两次 prepare 8160.008/8161.611 ms 单列，不混入执行中位数；不代表每配置 3 次冷启动或真实 Main 基线已测。 / The final frozen candidate retains scoped native-target gains and separate preparation timings. Evidence: `D:/AgentReviewAcceptance/native-plan-matrix-bc-02/report.json`.
- **独立 Sol 最终 fresh 验收：** 首轮 BC 1 对、2 runs、4 个原输入；连续取消/审核续接 3 个原输入；弹窗显式恢复 4 个原输入，合计 11 份原执行回执，均通过且无自动重试。255 项独立审计 `errors=[]`，3 张实际后图经目视核对；Main 原证据 892 项审计同为 `errors=[]`，两者分别保留、不作为测试数累加。清理正常，648 个产品文件 SHA 清单一致：`e2567f3bff8a59086245d5ac09dbd8429adee754cc005fe1bb696215b811de4b`。 / Independent first-run checks passed on the same frozen candidate; audit items and original inputs are separate evidence counts. Fresh reports: `D:/AgentReviewAcceptance/independent-plan-final-01-bc/report.json`, `D:/AgentReviewAcceptance/independent-plan-final-01-continuity/report.json`, `D:/AgentReviewAcceptance/independent-plan-final-01-notice/report.json`.

初期 `task_plan.v1` 明确拒绝 `target_memory`、动态输出引用和 `read_spec`；`read_text` 只提供原观察并要求 Agent 复核。`native_condition` 仅用于点击或搜索跳转；`agent_judgment` 可声明 Decision 条件。新增 `review` 控制后仍须用原 wait_id 显式继续。文档和错误必须如实表达这些边界，不能把下方最终设计写成当前功能。 / The source contract is deliberately narrower than the final design; see [TASK_PLAN](../../development/TASK_PLAN.md).

初始静态审阅修复包括核验目录创建、审核来源一致、跨 owner 校验、审核幂等、取消独立结算 ID 和客户端状态投影。此后已运行相关产品路径；整段性能收益仍未证明。 / Static repairs were followed by scoped runtime checks; end-to-end benefit remains unproven.

初始静态检查记录：12 个 Python 文件 UTF-8/AST、6 个模块导入路径、文档链接、JSON 和差异空白检查通过。后续独立测试批次为核心运行/核验相关 277 passed、学习恢复相关 120 passed、客户端/启动配置 80 passed；不同批次可能重叠，不累加为总数。首次公开计划排队查询失败后，修复候选 root03 一次提交完成两个正确详情，128 次只读轮询、无记录的中途 callback，并完成清理。缺少 Main 模型遥测时 token 仍为未知。 / Scoped batches overlap and are not summed. Root03 passed after the original status-queue failure: two correct details, 128 read-only polls, no recorded callback and complete cleanup. Missing Main-model telemetry remains unknown.

## 常规执行脱离逐步介入 / Routine execution without stepwise Main intervention

目标是一次计划提交后，定位、输入、核验及推进由宿主/客户端适配器连续处理，只在完成或确有异常时返回主 Agent。只减少语义审核、却仍要求 Main 逐图转发或逐步 continue，不算完成这个目标。 / After one plan submission, the host/client adapter owns grounding, input, verification and advancement. Eliminating semantic review while retaining Main-driven screenshot forwarding or per-step continuation does not meet this goal.

1. **固定流程闭环（Task 2–3）**：1–8 步线性计划、显式参数、窗口身份与原票据已接通；新数据公开闭环及最终候选取消、原 wait 显式续接与选窗恢复通过，未宣称 dead-host 或自动跨窗继续。 / The bounded loop and scoped final-candidate continuity passed; dead-host and automatic cross-window continuation are not claimed.
2. **去掉常规定位交接（Task 4）**：明确结构化目标先走当前可靠原生定位；学习定位仅在显式提供固定版本且完成来源接入后可选使用。没有可靠本地命中时，直接沿已配置的本地模型/视觉来源定位。真正的来源故障仍报错，不以换来源掩盖。搜索框原主故障与聚焦身份已修，browser03 正确填写读回通过；更多准备扫描优化仍待。 / Prefer trusted current native targets and otherwise preserve the selected direct source. Browser03 passed after primary repairs; preparation-scan optimization remains future work.
3. **核验后自动推进（Task 3）**：充分本地证据可直接结算；图像核验须接入真实固定版本参考后才能启用。语义条件用已有 Decision 配置；不确定保留原票据返回 Agent，不让布尔判断冒充定位、提取或输入授权。 / Advance from sufficient local or authenticated semantic proof; image references need real provenance, and uncertainty preserves the original ticket.
4. **客户端只等完成或异常（Task 5）**：实现既定 `run_plan(request_id, command, *, event_callback, total_timeout)`，跟踪原 run/command IDs，正常等待不触发 Main 模型回合。超时返回原状态，不重派；异常一次带出失败步骤、原回执、图像和等待身份。 / The client follows original IDs without invoking Main for healthy polling; timeout and exceptions retain original evidence.
5. **区分两条使用路线**：本地定位/宿主直连视觉 API 是首个“正常中途零 Main 介入”的验收路线；Codex `agent_delegate` 保留现有同一视觉 worker，但在仍需 Main 发工具调用续接时，只宣称减少审核，不宣称零 Main 介入。Python 宿主不能自行调用 Codex collaboration 工具。 / Accept the direct-source route first; the delegated route cannot claim zero Main intervention while it still depends on Main-issued tool calls.
6. **再扩展变量与收益（Task 4、6）**：本轮可靠步骤与匹配原生目标收益已有证据；受约束动态读取/输出绑定、学习引用、每配置 3 次冷启动、100 次调度百分位及真实 Main 模型基线仍为后续工作。 / The scoped loop and matched target gains have evidence; dynamic dataflow, learned references, cold-start runs, scheduler percentiles and a real Main-model baseline remain future work.

**达标口径 / Acceptance definition:** 固定常规任务中，排除初次规划与最终汇报，Main 中途调用次数为 0；适配器内部轮询单独计数，不能把 Main 转发视觉请求漏记。异常允许返回 Main，但必须保留原输入事实。Decision 与学习安装均可选；不能为了数字好看降低核验或换小模型。本方短计划闭环、显式恢复、BC02 匹配收益及同冻结候选独立验收已通过；真实 Main 时间/token 收益仍未知，远期项目仍待。 / Zero intermediate Main turns/tool calls on the healthy path, with transport polling counted separately. The scoped loop, explicit recovery and matched target benefit passed independent acceptance; actual Main latency/token savings remain unknown and broader work remains open.

## Review Focus / 审阅重点

1. UIA 树中存在 Edit，但 point hit 指向 Document/mixed；必须保留零输入和诊断，不能认作可写。归 Task 1、4。 / Conflicting hit/editability evidence.
2. 同一按钮标签在不同容器重复，或滚动/DPI/窗口变化使旧坐标失效；必须重新唯一定位。归 Task 4。 / Duplicate labels and stale geometry.
3. Decision 显示 success 但只证明中间状态，或取消已到达；不得结算完整任务或派发下一步。归 Task 3。 / Incomplete predicates and cancellation races.
4. 进程在发送或输入后、落盘前退出；恢复只能显示原事实，不能自动重新付费/重输。归 Task 2、3、6。 / Crash windows and unknown outcomes.
5. 临时计划读到错误变量/资产版本，或被当成 reviewed_program；在第一项输入前拒绝。归 Task 2、4。 / Provenance, version and dataflow mismatch.

## 优先级与交付 / Priorities and deliverables

| 顺序 / Order | 可独立验收的结果 / Deliverable |
| --- | --- |
| P0 — Task 1 | 计时可信，搜索框主故障可复现并修复 / Trustworthy timing and repaired primary field path |
| P1 — Task 2–3 | 无学习安装也能提交两步计划，核验成功自动推进 / Execution-only plan advances on verified success |
| P2 — Task 4–5 | 可靠定位减少识图，交接/扫描/等待减少 / Fewer unnecessary grounding and observation round trips |
| P3 — Task 6 | 匹配基线的流程、正确性与收益验收 / Equivalent-baseline correctness and benefit evaluation |

Task 1 的离线计时/诊断与 Task 2 的隔离后端实现可分工；真实故障路径修复和相关回归未通过前，不跑完整浏览器链。主 Agent 负责接口和整合，Sol Ultra 承担边界清楚的实现/验证，持续复用视觉会话。 / Offline work can proceed independently, but repair and regression precede live full-flow testing. Main owns integration; workers remain bounded.

## Task 1: 补齐时间轴并修复搜索框主故障 / Timing and primary field failure

**Files:** Modify `app/agent/windows_text_field_reader.py`, `app/core/local_text_focus.py`, `app/vision/agent_command_jobs.py`; reuse `scripts/learning_benchmark_client.py`. Create `scripts/benchmark_execution_plan.py` with a read-only summary mode first. Tests: `tests/test_local_text_focus.py`, `tests/test_input_sequence_field_binding.py`, `tests/test_local_step_timings.py`, new `tests/test_execution_plan_measurement.py`.

**Interfaces:** `summarize_execution_timeline(events: list[dict]) -> dict` produces disjoint measured spans plus explicit unknown/overlap fields. Diagnostic schema `text_focus_hit_diagnostic.v1` records capture/window identity, origin, viewport, DPI context, raw hit type/RID/bbox, bounded ancestors and readonly attribute category; no field values or secrets. Keep existing rejection codes.

- [ ] Add tests for `test_handoff_is_not_pure_inference`, `test_query_receipt_is_not_action_duration`, `test_nested_decision_times_are_not_added`, and `test_missing_timestamps_stay_unknown`. Replay this demonstration's original JSON; expected totals remain 48.164387 s and handoff 40.7013185 s without rounding-induced double counting.
- [ ] Add `test_document_mixed_rejection_has_hit_provenance`, `test_nonzero_origin_hit_binding`, `test_dpi_context_is_recorded`, `test_diagnostic_omits_field_value`. Reproduce the exact refusal in a bounded read-only live probe before choosing a code fix. If point-hit evidence remains unavailable, report that concrete blocker; do not substitute a writable descendant or waive the guard.
- [ ] Locate the failing layer using fresh raw hit and tree evidence, then implement the smallest common-layer fix supported by it. Preserve `Document/mixed -> not writable` when the actual target remains unproven. Encode the discovered primary-path regression before the fix; do not guess that DPI or YouTube is responsible.
- [ ] Run `python -m pytest -q tests/test_local_text_focus.py tests/test_input_sequence_field_binding.py tests/test_local_step_timings.py tests/test_execution_plan_measurement.py`. Expected: regression fails before the fix, passes after; original negative cases still reject with zero input.
- [ ] Verify one real search-input operation via the maintained API and retain first failure and rerun separately. Update a new scoped verification note with failure, invariant, fix location, cross-app rationale, regression and safety impact. If only observation was possible, mark the defect unresolved and block full-flow acceptance.

## Task 2: 共用运行器的临时计划入口 / Transient plan over the shared runner

**Files:** Create `app/execution/task_plan_contract.py`, `task_plan_backend.py`, `task_plan_admission.py`, `run_backend.py`; modify `app/learning_memory/workflow_runner.py`, `workflow_runtime.py`, `app/instant_mcp.py`, `scripts/run_local_step_session.py`. Tests: new `tests/test_task_plan_contract.py`, `test_task_plan_runner.py`; existing `tests/test_workflow_runner.py`, `test_workflow_runtime.py`, `test_agent_command_dispatch_attempts.py`.

**Interfaces:**

- `validate_task_plan(value: dict) -> dict`: strict `task_plan.v1`, `title`, frozen `inputs`, `steps` (1–8). Each step has unique `step_id`, semantic `action` and explicit `verification`; action kinds `click/input_sequence/read_text`. Reuse existing action field validation and typed input/output references, reject raw coordinates and cyclic/forward output references.
- `RunBackend` port: `status(run_id) -> dict`, `prepare(run_id, request_id, *, vision_capabilities=None) -> dict`, `cancel(run_id, request_id) -> dict`, `pinned_step(run_id, step_id) -> dict`, `metrics(run_id, trial) -> dict`, `validate_resume(run_id, state, *, revalidate_initial=False) -> None`.
- `WorkflowRunner(..., backend: RunBackend | None = None)` keeps the current MemoryWorkspace/TrialService adapter as its default. All direct program/metrics/recovery lookups used for ordinary runs go through that backend; existing learned takeover methods keep their original explicit source restrictions. The dispatch/settlement state machine is shared, not copied.
- `TaskPlanBackend` stores `source_kind=caller_plan`, immutable plan SHA, target identity, step tickets and original results inside the owning session. It implements the backend port and receives authenticated verification settlement in Task 3. It is not `reviewed_program`; optional learned references are independently validated.
- `kind=task_plan`, request actions `start/status/continue/cancel/review`; `start` includes the plan and freezes the host-selected target, returning `plan_id/run_id` and original runner state. `continue` requires current `run_id/wait_id`; grounding continuation remains the original `grounding_resolve + agent_command_continue` contract.

- [ ] Add `test_two_step_plan_runs_without_learning_installation`, `test_same_start_id_same_plan_is_idempotent`, `test_same_start_id_changed_plan_rejected`, `test_caller_plan_cannot_claim_learning_review`, `test_failed_or_unknown_first_step_never_dispatches_second`, `test_cancel_preserves_dispatched_action`. Tests must use the real queue/runner with isolated adapters, not a second in-test scheduler.
- [ ] Introduce the default adapter with identical learned behavior; run existing runner/runtime/recovery tests before connecting the new source. Keep exact pinned program versions and `steps_only` semantics unchanged.
- [ ] Add session-local plan backend/admission and wire the existing host tick/queue. One active input owner must cover both learned runs and task plans; reject concurrent `step/select/launch` commands that would invalidate the active plan.
- [ ] Run `python -m pytest -q tests/test_task_plan_contract.py tests/test_task_plan_runner.py tests/test_workflow_runner.py tests/test_workflow_runtime.py tests/test_agent_command_dispatch_attempts.py`. Expected: same original execution IDs, one input attempt per ticket and no intermediate Agent callback on an isolated rule-proven happy path.
- [ ] Exercise the public Instant entry with `learning_enabled=false`, empty learning storage and no workbench imports. Extend isolated delivery dependency checks for the new entry; this check does not count as desktop acceptance.

## Task 3: 核验成功直接推进 / Sufficient verification advances the plan

**Files:** Create `app/execution/task_plan_verification.py`; modify `task_plan_backend.py`, and only necessary reusable boundaries in `app/execution/decision_check.py`, `app/learning_memory/runtime_verification.py`. Reuse `app/judgment/service.py`, `app/learning_memory/image_verification.py`, native observation and original receipt validation. Tests: new `tests/test_task_plan_verification.py`; existing `test_execution_decision_check.py`, `test_workflow_decision_verification.py`, `test_decision_service.py`.

**Interfaces:** `verify_task_plan_step(backend, *, run_id: str, request_id: str, execution_request_id: str) -> dict` returns `verdict`, `judged_by`, bound evidence and original receipt references. `TaskPlanBackend.record_verified_result(...)` accepts only revalidated local proof or authenticated Decision results, settles the current ticket once, and exposes the next step to the same runner. Agent review has distinct provenance and the original wait binding.

- [ ] Add `test_local_proof_success_makes_zero_decision_calls`, `test_adopted_decision_advances_without_agent_review`, `test_shadow_never_auto_advances`, `test_uncertain_timeout_missing_key_or_budget_waits`, `test_success_after_cancel_does_not_dispatch_next`, `test_repeat_status_never_resends_decision`, `test_player_visible_is_not_playing`, `test_dynamic_output_cannot_be_fabricated_by_predicate`.
- [ ] Define a single evaluation chain: sufficient current native rule / pinned image check → explicit Decision condition → Agent on uncertainty. Binding/evidence failures stop before any semantic fallback. Reuse original final evidence; obtain a second fresh observation only for a declared temporal predicate. Input-sequence verification wraps the completed sequence; it does not claim existing batch routes suddenly gained before-action Decision support.
- [ ] Apply frozen exact auto allowlists and existing thresholds/authentication; plan budgets only tighten the host cap. One paid request per semantic checkpoint by default; no retry or post-hoc automatic allowlisting. Record enclosing judgment time including encrypted final persistence.
- [ ] Run `python -m pytest -q tests/test_task_plan_verification.py tests/test_execution_decision_check.py tests/test_workflow_decision_verification.py tests/test_decision_service.py`. Expected: success advances once; uncertainty/failed evidence pauses; originals remain recoverable without a key or new dispatch.
- [ ] Verify public MCP→queue→runner→verification→next-step integration offline. Existing learned image-first behavior and explicit Agent assertions must retain their meaning. Document that a boolean outcome does not plan, locate or extract text.

## Task 4: 减少不必要的视觉定位 / Avoid unnecessary grounding calls

**Files:** Create `app/execution/task_plan_target.py`; modify `app/vision/agent_command_jobs.py` only at current-target selection; reuse `app/learning_memory/runtime_target.py`, `app/core/local_control_target.py`, `app/operation/recognition/control_target.py`, `native_control_hit_binding.py`, and current UIA provider. Tests: new `tests/test_task_plan_target.py`; existing `test_agent_grounding_execution.py`, `test_field_focus_geometry.py`, `test_workflow_target_bindings.py`.

**Interfaces:** `resolve_task_plan_target(coordinator, *, step: dict, binding: dict) -> dict` returns `resolved|miss|ambiguous|invalid`, current evidence identity and target proof. `resolved` must feed the existing gated local-control/memory path; preserve `windows_uia`/recipe provenance instead of claiming an Agent generated it. No caller-supplied historical x/y values.

- [ ] Add `test_unique_current_uia_target_skips_visual_handoff`, `test_duplicate_label_requires_grounding`, `test_navigation_invalidates_old_target`, `test_wrong_window_or_dpi_binding_rejected`, `test_pinned_recipe_revision_unchanged`, `test_unknown_goal_uses_existing_visual_route`.
- [ ] Use existing pinned recipe resolution first when supplied; otherwise use explicit structured name/type/container criteria on current evidence. If no trustworthy unique result exists, continue through the configured original visual provider. Provider exceptions/protocol corruption remain errors, not silent misses.
- [ ] Keep dynamic labels resolved from this run's typed parameters/verified outputs; copy only semantics across steps. Do not use a previous screenshot's coordinates or a local image-verification score as target proof.
- [ ] Run `python -m pytest -q tests/test_task_plan_target.py tests/test_agent_grounding_execution.py tests/test_field_focus_geometry.py tests/test_workflow_target_bindings.py`. Expected: known unique targets produce zero visual handoffs, novel/ambiguous ones retain explicit handoffs, all actual clicks pass the same action gate.

## Task 5: 减少客户端空档与本地重复观察 / Client and observation overhead

**Files:** Modify the maintained `skills/codex-vision-session/SKILL.md`, relevant sections of `AGENT_GUIDE.md`, `scripts/learning_benchmark_client.py`, `app/execution/conditional_observation.py` and current browser-content observation only where profiling identifies redundant work. Tests: `tests/test_learning_benchmark_client.py`, `test_grounding_handoff.py`, `test_conditional_observation.py`, `test_browser_content_readiness.py`, `test_uia_snapshot_ancestry_cost.py`, new `tests/test_task_plan_client.py`.

**Interfaces:** Client `run_plan(request_id, command, *, event_callback, total_timeout)` submits once and follows original status IDs, returning only terminal state or actionable handoff. Callback receives a bound pending event; it cannot autonomously invoke Codex collaboration from a Python process. Actual Codex delegation remains client-side, one recorded Sol Ultra worker, one connection.

- [ ] Add `test_ready_result_is_returned_without_fixed_client_sleep`, `test_pending_polls_original_id_only`, `test_grounding_event_delivered_once_per_request`, `test_same_observation_stage_reuses_only_valid_metadata`, `test_input_or_layout_change_invalidates_observation`, `test_uia_io_overrun_reported_not_hidden`.
- [ ] Deliver compact state, exact image reference and timing together. Dispatch/continue promptly; no source research, full-log dumping or duplicate screenshots between healthy steps. Preserve bounded waits and event-driven early return; do not busy-poll or treat a wait timeout as cancellation.
- [ ] Reuse already-valid UIA metadata only within the same observation generation. Keep mandatory live pre-input revalidation. Remove a repeated whole-tree scan only after proving which consumer can use the same bound evidence; do not globally shorten capture/visibility checks.
- [ ] Use existing conditional observation for explicit reliable markers. Keep default 2 s behavior elsewhere; do not call a polling budget a hard COM/network deadline. Defer generic ROI uploads, a new autonomous planner and lower model effort until matched measurements justify them.
- [ ] Run `python -m pytest -q tests/test_task_plan_client.py tests/test_learning_benchmark_client.py tests/test_grounding_handoff.py tests/test_conditional_observation.py tests/test_browser_content_readiness.py tests/test_uia_snapshot_ancestry_cost.py`. Read back maintained skill changes; if installing the personal copy, back it up and verify loading separately from existing-session state.

## Task 6: 流程与收益验收 / Correctness and latency acceptance

**Files:** Complete `scripts/benchmark_execution_plan.py`; add `tests/test_execution_plan_benchmark_scoring.py`, `tests/fixtures/execution_plan_app.py`, `docs/verification/CONTINUOUS_EXECUTION_ACCEPTANCE.md`. Update affected `README.md`, `docs/development/DECISION_API.md`, `AGENT_GUIDE.md`, local current/next/summary docs when behavior is implemented, never ahead of it.

- [ ] Add scoring checks before live runs: wrong target/content, player loaded but paused, delayed content, stale/occluded frame, interrupted host, API uncertainty, duplicated callback and successful cleanup. Fixture truth must be independent of the runtime's own success verdict. Published screenshots, learned assets and run history cannot become acceptance inputs.
- [ ] Compare three explicit configurations: A = repaired ordinary step-by-step Agent flow; B = short plan with equivalent semantic verification and the same grounding route; C = same plan plus this round's freshly learned or native reliable targets. B−A isolates orchestration; C−B isolates target reuse. Do not mix lower reasoning effort, weaker verification or a different provider into the main claim.
- [ ] Per comparison use at least 10 alternating matched pairs across two same-session blocks (5 pairs each), plus 3 cold-start runs per relevant configuration. Report each result, median, range and first-attempt/recovery status; p95 from this small desktop sample is exploratory. Use at least 100 offline scheduling transitions for the provisional 500 ms p95 enqueue target. End-to-end ≥50% median improvement on reusable paths is a goal, not a promised result.
- [ ] Separate actual paid Decision samples from offline scheduling samples. Start with a declared maximum of 4 paired semantic cases × 2 modes × 2 checks = 16 paid POSTs for the first comparison slice; fewer checks reduce use. Before further paid slices record a separate bounded budget under existing authorization. No extra calls for polling or unknown outcomes. Missing main-model token telemetry remains unknown, not zero.
- [ ] Main first completes unit/contract coverage, real single operations, then continuous same-window runs covering changed query/data, safe dialog interruption, cancellation, explicit recovery and cleanup. Do not claim automatic cross-window or dead-host continuation. Use the project capture/action interfaces; for the video scenario verify correct official content and progressing playback, leaving playback open only if requested.
- [ ] Freeze one candidate after relevant repairs, then Sol Ultra independently verifies the same payload. Preserve original failures and corrected reruns. No repeated installers for script/observer changes. Build/release only as a separate explicit delivery step after the results are reviewable.
- [ ] Publish the scoped report with task completion rate, false-success/false-failure/uncertain counts, automatic coverage, Agent interventions, actual provider calls/tokens, elapsed-time layers and limitations. Existing browser-demo failures remain linked; a successful rerun must not erase them.

## 最先执行的切片 / First implementation slice

首个里程碑已通过：**没有学习工作台、没有旧学习资产，一个新数据两步任务只提交一次；两个效果经真实 Decision 核验后连续完成，中途无审核 callback。** 此后 browser03 单项修复、最终候选 BC02 同口径原生目标比较、continuity02 与 notice01 连续显式恢复及清理也已通过，原失败分别保留。同冻结候选独立 Sol fresh 三组已通过；本轮短计划源码里程碑与 Main 新安装版流程通过，最终发布状态按上方记录，不把混合远期条件的 checkbox 全部勾完。

Main's scoped final-candidate loop optimization and the independent Sol fresh group passed with original receipts, independent effects and cleanup. The short-plan source milestone and Main installed journeys passed; final installed-independent and publication status belongs in the release record. Browser preparation scans, bounded dynamic outputs/learned references, three cold runs per configuration, 100 scheduling transitions and a real Main-model baseline remain future work; original failures and required visual handoffs stay separate.

## 本次计划校验 / Planning verification

上方记录当前证据；混合实现与完整验收的勾选项须全部条件闭合后才能关闭。静态通过、离线通过、单项通过和连续实机通过分别报告。 / Mixed implementation/acceptance checkboxes close only when all conditions are met. Static, offline, single-action and continuous live evidence remain distinct.
