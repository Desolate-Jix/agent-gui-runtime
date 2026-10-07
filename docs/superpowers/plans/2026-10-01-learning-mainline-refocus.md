> **当前排程已替代 / Scheduling superseded (2026-10-03):** 当前执行只遵循[有限试用收尾计划](2026-10-03-learning-trial-closeout.md)。本文件是历史计划与证据快照，以下 Goal、优先序及复选框不作为新的试用门槛；收益采样及广泛恢复后置，原始验收事实与限制保留。 / Follow the linked closeout plan. This historical plan preserves evidence; its goals, ordering and checkboxes do not create current trial prerequisites. Benefits and broad recovery are deferred.

2026-10-03 T16 后续：`resume_unexecuted` 已补到公开接管预览和共同恢复层；只允许原任务 cancelled、动作事实 false、空派发尝试且完整新观察确认目标效果未完成。接管仅保留已验证上游，原步骤不伪造成功，提交停在 takeover_ready，明确继续才产生新执行 ID。首次继续核验完整初始状态；之后新增历史必须由原命令/回执重建，runner 进度漂移及终态加遗留等待均拒绝。Main 374 项相关回归早于最后终态窄改；最后改动的 125 项直接相关回归通过，不累加。原 T16 零输入事实只读复验通过，163 文件未变；这是源码/合同通过，非实机接管。T16 原窗口/PID 已退出，原正常结束入口确认 cleanup_verified=true、driver exit 0；支持的正常重连尚未执行；普通恢复选择 UI、完整续跑/弹窗/连续清理、同冻结独立实机、桌面像素/真人与交付仍待。保留首次失败，正式 v0.1.1/UI v14 不改，收益未知后置。 / T16 follow-up implements explicit unexecuted-step continuation in public takeover previews and shared recovery. Only cancelled zero-input originals with empty dispatch attempts and a complete fresh observation proving the effect absent qualify. Import preserves verified upstream history, never invents success for the interrupted step; commit pauses, and explicit continuation creates a fresh execution ID. Initial state and all later receipt-backed history are revalidated; runner progress drift and terminal states retaining waits are rejected. Main's 374 related checks precede the last terminal-only repair; its final 125 direct checks pass without adding totals. Read-only replay validates the original T16 no-input facts with 163 files unchanged. This is source/contract evidence, not live takeover acceptance. The original window/PID is absent and the supported finish path verifies cleanup with driver exit zero; normal reconnect, ordinary recovery-choice UI, full continuation/modal/continuous cleanup, same-freeze independent live review, native pixels/human use and delivery remain open. Preserve first failures; stable v0.1.1/v14 stay unchanged and benefits remain unknown/deferred.

当前优先序：T16 原窗口和旧连接已经正常收尾（cleanup_verified=true、driver exit 0），原失败和取消票据保留；下一步从支持的正常重连入口载入修复；不热改原 MCP、不改写原证据、不把新连接计为原连续通过。未执行步骤的明确继续源码/API 已完成，下一步接入普通工作台恢复选择，并用全新低风险内容核验原待处理边界：终态结算 → 同窗口新 epoch → 当前效果与明确处置 → 新执行 ID 续跑 → 剩余步骤、弹窗、完整收尾 → Main 同冻结复验后独立实机复测。已完成效果接管与未执行步骤继续必须区分；不确定输入或观察仍暂停。正式 v0.1.1/UI v14 不变；收益后置、桌面像素/真人/交付仍待。 / T16's original window and connection now finish normally with verified cleanup and driver exit zero; retain failures/cancelled tickets and load the repair through supported normal reconnect next. Do not hot patch the original MCP, rewrite evidence or count a new connection as the original continuous pass. The explicit unfinished-step source/API path is implemented; next wire ordinary workbench recovery choices and validate fresh low-risk original-pending recovery through settlement, same-window epoch, current-effect choice, fresh-ID continuation, remaining steps/modal/full cleanup and same-freeze Main then independent live review. Keep successful-effect adoption distinct from unexecuted-step continuation; unknown input/observations remain paused. Stable v0.1.1/v14 are unchanged; benefits/native pixels/human/delivery remain open.

2026-10-03 T9：普通目标规则修改、重新待审、Agent 审核和保存重开后，Q57、R83 及恢复后的完整 R83 三轮四步任务通过。一次重复运行的末步因 180 秒识图等待超时而失败，未派发输入；原失败保留，另建单步恢复运行收尾，不算原运行通过。独立界面已完成新采集、编辑保存、确切版本读取和 Agent 重新定位后的实际复用。 / T9 verifies ordinary rule editing, pending review, Agent review and reopen through three successful four-step Q57/R83 runs, including the full rerun after recovery. One repeated run retains its final-step 180-second grounding timeout with no input. A distinct one-step recovery completes cleanup without rewriting that failure. Fresh standalone capture, versioned edits, pinned reading and Agent-assisted fresh grounding/reuse pass.

当前仍是源码候选：884 个冻结文件未变，正常关闭与原进程/窗口退出已核对；T10 因 Agent 读图误判未通过，T11 全新数据限定独立复测已由 Main 核验通过；T12 实际窗口正常载入和关闭，但原生取图两次超时，桌面像素、真人易用性和限定弹窗/宿主中断恢复仍待。模型、准确率和速度收益未知；正式 v0.1.1、UI v14 未改，未打包发布。 / This remains a source candidate: all 884 frozen files match, and normal cleanup/process/window exit are verified. T10 retains an Agent-inspection failure; Main verifies T11's bounded fresh-data independent pass. T12 loads/closes the actual window normally, but native capture twice times out; native pixels, human usability and bounded modal/host-interruption recovery remain open. Model, accuracy and speed benefits are unknown; stable v0.1.1/v14 remain unchanged without packaging/publication.

本轮只关闭 Main 对应限定路径，不改完整验收复选框；保留 T10 首次失败；T11 限定结果已核验，真人、桌面视觉、限定恢复与收益仍分别待核验。 / Close only Main's bounded paths; keep full acceptance checkboxes unchanged and retain T10's first failure. T11's bounded result is verified; human/native-visual, bounded-recovery and benefit gates remain separate and open.

[试用核对 / Trial review](../../verification/LEARNING_TRIAL_READINESS.md)

## 2026-10-03 T7独立限定旅程已核验 / T7 independent bounded journey verified

T7独立限定旅程经Main核验 PASS_WITH_RECORDED_CALLER_FAILURES：全新四步教学、普通Qt参数/ensure_selected语义修改pending、Agent审核四步、三版保存重开，以及V56/V56重复/W90三轮completed、编辑态零输入拒绝和正常清理均通过；884冻结文件一致，human_review=false。 / Main verifies T7 independent bounded journey as PASS_WITH_RECORDED_CALLER_FAILURES: fresh four-step teaching, ordinary Qt parameter/ensure_selected semantic editing to pending, four-step Agent review, three-version save/reopen, three completed V56/V56-repeat/W90 runs, no-input editing refusal and normal cleanup; all 884 frozen files match, with human_review=false.

仅此独立场景通过，非真人、全产品、收益或发布验收。下一主线收拢普通入口、桌面/真人易用性与试用结果；更广已审核→语义修改失效传播实机覆盖及独立界面完整旅程仍待。收益unknown后置，正式v0.1.1/UI v14不变，不打包发布；499早于最后窄改，后续57窄测不累加。 / This is a bounded independent pass, not human/full-product/benefit/release acceptance. Next consolidate ordinary entry, desktop/human usability and trial results; broader live review invalidation after semantic editing and the complete standalone-interface journey remain open. Benefits stay unknown and deferred; stable v0.1.1/UI v14 are unchanged, with no packaging/publication. The 499 run precedes the last narrow edit; subsequent 57 checks are not added.

[Main原审计 / Main original audit](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-transfer-07-independent-selection/main-final-audit.json)

## 2026-10-03 Main T6限定场景通过 / Main T6 bounded scenario passes

Main T6限定场景已通过：全新四步教学、普通Qt参数化ensure_selected、Agent审核保存重开；M63、重复M63、P91三轮四步completed，首步真实输入true/false/true，rename状态明确零输入拒绝并结算failed，正常清理。884冻结文件未变，审计固定867本轮文件SHA；保留schema extra target未入队及stale wait拒绝两项调用方失败，不声称首次全部无错。 / Main passes the bounded T6 scenario: fresh four-step teaching, ordinary Qt ensure_selected parameter editing, Agent review/save/reopen, three completed four-step runs with actual first-step input true/false/true, explicit no-input rename refusal settled failed, and normal cleanup. All 884 frozen files remain unchanged; the audit hashes 867 current-round files. Retain the unqueued extra-target schema rejection and stale-wait caller rejection; no error-free first attempt is claimed.

下一步是同一冻结候选独立复测；真人易用性、普通桌面视觉、试用结果与交付仍待，收益unknown后置。499项合并回归早于最后窄改，随后57项窄测不累加；正式v0.1.1/UI v14不改，不打包发布。 / Independent retest of the same frozen candidate is next; human usability, ordinary desktop visuals, trial results and delivery remain open, with benefit unknown and deferred. The 499-check regression predates the final narrow edit; the subsequent 57 checks are not added to it. Stable v0.1.1/UI v14 remain unchanged, without packaging or publication.

[Main原审计 / Main original audit](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-transfer-06-selection/main-final-audit.json)

# Learning mainline refocus Implementation Plan / 学习主线重排计划

## 2026-10-03 ensure_selected 接线已实现，待实机连续回归 / Wiring implemented; live continuous regression pending

ensure_selected 的普通UI、运行、Trial、规则验证、恢复和归档接线已实现：已选且非编辑才允许零输入，未知/编辑拒绝，普通click不变；真实 action_executed=false 与 command成功分开。内部capture_loader仅读取归档原PNG字节，不访问原磁盘；memory_selection_satisfied不给memory_execution_hit收益资格，正式收益unknown后置。 / ensure_selected is implemented across ordinary UI, runtime, Trial, rule verification, recovery and archive consumption: only selected non-editing state permits no-input completion; unknown/editing is rejected and ordinary clicks retain their contract. Actual action_executed=false remains separate from command success. Internal capture_loader reads archived original PNG bytes without original-disk access; memory_selection_satisfied does not gain memory_execution_hit benefit eligibility, and measured benefit remains unknown.

Main亲跑23模块合并回归499 passed / 65.62s（TP/main-selection-combined.xml）；随后审阅发现归档未复算额外success_conditions，真实RED 1 failed后修复，新8+旧49=57 passed / 1.06s（main-selection-condition-red/green.xml），已选状态不替代业务成功。499发生于最后窄改之前，两批不累加、不称最终冻结；Main仍在只读审阅。 / Main runs 23-module regression: 499 passed in 65.62s. Subsequent review finds archive validation omitted extra success_conditions; one actual RED failure precedes the repair, followed by 8 new plus 49 existing checks, 57 passed in 1.06s. Selected state does not replace business success. The 499 run predates that final narrow edit; results are not added together or presented as a final freeze, and Main review continues.

T6仅准备、未启动，无修复后实机/独立通过；下一优先序是Main全新实机单项与同会话连续回归（重复M63、换P91、rename拒绝和收尾）→同一冻结候选独立复测。T5原失败及T4限定范围保留；UI v14/独立正式v0.1.1不变，不打包发布，未到试用发布。 / T6 is prepared but unstarted, with no post-fix live or independent pass. Main fresh single-operation and same-session continuous regression must precede independent retest of the same frozen candidate. Preserve T5 failures and T4's scoped pass; v14/separate stable v0.1.1 remain unchanged, without packaging/publication or trial-release readiness.

[当前细节与待实机计划 / Current details and pending live plan](../../verification/LEARNING_NATIVE_TRANSFER.md)

## 2026-10-03 三态探针完成，显式选择实现中 / Three-state probe complete; explicit selection in progress

三态探针已完成并正常清理：SelectionItem=true仍可能处于rename，虚拟Edit焦点不能判定编辑状态。正在实现明确的 click.selection_intent=ensure_selected，经原gated路径：已选且无编辑可无输入完成，未选中重验后再输入，未知拒绝；当前源码已不等同v20冻结，尚无修复后实机或独立通过。正式v0.1.1和UI外观未改，不发布；T5原失败及六部分分析保留，T4仅在限定范围通过。 / The three-state probe completes with normal cleanup: SelectionItem=true does not exclude rename, and virtual Edit focus cannot identify editing. Explicit click.selection_intent=ensure_selected is being implemented through the original gated path: selected without editing may complete without input, unselected requires revalidation before input, and unknown is rejected. Current source no longer equals frozen v20; no post-fix live or independent pass is claimed, with unchanged stable v0.1.1/UI appearance and no publication. Original T5 failures and their six-part analysis remain recorded, alongside the limited T4 pass.

[三态原证据 / Three-state findings](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-row-selection-probe-01/THREE_STATE_FINDINGS.md) · [T5失败分析 / T5 failure analysis](../../verification/LEARNING_NATIVE_TRANSFER.md)

## 2026-10-03 T5 independent acceptance failed / T5 独立验收未通过

本计划T4 Main范围链通过，但T5独立验收未通过：首次调用方断边及分支修正后rename/open业务失败均保留，正常清理不代表任务成功。先完成共同契约调查、产品修复和Main相关单项/连续回归，再同候选独立复测；真人/试用结果/收益/交付仍待。原记录见 [迁移文档](../../verification/LEARNING_NATIVE_TRANSFER.md)。 / T4 passes the Main scoped chain, but T5 independent acceptance fails; preserve both caller adjacency failure and rename/open business failure after correction, since cleanup is not task success. Shared-invariant investigation, repair and Main single-operation/continuous regression precede same-candidate independent retest. Human/trial results/benefit/delivery remain open; see the linked transfer record.

审核下拉与摘要现已由Main改为“已审核”，仅workflow_steps_pane.py两处文字；离屏无连接只读重渲染exit0、Main看图正确且库/队列不变，普通桌面整窗视觉仍未验。当前源码仅此1个UI文件与v20实机候选不同，原v20清单未改，无运行语义或版本/包装变更。 / Main has changed both review labels to Reviewed in the single UI file workflow_steps_pane.py; disconnected read-only offscreen rerender exits zero with correct inspected images and unchanged library/queue. Ordinary desktop whole-window visual acceptance remains open; this one UI file differs from the v20 live candidate, whose original freeze stays intact, without runtime/version/packaging changes.

Main下一步先用全新专用探针采未选中/已选中/rename三态，确认可靠原生选择/编辑事实；再在明确选择语义下复用既有already_satisfied/三态观察原语。普通click不猜skip，未知拒绝，不用清空选择/改点/固定Escape掩盖；状态修复尚未实施，不能宣称就绪。 / Main next captures unselected, selected and rename states using a fresh dedicated probe, then reuses existing already_satisfied/three-state observation primitives under explicit selection semantics. Ordinary clicks must not infer skipping; reject unknown state without clearing selection, moving the click point or fixed Escape workarounds. The state repair is not implemented and readiness is not claimed.

## 2026-10-03 T4 v20 Main 迁移完成 / T4 v20 Main transfer completed

T4完成本计划的Main迁移链：全新四步教学、普通控件离屏参数化/Agent审核、保存重开、同会话R57/S83连续复用和清理。当前进入同候选独立验收，真人/试用结果/交付仍待；Agent操作不是人工验收，字体问题已定位离屏环境，实际桌面视觉验收仍待、收益unknown。原证据与历史失败见 [迁移记录](../../verification/LEARNING_NATIVE_TRANSFER.md)。 / T4 completes the Main transfer chain with fresh teaching, ordinary offscreen parameter editing/Agent review, save/reopen, two runs in one session and cleanup. Same-candidate independent acceptance is underway; human/trial results/delivery remain open, Agent work is not human acceptance, and the offscreen font cause is identified while desktop visual acceptance and benefit evidence remain open. See the linked transfer record and retained failures.

## 2026-10-02 本批出口 / Current slice outcome

v20 修复原生行名称待审提议与来源重验：同帧唯一 List/ListItem 下，原执行点必须位于名称等于该行名称的唯一 Edit 子控件；初始 row_name 规则以本次行名为 constant，普通编辑可改为 folder_name 参数。HeaderItem 锚只用于此原生关系；不开放普通 Edit 点击，不加 fallback。Main 120 passed / 43.86s，XML 零 failure/error/skip，冻结876文件（source-freeze-native-v20.json）；相对v19只改 target_recipe_proposal/action_evidence 两生产文件，新增原生行提议回归，并将旧不支持双击样例改为 right。T3 完整四步教学成功，但目标规则为空，未完成普通编辑/复用；Main 的 read_spec 缺 target 且误附 agent_judgment 导致 needs_correction，原失败保留。T3 正常清理见 teaching-gap-audit.json。T4 已开始原 MCP 启动，尚无新实机结论；新教学、普通修改/Agent审核、保存重开、同会话换数据连续复用和收尾仍待验。v14 外观与正式v0.1.1保持，本轮不打包或发布。 / v20 repairs pending native row-name proposals and source revalidation: one same-frame List/ListItem must contain exactly one same-name Edit child hit by the original execution point. Initial row_name constraints use the observed row name as a constant and ordinary editing can parameterize folder_name. HeaderItem anchors are limited to this native relation; ordinary Edit clicks and fallback remain unsupported. Main passes 120 checks in 43.86s with zero XML failures/errors/skips and freezes 876 files. Two production files change from v19, with a new native-row regression and the obsolete unsupported-double test changed to right. T3 completes four teaching steps but has no target recipe, so ordinary editing/reuse remains unverified; the caller's malformed read_spec/agent_judgment correction failure is retained alongside verified cleanup. T4 has begun original MCP startup without new live conclusions. Fresh teaching, ordinary Agent editing/review, reopen, continuous changed-data reuse and cleanup remain open; accepted UI and stable release are unchanged, with no packaging/publication.

用户接受 v14 外观，继续学习开发。P3 限定恢复已在全新 live-06 完整通过：教学、普通编辑/Agent 审核/三版保存重开、动态数据复用、同窗口弹窗、填写已完成后宿主中断、原结算、同一准入到 ready、fresh effect 接管、仅继续 step6、Trial/Runner completed 与正常 cleanup。P4 的明确 Agent 审核及新数据复用因此已有证据，真人审核仍未验。三类共同输入证明修复，Main 151 passed；同一873文件候选，原失败不重评分。[范围与原证据](../../verification/LEARNING_RECOVERY_V17.md)。 / The bounded recovery gate and Agent-edited fresh reuse pass; human acceptance and broader recovery remain open.

下一顺序：全新低风险第三方学习/普通修改/复用/收尾 → 相关 Main 连续回归后冻结同候选独立完整验收 → 真人易用性与候选交付闭合。稳定性优先，收益采样继续后置、标准不变；不重做已闭合 P1/P3，也不声称任意 Windows 状态都能成功。以下旧状态为历史。 / Next validate transfer, independently accept the frozen candidate after Main coverage, and complete human/delivery gates; do not reopen verified slices or make universal stability claims.

## 2026-10-02 最新执行重心 / Latest execution focus

用户最新要求：收益暂且不论，先核验每次运行的稳定性并检查窗口激活失败。当前只关闭有证据的具体缺口，不承诺任意 Windows 状态下每次成功。顺序改为窗口激活与连续选择 → 同窗口完整异常恢复及清理 → 修改规则的完整复用与第三方流程；模型/准确率/速度对照后置，原标准和历史结果不改。 / The user prioritizes stable execution and activation diagnosis. Validate focus, bounded continuous recovery and cleanup before edited reuse and transfer; defer benefit sampling without changing its standards or historical results.

已完成：P1 本批普通学习、同会话两轮复用、缺失停止、普通修正和清理；v9 修复合法 Agent continue 的终态关联，Main 96 项通过，原 live-04 的 165 个文件只读重放未改。P4 规则语义编辑后待审、保存重开及旧版保留已验，明确审核和新现场复用未验。原 live-04 的准入失败和逻辑清理未通过保持原结论；源码修复不等于完整恢复验收。 / Scoped P1 and the v9 continuation-proof source repair are verified. The ordinary rule draft persists and invalidates review correctly, but explicit review and fresh reuse remain open. Original failures stay unchanged and full recovery has not passed.

激活调查：两份原宿主日志先记录连接 Shell 前台线程 47200 的 AttachThreadInput error 5，随后才是 SetForegroundWindow 拒绝。用户未开菜单；事后同 HWND 的 menu=false、DWM cloaked=2 不能倒推故障瞬间的桌面状态。SetForegroundWindow 不保证扩展错误码，不能据5判定目标需管理员权限。已在共同层保留附件线程及阶段证据、清除旧 LastError并标明此错误码不可靠；原前台核验与输入门控不变。 / Original logs identify denied attachment to the Shell foreground thread before foreground rejection. Later desktop observations do not reconstruct the failed instant. The shared diagnostic now preserves earlier thread errors and marks unguaranteed foreground error codes without weakening verification.

本轮验证：Main 44 项相关检查通过；同一原 MCP/宿主、两个自建窗口连续 7 次选窗及截图成功，其中 7 次为确切跨窗口切换，正常清理通过。它不是完整学习任务/恢复验收，也未复现旧 Shell 前台条件。更早 v9 的单窗选窗加三次截图成功时，目标本来就在前台，只证明相应有限路径。 / Main passes 44 focused checks. One original MCP session passes 7 selections/captures with 7 actual cross-window transitions and cleanup. This does not establish full workflow/recovery stability or resolution of the original Shell condition.

证据与限制 / Evidence and limits: [窗口激活稳定性记录](../../verification/WINDOW_ACTIVATION_STABILITY.md)。正式 v0.1.1 不变；本轮未打包、提交或发布。下方按候选保存的旧“当前/下一步”段均为历史，以本节和主线计划为准。 / The stable release is unchanged. Earlier candidate-specific current/next entries below are historical; this section and the mainline plan control priority.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task after development resumes. Bounded Sol delegation may be used under the existing project rules; Main owns integration and live acceptance. No ritual commits, new worktrees or extra approval rounds.

**Goal:** 学习模式是 Agent 能从真实操作中生成、人工能审核和修改、下次能换数据复用的工作流。优先证明三个收益：减少模型使用、提高任务正确率、缩短完成时间。 / Produce editable, reviewable workflows from real teaching and measure model use, correctness and elapsed time.

**Architecture:** 复用既有学习库、不可变程序、工作台、Trial/Runner、MCP 和门控执行器。当前恢复实现作为候选验证，后续实现由完整流程暴露的阻断驱动。 / Reuse maintained storage, editor, runtime and gated dispatch; let observed journey failures determine further implementation.

**Tech Stack:** Python、PySide6、原 MCP/InstantSession、Windows UIA、pytest、原 benchmark collector。 / Existing Python/Qt/MCP/UIA and measurement stack.

**Spec:** [成功标准](../../LEARNING_WORKFLOW_SUCCESS_SPEC.md)；原 T0–T8 保留为[技术参考](2026-09-29-learning-workflow-benefit.md)。本文件是当前优先顺序；不重做已完成项，不改写历史失败。 / This file controls current priority; earlier detailed tasks remain references.

## Global constraints / 全局约束

- 用户于 2026-10-02 恢复“按计划执行”；按本文件最新执行顺序继续，P0/P1 已闭合范围不重做。2026-10-01 暂停/计划调整记录作为历史保留。 / The user resumed execution on 2026-10-02; follow the latest sequence without reopening closed P0/P1 scope.
- 学习树：`<LEARNING_WORKTREE>`，分支 `codex/dev-workflow-editor`；保留已有未提交内容。正式 v0.1.1 已独立发布，学习版本不变。 / Preserve the dirty learning tree and separate stable release.
- 用户已授权低风险实机测试；旧文档“等两次填写确认”等历史状态不再当作当前阻断。仍须核对新鲜窗口、目标和输入证据，使用原门控执行器；高风险行为另按实际权限处理。 / Existing low-risk authorization persists; current target evidence and action gates remain mandatory.
- 使用新数据、新学习资产和低风险目标；日常浏览器配置、扩展、缓存及旧学习资产保持。 / Use fresh isolated test content and preserve everyday data.
- API、当前 Agent、委派 Agent、本地模型是可选路线。本轮用已可用的真实路线，不为验收购置 API 或下载模型；未接决策 API 不阻断主流程。 / Use an available real route without adding provider or model requirements.
- 模型调用未知记未知，token 缺 usage 记 null；交接数、工具数、等待次数不冒充模型调用。 / Preserve telemetry coverage and unknowns.
- Main 完成单项、同会话连续、异常恢复和清理后，再交同冻结候选独立实机验收。原失败保留；仅在准备交付时集中打包，发布另按用户指令。 / Main acceptance precedes independent live testing; retain failures and defer packaging.

## Current evidence / 当前证据

R1a/R1b 已有同窗口学习、完整六步教学、普通编辑保存重开和换数据复用的历史实机证据；不是从零开始。新接管采集/公开控制、runtime 失败来源和重复 epoch 来源链已有源码及持久集成检查，但最新候选完整 GUI 接管仍未通过。 / Prior journeys are retained; latest takeover integration is not live acceptance.

暂停前的窄检查和原 `results.xml` 的 2 failed 保留。恢复后，`20261001-learning-takeover-live-wiring-01/main-final-contracts.xml` 已确认 584 passed；本轮 Main 夹具/客户端 38 passed、worker 夹具 9 passed，集合重叠不相加。849 个 app/scripts/tests 源文件已冻结；P0 已完成，不再扩大为新的源码前置。 / The resumed consolidated run and scoped fixture/client checks pass; P0 is closed without erasing the first failures.

本轮 `20261002-learning-mainline-01/live-p1-01` 已选窗、预览和开始学习；原 `teach-query` 在 focus 等待定位回复超过 180 秒后返回 failed / `_Cancelled`，没有完成六步教学或生成可复用程序。回执的未知输入事实保持未知，不自动重放；`cleanup.json` 确认 cleanup_verified=true、pending_ids=[]，驱动及夹具退出 0。此尝试保留为未完成，不写成 P1 通过，也不凭等待超时推断模型或定位算法缺陷。 / The original teaching attempt timed out while awaiting grounding and remains incomplete; cleanup is verified. Unknown dispatch facts and the original receipt are preserved.

最新 `live-p1-02` 已完成本轮六步真实教学、原 Agent 整理、可见普通编辑保存重开，以及 R-531 的六步完整复用：读取输出与填写规则均为当次 `p1-current-alpha-20261002`。编辑和审核由 Agent 实施，`human_review=false`。首次遮挡导致 CaptureVisibilityError；另一次外部驱动误消费旧 failed 快照，修正仅在驱动，不能算第二个产品运行失败。原失败和读取事件补收记录保留。 / Fresh teaching, synthesis, visible editing/reopening and one six-step reuse are verified, with truthful Agent attribution and original failures retained.

R-745 第二轮完成查询和 Find；Open 原动作 completed/action_executed=true，但尚未审核及读取、填写和核验。本次重心审查通过原 cancel/status 结算为 cancelled，Open 的工作流结论保留 uncertain，不补写 success。原宿主及夹具正常退出，cleanup_verified=true、pending_ids=[]、host_alive=false。两轮连续复用门槛仍开放；下一轮须在同一新现场完整完成两轮，不能拼接两次窗口生命周期。 / The second reuse was explicitly cancelled during this review; original dispatch and uncertain workflow verdict remain distinct. Cleanup passes, while two-round continuity remains open.

最新 live-p1-03 已完成本轮保存版本的同窗口、同宿主、同会话无复位两轮：R-381 读取并填写 continuity-current-a-20261002，重排后 R-590 使用 continuity-current-b-20261002；均六步 completed。R-000 在打开详情前 absent，action_executed=false、dispatch_attempts=[]，下游未执行；普通 Run 输入框改为 R-362 后六步 completed。Main 回读原 Start/Trial/worker/当前读值及填写规则，核验 42 个原始引用 SHA、原图固定引用和三版程序相等；原始图 revision 也可读。收尾 pending_ids=[]、host_alive=false、窗口退出、cleanup_verified=true。849 文件未变的证明只对应本次 P1 收尾、后续 P2 代码改动之前。 / Current continuous reuse, missing-target stopping, ordinary correction, immutable artifacts and cleanup are verified from original evidence before the new measurement-source changes.

P1 范围和限制：Agent 核验编辑/审核能力，真人未审核；普通 UI 显示失败步骤，但具体 absent 原因仍在原回执。已核对语义保存为 pending、审核后保存为 reviewed；此实机切片不另证明再次语义修改后的 reviewed→pending 传播。两轮原 worker 的视觉定位交接为零，规划/判断计量仍不完整，总量/token 继续 null。保存各尝试耗时与等待，但尚无配对，不能用于收益判断。首次审计辅助脚本误读根 error 字段导致 TypeError，原失败保留，修正仅在外部审计器；多余 continue 拒绝也单列调用方错误。详见 live-p1-03/p1-main-audit.json。 / Review attribution, source/physical coverage and caller errors remain explicit; no benefit claim follows from this journey.

## Execution focus / 执行重心

按用户最新指令，收益采样暂停排期，当前先完成实际稳定性出口；既有 P1 不重做，既有终态关联修复不再重复开发。 / Benefit sampling is deferred while concrete stability gates are closed; do not reopen verified P1 or the completed continuation repair.

| 优先级 / Priority | 下一结果 / Next outcome |
| --- | --- |
| 1 | 激活诊断与两个窗口连续切换已完成有限验证；保留旧 Shell 条件未复现的限制，异常必须明确停止 / Retain the bounded activation result and unresolved original condition |
| 2 | 同窗口弹窗、原宿主中断、终态结算、明确接管、余下任务及完整清理 / Complete the bounded continuous recovery journey |
| 3 | 已保存待审规则明确审核后换数据完整复用，之后低风险第三方迁移 / Complete reviewed-rule reuse and transfer |
| 后置 / Deferred | 计量覆盖、新六对诊断及正式收益配额；标准不降低 / Benefit telemetry, pilot and formal quotas remain unchanged |

## Review focus / 审查重点

| 用户会遇到的情况 / Condition | 归属及验收 / Owner and check |
|---|---|
| 新编号、同名行、重排和新详情 / New IDs, duplicate labels, fresh details | P1：选对当前记录，下游使用当次结果；缺失/歧义拒绝 / Fresh identity and dataflow |
| 人工修改规则后保存重开 / Edit and reopen | P1：新版本生效，旧程序与图保留；谁审核按实际记录 / Immutable revisions and truthful review attribution |
| 正向任务被拒绝或需要补救 / Refusal or repair | P2：计失败及全部耗时，不能删样本 / Retain failed attempts and their cost |
| 动作已执行但宿主退出 / Host exit after input | P3：原回执结算、现场效果核验、明确继续、无重复输入 / Original settlement without replay |
| 新第三方应用 / Fresh external application | P4：普通入口完成任务；夹具专用能力单列 / Generality and usable entrypoints |

## P0 — Close the current candidate / 收尾当前候选

**Files:** `tests/test_agent_command_protocol.py`、`tests/test_workflow_takeover_public_recovery.py`、本轮原测试清单、受影响文档；产品只修改实际失败的共同路径。 / Restrict edits to reproduced failures.

- [x] 回读暂停前最后产物和源文件；两个夹具已有绿色证据，不重新把它们列成待开发功能。 / Reconcile the final pre-pause artifacts.
- [x] 用证据根内 `run_final_contracts.py` 完成一次已列明的相关回归。失败按根因补最窄回归再复测；通过后不为了增加数量重复全跑。 / Complete the existing related test manifest once.
- [x] 同步最新接口和限制、保存候选源文件 SHA 清单；不生成安装包。 / Synchronize current documentation and freeze source hashes.

**Exit:** 已知失败有结论、相关检查通过、文档和候选一致。P0 完成后直接进入 P1，不增加新的恢复架构任务。 / A verified, documented candidate goes directly to the user journey.

## P1 — Complete the ordinary journey / 完成普通用户流程

**Files/entrypoints:** `scripts/run_learning_memory_workbench.py`、`scripts/run_learning_workflow_fixture.py`、原 MCP/学习与运行入口；已有 `tests/test_workflow_guided_journey.py`、`test_workflow_guided_output_journey.py`、`test_workflow_target_journey.py` 按故障选择复用。

- [x] 新 Record Desk/新数据完成查询→唯一记录→详情→读取当前值→填写→核验；原 Agent 对话消费实际学习事件并生成草稿，经可见普通工作台修改参数/目标条件/成功规则、审核保存并关闭重开。从教学、整理到运行都无需用户手贴内部 ID/JSON。禁止内部程序直接构造或答案注入替代生成、读取和编辑验收；历史离屏控件证据单列。完成的是 Agent 验证编辑能力，真人审核仍未发生。 / The fresh teaching/synthesis/visible-editor journey is verified; actual human review is not claimed.
- [x] 同一应用不复位连续复用两轮：改变编号/当前值，再改变次序/位置；运行保存版本，验证确切记录及当次下游值，保留原图、旧程序和流程图。 / Run two continuous fresh-data variations without resetting the application.
- [x] 对缺失或重复目标做一个明确负例；暂停位置和修正入口可理解，用户无需填写内部 ID/JSON。收尾宿主和窗口。 / Validate one missing/ambiguous target and usable recovery feedback, then clean up.
- [x] 同时采集端到端耗时、原始动作/模型证据及等待；分列“人工可审核修改”的产品能力与“真人实际审核”的事实。Agent 可验证编辑入口并继续先导试采，报告真实审核者；不代替用户署名、不标成真人审核。本批已核对语义保存为 pending、审核后保存为 reviewed。 / Separate editable review capability from actual human participation, preserve true reviewer identity and record the verified pending-save to reviewed-save transition.
- [ ] 更广验收仍须验证再次语义修改后的 reviewed→pending 传播及下游影响提示；本批未实机证明，不归入已完成项，也不重新阻塞 P2 先导。 / Later acceptance must verify invalidation after another semantic edit; this unverified scope does not reopen the pilot prerequisite.

**Exit:** 完整任务、普通编辑重开、变化复用及清理可复查。单步通过、离屏通过与真人审核分别记录；不能自动勾选整个 R1/R2。 / Evidence must cover the declared journey rather than substitute isolated checks.

**Next action:** P1 本批出口已核验，转入 P2 实测。保留首次失败及原版本；具体缺失原因的界面提示记后续易用性项，不新增恢复架构前置。 / Proceed to matched measurement without reopening verified implementation or erasing failures.

## P2 — Measure an early comparison / 提前做小规模收益对照

当前 P2：source-v5/cohort-05 的首 A/C 原任务和 finish 都成功，A328.390326秒、C564.687463秒；C本次 step-4.current_detail 绑定 step-5 填写且最终显示 Matches current detail。但C来源覆盖因重复引用为partial，首对继续采集检查点尚未通过；保留原两行结果，停止本候选采余下五对。此计时包含执行者、工具往返、汇报、Main 核验和结算；C最终completed返回后至finish为344.305728秒，主会话收尾明显拖慢，不能归因于模型推理。 / Both first tasks originally succeed, but duplicate provenance references block the collection checkpoint. Keep original rows and stop this candidate before repair; caller settlement accounts for substantial elapsed time and does not identify model inference latency.

共同采集修复已核验：异步returned/running只读准入与真正终态分开；同session原路径规范化去重，原Windows规则引用沿只读索引读取；memory plan绑定原动作goal，附加视觉提示不替代动作语义。Main最终266 passed/10.67s，真实v5原件只读复查coverage=complete、errors=[]，58个唯一快照及原图SHA一致，旧journal/原分未改。部分步骤仍为Agent核验，全规则资格false、总调用/token未知；runtime/client/输入门控和终态评分不变。 / Bound asynchronous retrieval, canonical snapshots and original action semantics are verified by related regressions and actual retained files. Mixed Agent judgment, unknown usage and unchanged original scores remain explicit.

source-v6/cohort-06（849文件、种子2026100206、每路线计划6例/600秒）现已完成4对/8次任务并正常清理；原首对检查点通过，C四例来源coverage=complete、errors=[]，全规则资格仍false。A首次成功4/4，C3/4；C04调用方读取格式化错误经原请求reread补救，最终任务8/8完成，原首次失败与全部耗时保留。稳定两对中位耗时A298.986秒/C246.596秒，描述性节省17.5226%，未达30%目标；模型总调用/token未知，准确率提升未证实。A04后只读审计误展开评分records，执行worker隔离失效；停止余下2对layout，不记失败、不补分、不续采旧清单。原8行、missing4、零unfinished和cleanup证明保留；正式配额不抵扣、真人/独立验收未完成，正式v0.1.1独立不变。 / The closed candidate retains four pairs, eight completed tasks and its original first-success/recovery scores; two layout pairs remain unstarted after post-task oracle exposure. Stable descriptive timing saves 17.5226%, below the target. Call coverage and correctness improvement remain unproven; no formal credit or release change follows.

历史保持：live-03仅准备，零尝试/输入且清理通过；v4/live-04 的 A 实际任务成功，但 Main 给 finish 多传 attempt_id 导致采集器退出，原0行/1unfinished，观察到清理318.975秒；v4/live-05 的 C 到step2，原异步回执被collector错误拒绝，原0行/1unfinished，观察到清理93.068秒。两现场原宿主/runner/窗口均退出，清理核验通过；未补造 finish、未重评分或拼接到v5。v5首C前 Main 只读核验误解 outputs 键的 KeyError 单列调用方错误，之后按真实键更正，耗时未扣除。 / Preparation, unfinished attempts, verified cleanup and caller errors remain separate; no original scores are rewritten or combined across candidates.

现有 agent_current/workflow_metrics、调用方 record_model_call 和公开任务摘要只能提供局部或调用方上报计量，完整规划/定位/核验/补救总量仍未闭合；A普通路线也没有工作流计量范围。总调用/token继续未知，不把工具数、等待或局部0次当总调用。不为计量购置API或换模型，继续测正确率和耗时。 / Existing hooks provide partial coverage only; complete actual call coverage remains open without replacing missing totals with tool counts or buying providers.

**Files/outputs:** 复用 `scripts/benchmark_learning_workflow.py`、`scripts/learning_benchmark_client.py` 及已有 collector；新证据目录保存冻结 manifest、`runs.jsonl`、`comparison.json`、`report.md`。 / Reuse existing measurement rather than build another framework.

**Historical wiring / 历史接线：** 当前 P2：v2 首 A 的现场成功而原采集结算失败已保留；共同 continue 结算修复后，v3 首 A 原 finish 与 Main 核验通过，319.965 秒。C 已通过原 read 重载固定程序与 recipe，前三步核验成功，但第四步内部 read 结果取回被 collector 拒绝，CLI 退出；原读取本身已 returned/agent_read_required，当前输出未提交，step5/6 未执行。原 comparison 保留1行 A 与1个未完成 C，不补造 finish 或把未完成记成功。v3 原宿主/runner/窗口均退出、pending_agent_workers=[]、cleanup_verified=true。 / Original A settlement and visible effects now agree; learned reload and the first three C steps are verified, but the internal read-result boundary interrupted C. The original unfinished attempt and verified cleanup remain intact.

只补共同原结果接线：B/C 内部 EID 必须绑定本 attempt 固定 program/trial/run/step/ticket，真实已派发且返回的 command/response 必须存在并一致；沿原 instant_result 只读取回，保存原 UTF-8/SHA/路径供 replay 复算。未知、跨轮/跨run、未派发、命令/身份/回执漂移拒绝；不重交、不额外截图、不改 runtime/client。原公开回执隐藏 command/result.request 的契约已用原 InstantSession.result 验证。Main 组合199 passed/9.04s，并用 v3 实际第四步原文件和原公开接口核对新准入，通过且旧文件 SHA 未变。保留三段 RED 及调用方 schema/旧 wait/Main 指导错误，不能把测试绿色当作完整 C 实机通过。 / The shared collector now validates and reads only bound original internal results, preserving original evidence and route policy. Main passes 199 related checks and validates the actual retained read through the unchanged public API; full new-candidate C acceptance remains open.

v4 849 文件、新种子2026100203、六对2/2/2 A/C 与600秒预算已冻结，manifest SHA ee1cd6900b1167977b24cffd609a1289f9dbbbb797e15930f11c436f3b7a5217；有效尝试尚未开始，完成配对仍为0。live-03 仅准备原宿主和自建窗口，重心复核时沿原 stop/public close 正常清理；原 journal 只有 opened/closed，没有 begin、工具输入或工作流运行。完整尝试时间为原 begin-after-prepare→finish，含执行者启动/判断/往返/等待/结算。Main Astra、持续 Sol 执行会话的此前普通/未完成学习经验及物理冷暖/服务商身份/usage未知均写入配置。这是 Main 主测，不是独立验收；下一出口是新候选六对完整任务的真实诊断。 / The next six-pair candidate is frozen but not yet started; there are no completed pairs. Attempt timing, persistent-worker history and telemetry limits stay explicit.

- [x] 首对采集前解决已核实的最小兼容缺口：`app/learning_memory/benchmark_manifest.py` 当前只接受正式三类 8/6/6 与 B 配额。为六对诊断增加明确的先导清单类型，沿原 freeze/collector 收据链运行；在 `tests/test_benchmark_manifest.py` 验证先导可冻结、正式不足配额仍拒绝、先导不能作为正式验收或抵扣配额。只修改该阻断及必要调用方，不新增 benchmark 框架、不填充假样本。 / Add a distinct pilot cohort with narrow regression coverage while preserving formal validation and provenance.
- [x] 采第一对前冻结 manifest：候选 SHA、模型路线、任务/种子/输入/初态、允许介入、超时及计分、计时起止、模型计量覆盖和成功规则。先固定一类完整任务的 6 对 A/C：稳定 2 对、新参数/当前值 2 对、次序/布局变化 2 对；不使用训练样本，A 不读学习资产，C 固定明确审核版本并记录实际审核者。相同模型/初态/成功条件，交替顺序；学习、人工等待和冷暖成本独列。 / Freeze conditions and scoring before six matched diagnostic pairs, with held-out inputs, truthful review attribution and no baseline access to learning assets.
- [x] 冻结计时具体边界：原 collector 在初态准备结束后的 begin→最终 finish（含当前效果观察）作为完整尝试耗时，包含执行者启动、判断、工具往返、等待、补救及结算，不能解释成纯动作或模型推理时间。初态准备、学习、宿主冷启动和最终清理独列，清理仍是验收门槛。统一600秒预算依据已验证路径选定，180秒草案不自动生效。原首次尝试为主配对，明确重跑另列，失败、等待和补救不删；工具事件并集不替代完整尝试耗时。 / Measure the original begin-after-preparation through final finish, including worker start, decisions, tool round trips, waiting and settlement; keep setup and cleanup separate and never equate this duration with model or action time.
- [x] 第一对完整 A/C 作为继续采集检查点：C允许固定程序已声明的规则+Agent混合核验，需来源完整无技术errors；remaining_action_agent_judgment及全规则资格false保留，不把先导改称全规则正式验收。Main 核对原 begin/finish、C 六步终态、当次读取→填写→核验、原 replay、无未决请求与实际窗口结果。通过后按冻结顺序继续余下五对；不换任务、不删失败、不调整600秒预算。检查点只要求原请求结算，不在批次中途关闭宿主；批次结束或失败退场才做完整进程/窗口清理。源代码若须修复，保留本候选全部尝试并清理，另冻候选，不能拼接成绩。 / Validate the first complete pair and settled original requests before proceeding in the same frozen order. Keep failures and budget; perform full lifecycle cleanup at batch end or failed exit, and never combine different source candidates. v6首对原replay已通过；本候选后因事后审计隔离失效正常停止，不续补余样本。 / The new first pair passes; later audit exposure closes this cohort without backfilling.
- [x] 已完成现有公开调用端的只读计量可行性核查，完整计量未闭合，后续接线仍待；六对诊断后、正式扩大前复核可用范围。原要求：只读核查现有真实调用端能否提供完整规划/定位/核验/补救调用和 usage；可用则明确接线范围，不可用则明确缺口并保持总量/token 未知。此核查不购买 API、不换模型、不新增统计框架，也不阻塞当前正确率和耗时诊断。 / Check existing caller telemetry before formal expansion; preserve unknown totals without buying providers, changing models or adding a measurement framework.
- [ ] 原命令/回执核对实际策略；成功率包含全部有效尝试，产品阻塞、失败及超时不删除。耗时同时报告全部尝试和双方均成功的配对；计入补救及等待期间额外判断，负向与恢复另计。报告错误点击、补救、完整耗时及可观测规划/定位/判断调用。无完整模型计量就明确总量未知；不因此停掉正确率和耗时测量。 / Retain failures and timeouts, report all-attempt and common-success timings, count extra judgments and separate negative/recovery sets; preserve unknown usage.
- [ ] 给出三个独立结论：已观察改善、未改善或证据不足，以及当前最大的耗时/错误来源。6 对只判断开发方向，不判定原 50%/30%/95% 目标或稳定 P95 已达到。 / Use the pilot diagnostically, not as final benefit acceptance.

**Exit:** 立即交第一份真实配对诊断，不等待 P3/P4 全部完成。若没有收益，先修实测主因并新冻结、重测受影响集合。六对先导是完整复合任务的诊断集，不自动抵扣原 R4 三类各 20 对 A/C、每类 5 对 B；扩大前另冻结三类及 8/6/6 分层。原总调用降 50%、稳定任务中位耗时降 30%、各类 P95≤基线 110%、正向成功≥95%且不退步目标保留；满分基线只报正确率持平，不能改题制造提升。 / Deliver the pilot report promptly, retain distinct formal cohorts and unchanged targets, and never promote parity into an accuracy gain.

本轮P2收尾：4/6对已完成，2/6对layout未开始；原四对仅诊断，不把全部任务最终成功当首次成功。先导完整六对出口仍开放，下一批另冻新种子/新当前值并披露旧会话经历。执行worker不承担原journal事后审计，Main/只读审计者仅向其提供白名单命令回执与当次PNG，原oracle留在隔离审计范围。 / Four pairs close this cohort; the full six-pair gate remains open on a new freeze with isolated audit roles.

## P3 — Validate bounded interruption recovery / 核验限定范围的恢复

T15 更新 / T15 update (2026-10-03): 共享 launch/close 归属缺口已修复；Main 344 项相关回归通过，887 文件候选冻结不变。全新同一 MCP 已实际完成新窗口 launch、正常 stop、原准入 starting→ready、凭原 launch 证据关闭同一 PID/HWND、driver exit 0。只闭合此生命周期收尾，不抵扣原 runner ticket 接管、剩余步骤、弹窗或完整 P3；T13 原失败/未清理窗口保留。下一实机从原 awaiting_grounding 等可观察待处理边界验证。[证据与边界](../../verification/RECOVERED_LAUNCH_CLEANUP.md)。 / T15 accepts bounded recovered launch cleanup on the unchanged inherited 887-file freeze after 344 Main checks. It does not accept original-ticket takeover, remaining workflow actions, modal recovery or complete P3; preserve T13 failures and use an observable pending boundary next.

T13 更新 / T13 update (2026-10-03): 已完成动作 adopt+stop 最终被规则结算到 step-3，ticket=null，未证明原终态结算/接管。另发现 capability_unknown 前置拒绝缺正式证明；共享主路径补 typed 回执，Main 166 项源码回归通过，新候选重冻，旧字符串仍拒绝。下一实机使用全新内容和原 awaiting_grounding 等可观察边界；不继续用时序竞速、不修改旧账本、不抵扣弹窗/同窗口结果/剩余动作/收尾验收。[原事实与修复范围](../../verification/VISION_ADMISSION_RECOVERY.md)。 / The completed-action stop probe leaves no ticket and proves no takeover. Shared admission gains typed proof with 166 Main source checks; legacy strings still reject. Fresh testing uses an observable original pending boundary without race-based acceptance, ledger rewriting or omitted modal/effect/action/cleanup gates.

当前限界：合法 Agent continue 的原 request/response、worker、唯一派发回执与 grounding 互证已完成，Main 96 项及原证据只读重放通过。多次派发若无法证明较早回执仍拒绝；不重放输入、不回填旧失败。完整同窗口接管、继续和清理仍待实机验证，现在优先于收益采样。 / The strict continuation proof is repaired and verified; unprovable earlier dispatches remain rejected. Full same-window takeover, continuation and cleanup remain the next live gate before benefit sampling.

**Interfaces:** 复用 `WorkflowTerminalRecovery`、`instant_recovery_preview` / `instant_recover_session`、原 `learning_workflow` 的 `takeover_preview` / `takeover_commit` / `continue`；不新增执行后端。 / Use existing recovery and dispatch.

源码边界说明：公开 manual Trial 能留 pending，但 terminal recovery 要求原 runner ticket；自动派发后的 tick 没有稳定的完成后未核验屏障。输入 worker 是 runner 内 daemon 线程，杀 runner 不能保证未结束输入仍产出终态，这个线程/屏障结论来自只读源码。live-02 已实际验证“完成的手动输入被 Runner 接纳→所属宿主中断→原终态结算”，随后准入实机失败；不能扩大为自动派发中途恢复通过。真实故障保留 unknown/refusal，不新增暂停协议或放松门控。 / The thread/barrier limit comes from source inspection. Live-02 verifies adoption of completed manual input, actual host interruption and terminal settlement, followed by failed admission; it does not establish recovery during automatic dispatch.

- [ ] 同一低风险应用连续任务覆盖一个活动弹窗、一次原宿主中断、原终态结算、同窗口实例当前效果核验、明确接管后继续剩余步骤及完整清理。全程使用原请求/账本并检查无重复输入。 / Validate a complete bounded interruption journey on the same window incarnation.
- [ ] 从普通界面或当前 Agent 对话完成恢复；若必须让用户手工传协议 ID，记录并修复这个实际易用性缺口。 / Make recovery usable through normal controls/conversation.
- [ ] 仅修本场景实际阻断。应用进程重建/新窗口实例、更多层重复硬中断和通用重绑定进入后续积压；现有来源链代码保留，不扩建也不删除。 / Defer broader recovery scope while preserving current implementation.

**Exit:** 任务与清理均成功，原未知输入不变成成功，失败重跑保留首次记录。此出口只证明限定恢复范围，不宣称任意应用重启恢复。 / Explicitly scope the recovery claim.

## P4 — Trial readiness and measured expansion / 试用就绪与后续扩展

- [ ] 一条已有文本规则优化：先确认当前 UIA/截图能证明动态目标与结果，再通过普通入口编辑；验 reviewed→pending、明确审核、保存重开、换数据完整复用和旧版本不变。保持当前详情读取与下游值绑定；不同时替换多个 Agent 判断，不以少一次审核推定少一次模型调用。代码若改变，仅修共同现有路径并跑相关检查；规则/源码变化后另冻候选。 / Validate one existing text rule through the ordinary editor, semantic invalidation, explicit review, reopen and fresh reuse. Preserve current-detail dataflow and old revisions; fewer judgments do not prove fewer model calls.
- [ ] 新六对采集前只做一次完整调用计量可行性核对，记录 A/C 各规划、定位、读取、判断及补救的实际覆盖；无法观测的总量/token 保持 null，不买 API、不另建采集框架。固定起止/超时/首次失败/补救/最终清理口径，正常任务终态及时 finish，不在计时窗插入审计、源码搜索或文档工作；调用方空档不归因模型推理、不事后扣除。 / Before fresh sampling, check actual coverage once, retain unavailable totals as null and freeze timing/settlement boundaries. Finish promptly; keep caller delays in the original clock.
- [ ] 新独立 cohort 固定六对 A/C（稳定、未见参数/当前值、布局/次序变化各两对），新种子/新值、同源候选与明确背景；执行者只看任务和现场，原始评分只由 Main/只读审计消费。先核验首对的原 finish、来源、无重放及未决，再采余下五对；完整报告分母、未开始与全部失败/补救成本。旧四对和停止的两对不续采、不拼分。此先导仅诊断，不抵扣正式配额，不能单凭不同 cohort 的前后数字宣称单规则因果收益。 / Freeze a separate six-pair cohort, isolate actors from scoring, validate the first pair before five more and preserve all costs and missing cases. Pilot credit stays zero; cross-cohort changes do not establish causal gains.

- [ ] 正式扩大前根据上述可行性核查单列模型收益闭合任务：让 A/C 真实路线的规划、定位、核验与补救调用具备完整可核验计量；不能用工具数、交接数或局部 0 次结案。若现有调用方无法提供完整证据，保留总量/token 未知及未完成状态，继续可测的正确率和耗时对照，不为采数购置 API。 / Obtain complete real call coverage before closing the model-use objective; missing telemetry remains an open limit.
- [x] 在全新第三方原生应用完成一个受支持的低风险流程，证明现有学习与执行能力可以迁移；沿用前项已核验的编辑契约，不重复打开 P1。真人审核未发生的部分保持待办。 / Validate one supported low-risk third-party journey before scaling without reopening verified P1; retain actual human-review gaps. （仅T7限定范围已验，真人仍待；见顶部原审计。） / Verified only for bounded T7 scope; human coverage remains open; see the original audit above.
- [ ] P2 诊断、限定 P3 和上述迁移已核验后，再单独冻结原 R4 正式三类各20对 A/C、每类≥5对 B；B 用于解释节省来源，先导抵扣仍为0。若场景/遥测不可用，明确剩余范围，不能改弱标准或用 loopback 模型代替真实收益。 / Freeze formal expansion only after the pilot, bounded recovery and transfer gates. Preserve formal quotas, zero pilot credit and honest telemetry limits.
- [ ] 准确率收益与成功率门槛分开报告：采集前固定真实易混变化及独立结果核验；A 满分只报持平。正式样本通过但未观察到准确率提升时，结论仍为“未证明改善”，不改题或重解释标准来补齐目标。 / Keep an accuracy-improvement claim falsifiable and separate from meeting the success threshold.
- [x] Main 单项、连续、异常和清理通过后，交同冻结候选独立验收；真实人工审核未发生的部分明确待办。 / Complete primary acceptance before independent testing and retain human-review gaps. （仅T7限定范围已验，真人仍待；见顶部原审计。） / Verified only for bounded T7 scope; human coverage remains open; see the original audit above.
- [ ] 提交可供用户评估的试用结果：支持范围、普通操作说明、三项收益各自状态及已知限制。用户要求交付时才做隔离依赖验证和一次集中打包；发布单独执行。 / Deliver a reviewable trial report before packaging/publication.

## Deferred work and stop rules / 暂缓项与防偏移规则

- 暂缓通用跨应用实例重绑定、多层故障组合、模型组合再选型、未发布决策 API 接入、大型 UI 重做、泛化重构和重复打包。保留现有接口。 / Defer breadth while retaining extension points.
- 每项新开发必须写明它阻断 P0–P4 哪个用户结果、用什么证据验收；无法对应的进入积压。 / Tie implementation to a specific blocked user outcome.
- 每次汇报先说明已完成的用户任务、三项收益证据和当前阻断；测试数只作支撑。 / Report outcomes and benefit evidence before test counts.
- 一个失败只沿共同根因修复，窄回归后回到原流程；未知缺口单列，不能用另一轮源码整理替代实机出口。 / Fix the invariant, then return to the interrupted journey.
- 暂停时的重心复核本身只改文档并收尾；2026-10-02 恢复后按已授权范围及最新执行顺序推进，只修实际阻断并回到原流程，不扩建泛化架构。实机、收益、打包和发布状态分别报告。 / The earlier paused review was documentation-only; resumed work follows the latest authorized sequence and repairs observed blockers without architectural expansion.

## 2026-10-02 Execution ledger / 本轮执行记录

以下按候选保存历史快照，不定义当前状态或排期；上方最新执行重心和优先级表为准。 / The following candidate-specific historical snapshots do not define current status or scheduling.

P0 complete：原汇总 584 passed；Main 当前夹具/客户端 38 passed，worker 夹具 9 passed，覆盖重叠不相加。原首次失败保留。现场候选冻结清单见 `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261002-learning-mainline-01/source-freeze.json`。P1 进行中；当前还没有本候选完整实机通过或模型收益结论。 / P0 is verified; P1 and benefit acceptance remain open.

2026-10-02 重心复核：采用上述 P1→先导 P2→限定 P3 顺序；补可见普通入口与审核归属、试采冻结及完整计分。原教学等待失败和正常清理保留，未新增产品测试/输入；原始证据见本轮 `live-p1-01/replies/focus-audit-status.json`、`cleanup.json`、`fixture-exit.json`。 / The review clarifies usable entrypoints and measurement policy while retaining the incomplete attempt and verified cleanup.

2026-10-02 最新审查：补记 live-p1-02 的教学、编辑和第一轮复用；第二轮明确取消并清理，不记完整通过。后续增加最小先导清单兼容、任务计时边界、完整模型计量与准确率改善出口。849 个冻结源文件未变，正式树仍为 `1092a273586b07939fed5bad7d0239e3c6a457ef` 且干净；本次只改计划/状态文档和原会话收尾，不开发、打包或发布。 / This review records verified partial progress, closes the original live session and sharpens measurement gates without changing product source or the stable release.

2026-10-02 P2 原采集失败：live-01 首 A 的现场与当前 fixture 结果成功，但原 finish 残留五个 continue 控制请求而记 completed=false；原计分不改。共同 collector 修复已通过 Main 178 项，live-01 原 CLI/host/runner/窗口退出，pending_agent_workers=[]，cleanup_verified=true。新 v3/种子/六对开始，不拼接不同候选成绩。具体共同约束、RED/GREEN、清理辅助错误及当前限制见 p2-control-settlement/main-incident-review.md、live-01/main-first-case-audit.json、main-cleanup-witness.json。 / The original collector failure and normal cleanup are retained; a new candidate starts fresh sampling without rescoring or cross-candidate pairing.

2026-10-02 P2 内部原结果接线：v3首A完整、C第四步原read已返回而collector拒绝读取，旧comparison保留1行/1unfinished。Main核对原命令/回执/原PNG、outputs空及下游未执行，原context和窗口清理通过。只补bound EID只读准入和同源replay，Main199项与真实原公开read检查通过；v4已冻结、未启动、不计配对。失败结构与范围见 p2-internal-result-wiring/main-incident-review.md；下一步仍为六对完整任务采样，不扩建恢复或重复打包。 / The internal-result boundary is repaired and scoped, while the original interrupted trial stays unfinished; next is matched sampling on the new frozen candidate.

2026-10-02 再次按用户目标核对：优先交完整任务和可判读收益，不把接线检查数当进度主体。第一对作为继续采集检查点，六对仍只作诊断；完整模型计量核查与编辑复用/第三方迁移前移到正式扩张之前。live-03 仅准备、零尝试/零桌面输入，原 CLI 和 fixture 退出0，pending_ids=[]，sampler_stopped=true，四个所属进程均退出，cleanup_verified=true；下一实机使用新现场但保留同一 v4 冻结清单与计分。证据见 live-03/main-preparation-cleanup-witness.json；本次只改计划/状态，不改源码、版本、发布或旧成绩。 / This goal audit adds a first-pair checkpoint and places telemetry feasibility and transfer before scale. The preparation-only session was normally cleaned without an attempt or desktop input; continue on a fresh site using the unchanged frozen v4 conditions.


2026-10-02 v5检查点：历史保持：live-03仅准备，零尝试/输入且清理通过；v4/live-04 的 A 实际任务成功，但 Main 给 finish 多传 attempt_id 导致采集器退出，原0行/1unfinished，观察到清理318.975秒；v4/live-05 的 C 到step2，原异步回执被collector错误拒绝，原0行/1unfinished，观察到清理93.068秒。两现场原宿主/runner/窗口均退出，清理核验通过；未补造 finish、未重评分或拼接到v5。v5首C前 Main 只读核验误解 outputs 键的 KeyError 单列调用方错误，之后按真实键更正，耗时未扣除。 / Preparation, unfinished attempts, verified cleanup and caller errors remain separate; no original scores are rewritten or combined across candidates.

当前 P2：source-v5/cohort-05 的首 A/C 原任务和 finish 都成功，A328.390326秒、C564.687463秒；C本次 step-4.current_detail 绑定 step-5 填写且最终显示 Matches current detail。但C来源覆盖因重复引用为partial，首对继续采集检查点尚未通过；保留原两行结果，停止本候选采余下五对。此计时包含执行者、工具往返、汇报、Main 核验和结算；C最终completed返回后至finish为344.305728秒，主会话收尾明显拖慢，不能归因于模型推理。 / Both first tasks originally succeed, but duplicate provenance references block the collection checkpoint. Keep original rows and stop this candidate before repair; caller settlement accounts for substantial elapsed time and does not identify model inference latency.

执行顺序调整为：立即结算已结束的原任务，不在计时窗口插入无关调查/文档；只修真实来源覆盖阻断并新冻结 → 首对原结果/replay/未决请求检查 → 余下五对与三项分别诊断 → 同窗口一次弹窗/一次宿主中断及收尾 → 按实测瓶颈优化，完成语义编辑后待审/复用、第三方应用迁移及完整计量缺口 → 再扩大正式三类对照和同候选独立验收。泛化重构、决策API接入、大型UI重做和重复打包后置；正式v0.1.1独立，当前不改版本、不推送或发布。 / Settle completed tasks promptly without inserting unrelated investigation into the attempt clock, repair the proven provenance blocker and freeze anew. Then validate the first pair, finish the pilot, bound recovery and complete measured optimization, edited reuse, transfer and telemetry before formal scale.

证据 / Evidence: 本轮 p2/internal-agent-result-wiring/main-final.xml、main-bound-public-envelope-check.json、p2/live-06/mailbox/replies/main-finish-c01.stdout；完整模型可行性见 p2/model-telemetry-feasibility-v4.json。


2026-10-02来源覆盖收尾：路径别名重复、原Windows规则索引和基本动作goal/视觉提示契约已在共同collector/provenance修复。Main原失败262 passed/2 failed为图片测试fixture错误地传入非声明参数，修正fixture投影后最终266 passed/10.67s；不改输入准入或图片/hash断言。真实v5原只读复查58个唯一快照、六步coverage完整无error，仍保留Agent核验限制。原v5 comparator在12个依赖/620源文件哈希门控下复算，原partial及两行成绩不变，原现场清理通过；v6另冻且尚未实机。下一步使用新现场完成v6首对，再按同清单完成余下五对，不再新增采集架构前置。 / Common receipt repairs pass related and actual-file checks; retained original replay and cleanup remain unchanged. Start the new frozen pilot rather than reopen collection architecture.

2026-10-02 live-07收尾 / Closed diagnostic update:

P1本批普通闭环保持完成。当前优先顺序：纠正执行者与原始评分快照审计的角色隔离，保留v6四对诊断和两对未跑；限定一次弹窗/原宿主中断，未知输入不得推定成功；通过普通编辑验证一个现有文本规则优化及修改后重新待审/复用；随后以新种子、新当前值和明确会话背景另冻六对先导，不补齐或拼接已关闭cohort-06。完整模型计量、第三方迁移、正式配额、真人及同候选独立验收仍保留，未降低50%/30%/95%标准。 / Preserve scoped P1 and the closed partial pilot. Correct audit isolation, bound recovery, validate one existing-rule edit and fresh reuse, then freeze a separate full pilot before transfer, complete telemetry and unchanged formal acceptance.
