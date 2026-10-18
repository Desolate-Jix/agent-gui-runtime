## 2026-10-02 当前候选与下一出口 / Current candidate and next outcome

## 2026-10-02 最新执行重心 / Latest execution focus

用户最新要求：收益暂且不论，先核验每次运行的稳定性并检查窗口激活失败。当前只关闭有证据的具体缺口，不承诺任意 Windows 状态下每次成功。顺序改为窗口激活与连续选择 → 同窗口完整异常恢复及清理 → 修改规则的完整复用与第三方流程；模型/准确率/速度对照后置，原标准和历史结果不改。 / The user prioritizes stable execution and activation diagnosis. Validate focus, bounded continuous recovery and cleanup before edited reuse and transfer; defer benefit sampling without changing its standards or historical results.

已完成：P1 本批普通学习、同会话两轮复用、缺失停止、普通修正和清理；v9 修复合法 Agent continue 的终态关联，Main 96 项通过，原 live-04 的 165 个文件只读重放未改。P4 规则语义编辑后待审、保存重开及旧版保留已验，明确审核和新现场复用未验。原 live-04 的准入失败和逻辑清理未通过保持原结论；源码修复不等于完整恢复验收。 / Scoped P1 and the v9 continuation-proof source repair are verified. The ordinary rule draft persists and invalidates review correctly, but explicit review and fresh reuse remain open. Original failures stay unchanged and full recovery has not passed.

激活调查：两份原宿主日志先记录连接 Shell 前台线程 47200 的 AttachThreadInput error 5，随后才是 SetForegroundWindow 拒绝。用户未开菜单；事后同 HWND 的 menu=false、DWM cloaked=2 不能倒推故障瞬间的桌面状态。SetForegroundWindow 不保证扩展错误码，不能据5判定目标需管理员权限。已在共同层保留附件线程及阶段证据、清除旧 LastError并标明此错误码不可靠；原前台核验与输入门控不变。 / Original logs identify denied attachment to the Shell foreground thread before foreground rejection. Later desktop observations do not reconstruct the failed instant. The shared diagnostic now preserves earlier thread errors and marks unguaranteed foreground error codes without weakening verification.

本轮验证：Main 44 项相关检查通过；同一原 MCP/宿主、两个自建窗口连续 7 次选窗及截图成功，其中 7 次为确切跨窗口切换，正常清理通过。它不是完整学习任务/恢复验收，也未复现旧 Shell 前台条件。更早 v9 的单窗选窗加三次截图成功时，目标本来就在前台，只证明相应有限路径。 / Main passes 44 focused checks. One original MCP session passes 7 selections/captures with 7 actual cross-window transitions and cleanup. This does not establish full workflow/recovery stability or resolution of the original Shell condition.

证据与限制 / Evidence and limits: [窗口激活稳定性记录](WINDOW_ACTIVATION_STABILITY.md)。正式 v0.1.1 不变；本轮未打包、提交或发布。下方按候选保存的旧“当前/下一步”段均为历史，以本节和主线计划为准。 / The stable release is unchanged. Earlier candidate-specific current/next entries below are historical; this section and the mainline plan control priority.


历史保持：live-03仅准备，零尝试/输入且清理通过；v4/live-04 的 A 实际任务成功，但 Main 给 finish 多传 attempt_id 导致采集器退出，原0行/1unfinished，观察到清理318.975秒；v4/live-05 的 C 到step2，原异步回执被collector错误拒绝，原0行/1unfinished，观察到清理93.068秒。两现场原宿主/runner/窗口均退出，清理核验通过；未补造 finish、未重评分或拼接到v5。v5首C前 Main 只读核验误解 outputs 键的 KeyError 单列调用方错误，之后按真实键更正，耗时未扣除。 / Preparation, unfinished attempts, verified cleanup and caller errors remain separate; no original scores are rewritten or combined across candidates.

现有 agent_current/workflow_metrics、调用方 record_model_call 和公开任务摘要只能提供局部或调用方上报计量，完整规划/定位/核验/补救总量仍未闭合；A普通路线也没有工作流计量范围。总调用/token继续未知，不把工具数、等待或局部0次当总调用。不为计量购置API或换模型，继续测正确率和耗时。 / Existing hooks provide partial coverage only; complete actual call coverage remains open without replacing missing totals with tool counts or buying providers.

执行顺序调整为：立即结算已结束的原任务，不在计时窗口插入无关调查/文档；只修真实来源覆盖阻断并新冻结 → 首对原结果/replay/未决请求检查 → 余下五对与三项分别诊断 → 同窗口一次弹窗/一次宿主中断及收尾 → 按实测瓶颈优化，完成语义编辑后待审/复用、第三方应用迁移及完整计量缺口 → 再扩大正式三类对照和同候选独立验收。泛化重构、决策API接入、大型UI重做和重复打包后置；正式v0.1.1独立，当前不改版本、不推送或发布。 / Settle completed tasks promptly without inserting unrelated investigation into the attempt clock, repair the proven provenance blocker and freeze anew. Then validate the first pair, finish the pilot, bound recovery and complete measured optimization, edited reuse, transfer and telemetry before formal scale.

[异步回执故障与验证](LEARNING_BENCHMARK_ASYNC_ENVELOPE.md)。

## 2026-10-02 当前重心与实测进度 / Current focus and live progress

学习主线保持“真实教学生成→可审核修改→保存重开→换数据复用→实测收益”。P0 已完成。本批 P1 普通闭环已核验：live-p1-02 六步教学、Agent 整理和可见编辑重开；live-p1-03 在同一原窗口/会话不复位完成 R-381、R-590 两轮六步复用，均填写当次读取详情。原图固定引用和旧程序保留。审核者是 Agent，human_review=false。 / This batch verifies teaching, visible editing/reopening and two continuous fresh-data reuses, with pinned graph/program versions and truthful Agent attribution.

R-000 缺失目标在 step-3 停止，原 action_executed=false、dispatch_attempts=[]，未执行下游读取/填写；普通输入框改为 R-362 后完整六步完成。原宿主和窗口正常退出，cleanup_verified=true、pending_ids=[]。普通界面能看出失败步骤并重新输入，但具体 request_absent 原因目前仅在原回执，作为易用性限制保留。本批不是任意应用、完整 R1/R2 或独立验收。历史超时、遮挡拒绝、驱动错误、取消和多余 continue 拒绝均不改写为首次成功。 / Missing-target stopping, ordinary correction and cleanup pass within the declared scope; detailed failure wording and wider acceptance remain open.

当前 P2：source-v5/cohort-05 的首 A/C 原任务和 finish 都成功，A328.390326秒、C564.687463秒；C本次 step-4.current_detail 绑定 step-5 填写且最终显示 Matches current detail。但C来源覆盖因重复引用为partial，首对继续采集检查点尚未通过；保留原两行结果，停止本候选采余下五对。此计时包含执行者、工具往返、汇报、Main 核验和结算；C最终completed返回后至finish为344.305728秒，主会话收尾明显拖慢，不能归因于模型推理。 / Both first tasks originally succeed, but duplicate provenance references block the collection checkpoint. Keep original rows and stop this candidate before repair; caller settlement accounts for substantial elapsed time and does not identify model inference latency.

共同采集修复已核验：异步returned/running只读准入与真正终态分开；同session原路径规范化去重，原Windows规则引用沿只读索引读取；memory plan绑定原动作goal，附加视觉提示不替代动作语义。Main最终266 passed/10.67s，真实v5原件只读复查coverage=complete、errors=[]，58个唯一快照及原图SHA一致，旧journal/原分未改。部分步骤仍为Agent核验，全规则资格false、总调用/token未知；runtime/client/输入门控和终态评分不变。 / Bound asynchronous retrieval, canonical snapshots and original action semantics are verified by related regressions and actual retained files. Mixed Agent judgment, unknown usage and unchanged original scores remain explicit.

source-v6/cohort-06（849文件、种子2026100206、每路线计划6例/600秒）现已完成4对/8次任务并正常清理；原首对检查点通过，C四例来源coverage=complete、errors=[]，全规则资格仍false。A首次成功4/4，C3/4；C04调用方读取格式化错误经原请求reread补救，最终任务8/8完成，原首次失败与全部耗时保留。稳定两对中位耗时A298.986秒/C246.596秒，描述性节省17.5226%，未达30%目标；模型总调用/token未知，准确率提升未证实。A04后只读审计误展开评分records，执行worker隔离失效；停止余下2对layout，不记失败、不补分、不续采旧清单。原8行、missing4、零unfinished和cleanup证明保留；正式配额不抵扣、真人/独立验收未完成，正式v0.1.1独立不变。 / The closed candidate retains four pairs, eight completed tasks and its original first-success/recovery scores; two layout pairs remain unstarted after post-task oracle exposure. Stable descriptive timing saves 17.5226%, below the target. Call coverage and correctness improvement remain unproven; no formal credit or release change follows.

总模型调用/token 仍未知，省模型、正确率和速度收益均未证明。工具/交接数与等待不冒充模型调用或推理耗时；满分基线只报持平。正式 v0.1.1 独立保持；当前学习源码未发布、未改版本或打包。P1及P2 v2/v3/v4的候选证明分别保存，原失败不移入新候选，也不补改旧记录。 / Benefits and full usage remain unproven; the stable release is separate, and each candidate proof and original failure remains tied to its own frozen revision.

[当前执行计划](../superpowers/plans/2026-10-01-learning-mainline-refocus.md)；Main 证据：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261002-learning-mainline-01/live-p1-03/p1-main-audit.json`。以下日期段均为历史，不覆盖当前顺序。 / The plan and raw evidence control current status; dated sections below are historical.

## 2026-10-01 明确新会话准入已接线 / Explicit epoch admission wired

学习开发源码未发布、未改版本；正式 v0.1.1 独立保留。下面原有日期段保留为阶段历史。/ Learning source remains unreleased; stable v0.1.1 remains separate. Earlier dated sections are historical.

本轮是恢复合同及宿主生命周期验收，不是收益测量。Main 482项，真实三轮异常恢复/发布中断同宿主/清理及原STDIO新工具通过，旧文件和冻结源码保持；所有实机模型清单为空、GUI输入为0。R3当前效果接管与完整任务仍待，R4–R6收益/优化/迁移未完成，总调用/token仍未知。/ Lifecycle and contract evidence cannot establish task/model savings, accuracy or speed.

详见 [本轮证据与限制](LEARNING_EPOCH_ADMISSION.md)。/ See the current evidence and limits.

## 2026-10-01 中断事实修复 / Durable interruption facts

本批是中断事实与只读回读合同验证，不是收益测试。输入层替身不能计作真实任务准确率或耗时，历史未知模型总调用/token 继续为 null。正式 C、公平 A/B/C、学习成本及三个任务族实测仍未完成。/ Process contracts are not benefit trials. Doubled inputs do not establish task accuracy, speed or model savings; reviewed C, fair comparisons and complete usage remain open.

详见 [WORKFLOW_INTERRUPTION_CONTRACT.md](../WORKFLOW_INTERRUPTION_CONTRACT.md)。

## 2026-10-01 R2 目标替换通过与 R3 只读修复 / Target replacement and read-only recovery

普通工作台完成目标规则收紧、应用、保存和重开：保留 `contains input record_id`，增加同一行文字的 `contains constant " · Record"`；仅 step-3 重新待审，其余步骤保持。旧程序、旧规则和旧 ready trial 在编辑期间逐字节不变，旧 trial 随后取消且无步骤输入。两个不同编号/布局的新运行各完整六步通过，并使用各自当前详情；12 个原 EID、26 个核心图像引用及原门控回执核对通过，宿主和窗口清理成功。 / Ordinary controls verify target-rule tightening, save/reopen, scoped review invalidation and immutable old pins. Two new six-step runs succeed with their current details; original receipts, images and cleanup are verified.

审核标记为测试失效传播而设置，`human_review=false`、`formal_C=false`；新目标仍待审。本批不是人工正式审核、公平收益或完整恢复验收。每轮五个输入命中规则，但仍有四个 Agent 读取/结果判断；总模型调用和 token 未知。原场景间有复位，不冒充无复位的连续状态累积。 / QA review markers do not establish reviewed C or benefits. Scenario resets limit continuity evidence; total model usage remains unknown.
`WorkflowRunClient` 现分离只读 attachment 核验与派发前 live gate。宿主实际退出后，新客户端及新开的普通 main 可读取本轮原结果、输出和回执，执行/继续/取消按钮禁用，账本与命令字节未变。活宿主仍完整验证 PID、创建时间及 runner；`control`、原回执绑定和动作门控保持原实现。 / Validated read-only attachment now works after the original host exits; dispatch still requires the original live identity and gate. Ordinary reopening preserves the ledger and disables action controls.

这只证明退出后的只读重连，不是原宿主进程重启续跑。活动 workflow 切换独立顶层弹窗仍不支持：admit 只放行原 ticket 的确切 EID/command，不能放宽竞争 select 代替窗口迁移合同。死宿主的原 worker 仍不能从磁盘自动恢复，未知结果不能当作未输入而重放。 / Read-only reconnection does not restore a dead worker or permit competing window selection; active dialogs and process restart remain open.
验证：目标编辑预检 31 passed；Main 合并检查 93 passed；只读恢复相关 worker 回归 250 passed。集合重叠，不相加。只读修复首次红阶段 5 failed / 41 passed 保留；实际输入首次完成两轮。审计先把 runner 投影误当原 trial、随后构造器参数写错，两个失败报告保留；改为原 public runner.status 全量核对后通过，未重放输入。 / Overlapping checks are reported separately. First failures remain retained; audit repairs required no input replay.

证据 / Evidence：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-target-rule-edit-01/main-live-audit-final.json`、`live-01/dead-host-reopened.json`、`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-recovery-boundary-01/main-integrated.xml`。未改版本、打包、发布或替换安装候选。 / No version, build, publication or installed-candidate replacement.
版本固定：original revision 2 → QA reviewed revision 3 → edited revision 4；新 recipe 为 `target-recipe-6191e744ea8a6d0d0d139a35e688ef88009f6652ed77aeadb00690b9ccfea3bb`，新 program 为 `task-program-a5a1671934847e43fa1b35bc771ac979f1d488404d56ee9c4a76ad4fdf552671`。图像按原路径+SHA 索引独立保存，不把路径条数当独立图像内容数。 / Immutable revisions and current references are pinned; archived path/hash references are not unique-content counts.

## 2026-10-01 目标反例、根修复与源码归属 / Negatives, root fix and source ownership

权威源码仍在 `<LEARNING_WORKTREE>`、`codex/dev-workflow-editor`。本轮 Sol 实际使用 `gpt-6.1-sol`。不发布、不改版本，低风险实机使用既有用户授权。 / The authoritative worktree and branch are unchanged; GPT-6.1 Sol dispatch is verified. No release/version change occurred.

- Failure：首次目标行消失后，原 step-3 返回 capability_unknown/action_executed=false；普通运行页无法表达明确的 Agent 识图能力。 / The ordinary entry could not declare vision capability for a memory miss.
- Root invariant：客户端能力必须明确声明并固定到原 run，不能从 source/模型名猜测；普通两条 run 入口遗漏了后端已支持的字段。 / Explicit client capability provenance must survive both ordinary start paths.
- Fix location：WorkflowRunPanel 只补可选声明与共同 run 构造，启动时固定；换会话清空，运行/等待禁改。默认未知与后端拒绝原样保留。 / The client entry is repaired without relaxing backend refusal.
- Why not app-only：修复适用所有 agent_current/delegate 工作流，不改 Record Desk 专属产品逻辑。 / This repairs a shared entry rather than a fixture-specific executor.
- Regression：worker 首次 10 failed/11 passed，最终 148 passed；Main 合并 owner、panel、原 Runtime/runner/Trial/jobs、恢复与普通旅程 **255 passed**（重叠集合不相加）。 / Source tests preserve first failures and confirm original pipeline behavior.
- Safety：声明不是授权；unknown 对照仍拒绝，local/API 不带声明，未放宽目标、窗口、截图或执行检查。 / Action gates and unknown-capability refusal remain intact.

复测 `20261001-learning-target-negatives-01/live-02` 同一新宿主，两轮原 revision 2 六步程序只走到第三步：Find 后界面分别为 0 行、同 ID/label/Open 的 2 行；Main 看当次原图回交 absent/ambiguous。原 worker 错误分别 request_absent/request_ambiguous，action_executed=false，原工作流 failed，第四至六步未派发。每轮前三个原执行 ID 唯一，两次 Start，不重放请求；fixture 无 Open/detail/controlled-field/Verify 事件。两场景之间有 case_reset，不宣称完整异常后任务通过。 / Both bounded negative runs terminate without selecting a row; case resets limit continuity claims.

严格审计通过：原响应文件字节 SHA、终态 canonical SHA、run/EID/程序/能力声明及截图核对；146 处核心图像引用对应 26 个路径/哈希对。宿主与 fixture 退出 0、pending 为空、cleanup_verified=true，运行期间 app/scripts/fixture 源码不变。首次 live-01 实机失败、UI driver 对 null 当前步骤的误断言、审计首轮将原文件字节哈希与投影 canonical 哈希混淆均保留；只修测试断言，没有重放实机输入。 / Strict receipt and image audits pass, retaining initial runtime, driver and audit mistakes separately.

第四批 owner 实现与备份逐字节一致，coordinator 仅改导入；worker 113 passed，Main 166 passed，独立源码 880 文件真实入口预检 passed，无输入/截图/模型推理。上述集合与最终 255 重叠，不相加。证据根分别为 `20261001-learning-runtime-owner-01`、`20261001-learning-ui-vision-declaration-01`、`20261001-learning-target-negatives-01`，都位于 `D:/AgentGUI-Projects/verification/AgentReviewAcceptance`。

原程序全部待审，正式 C=false，总模型调用/token=null；公平收益未跑。R2 目标规则替换、R3 活动弹窗/宿主重连/异常后完整任务、R4–R6 保持开放，整项目代码分层尚未完成。 / Review, full recovery and measured benefit/transfer gates remain open.

## 2026-10-01 授权后的实机检查点 / Authorized physical checkpoint

用户批准低风险实机测试，无需逐次确认；下方待确认说明为历史快照。本轮产品 app/scripts 哈希未变，真实输入走原宿主与门控，不发布、不改版本、不替换安装包或使用付费 API。工作树/分支：`<LEARNING_WORKTREE>` / `codex/dev-workflow-editor`。 / Low-risk physical tests are authorized. The batch preserves product-source hashes and original gated execution without delivery, version or paid-API changes.

证据根目录 / Evidence root: `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-variation-live-01`。

| 检查 / Check | 结果与边界 / Result and boundary |
| --- | --- |
| R1c 两种布局、新编号 / Variation | live-04 两轮完成，live-05 以原固定版本再完成 R-731 / R-284 两轮六步，当次详情正确用于本次填写并 Matches current detail。main-audit-live05.json 严格通过：34 核心图像引用全部可核验，2 项使用相同 SHA 的归档。每轮 4 memory_uia + 1 memory_visible_row，2 rule + 4 Agent；模型总调用/token 为 null。 / Six-step variations and current-run dataflow pass strict archived-image checks; complete usage is unknown. |
| R2 普通编辑 / Editing | 实际 main 离屏控件完成 QA 审核、仅改名、保存重开、读取语义修改、4/5 步依赖失效和单独复核。旧版本及旧 ready run pin 不变；旧 run 无输入并取消，新版真实六步成功。main-audit-r2.json strict-images/after-cleanup 通过，正常 MemoryWorkspace 复核五个不可变版本。QA 标记 human_review_claim=false，不计人工审核/C；未验目标 recipe 替换和消失/重复反例。 / Bounded read-semantic editing, immutable pins and physical execution pass; broader target edits remain open. |
| R3 中断/取消 / Recovery and cancellation | 普通工作台关闭重开续接原 run/program/wait/pending EID/history；取消原任务结算 cancelled、pending=None，保留已发生 Find 的原终态并标 uncertain。随后同窗口/宿主中新任务完成六步，没有重派旧 pending。 / Original identities recover and cancellation preserves executed-input facts; a new task completes. |
| R3 独立 Notice / Standalone dialog | 核对同 PID/生命周期/父窗口归属后，原 select + 新 grounding 关闭弹窗；原终态 failed/action_executed=true/post-observation unavailable 保留，回选父窗口的新图及 fixture 事件核验关闭。活动 workflow 的竞争 select 仍拒绝，此项不算完整工作流弹窗恢复。 / Explicit dialog binding and parent recovery pass without masking unavailable post-close capture or bypassing workflow admission. |
| 收尾 / Cleanup | live-05 原宿主、三次完整工作台运行及 fixture 退出 0，cleanup_verified=true，源 app/scripts 哈希不变；之前失败的自建会话也已关闭，原证据保留。 / Owned cleanup and frozen-source checks pass. |

实际执行的检查 / Checks actually run:

```text
run_workbench.py 1 / 2
r2_edit.py review-title / semantic / review-final
r2_control.py start / status / cancel
run_r2_workbench.py
audit_live.py --live live-05 --strict-images --output main-audit-live05.json
audit_r2.py --strict-images --after-cleanup --output main-audit-r2.json
```

主 Agent 另复核弹窗选择辅助合同 20 passed（popup-selection-main.xml）；这是外部测试辅助逻辑，不与此前产品源码 609 passed 相加，也不代替真实弹窗结果。 / Twenty helper checks have a separate non-product scope.

首次失败保留 / First failures retained:

- live / live-02：截图被已有置顶窗口遮挡，首次白名单修改未重载而拒绝 select；只调整自建夹具初始位置。live-03 新测试脚本名不匹配进程检查，在任务输入前拒绝。 / Harness admission, capture and fixture-identity failures precede task input.
- live-04 round2、live-05 post-cancel：驱动把旧完成/取消快照当新结果；原新 run 已创建 ready，脚本按原 start 的 run_id 修正后续接，未重复 start。first-ui-driver-error-1.json、ui-driver-error-2.json 等保留。 / Stale test snapshots are corrected without replacing prepared runs.
- live-04 Notice Close 错绑父窗口，被 agent_grounding_target_region_changed 拒绝；复测明确选择独立窗口，未放宽像素门控。live-05 关闭后原目标截图不可用，保留 failed，未重试点击。 / Correct the binding while preserving freshness and post-close failure facts.
- live-04 round1 step1/2 recognition 原 PNG 被默认 40 张保留策略清理，日志明确记录；不能用 memory frame 冒充缺失原图。live-05 每批及时复制 PNG，preserved-images.json 保存原路径、归档路径和 SHA。 / Missing originals remain explicit; subsequent image archives are byte verified.

R1c 主正向检查已过；R2/R3 的目标反例、活动工作流跨窗口与宿主进程重连仍开放。R4 配额、公平 A/B/C 和全量计量、R5 实测优化、R6 第三方迁移与同候选独立实机验收尚未完成。worker 本轮只有静态/只读审计和外部辅助脚本，不是独立实机验收；工作台离屏控件也不冒充人工外部编辑窗口测试。 / Variation passes within scope. Broader recovery, benefits and independent physical acceptance remain open; source/worker/offscreen evidence retains its separate scope.

## 2026-10-01 此前逐类评分与执行边界整理 / Earlier scoring and execution boundaries

用户当前目标是正式源码梳理、暂不发布并继续学习计划。评分新增 by_task_family 与 all_families，保留 matched_aggregate；每类单独检查配额、调用、速度和正确率，合并改善不掩盖单类退步。首次新增测试 5 failed / 46 passed，worker 最终 53 passed，主 Agent 原命令复核 53 passed；证据 scoring-red.xml、scoring-green.xml、scoring-main-verified.xml。

The current goal is cleanup without publication plus continued learning acceptance. Per-family assessment supplements the aggregate; main rerun passes 53 synthetic/collection checks. These are not empirical benefit measurements.

执行服务三个唯一实现迁入 app/execution，旧路径兼容；五个维护消费者切换导入。新边界首跑 8 failed；首次回归 2 failed / 400 passed（遗漏旧入口预检）；修复后 403 passed，主 Agent 加入 API/记忆/工作流接线复核 477 passed。孤立源码目录真实入口依赖预检 passed=true，无输入/截图/推理执行。范围见[边界说明](../EXECUTION_MODULE_BOUNDARIES.md)。

The execution move preserves byte-identical implementations and original gates. Initial compatibility-preflight failures are retained; the main integration rerun passes 477. Isolated dependency preflight is separate from physical acceptance.

本轮证据根目录为 D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-acceptance-01。未提交、推送、发布、改版本或替换安装候选；R1c 与 R2–R6 实机/收益未闭合。C 组目前尚缺启动前固定定义审核与本轮实际规则覆盖的采集合同，不能把 learned 策略或定义含 recipe 当成完整 C 证据。 / Publication and physical/benefit gates remain open; learned strategy alone does not establish reviewed definitions or actual rule coverage.

第二批动作合同 red=3 failed/9 passed，修复后 worker=307 passed；模型、校验与 handler 原语义复核见 contract-main-source-audit.json。定义概览 red=3 failed，相关 UI=51 passed，文案复验=4 passed（重叠）。最终主 Agent 合并 36 个文件：final-source.xml=774 passed/0 failed/0 skipped，91.21s；该数字包含此前切片，不相加。主窗口最终截图 summary-main-draft.png 已核对，草稿与已保存审核状态分开。

The second contract move and definition overview pass scoped regressions. The final 774-test main run overlaps earlier slices; final UI evidence is inspected and remains offscreen/synthetic.

当前说明文档曾被源码白名单遗漏，新关系检查首次失败，补齐后 delivery-docs-green.xml=10 passed。默认 git diff --check 将已有 CRLF 视为尾空白；按保留 CRLF 的本仓库文本约定使用 core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol 检查通过，未改 Git 持久设置或批量重写历史文件。

Required guide selection is repaired and checked. Whitespace verification respects preserved CRLF without changing persistent Git settings or rewriting unrelated files.

R1c 最新预览来自本轮新宿主：两种布局、正确编号和字段已看图；commands 仅 select/capture，physical_inputs=0，fixture 退出 0、client.cleanup_verified=true。两轮操作独立确认仍待回复，没有把预览标成复用成功。

Fresh variation previews and owned cleanup are checked without task input. Exact action confirmation and real variation/benefit acceptance remain open.

最终隔离目录为 874 个维护文件；执行输入/读取预检 passed=true，校验新旧合同入口与真实依赖。isolated-workbench.json 另证实 python -I 实际学习工作台空状态离屏启动/关闭通过，93 个本地模块均来自包目录，无新宿主或任务输入。不是 MCP 握手替代功能检查，也不是实机完成。 / Final isolated dependency and actual offscreen workbench-start checks pass without physical acceptance.

隔离工作台首次截图中文显示方框：QString 内容及 UTF-8 正确，但离屏 QFontDatabase 有 0 个字体，中文字形不可用。font_probe.py 证实注册系统 msyh.ttc 后字体数为 2、中文字形可用；只补测试初始化，重新用全新空目录启动后中文截图已核对。首个 startup 报告与方框图另存 first，未把首次截图计为布局通过，也未修改产品字体、系统字体或执行安全。 / The first isolated offscreen capture lacked fonts, not Unicode data. Existing test font registration fixes the harness; the fresh rerun is visually checked, with initial evidence retained.

## 2026-09-30 调用方计量与可选判断合同 / Caller telemetry and optional judgment contract

用户要求先推进两个不依赖桌面输入的独立任务。源码在 `<LEARNING_WORKTREE>`，分支 `codex/dev-workflow-editor`；没有创建新分支、修改版本、提交、推送、打包或发布。原件备份和首次失败保存在 `<EVIDENCE_ROOT>/20260930-telemetry-judge-01`。 / Two independent non-desktop slices in the existing source checkout; originals and initial failures are preserved, with no delivery or Git publication.

实现 / Implemented:

- 原 learning_workflow 的 record_model_call 绑定原执行票据/回执，或确切草稿整理完成/纠错回复。provider/call_id 幂等，冲突和跨运行归属拒绝；调用方自报计量单列 caller_reported_partial，不认证供应商真实性、不与 observed 重算，不补造全量。 / Receipt-bound, idempotent caller records are separate, partial and not independently verified.
- 原运行状态/宿主报告和 synthesis_status 返回该部分汇总；缺用量或耗时保持未知。内容/来源哈希变化、损坏或丢失使调用方汇总不可用，不重派输入、不修改原执行事实。 / Existing status/report paths expose partial telemetry; invalid evidence cannot affect execution or cause replay.
- 默认关闭的 OptionalJudgment 接收绑定条件与证据的执行/学习请求，严格 true/false/null 映射 success/failure/uncertain，拒绝错绑回复和静默丢图；关闭/未连接时不创建证据或调用 provider。它只预留程序接口，没有供应商网络适配、设置 UI 或自动结算接线。 / A disabled shared judgment contract is reserved, without vendor/UI/settlement integration.

主 Agent 实际运行 / Commands actually run:

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:QT_QPA_PLATFORM='offscreen'
& '<PYTHON_EXE>' -X utf8 -m pytest -q tests/test_caller_model_calls.py tests/test_optional_judgment.py tests/test_workflow_metrics.py tests/test_learning_synthesis.py tests/test_learning_synthesis_conversation.py tests/test_workflow_measurement.py tests/test_workflow_measurement_storage.py tests/test_workflow_verified_trial.py tests/test_workflow_verification_wait_metrics.py tests/test_workflow_runtime.py tests/test_workflow_runtime_verification.py tests/test_workflow_runtime_report.py tests/test_workflow_compile_control.py tests/test_instant_mcp.py tests/test_instant_command_queue.py --tb=short --junitxml='<EVIDENCE_ROOT>/20260930-telemetry-judge-01/final.xml'
```

结果：**278 passed，1 skipped，64.08 秒**。跳过的是既有存储测试 `test_existing_run_directory_symlink_cannot_escape_session`，原因 `directory symlink is unavailable`；不报告为通过。覆盖新契约、合成草稿控制入口、原运行/报告集成及已有核验/队列兼容；无实机输入或付费模型调用。 / Source/isolated checks passed; the existing directory-symlink capability check was skipped and is not counted as passing.

保留的先失败后修复证据 / Retained first failures and repairs:

- `red.xml`：24 failed、7 passed；初始入口和判断模块未实现。后续 `focused-01.xml`：31 passed。
- `red-synthesis.xml`：2 failed、12 passed；草稿状态未露出调用方指标、有效 JSON 变更未被识别。修复后 `integrated-01.xml`：133 passed、1 skipped。
- `red-binding.xml`：1 failed；原始回执更改后仍显示用量有效。新增来源哈希复核后 `focused-binding.xml`：35 passed。
- 增加原运行/宿主报告和双图用量契约后，最终集合见 `final.xml`。各集合有重叠，不相加。 / Final coverage includes original runtime/report integration and before/after evidence; overlapping suites are not added together.

Luna 仅做只读契约核对，没有执行测试；主 Agent 核对并修复来源回执复核缺口。此审阅不是同候选实机独立验收。 / Read-only review did not run tests or constitute independent physical acceptance.

边界：调用方内部不可见的总调用/token 仍为未知；未验证真实判断 API、模型准确率或学习速度收益。将来适配器须落实网络超时与实时图像采集；此接口本身不强制中断挂死 provider，也不证明图像引用的新鲜度。旧宿主未重载；R1c、R2–R6 实机/收益出口状态不变。详见[合同](../OPTIONAL_JUDGMENT_AND_MODEL_USAGE.md)。 / Hidden usage, live connectivity/accuracy/benefits and physical acceptance remain unproven; adapter deadlines and fresh capture remain future integration work.

## 2026-09-30 普通逐步结果与当前阻塞 / Per-step results and next gate

运行页新增只读“本次步骤结果”：逐步显示通过/未通过/不确定/等待核验、规则/Agent/运行时核验来源，以及有证据的时段与已记录模型调用。输入已派发不等于通过；缺少时钟和调用证据显示未知，已记录 0 次不等于完整模型调用为 0。切换运行或会话清除旧行，旧运行不借用新版步骤名称。原开发者信息保留，不需要阅读 JSON 才知道每步结果。 / The ordinary run page now exposes ledger verdicts, judgment sources and partial telemetry without equating dispatch with success or recorded counts with complete usage. Switching runs clears stale rows and pinned titles do not drift.

实现复用原 Trial history 与计量账本：`workflow_metrics.load_run_metrics` 返回按原 step_id 汇总的 `by_step`，`WorkflowRunHistory` 只读呈现，不新增执行器、输入权限或审核判定。新测试先 4 failed；运行页、恢复、实际 main 原队列、两轮当次输出、宿主报告及计量共 70 passed。首次截图第二行不完整，增大表格最小高度后只复测相关主窗口旅程 1 passed（与 70 项重叠，不相加）；`history-main-final.png` 已核对。均为全新合成内容的隔离/离屏验证，非真实输入和收益验收。 / Existing persistence supplies the view. Source checks and the inspected main-window capture pass; a focused layout rerun overlaps the 70 checks.

证据 / Evidence：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20260930-run-history-01`。文档原件已备份，本轮没有打包、发布或修改版本。

当前主线核对：R1a/R1b 已有原始实机与清理证据；R1c 已冻结两轮 Record Desk 变化、截图预览、43 项源码预检和零输入清理，但明确操作确认仍未收到。只读子 Agent 核对和主 Agent 源码复核找到的普通 history 展示缺口已补齐；不把历史未勾选项直接推成未实现，也不把本轮局部检查当作完整验收。 / R1a/R1b evidence remains intact; R1c preflight has no physical inputs and awaits explicit confirmation. Read-only gap review identified the history view now implemented, not an independent physical acceptance result.

下一步必须在确认后加载当前源码的新宿主，重新截图定位，按已预览的 R-731 / R-284 两轮范围运行原保存程序。R2/R3 实机变化、异常恢复与清理，R4 配对收益，R5 基于实测优化，R6 第三方迁移和同候选独立验收仍开放。不能以更多源码微调、重复测试或旧记录回填替代这些出口；未知总调用/token 继续未知。真实输入依 AGENTS.md 的“确切预览和独立确认”要求等待用户答复。 / The next substantive step needs the pending exact-action confirmation. Physical continuity, paired benefits, measured optimization and transfer gates remain open; more source checks cannot substitute for them.

## 2026-09-30 改名保留审核 / Preserve review on rename

修复仅修改步骤显示名称时，当前步骤及依赖其输出的后续步骤被错误重置为待审核、已观测动作被标成人工修改的问题。保存仍生成不可变新版本；原目标规则、审核状态及动作来源保留。目标、填写来源、条件或验证规则等执行语义改变时，当前及相关下游步骤仍重新待审；明确撤销审核和原待审状态不会被改名覆盖。 / Cosmetic step renames now preserve review, provenance and locator bindings in a new immutable revision; semantic edits still invalidate affected steps, and explicit pending review stays pending.

故障契约 / Root contract：公共 `WorkflowProgramService._derive_provenance` 曾把 title 纳入执行语义变化集，并递归传播给下游；现仅从该变化集中排除显示标题，对所有工作流编辑入口统一生效。没有改变执行授权、动作校验或自动派发行为。 / Separate display metadata from executable semantics in the common save service, without changing action gates or dispatch.

验证 / Verification：新服务测试先 2 failed / 4 passed；补充普通 main 入口及来源检查后先 4 failed / 4 passed。修复后程序、目标依赖、目标编辑旅程、步骤面板及普通 main 保存重开共 **57 passed**。实际 Qt 控件完成改名、保存、关闭重开、旧版本读取且没有输入入队；这是全新合成内容的离屏验证，不能替代真实外部窗口验收。原失败记录和最终 JUnit：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20260930-title-review-01`。 / Fresh offscreen controls verify persisted behavior and unchanged old revisions; first failures remain retained.

R1c 确切真实动作确认仍待回复；R2–R6 的实机变化、恢复、公平收益及第三方迁移未完成。未打包、发布或改版本。 / Physical variation, continuity, measured benefits and transfer remain open; no release occurred.

## 2026-09-30 审核等待计量 / Verification wait measurement

新运行现在单独记录从首次需要审核到原步骤结算或取消的等待时段，包括 Agent/人工审核和继续操作延迟；它不等于模型推理时间，也不增加模型调用数。重复查询、过早继续和同宿主重建 runner 不重置起点；跨进程重开标记不可计时，旧运行不补估算。总模型调用/token 仍未知。 / New runs measure verification handoff waits through reconciliation or cancellation, not inference or model calls. Repeated controls preserve the original clock; cross-process waits remain unmeasured and historical runs are not reconstructed.

相关运行时、计量、持久化、报告、取消及离屏面板检查 135 passed、1 skipped（当前环境无法创建目录符号链接）；新回归先 11 failed，补充损坏状态用例先 1 failed / 14 passed，修复后上述相关集合通过。原命令身份、重复计时拒绝、连续两步、取消、跨进程未知和真实单调时钟均覆盖。证据：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20260930-verification-wait-01/focused-final.xml`。 / Focused verification: 135 passed, one directory-symlink capability skip; first failures remain recorded.

这是源码/隔离验证，未重新进行真实输入、打包或发布。R1b 原始实机证据保持不变；R1c 两轮真实变化测试的确切确认仍待回复，R2–R6 与三项收益仍未闭合。下一实机候选须加载本次源码并重新截图定位。 / This source-only change neither rewrites prior physical evidence nor closes physical variation, continuity, benefit or transfer gates; the next candidate must load the new source.

### R1c 变化预览与源码预检 / Variation preview and source preflight

后续两轮限定自建 Record Desk：相同已保存程序分别查询 R-731、R-284，使用同名记录、不同次序及 detail_above_rows / search_below_rows 布局和新详情。两场景已冻结并逐张核对实际截图；执行前仍须重新定位。只调用 select/capture，预览宿主和窗口已清理，用户确认待答复。首次预览因采集器只读白名单不含 select 而未派发；修正预览调用配置后复用原冻结数据成功，不重抽场景。 / Two exact variation previews are frozen and inspected without desktop input; approval is pending and preview resources are stopped. The initial select-admission failure remains recorded, with the same cases retained.

`r2-r3-source-preflight.xml`：动态目标、程序依赖、宿主变量绑定、普通上游输出入口、取消结算、运行页恢复和无名列表共 43 passed。仅源码/隔离及离屏检查，不能替代 R1c/R2/R3 实机通过。证据根目录 / Evidence root: `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20260930-learning-variation-02`。 / All 43 scoped checks pass; physical variation, recovery and benefit gates remain open.

## 2026-09-30 完整教学与换编号复用通过 / Full teaching and new-ID reuse passed

R1b 在同一全新 Record Desk 窗口和原 MCP 宿主内完成六步教学：查询 R-599 → 唯一行 → 打开详情 → 读取当次 Detail → 填写 → Verify value。普通工作台用真实控件修改上游输出绑定和动态行规则，保存新版本、关闭重开，再以 R-953 连续运行六步；新详情 `detail-73178a74a55a` 替换旧详情 `detail-a52e0dfef4be`，字段 UIA 核验及窗口 Matches current detail 均成功。 / R1b completes six-step teaching, ordinary editor changes, immutable save/reopen and same-session six-step reuse with a new record and fresh downstream detail.

五个复用输入动作全部命中当前学习规则：四个 memory_uia、一个 memory_visible_row；视觉定位交接 0。读取步骤由当前 Agent 查看原截图后回交本次输出，Find/Open/Verify 三个结果使用已声明的 Agent 判断，原运行通过工作台“继续原运行”按钮续接。不是完全无需 Agent 的规则链；未观测的总模型调用和 token 继续为未知，也没有公平对照的提速或准确率收益结论。 / All five input targets resolve from current learned rules without vision-grounding handoffs. One current-agent read and three declared agent result judgments remain; total calls/tokens and comparative benefit are unproven.

工作台驱动为实际 main 的离屏控件，目标窗口输入是真实 gated 输入。原始回执审计验证六个步骤、当次输出、当前候选和固定窗口身份、旧/新程序版本可加载、无输入重放及完整清理；宿主 exec 13540、工作台 exec 89403 退出 0，fixture 退出 0。最初先停止学习再审核使整理读到旧图，返回 needs_review；审核后通过原 learning_stop 提交新图后整理成功，没有重放输入。审计脚本首次误把 input_check 当作 steps 中一项；核对真实回执后改为检查独立 input_check 及值哈希，复核通过。 / Receipt and version audits plus cleanup pass. Preserve the pre-review synthesis response and initial audit-schema mistake separately; neither caused input replay.

证据 / Evidence: `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20260930-learning-full-task-02/live-task-01/full-task-audit.json`、原回执、workbench-saved-program.json、reuse-completed.json、截图与 cleanup.json。本轮沿用已通过 41 项检查的源码，四个文件哈希复核一致；未改产品源码、版本或发布包。 / This physical run uses the previously checked source, with four source hashes unchanged; no product code or release changes occurred.

R1b 主链已通过；R1c 的重新排序/状态变化集合、R2–R3 异常与编辑失效、R4 冻结配对计分、R5 按瓶颈优化、R6 外部应用迁移及同候选独立验收仍未完成。本轮两次完整流程授权已执行完毕，新增真实输入须给出新的确切预览；源码与离屏检查继续推进。 / R1c and R2–R6 remain open, including measured benefits and independent acceptance. The approved two flows are consumed; further physical inputs need their own exact preview while source/offscreen work can continue.

## 2026-09-30 完整任务预检与动态行修复 / Full-task preflight and dynamic-row repair

R1a 同窗口学习复用已通过。R1b 新建 Record Desk 的只读截图/UIA 预检发现无名列表被目标编辑器隐藏、记录专属子控件 ID 被固定进规则的问题。现支持用非空自动化 ID 精确识别无名容器；普通编辑器可明确取消行内属性/动作的固定 ID 限制，匹配仍在每个当前行内要求唯一，旧规则不自动改变。 / R1a passed. Fresh R1b preflight exposed unnamed-container filtering and record-specific child IDs. Identified unnamed containers and explicit per-row ID choices are now supported while preserving unique matches and existing recipes.

新增回归先 5 failed / 3 passed，修复后目标解析、编辑器、服务及实际 main 保存重开共 41 passed；中文界面截图已核对。本轮真实 UIA 树回放同一规则分别选中 R-599、R-953 的 Open detail，没有执行点击。证据：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20260930-learning-full-task-01`，最终 JUnit 为 `unnamed-rows-fixed-final.xml`，`live-task-01/row-replay.json` 为只读回放。一次命令误列不存在的测试文件，0 tests，单独保留 fixed-02.xml，不计通过。 / Tests and read-only real-tree replay pass; an invalid test-path invocation remains separately recorded.

两轮完整查询/详情/填写/校验的确切预览已给用户，确认尚待答复；当前只有 select/capture，无新增真实输入。预览宿主 exec 82353 已按 stop 请求正常退出 0，自建窗口退出 0、cleanup_verified=true，原回执中只有 select/capture。完整任务请求与回读脚本已完成合同校验，缺确认的输入在入队前被拒绝，队列未改变。确认后使用修复后源码的新宿主并重新截图核对同一范围，不复用已关闭句柄或旧坐标；不可把请求校验或离线回放记作完整实机通过。R1b/R1c 及 R2–R6、总模型用量及性能/准确率收益仍未通过。 / Exact full-flow approval remains pending; no physical input occurred. The original preview host and fixture are now cleanly stopped. Request contracts and fail-closed admission are checked without input; load a new repaired host and refresh the confirmed target before acceptance. Full-task and benefit gates remain open.

### 本轮故障归类 / Failure contract

- Failure：有效无名容器不可选；跨编号的控件完整 ID 不同，编辑器固定原 ID 导致复用失配。 / Unnamed containers were excluded and instance-specific child IDs prevented reuse.
- Root invariant：动态行规则必须由当前容器、当前数据和行内唯一目标决定；不能隐式固定学习行实例。 / Resolve current data and unique row-scoped targets without silently pinning the learned row instance.
- Fix location：公共 `uia_rows.py` 容器合同和 `workflow_target_editor.py` 的明确编辑选项。 / Common selector validation and ordinary editing controls.
- Why not app-only：不改 Record Desk，不猜编号前缀，不加入模糊 ID 后缀匹配；同类原生 UIA 列表可用。 / No fixture rewrite, inferred ID prefix or fuzzy suffix matching.
- Regression：不同当前输入选中不同按钮、无名 ID 缺失/空白拒绝、重复容器/属性/动作拒绝、固定 ID 默认保留、取消限制后保存重开并换样例预览。 / Cross-row resolution, strict ambiguity refusal and persisted explicit editing are covered.
- Safety impact：只在人工明确取消子控件 ID 限制时采用原已支持的行内名称/类型规则；服务预览验证每行唯一，执行仍走原新鲜截图和 gated API，不新增输入权限。 / Explicit edits use existing row-scoped semantics; preview and execution still require unique fresh targets.

## 2026-09-30 同窗口学习与复用通过 / Same-window learning and reuse passed

R1a 第二轮在全新数据、同一 Record Desk 窗口和原宿主内完成：学习填写“学习样本甲”→ 当前 Agent 整理参数化草稿 → 普通工作台修改标题、保存并关闭重开 → 参数“复用样本乙”替换原字段 → UIA `field_equals` 成功 → 自建宿主及窗口清理。复用过程没有手工 MCP 恢复或输入重放。工作台使用实际 main 的离屏控件，目标窗口的两次输入是真实 gated 输入。 / The fresh second attempt completes learning, agent-assisted synthesis, normal workbench editing/save/reopen, parameterized reuse and native verification in one original window and host. The real main workbench is driven offscreen; target input is physical and uses the original gated runtime.

首次同窗口尝试保留为失败：乙值已写入，但字段内 1×15 像素的文本光标闪烁使两帧像素核验拒绝，工作台超时。公共观察器现只对有效截图中的字段像素不稳定最多完整重采三次，每次重新读值和前后截图，固定窗口与目标身份，保留失败证据；持续变化、身份漂移和损坏截图仍拒绝。没有重放输入或加入像素容差。 / The first attempt failed on a blinking caret after successful typing. The shared observer now allows at most three complete fresh read pairs for valid but unstable field pixels, preserving identity, strict pixel checks and prior failures; input is never replayed.

回归先为 4 failed / 1 passed，修复后相关 52 项通过。第二轮实机核验首对截图已稳定，没有触发重采；重采分支由真实 PNG 的隔离回归覆盖，不能写成现场重采已触发。审计脚本首次误认为学习事件 after 含 window_identity，随后按原动作回执中的原生身份逐步骤核对通过；这不是额外输入或产品运行失败。 / Regression evidence is 4 failing / 1 passing before and 52 passing after. The successful live pair needed no reacquisition; that branch is covered by PNG-based isolated regression. A read-only audit schema assumption was corrected without additional actions.

证据根目录 / Evidence root: `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20260930-learning-continuity-02/live-physical-learning-01`；`checkpoint-verification.json`、原始回执、工作台和目标截图及 cleanup.json。首次失败与 JUnit 位于相邻 `20260930-learning-continuity-01`。原 run_id：`trial-0991ae2ce6578d325ca645c60bfe8f8d811f063c11e313a6e9f0d7d61c80b33b`。

本轮只关闭 R1a 小检查点。复用命中 memory_uia，视觉定位交接为 0；输入组合 1408.857 ms，规则核验 200.5099 ms，分别为原回执阶段耗时，不能相加当完整任务或公平对照。模型调用总量/token 未知，三项收益尚未证明。R1b/R1c 的查询、动态行、当次详情数据流与修改验收，以及 R2–R6 连续变化、对照、优化和第三方迁移仍未完成。下一项是新数据的完整 Record Desk 流程；已有两次填写范围不扩展为查询、详情点击或新内容填写，须准备确切预览再独立确认。未打包、发布或改版本。 / R1a alone is closed. Zero reuse grounding handoffs and phase timings do not establish total model savings or speed/accuracy gains. R1b/R1c and R2–R6 remain open; the next full-flow input scope needs its own exact preview and confirmation. No release occurred.

### 公共故障闭合 / Shared failure closure

- Failure：原值已正确写入，光标闪烁导致规则核验 uncertain、普通运行无法完成。 / Correct typing was followed by uncertain verification.
- Root invariant：本次字段值必须绑定同一窗口、目标及稳定的前后证据；单次瞬态失败不能代表已执行动作失败。 / Bind the current field value to stable same-target evidence without conflating observation failure and input failure.
- Fix location：`app/learning_memory/verification_observation.py` 的公共只读观察器。 / Shared read-only observer.
- Why not app-only：适用于其他带闪烁输入光标的原生输入框，不识别 Record Desk 专有像素或绕过真实身份检查。 / General native field behavior, not fixture-specific masking.
- Regression：`tests/test_verification_observation_stabilization.py` 覆盖最新值、重采上限、跨次身份漂移和无效截图；相关六个测试文件共 52 passed。 / Fresh values, bounded retries, identity drift and invalid evidence are covered.
- Safety impact：只增加只读完整重采，没有点击、重发、提交或放宽像素匹配；三次不稳仍拒绝。 / Read-only reacquisition adds no input authority and preserves refusal on persistent instability.

## 2026-09-30 普通运行入口的未入队恢复 / Unsubmitted-run recovery

修复 `start` 已创建 ready 任务、紧接的 `run` 因队列忙或宿主暂未就绪而未入队后，普通面板无法继续原任务的问题。成功创建时即保存准备状态；恢复后由用户选择单步或连续运行，固定原 run_id、程序版本、起点和输入，不自动重发或重新创建任务。 / Preserve a successfully prepared trial when the subsequent run request is not submitted; an explicit user action resumes the original identity and inputs.

新增四个反例先全部失败，修改后运行面板、恢复、客户端、普通 main 旅程与运行报告共 65 项通过。先前编辑命令未成功写入时的复测仍为 4 failed / 61 passed，原 XML 保留；最终为 `focused-fixed-final.xml`。证据根目录：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20260930-learning-recovery-01`。 / Four regression cases fail before the production fix; the final focused suite passes all 65 checks, preserving earlier failed runs.

本次仅源码及离屏组件/入口检查，未再次执行真实填写、未更新安装版或发布。R1a 同窗口连续性与普通 UI 无手动协议恢复仍待新宿主实机复验；R1b/R1c 和 R2–R6 继续未完成，总模型调用/token 与性能准确率收益仍未证明。下一步使用修复后的新宿主复验完整学习、审核、保存重开与复用主链。 / Source verification does not close physical continuity or empirical benefit acceptance; the next step is the complete journey on a newly loaded host.

- Failure / 失败：执行请求未入队后，队列清空仍不能从普通按钮继续已经准备好的任务。
- Invariant / 根契约：已创建任务与执行入队是两个状态；入队拒绝不能丢失原任务身份和明确重试入口。
- Fix / 修复位置：公共 `WorkflowRunPanel._accept_receipt` 的成功 start 分支。
- Generality / 通用性：适用于所有工作流，不依赖 Record Desk、字段或坐标。
- Regression / 回归：`tests/test_workflow_run_admission_recovery.py` 覆盖两类拒绝和两种执行模式，检查原 run_id、仅一次 start 和禁止自动重发。
- Safety / 安全：未放宽宿主、队列、版本、起点及原请求未知状态的检查；不新增输入权限。

# 学习工作流收益开发记录 / Learning workflow benefit development ledger

## 2026-09-29 已授权两次填写与恢复边界 / Authorized fills and recovery limits

用户已明确确认原预览中的两次填写。原 `teach-fill` 成功写入“学习样本甲”，保留实际前后截图并生成带 `value` 参数、UIA 目标和 `field_equals` 规则的草稿；普通工作台已修改标题、保存、重开。重开测试窗口后，工作流原请求 `trial-exec-267b8898992184a9b30bb8b9685e6771` 成功写入“复用样本乙”。两次均只执行 focus/type/check_input，没有 Enter 或提交。第二次目标记忆命中，未产生视觉定位交接或外部识图调用；模型调用总量与 token 仍未知。 / Both approved fills occurred once. The second used the learned target and current parameter without a vision-grounding request; total model usage remains unknown.

第二次原运行 `trial-df4b4f2855053b039f06cb0d23c37de2a9a1d807cec90075a6265e930cec2526` 经原 wait_id 继续后，由本次 UIA 实值核验为 success/completed；只读重开工作台没有新增命令，所有自建宿主及测试窗口清理通过。 / The original run was reconciled using its original wait and a fresh UIA field value, without input replay; owned resources were cleaned.

**范围未闭合：** 首次查询脚本误用了 `learning_session_id`（事件查询应为 `learning_id`），导致原窗口提前清理；因此这是重开后的复用，第二次输入前新窗口字段为空，不能算“同一窗口由甲替换成乙”的连续通过。后续还需手动 MCP 恢复，R1a 普通用户无干预链与同窗口连续性仍待复验，R1b/R1c 及 R2–R6 未完成；没有提速或准确率提升结论。 / Reopened reuse is verified; same-window continuity, hands-off normal UI recovery and full benefit acceptance remain open.

本轮修复合法目标记忆被缺省视觉能力挡住、无 result 失败回执不能结算、记忆库短事务抢锁和同步恢复后旧错误提示残留。主 Agent 源码回归 157 passed，加宿主报告/客户端回归 55 passed（有重叠，不能相加为唯一用例数）。锁和报告修复没有热加载到已运行宿主；现场完成截图仍保留旧错误提示，不能把源码通过写成新候选实机通过。 / Source fixes pass focused checks; the existing live host did not hot-load the final lock/report changes, and its stale visible error is preserved as evidence.

证据 / Evidence: `D:/AgentReviewAcceptance/20260929-learning-benefit-01/live-physical-learning-02/physical-checkpoint-verification.json`、`workbench-completed.json`、`recovery-cleanup-02.json`；首次失败及各次工作台产物分别保留。未打包、推送、改版本或调用付费模型 API。 / First failures remain separate; no release or paid-model test occurred.

## 2026-09-29 真实填写暴露的公共故障 / Shared failures exposed by physical fills

1. **Failure / 失败：** 记忆复用先被 `capability_unknown` 拒绝；失败回执缺少 result 被误当成待验证。修复后第二次填写成功，运行协调又遇到工作区锁占用；原等待恢复 completed 后旧错误提示仍残留。首次失败均保留。 / Admission, failed-receipt settlement, short-transaction contention and stale reporting failed at distinct layers.
2. **Invariant / 根因契约：** 可由本地记忆规则完成的定位不应先要求视觉模型能力；终态失败不得请求 Agent 判断成功；共享短事务须保持互斥并允许有界等待；明确恢复后的报告应反映当前状态。 / Separate memory resolution from model requirements, preserve terminal facts, serialize transactions and update current reports.
3. **Fix location / 修复：** `agent_command_jobs.py` 仅允许合法 target_memory 在 capability_unknown 时先匹配，未命中仍按原能力拒绝；workflow_trial/runtime/runner 按原命令及回执结算 failure/cancelled，未知 action_executed 保持 null；MemoryWorkspace 只对明确 OS 锁占用最多等待 1 秒，不重试服务或输入；宿主成功 run/continue 清理旧 runtime error，失败和纯查询不清理。 / Fix shared admission, reconciliation, library locking and host reports.
4. **Why general / 通用性：** 不依赖 Record Desk 标题或坐标。具体抢锁者未记录，可能是编辑器或同宿主的输入线程，不能归咎于某一个窗口。 / These contracts apply across workflows; the exact concurrent lock holder was not recorded.
5. **Regression / 回归：** memory-admission RED 5 failed、failed-receipt RED 3 failed、memory-lock RED 2 failed、runtime-report RED 7 failed 均保留。主 Agent 最终分别运行 `physical-reuse-final-source.xml` 157 passed 与 `physical-reuse-report-source.xml` 55 passed（重叠）。真实第二次回执 memory matched、current_capture、UIA input_check matched；原 wait_id 恢复后 field_equals 读取本次乙值，原动作没有重放。原失败请求离线取消结算不改变任何原命令或回执。 / Unit/contract and original-receipt evidence are kept separately from successful recovery.
6. **Safety impact / 动作影响：** 未扩大用户的两次填写授权；两次物理输入各一次，无 Enter/提交，仍复用 execute_recognition_plan 和原输入链。显式 unsupported、非法记忆、身份/证据不匹配继续拒绝。锁等待不取消互斥、不重复服务方法；缺少输入事实不猜测为 false。 / No extra input authority, model-capability bypass on misses or replay was introduced.

脚本故障单独记账：首次事件查询参数错误使原宿主清理；离线恢复脚本前两次分别遇到测试前置断言和 MCP 结果字段假设错误，第三次完成；工作台最初指向新会话而没有原草稿，后来重复等待已保存草稿，均无额外填写。用户已批准的两个物理值最终均匹配，但普通 UI 无人工 MCP 干预和同窗口连续验收仍未通过。 / Harness failures do not become product passes, and recovered inputs do not close the full usability gate.

## 2026-09-29 真实宿主连接与工作台重开 / Live host attachment and workbench recovery

1. **Failure / 失败：** live-guided-recovery-01 在保存后不能连接，02 加入界面状态证据复现 workflow_run_host_not_ready：指针 PID 62196 为虚拟环境启动器，ready 报告 PID 63788 为它的直接 Python 子进程。源码复现还证实切换会话残留旧输出、空输出留旧 tooltip、非 start 回执接受错误 run_id。
2. **Invariant / 根因契约：** 启动器与执行进程可能不同，但必须属于同一确切会话；界面显示和控制结果必须归属于当前会话/原运行。 / Distinguish launcher ownership from verified runner identity and preserve data ownership.
3. **Fix location / 修复：** workflow_run_client._verify_runner 核对活性、父进程、入口、--output，并固定实际 PID/创建时间；_original_receipt 核对返回 run_id。workflow_run_panel 在会话切换及空输出时清除对应文字与 tooltip。 / Shared editor attachment and presentation paths, not an app-specific workaround.
4. **Why general / 通用性：** 适用于同一运行框架中的 Windows 虚拟环境启动、跨会话查看和任何工作流回执，不依赖 RecordDesk 控件内容。 / Applies to all workflows using the same attachment client.
5. **Regression / 回归：** 6 个身份/残留反例先失败，修复后 63 项通过；tooltip 反例先失败，局部 7 项通过。launcher 的 owned 反例与 4 个拒绝分支先失败；首次整合 5 failed/66 passed 属于测试误改全局 psutil.Process 后触发 isinstance TypeError，改为模块级代理后 71 passed。首次测试插入位置的尾部语句归属也在最终验证前纠正。最终证据 guided-recovery-integrated-fixed.xml。03 实际只读恢复行为成功但 UI 截图缺字体；04 仅修正离屏验收脚本字体，真实只读 main 旅程、中文截图、20 条清理前命令、两次空 start 输出/互不重用执行 ID 和全部清理均通过。 / Preserve first attempts, harness failures and successful reruns separately.
6. **Safety impact / 动作影响：** 未改变输入派发、点击门控或确认要求；不直接接受任意子进程，也不重发未决请求。没有物理点击、填写、模型 API 费用、发布或版本变更。R1–R6 未整体完成，empirical_acceptance=false、模型总量未知。 / No additional input authority or empirical benefit claim.

证据根 / Evidence: D:/AgentReviewAcceptance/20260929-learning-benefit-01；live-guided-recovery-01/02 为失败，03/04 为行为成功。所有宿主 cleanup_verified=true，fixture returncode=0；04 的 recovered-main.png 和 completed-main.png 由主 Agent 目视核对。子 Agent 仅脚本实现及只读源码复核，不计独立实机验收。备份 source-before-guided-recovery；摘要 guided-recovery-verification.json。


## 2026-09-29 普通参数化、结果来源与运行入口 / Guided inputs and run entry

- **Failure / 失败：** 参数绑定依赖两处手写名称，缺失引用不能直接选择修正；运行对话框在关闭后才解析类型。实际截图还显示了生成的 `input_sequence` 内部标题。
- **Root invariant / 根合同：** 人工选择必须指向当前草稿中唯一、类型正确且较早的来源；失效不能静默换值。运行参数需验证成功后才提交，当前结果只能属于本 run；运行名称来自固定版本。
- **Fix location / 修复位置：** `workflow_steps_pane.py`、独立 `workflow_input_dialog.py`、`workflow_run_panel.py`。原服务/调度/动作后端不变。
- **Why general / 通用性：** 使用已有变量和步骤定义，适用于任意已支持工作流，不依赖夹具字段名；图视图自动提交、类型改变、重名、重排及恢复导航均覆盖。
- **Regression / 回归：** 选择器 RED 8 failed；对话框 RED 缺模块→10 passed。首批集成41 passed；运行入口RED2 failed。展示复测初次1 failed/23 passed属于断言误把提示中的“保存新版本”也判作错标题，改查确切无关标题后24 passed。截图发现内部标题，RED1 failed/1 passed后修可读名称。最终相关集成128 passed；加强的两条原队列旅程2 passed，不相加。
- **Safety impact / 输入影响：** 取消及校验错误零派发，未增加执行权限或绕过原动作入口。本轮无物理输入、无模型调用；测试中的操作成功和 Agent review 明确为合成回执，不能用于收益或真实验收。

保留诊断首次失败：`guided-run-presentation-red-initial.xml` 是测试节点名拼写错误，未运行任何测试；更正命令后产生真正 RED。未将其归为产品故障，也未覆盖原文件。子任务负责对话框和一条测试，主 Agent 检查实际差异、独立运行集成及查看四张截图；源码交叉核对不是独立实机验收。 / Retain invocation mistakes and source-only review separately from product evidence.

证据：`guided-input-integrated.xml`、`guided-queue-journey-final.xml`、`guided-root-render/*.png`，均位于本机证据根。UI 修改前全套2670/1保留为历史，当前不宣称全套已重新运行。下一步 R1 活宿主全任务及 R2/R3 变化恢复，同时补真实调用方计量；不继续重复建设参数编辑器。 / Continue toward physical use and empirical benefit.


## 2026-09-29 执行策略与原请求恢复 / Execution strategies and reconciliation

- **Failure / 失败：** 原 start 终态的 instant_result 再次返回同 trial 时被误判复用；无条件覆盖又会把已完成状态倒退为 ready。策略初始未接线；恢复的 steps_only 票据可能夹带 target_memory。
- **Root invariant / 根合同：** 同 attempt＋原 request 的只读回执幂等且不得回退状态；运行策略先于票据固定，不能混入另一条策略的定位/验证。
- **Fix location / 修复位置：** 公共 Trial/control/workspace、目标描述及 runtime verification，开发采集器；无新输入执行器、无供应商切换。
- **Why general / 通用性：** 不依赖 Record Desk 按钮名称；同一约束覆盖所有工作流起点、当前变量、原回执和待处理验证。
- **Regression / 回归：** 原 start 修复 RED 1 failed/18 passed → 19 passed；collector 策略 RED 3 failed/19 passed → 23 passed。核心策略先见 11 failed，后补绑定 RED 2 failed/11 passed、恢复 RED 3 failed/13 passed；最终集成 264 passed，集中源码 2670 passed/1 skipped。完整 XML 保留在证据根。
- **Safety impact / 输入影响：** 策略只减少自动匹配/核验路径，仍走原票据和动作门控；本轮实机零输入。B 原生 rule 写入被拒绝，Agent review 不伪装原生证据。

真实联调 live-execution-strategy-04：全新库、窗口、录制与截图；当前 Agent 实际读取教学图和 B 的新图。C 同程序由原生规则完成；B 在 verification_required 等待，经原 review/continue 完成；A 禁止学习执行。原 start 回读不回退完成快照；同一连接和固定 program_id，源程序不改写，两个宿主均清理。A 仅 discover；B/C 为只读标签任务，不是三个预定物理任务。采集结果均 completed=false、empirical_acceptance=false，完整调用/token 仍未知。 / Fresh real-MCP source integration, not physical or benefit acceptance.

首次联调失败保留：01 的 Windows venv launcher PID 与 Qt 子进程 PID 不同，02 的诊断脚本误用 begin 位置参数，03 的诊断脚本用了大写请求 ID。均为诊断调用层；核验进程祖先/命令行后绑定窗口进程，改用确切关键字与小写 ID，04 复测通过。01–03 自建窗口均退出；02–03 MCP 清理通过；01 尚未启动 MCP。没有改弱生产校验。 / Retain harness failures separately from the passing rerun.

计量审计：原生 verification 事件不是模型调用；API grounding attempts 有真实边界；Agent handoff 仅是等待，planning 与 Agent 判断的内部调用/usage 仍不可观测。没有为填满指标添加虚构事件。 / Missing caller telemetry remains unknown.

文档已同步 README/AGENT_GUIDE、四份本地维护文档、成功标准、计划和基准说明。当前工作树不存在 RUNTIME_STATE_GRAPH.md/zh-CN，策略沿用原运行状态，不凭空创建历史图；OpenClaw 迁移未改变。没有发布、打包、改版本或独立 Agent 实机验收。源码只读审查发现的 B 恢复票据问题已修并纳入回归。 / Documentation and source review are scoped separately from independent live acceptance.


Plan: `docs/superpowers/plans/2026-09-29-learning-workflow-benefit.md`

## 2026-09-29 开始实施 / Implementation started

用户已要求按计划开发，完整 T0–T8 目标保持。当前工作树 `codex/dev-workflow-editor` 基于 `c7a3099607d039fb3e377be1de7ff26151d1101c`，保留之前未提交实现。修改前维护源码已备份到 `D:/AgentReviewAcceptance/20260929-learning-benefit-01/source-before.zip`，对应清单为 `source-before.json`。 / The user authorized implementation of the full plan; existing work is preserved with a pre-change source snapshot.

Ruling: 沿用已有工作树，主 Agent 负责运行时与集成，两个有界子任务分别负责测量和目标引用；不按每任务重复建工作树/提交/审查。项目用户指令和既定计划允许这种分工。 / Reuse the existing checkout and delegate disjoint work, with main-agent integration.

Pre-flight: T1 提供 `TargetMemoryRef` 与持久化 recipe，T2 消费并生成当前候选；T3 的结果契约供 T5 调度消费；T6 编译与 T7 UI 写同一程序定义；T0/T8 共同使用测量事件。共享文件合并由主 Agent 串行安排。 / Interfaces and write ownership are coordinated centrally.

Ruling: 计划中的“本轮只写文档”是上一轮范围；本轮用户已授权实施。对照基线的夹具和计时模块可与 T1 并行开发，但收益数据必须先冻结输入/口径，不能用后验选题冒充基线。 / The new instruction supersedes planning-only scope; measurement definitions are frozen before scoring.

CodeGraph 对此工作树未初始化，已经工具确认；使用 rg 和精确 UTF-8 源码读取。 / CodeGraph unavailable for this checkout, confirmed by tool.

## 任务状态 / Task state

当前逐项状态统一见 [完整计划首表](../superpowers/plans/2026-09-29-learning-workflow-benefit.md)。T6 同状态多动作来源、规则提议及保存重开已通过源码检查；完整自动生成和实机收益仍未闭合。 / Multi-action compilation is checked; full product acceptance remains open.

下方历史段落保持当时事实；当前状态以本节及最新证据校准为准。 / Historical sections retain their original scope.

## 最新证据校准 / Latest evidence reconciliation

当前批次：原 Trial 新增启动时固定的 execution_strategy（learned 默认、steps_only）。steps_only 在生成原票据前禁用记忆定位，保留本次目标含义和当前变量，结果必须交回 Agent review；已保存程序不改写。采集器将 A 普通执行、B steps_only、C learned 与真实命令/回执核对，拒绝跨运行引用、策略冲突和 A/B 的目标记忆。 / Trial strategy is pinned before ticket creation; collection validates actual route commands and receipts.

检查：execution-strategy-integrated.xml 为 264 passed；集中源码 execution-strategy-source-suite.xml 为 2670 passed / 1 skipped。全新可见 Record Desk 经同一真实 MCP 完成 C 原生规则读取与 B 当前 Agent 看图后 review/continue；原 start 回读未覆盖后续完成状态，宿主和自建窗口清理通过。未派发物理输入。 / Focused and consolidated source checks pass; fresh real-MCP read-only strategy integration and cleanup are verified.

尚未达成：完整调用方模型计量、冷暖/学习开销及易混/负向/恢复集合、普通用户完整学习后连续点击填写、实机 A/B/C 配对和三项收益。总模型调用/token 仍为未知，empirical_acceptance=false；本轮只读任务不冒充查询、打开记录或下游填写成功。 / Complete caller telemetry, physical paired tasks and empirical benefits remain unverified. No release or version update.

证据根 / Evidence: `D:/AgentReviewAcceptance/20260929-learning-benefit-01`。

### T7a 普通运行、原请求恢复与绑定 / Normal execution and original-request recovery

新增 WorkflowRunClient/WorkflowRunPanel，接实际 main 的运行页。客户端复用 InstantSession.submit/result 和原队列；source control 标记仅记录原请求关系，不是第二套执行器/完成账本。编辑器 close 不拥有宿主；未知模型总量和 token 显式保留。 / The editor attaches to the existing runtime and preserves its ownership and accounting.

1. Failure / 失败：原工作台仅准备票据；关闭后丢失未决控制 ID。源复核又发现改会话路径仍能用旧连接、恢复后选不同步骤仍运行旧起点、回执/当前 trial 未完整核对原命令参数，以及连接后学习按钮未启用和状态被轮询覆盖。 / Missing execution/recovery and stale UI/original-binding gaps were reproduced.
2. Root invariant / 不变量：界面选择、已保存版本、原起点、请求/回执和本次参数须一致；已知未入队、未知结果及实际完成不得混淆；状态查询不重派发。 / Preserve exact control identity and truthful outcomes.
3. Fix location / 修复：公共原队列上方的非所有者 client、原运行 panel 及 main/pane 的上下文同步；未新建输入后端。 / Client/normal UI integration over the existing executor.
4. Why not app-only / 通用性：所有使用同一持久程序和宿主的应用均共享这些约束；不依赖测试窗口标题或坐标。 / The fixes apply across applications.
5. Regression / 回归：run-main-red.xml 3 fail；run-recovery-ui-red.xml 4 fail；run-learning-connection-red.xml 1 fail；run-binding-review-red.xml 2 fail；run-receipt-binding-red.xml 2 fail。另保留 worker 的 client/admission/recovery RED。最终 run-integrated-recheck.xml 97 pass，run-source-full.xml 2552 pass/1 skip；run-main-final.png 已视觉检查。 / Initial failures and later passing runs remain distinct.
6. Input impact / 输入影响：产品新增显式运行按钮，仍通过原宿主和原 gated action API；本批隔离检查仅写真实控制/调度队列并使用合成回执，没有消费桌面输入命令、启动真实宿主或做实机独立验收。 / No physical actions were dispatched by this batch; existing runtime gates remain.

Ruling: 原计划 T7a 的实际 main 用例集中到 test_workflow_run_journey.py，保留旧 user_journey/步骤/目标/runner 回归；移除“已源码实现仍待创建”的旧描述。82/95 项整合结果是中间检查点；后续修复后的当前基线为97项及完整源码XML。 / Dedicated main-entry tests and final evidence supersede intermediate checkpoints without deleting them.

完整命令 / Full command: `python -X utf8 -m pytest -q tests --junitxml=D:/AgentReviewAcceptance/20260929-learning-benefit-01/run-source-full.xml`，QT_QPA_PLATFORM=offscreen。物理单项/连续任务、自动整理纠错及公平收益仍待办，目标保持 active。 / Physical and benefit gates remain open.

### T7 目标编辑与纠错详情 / Target editing and correction details

本批功能：v3 editorial/unverified、固定 UIA 和单条件 visible_row 编辑、同一解析器的只读学习图预览、参数/上游输出依赖保护、原主窗口保存重开，以及持久整理错误及有证据的回复顺序。截图为 `target-editor-main-final.png`。源代码静态交叉复核不等于另一 Agent 的实机独立验收。 / Implemented source and offscreen behavior; source review is not independent physical acceptance.

1. Failure / 失败：目标条件可引用未知/未来输出；直接保存人工规则可能绕过动作/控件类型检查；变量改成非文本后旧预览仍有误导风险。 / Invalid dependencies or type mismatches could bypass the editor.
2. Root invariant / 不变量：持久化、预览和运行须采用同一动作语义与本次有类型的数据依赖；原动作证据不能替新人工目标背书。 / All entrypoints enforce the same typed semantic contract.
3. Fix location / 修复：target_recipe、target_resolution、workflow_program 的公共验证；目标提议服务和普通 editor 调用同一合同。 / Shared contract and program validation with normal UI integration.
4. Why not app-only / 通用性：约束适用于所有引用该程序/目标规则的客户端和应用，不依赖某窗口标题、列表标签或夹具坐标。 / The invariant applies across applications and clients.
5. Regression / 回归：target-program-deps-red.xml 保留 3 个缺陷；target-review-red.xml 保留 3 个类型/绕过缺陷；correction-order-red.xml 保留 5 个顺序缺陷。64 项整合复测通过，完整源码 2512 passed / 1 skipped。target-editor-integrated-final.xml 的 2 failed / 62 passed 是夹具把 schema text 错写 string，修正后的 recheck 文件另存，未覆盖初次失败。 / Failures and successful reruns are retained separately.
6. Input impact / 输入影响：没有新增输入路径、放宽输入检查或真实点击；预览标 learning_capture，人工新规则为 unverified。未进行新的物理验收或收益测量。 / No input authority or dispatch was added by these source checks.

实际完整命令 / Actual full command: `python -X utf8 -m pytest -q tests --junitxml=D:/AgentReviewAcceptance/20260929-learning-benefit-01/target-editor-source-full.xml`，QT_QPA_PLATFORM=offscreen，162.68 秒。当前计划按此检查点继续，72 项旧聚焦和 2472/1 旧全套保持历史标签。 / Current full-source evidence supersedes earlier source baselines without rewriting history.

### T7 普通草稿入口 / Normal synthesis-draft entry

当前代码：workflow_learning_review 只读已有会话与内容库，editor_client/workspace 提供短事务入口；workflow_steps_pane 用原异步任务机制显示状态，保存调用既有版本/规则服务。无新模型或执行宿主。 / Read an existing learning session and save through the maintained services.

1. Failure / 失败：工作台无整理状态/草稿入口；无 request 的不支持动作段被误报为等待发起整理。 / Missing normal controls and misleading unsupported-only state.
2. Root invariant / 不变量：只读状态须区分未发起、录制缺口和无可编译步骤；读取不能产生模型/输入任务或覆盖未保存修改。 / State reads are truthful and free of execution side effects.
3. Fix / 修复：共用 review 适配只读编译无请求的归档，零步骤为 needs_review；原 pane 加状态/打开入口，草稿保存保留版本摘要并仅提交仍被引用的规则。 / Repair common state classification and use existing optimistic saves.
4. Generality / 通用性：没有按应用名称或坐标加分支；支持的学习段使用统一接口。 / No application-specific workaround.
5. Regression / 回归：入口 RED 为 3 failed（缺少新入口）；适配 empty-red 为 1 failed/6 passed（误报 not_requested）；首次 UI 集成 26 passed；最终相关入口、适配、程序、来源测试 72 passed。主 Agent 检查原 XML 与实际窗口截图。全套 2472/1 发生在本批 UI 前，集合不可相加。 / Preserve failures and distinguish focused checks from the prior full suite.
6. Input impact / 输入影响：本批仅全新合成数据离屏交互，检查等待→草稿→修改→保存→重开、错库拒绝和未保存保护，均无 commands 派发。未证明 live host、真实动作或收益。 / Offscreen evidence does not count as physical or benefit acceptance.

Evidence / 证据：synthesis-ui-entry-red.xml、synthesis-ui-adapter-empty-red.xml、synthesis-ui-integrated-final.xml、synthesis-ui-main.png；源码/文档摘要在 synthesis-ui-checkpoint.json。 / Evidence and source hashes are retained.

### T6b 同会话整理交接 / Same-session synthesis handoff

Ruling: 对外使用 `synthesis_request`，不为新功能放宽原命令 `request` 的个人文本脱敏。整理回复是当前 Agent 的工作，不借用视觉 continue、不新开 Agent。 / Name the new payload explicitly and retain original-command redaction.

1. Failure / 失败：prepare/status 的整理请求被通用回执清理；来源 ValueError 被误报为待修注释；篡改归属的 attempt/completion 仍可返回；只有不支持动作时也请求生成空草稿。 / Public payload loss, misclassified source faults, weak reply scope and empty synthesis.
2. Root invariant / 不变量：公共合同必须保留任务载荷并区分原命令；来源故障不让模型猜修；持久回复必须属于原请求/来源；无可编译步骤不能冒充可用草稿。 / Transport, source identity and truthful draft state are shared contracts.
3. Fix / 修复：learning_synthesis 的字段和持久回复核验；compiler 明确 LearningAnnotationError，仅转换可修注释错误；无步骤返回 needs_review/no_compilable_actions。 / The common synthesis/compiler boundary owns the repair.
4. Generality / 通用性：未加入 fixture 控件名称、坐标或特定应用分支，所有受支持学习段均使用同一合同。 / No application-specific workaround.
5. Regression / 回归：synthesis-contract-red.xml 为 6 failed/1 passed，其中待定测试缺 reserve 属夹具错误，补确切票据后通过；empty-draft 首版夹具漏 step 派发字段，修正后 valid-red 才复现真实 awaiting_agent 缺口。MCP payload-red 保留旧字段缺失。整合175项通过，完整源码见本节首表。 / Initial product and fixture failures remain distinct from successful reruns.
6. Input impact / 输入影响：真实案例仅 read_text；两次新录制、当前 Agent 阅读原图并写审核/整理回复、一次有效整理、重复回复幂等、待审保存/审核保存/重开、旧版本保护、两轮各两步、零输入、宿主清理通过。未改动作门控、未验证物理或收益。 / Real current-agent generation and reuse are scoped to a read-only native journey.

Evidence / 证据：`live-synthesis-readonly-01/{review-evidence,agent-reviews,agent-synthesis-evidence,agent-synthesis-reply,summary,cleanup}.json` 与两轮原结果。`handoff_elapsed_ms` 为整理交接墙钟时间；模型总量未知，不据此宣称推理变快。 / Current-agent decisions and transport evidence are preserved separately from unavailable total usage.

### 读取观察与人工审核修复 / Read-observation and review fixes

1. **Failure / 失败：** case02 保存来源失真；source_evidence 修复后人工 reviewed 仍被重置；case03 第二步因整窗 hash 变化暂停。 / Persisted provenance/review and global-frame rejection.
2. **Root invariant / 公共不变量：** 来源、审核、当次成功应分开。case03 两张原图仅在查询框光标 `(14,139)-(15,154)` 有15像素差异，目标标题框为 `(11,11,618,118)`；整窗字节相等误作读取目标稳定条件。 / Review and provenance are distinct; unrelated caret pixels do not invalidate an unchanged read target.
3. **Fix location / 修复层：** workflow_program 只在新来源或受影响修改时置 pending；verification_observation 保留完整前后帧字段，先核对身份/几何/应用和两次完整 UIA 的唯一控件，再核对目标区域原图像素。缺目标的 absence 检查仍要求整窗稳定。 / Common program and observation contracts own the fixes.
4. **Why not app-only / 通用性：** 未添加 fixture 名称、坐标或像素阈值；所有受支持原生读取都用当前控件框。 / No application-specific selectors or tolerance threshold.
5. **Regression / 回归：** 外部闪烁通过，目标内像素、对象/窗口/几何漂移、歧义、不完整树、被改截图仍拒绝。case04 两轮共6观察，其中一次全图 hash 改变但目标区域及其他身份字段一致而成功。审核保存/旧版本保护经原 MCP 实测。 / Negative invariants and a real scoped-stability event are checked.
6. **Safety / 输入边界：** 不改动作门控，不做输入，不重放未知动作；目标内变化仍 uncertain，未声称任意动画或布局都可处理。前三轮失败和本轮修复后成功分开保留。 / No input gate or replay changes; scope limits remain explicit.

### T6 同状态多动作 / Multi-action evidence

Ruling: 保留 v1 和现有 pin；新自动提议用 v2 的第二份 learning_action 引用绑定既有不可变 bundle/segment/event/observation。代表图与动作图是不同证据，不通过放宽旧比较或隐式采用新图解决。此片不修改输入执行器。 / Preserve old contracts and distinguish representative and action evidence.

1. Failure / 失败：同状态 B 的 before 图不同，编译只得到 A。新 test_learning_action_evidence 首轮 6 项失败，见 learning-action-evidence-red.xml。 / The second action lacked a proposal.
2. Root invariant / 不变量：复用规则必须固定它真正来源的动作与状态；代表界面的版本不能冒充每次动作前图。另一次只读复核发现改目标/锚点/动作后重算 recipe 摘要仍可借用原动作，主 Agent 用 3 项 RED 重现。 / Independent action and rule provenance must remain truthful.
3. Fix / 修复：action_evidence 从冻结 bundle 核对唯一 segment/event、成功边、before 状态、pin 和 observation；target_recipe 分版本校验并核对实际选中 UIA 控件、独立锚点及录制动作语义；compiler/proposer 产 v2。 / Shared persistence and proposal paths own the fix.
4. Generality / 通用性：未绑定 fixture 名称或坐标；复用所有受支持 click/input_sequence 的实际候选、UIA 和原作业身份。固定旧 bundle 是版本语义，后续 graph head 不自动改旧程序；未增加全局撤销策略。 / Generic recorded-source contracts preserve pinned versions.
5. Regression / 回归：整合 114 passed，补充绑定/HTTP 23 passed，全套 2445 passed / 1 skipped。learning-action-rule-binding-red.xml 保留 3 项缺口；learning-action-anchor-valid-red.xml 保留实际完整目标框重叠锚点的 RED。旧规则字节、旧 pin/原图、保存重开、当前控件移动、bundle/观察/两类图片篡改、重算摘要后的审核状态/command 错绑均覆盖。 / Current tests cover persistence, binding and compatibility, not physical execution.
6. Input impact / 输入影响：无真实点击，不改变门控；v2 自动证据不会授权修改后目标。人工编辑仍须实现明确 editorial 来源和待验证版本，已列入 T7，不删改用户原有工作流。 / No input or weakened gates; editable revisions remain required.

首次整合 110 passed / 1 failed：代表图被改已被原 InterfaceContentService 以 DesktopReviewError 正确拒绝，新测试误仅期望 ValueError；修正期望类型，未放宽产品校验。另一个初写锚点负例误改了 anchor 控件而非 target，保留该失败后核对 fixture，正确用例重新在未修实现上失败再修复。后续通过不记为首次通过。 / Fixture mistakes and their corrections remain explicit.

T6b 前期接线调查（历史）：当时 stop 缺整理交接；后来新增服务，再发现公共 request 清理问题。本批采用 synthesis_request 并通过真实只读链，普通 UI、物理参数复用和收益仍未验收。 / Historical findings are now resolved within the current read-only scope.

### T6 采集、归档与待审提议 / Capture, archival and pending proposals

原 host 的 step/input_sequence 和 Agent job 冻结 event_id/command SHA，经 owner scope 传入现有 action API；非学习命令不额外采集。Agent/Memory 使用派发前复核 capture，来源来自实际选中候选；框外点击点、来源缺失和不完整 UIA 明确 unavailable。额外 UIA 成本记为 learning_target_observation，不能从基准耗时剔除。 / Existing ownership and request identity bind the recorded observation and its extra cost.

receipt_adapter 以实际目标图为 event.before，保留原完整回执；graph_source 归档内容摘要引用和原 PNG。篡改、窗口/应用/事件错绑、不完整树拒绝。compile 只读生成唯一目标与独立锚点的待审规则；显式 save 校验所有引用/语义/版本后保存，错误提议不改 head，不覆盖人工版本。API 回环集成实际经过 HTTP/provider/job/action/recorder/archive/compiler/save，native 提供器与输入被隔离替换。 / Protocol integration is not provider-accuracy or physical-input acceptance.

本批检查：整合 131 passed；最终源码 2429 passed / 1 skipped。保留 learning-observation-source-red.xml、learning-observation-chain-red.xml、learning-proposal-integration-red.xml、learning-proposal-save-red.xml、learning-proposal-visual-box-red.xml。learning-api-recording-first.xml 首败为测试 coordinator 忽略真实 job context；learning-t6-integration-root.xml 的 115 passed / 1 failed 为错误传播用例缺 candidate source，在新前置条件提前返回。修正测试输入后主 Agent 复测通过，未删掉失败记录。 / RED and integration-fixture failures remain separate from the final passes.

native-learning-observation-01 对已核对 PID/创建时间/HWND 的本轮 Record Desk 做截图与 22 控件 UIA 只读采集，按实际 Show notice 候选归档并重开核验；input_command_count=0。事件明确 read_only_probe/action_executed=false，未伪造成功动作或自动工作流验收。该脚本使用现有自建夹具，不访问日常浏览器。 / Native read-only evidence verifies collection and archival only.

上一批限制记录：当时同状态 graph pin 保留首个代表版本，后续不同 before 图返回 exact_before_interface_required；本批已用独立动作来源修复，见上节。此前源码调查不是独立实机验收，真实输入与收益仍未完成。 / The former multi-action gap is addressed above; physical acceptance remains separate.

### 计量与测试隔离 / Telemetry and test isolation

API 网络起止时间和实际 usage 从 provider/ApiGroundingError 保留到 recognition_calls。runner 快照从当前 Trial pending/history 读取原命令及异步回执，按 grounding request ID 幂等记录；先人工审核后调度也有计数。局部统计不能代表整体规划或 token；坏日志/错误关联明确不可用，不改原执行状态。回环 HTTP 测试隔离了系统窗口/物理输入，不代表供应商准确率或实机输入验收。 / Actual attempts are bound to run evidence with partial coverage; loopback is protocol integration only.

首轮全套在 tests/test_workflow_user_journey 停留于真实事件循环：前面的实例级 exec monkeypatch 恢复后留下同名实例属性，遮住后面的类级替换。独立最小检查证实此状态，保留 interrupted.json 后只结束确切 PID 的自建 pytest。新增37返回值复现先失败，改测试实际 QApplication 实例的 exec 后，与前置入口测试连跑4项通过。首次完整运行不记通过；后续首个失败和最终结果按各自 XML 留存。 / Test-hook shadowing is repaired without modifying product startup behavior; the interrupted run remains a failed attempt.

后续诊断运行 `learning-source-first-failure.xml` 为 1477 passed / 1 failed：旧用例让 request 默认为 single、action 为 double，却期望直到 recipe 语义层才失败。当前公共边界正确地提前返回 memory_action_click_kind_mismatch。测试现分别覆盖请求/动作不一致，以及两者一致改为 double 后旧 recipe 的 action_semantics_changed，均断言拒绝发生在观察前；未改生产校验。相关10项通过见 `memory-request-contract-final.xml`。 / The earlier assertion expected a later error despite inconsistent click semantics. Both early binding rejection and stale-recipe rejection are now checked without weakening production validation.

### 实机队列故障闭合 / Native queue failure closure

1. **Failure / 失败：** `live-readonly-chain-01/failure.json` 中前两步完成，第三步遇到并发 status 占队列，错误成为 `workflow_original_queue_busy` / `result_unknown`，链停止。 / A concurrent status request interrupted the third read-only step.
2. **Root invariant / 公共不变量：** 原客户端与调度器应共用原子入队；确定未入队和可能已派发的未知结果必须区分。 / Queue admission must be atomic and distinguish non-submission from unknown dispatch.
3. **Fix location / 修复层：** `app/core/instant_command_queue.py` 统一锁与入队；`instant_mcp.py`、`workflow_runner.py`、`workflow_runtime.py` 区分 queue_busy 延后与未知回执，并结算取消。 / The fix is in common queue/runtime code.
4. **Why not app-only / 通用性：** 与 Record Desk 控件无关，所有客户端状态查询与连续调度共享该队列。 / All applications share this admission path.
5. **Regression / 回归：** 队列线程/跨进程竞争、原 ID 幂等、写入错误、等待时取消纳入相关 133 项；第二轮原 MCP 三步只读链通过并完成宿主清理。首次失败未改记成功。 / Contract tests and the native rerun retain first-attempt history.
6. **Safety / 输入边界：** 只有确定未写入新命令的忙状态允许延后；写入错误继续 unknown，已派发输入不重放。未入队取消回执明确 action_executed=false；本次两轮均无物理输入，不据此宣称点击安全或提速。 / Deferred submission does not relax unknown-input handling.

## 目标定位主链接线 / Target execution integration

本批源码已实现不可变 `target_recipe.v1`、命令引用传递、当前窗口/UIA/模板解析、`MemoryGroundingTarget` 原执行路由适配及输入框定位引用。当前匹配发生在模型准备/委派/API 请求之前；实际输入仍由原 `POST /action/execute_recognition_plan` 处理，输入前再次检查当前图、窗口进程与上下文。预期未命中明确记录并进入配置的识图路线，规则文件损坏或绑定冲突失败，不隐藏为 fallback。 / Immutable recipes and current observations now reach the existing action route before visual model work; expected misses are explicit and corrupt evidence fails.

`runtime_target.py` 只打开宿主配置的记忆库，原生读取期间不持有库锁。测试从本轮合成截图和真实记忆持久文件出发验证模板移动后的当前坐标；没有复用历史学习资产。 / Runtime resolution uses only the host library and releases storage locks during native observation.

已执行：

- 主 Agent 目标引用/工作流/输入链回归：118 passed；`target-contract-root.xml`。 / Reference-chain regression.
- 主 Agent 定位执行整合：`tests/test_memory_runtime_target.py tests/test_memory_grounding_execution.py tests/test_target_resolution.py tests/test_memory_observation.py tests/test_target_recipe.py tests/test_input_sequence.py tests/test_input_sequence_field_binding.py tests/test_agent_command_jobs.py tests/test_agent_grounding_execution.py tests/test_local_step_timings.py`：136 passed；`grounding-integration.xml`。 / Integrated offline regression.
- 保留首次失败：模型准备与委派未接线、runtime 模块缺失、输入框丢失引用的 RED 证据；另一次测试使用了错误的原生身份字段，修正测试边界后复测通过。文件在本页 evidence 根，不将后续通过改记为首次成功。 / Initial failures and test-fixture correction are retained.
- 子任务测量/计分/夹具 11 passed，纯动态行选择器与 recipe 12 passed，纯规则验证 10 passed；这些仍需主 Agent 整合复测，不代表生产路径或独立实机验收。 / Worker checks are component evidence only.

以上批次结束时：T0 计分/测量模块已写但未接完整真实基准；T1 引用链离线通过；T2 主链接线离线通过但真实单项待验证；T3/T4 纯模块已有离线证据、生产整合待完成；T5–T8 未完成。后续进度见下节，没有真实模型收益、安装包或发布结论。 / This is the earlier batch checkpoint; subsequent progress follows below, with no benefit or release claim.

## 当前只读实机与边界补强 / Native read-only checks and boundary corrections

全新 Record Desk 夹具在 `live-fixture-01` 创建，运行数据没有使用旧学习资产。原 Instant MCP 同一连接完成 select、learning_start、capture、event、review、import、template、stop；`real-memory-prepare/results.json` 保留回执，最终宿主 `cleanup_verified=true`。`real-memory-resolution.json` 验证从新持久资产在当前图重新找到 Show notice；`real-verification-observations.json` 为原生按钮存在和当前字段值的只读观察。没有执行点击、输入或模型调用，不能计作真实动作成功或收益。 / A fresh fixture completed the original MCP recording/import/template path with host cleanup. Current target and UIA reads are observed evidence, not action or benefit acceptance.

确切预览后的单次点击仍待用户确认；未得到确认前没有执行。夹具没有读日常浏览器数据；API loopback 或夹具真值不能成为模型准确率、速度的证据。 / The previewed click remains unapproved and unexecuted; everyday browser data is untouched.

主 Agent 复核并修复两个公共边界：目标准备/结果观察必须获得既有桌面单步锁，不能与另一输入步骤竞争窗口绑定；公开动作 API 不支持独立解析宿主 target_memory 时必须显式拒绝，不能忽略引用。保留 `target-boundary-red.xml`、`verify-boundary-red.xml`；第一次锁验证测试误用了替换锁的 timing fixture，恢复真实锁后重测，未将该次失败抹去。 / Shared binding and unsupported-reference boundaries were repaired, with initial failures retained.

- 定位执行、动态行及异步 MCP client 主 Agent 回归：155 passed，`target-boundary-final.xml`。 / Target/client regression.
- 调度、Trial、异步回执、结果规则和原生观察主 Agent 回归：61 passed，`runner-verification-final.xml`。 / Runner and outcome regression.
- T5 每个 run 独立文件和 active 指针、旧 run 幂等查询、single_complete 确切继续及异常原因已纳入上述检查；尚未连接真实宿主队列。 / Persistent scheduler behavior is tested, not yet host-wired.

以上测试集合含重叠，不相加；真实连续运行、自动生成可用规则、用户入口和公平 A/C 基准仍是后续完成门槛。 / Suites overlap; complete live execution, usable generation/UI and matched benefit evidence remain open.

## 草稿编译与中断保留 / Draft compilation and interrupted histories

`workflow_compiler.py` 从已验证的本段 immutable GraphSource 生成只读定义候选，显式参数绑定先核对首轮输入摘要，人工保存过的版本保持不变；缺少目标/结果规则会返回 unresolved。它尚不替代 Agent 的一次规则整理，也没有普通 UI 的自动生成入口。 / The compiler preserves evidence and edited revisions while exposing missing rules; synthesis and normal UI integration remain incomplete.

主 Agent 阅读后发现 `_draft` 会按过滤后相邻节点补边，要求先补“成功 A→失败/待定 B→成功 C”的失败回归。修复后只有实际顺序直接连续且界面衔接的两个成功动作才建边，不能绕过 B；事件顺序未知不建边。不支持的双击/右击/滚动不会被伪装为普通单击。首次失败见 `compiler-order-red.log`。 / A review found and repaired false continuity after filtering failed actions, preserving explicit unsupported-action boundaries.

主 Agent 实际执行 `tests/test_workflow_learning_compiler.py tests/test_workflow_program.py tests/test_learning_memory_v1.py tests/test_learning_async_receipts.py tests/test_instant_mcp.py`：150 passed，`compiler-mcp-root.xml`。以上使用新合成数据和真实持久化模块，无 GUI 输入或真实模型收益测量。 / The focused source/recording/MCP suite passed using fresh synthetic data and actual persistence, without physical input or a model benchmark.

## 原队列、动态变量与程序图整合 / Queue, bindings and program graph integration

`WorkflowRuntime` 已把 run/continue、原请求终态回读和结果验证接入 `run_local_step_session.py` 的原命令队列；没有新增输入执行器。`workflow_target_bindings.py` 从本次 Trial 的确切票据读取参数和成功上游输出，并传到原 local/Agent/API 路线。正常记忆未命中时使用含本次对象条件的内部请求副本，原命令保持不变；执行前重新观察继续使用冻结的变量。 / The host adapter uses the original queue, and dynamic bindings derive from the exact Trial ticket. Visual handoff preserves current target identity without rewriting the original command.

取消结算核对原回执，派发事实为 true/false/unknown 时分别保留，不把 cancelled 当作从未执行。重开只读状态。程序图由同一程序定义投影显式分支，保留关系表和旧观测图；节点定位编辑、非语义修改保留目标引用、目标语义变化解绑已加入离屏回归。 / Cancellation retains actual dispatch facts; reopening is read-only. Program projection and edit/reference behavior are checked offscreen.

主 Agent 为核对完整计划的当前基线，实际运行（`QT_QPA_PLATFORM=offscreen`）： / Main-agent baseline check:

```text
python -X utf8 -m pytest -q tests/test_workflow_runtime.py tests/test_workflow_runner.py tests/test_workflow_cancelled_trial.py tests/test_workflow_target_bindings.py tests/test_memory_grounding_execution.py tests/test_input_sequence.py tests/test_agent_command_jobs.py tests/test_workflow_steps_ui.py tests/test_workflow_program_graph.py tests/test_learning_membership_ui.py
117 passed in 13.25s
```

证据：`D:/AgentReviewAcceptance/20260929-learning-benefit-01/plan-status-root.xml`。此前宿主接线检查为 118 passed（`workflow-host-wiring.xml`），worker 动态接线为 96 passed、UI 为 18 passed；集合有重叠，不相加。没有启动真实输入、运行完整脚本窗口或进行模型收益对照。后续仍需检查队列竞争、各种等待状态取消、完整入口、真实连续运行与公平基准。 / Suites overlap. No new physical input, full-window journey or model benchmark was performed; remaining gates are explicit in the plan.

### T7b/c 同会话纠错与复合目标 / Bounded synthesis and compound targets

上一目标轮：计划与文档校准改变权威状态，计为 progress。本轮实施服务/调用方/UI并取得新的真实只读证据，继续计为 progress；完整目标仍 active。 / The prior planning turn and current implementation both made evidence-backed progress.

1. Failure / 失败：原整理允许无限自动纠错；完成/重复回读漏核对轮次与来源，旧记录无顺序却可按文件名续接。目标编辑仅一规则/一条件；切换模式后策略标题仍旧。 / Reproduced budget, identity, source and editor limitations.
2. Invariant / 不变量：一次初次回复后最多一次自动修正；明确用户补充开新回复轮次但不改变来源身份，迟到/重复/重开不能重获预算；所有策略需证据/动作/依赖相容，显示与选择一致。 / Preserve bounded rounds and truthful target semantics.
3. Fix / 修复：learning_synthesis/workflow_control/MCP说明、普通学习状态页；target_editor/service/target_recipe 的逐策略检查。新用户续接仍是原服务，未新增模型客户端或输入执行器。 / Shared service/caller and editor changes.
4. Generality / 通用性：所有学习来源和使用既有定位器的应用共享这些合同，不依赖测试窗口的固定标题/坐标。 / Contracts are application-independent.
5. Regression / 回归：synthesis-conversation-red.xml 8 fail；caller UI 首轮有一次共享编辑器尚未完成的中间态，真正 UI RED 为 synthesis-caller-ui-repro.xml 1 fail；synthesis-review-red.xml 5 fail；compound-target 记录包含夹具修正前和真正功能/UI RED。184 项整合和源码全套2574/1通过；后续标题显示RED 2 fail，第一次修正34 pass/2 fail，最终 compound-label-integrated-recheck.xml 36 pass。源码全套命令 `python -X utf8 -m pytest -q tests --junitxml=D:/AgentReviewAcceptance/20260929-learning-benefit-01/synthesis-compound-source-full.xml`，QT_QPA_PLATFORM=offscreen。 / Preserve first failures and scoped later evidence.
6. Input impact / 输入影响：预算只控制整理回复；所有原动作门控保持。本批真实链只 select/read_text 与学习控制，没有键鼠点击/填写。 / No physical input was dispatched.

真实新证据：live-synthesis-correction-02 为新原生窗口/数据/连接，由当前 Agent 查看原图后生成回复；脚本明确移除一个 control_type 模拟结构错误，当前 Agent 读取原错误并修正。两次回复、一条注入失败形成 pending 草稿；原 MCP/窗口清理通过。complete_live_synthesis_workbench.py 用该草稿在实际 main 离屏修改保存重开，review_status 保持 pending，不能称人工已批准或动态/收益验收。总模型调用和 token 仍 null，54秒交接含等待，不称推理耗时。 / Real same-agent read-only correction and offscreen persistence are separate from physical/benefit claims.

启动器首次失败 live-synthesis-correction-01：把 Windows venv launcher PID 当窗口 PID，断在 MCP 启动前；窗口正常关闭。修复调试脚本为核验子进程链/实际命令与新数据路径，select 使用已验证窗口 PID；02 为修复后首次成功。位置是测试启动器，无生产输入降级或旁路。 / The launcher failure and successful rerun remain distinct.

Ruling: 缺顺序的 legacy attempts 可读，但不能伪称知道最后回复并续接；完成重复请求保持同内容幂等，同时核对原续接轮次及来源。实际调用编排通过原 MCP 状态和说明驱动当前 Agent，存储层不隐藏调用模型。T7a–c 源码闭合后先补 T0/T8 对照工具与计量，再按已有确认要求进行物理验收。 / Preserve verified source work and continue toward measurable use.



### T0/T8 交接计量、计分完整性及受控字段 / Measurement and scoring integrity

1. Failure / 失败：Agent 交接缺少独立等待时钟；旧计分可把同 case 重跑充样本、抬高首轮率，且混合变化/冷暖。首次修正仅用成功样本摊平仍漏掉重试成本；夹具缺少下游字段，控制 A→B→A 会重放旧变更。
2. Invariant / 不变量：观测覆盖与实际调用分开；样本、首次成功及全部成本可追溯；当前输出变化不能自动完成被测任务，重复控制不得改变已更新数据。 / Preserve observed scope, independent cases, complete costs and current data.
3. Fix / 修复：原 AgentCommandJobs wait 边界、workflow_metrics 原票据投影、benchmark_scoring 及独立 fixture/launcher；没有新增执行器。 / Existing boundaries and test harness only.
4. Generality / 通用性：计量和计分不依赖窗口标题或坐标；夹具只用于观察新值和独立验收。 / Common accounting applies across applications.
5. Regression / 回归：agent-handoff-measurement-red.xml 的5项是测试目录缺失，functional-red.xml 的5项才是缺计量；malformed-red.xml 保留坏 source 类型缺陷。scoring-integrity-red/retry-red/retry-red-02、controlled-field-red/receipts-red 均保留。首次全套 cancelled 用例要求等待严格大于零，但 Windows GetTickCount64 分辨率 15.625ms，同 tick 合法为零；已修断言。进一步 clock-domain-red.xml 证明该时钟与既有 API/规则使用的 QueryPerformanceCounter 有约159ms偏移；生产已统一 perf_counter_ns，不能把两个时间基准混合汇总。scoring-nonstable-retry-red.xml 复现未见数据多次失败仍被首轮收益判 met，现将任何正向重试标为待完整成本比较。 / Preserve reproducible clock-domain and non-stable retry failures.
6. Input impact / 输入影响：本批仅真实线程/存储边界与离屏原生窗口检查，合成 grounder/动作边界不证明真实识图或物理输入；无实机点击、发布、安装或浏览器配置更改。 / Source/offscreen evidence is not physical acceptance.

Ruling: 摊平必须累计失败和补救；源码计分输入未绑定冻结清单，met 只表示该输入满足数学条件。当前正向重试使收益判断 unknown；易混集须显式提供。静态复核指出单独计量写盘会新增派发前失败点，现把时间记录合入原关键命令状态提交，未绕过原状态持久化要求。oracle 文件原子替换，但 UI、oracle、事件日志不是跨介质单事务，未把该夹具限制藏成生产保证。 / No survivor-biased savings, extra telemetry commit barrier or fabricated acceptance.
渲染：首次 offscreen 缺字体的 controlled-field-preview.png 保留；注册 Windows msyh.ttc 后的 verified 图已检查，源文本未损坏。下一步仍为冻结采集入口及真实完整用户链，不重复已验证组件。 / Font-only render recovery is distinct from product changes.


## 冻结清单与原 MCP 采集入口 / Frozen manifest and original MCP collector

本批新增 benchmark_manifest、benchmark_learning_workflow 及两组测试；原执行器、版本和安装版不变。Luna 只读核对采集绑定及失败边界，Sol 实现限定清单模块，主 Agent 负责采集器、集成、复现和最终检查。外部 ChatGPT 上轮高思考档无法核验的阻断未被当作已咨询；本轮没有新外部咨询或独立物理验收。 / Bounded source work and root verification only; no outside acceptance or publication.

1. Failure / 失败：此前没有可执行冻结采集入口；实现期间复现未决尝试能开始下一案例、过期仍可交新请求、失败 Agent 回执匹配宽规则后误计成功、后续终态覆盖失败、状态查询未结束判定错误、负向 pending 被当正确拒绝，以及结果判定器变化后仍可按旧清单复算。 / Missing collector and concrete accounting/state failures were reproduced.
2. Root invariant / 不变量：冻结任务与评分代码不可静默漂移；原命令身份、终态和首次失败不得被查询或重跑覆盖；任务成功与协议完成分开，未知覆盖保持未知。 / Preserve frozen definitions, original identities, first failures and honest coverage.
3. Fix location / 修复位置：开发采集层沿用 LearningBenchmarkClient；调用前保存意图、返回后保存原回执和摘要链，绑定 trial 归档生产局部计量及原证据文件；结果从冻结规则复算。 / Collection and comparison layers, with no second executor.
4. Why not app-only / 通用性：入口与原 MCP 回执/工作流身份绑定，不依赖 Record Desk 控件名或坐标；种子、输入、路线和真值的实际落实仍需应用夹具驱动，不能凭不同 case_id 宣称独立变化集。 / Generic transport provenance is implemented; realized cases remain to be verified.
5. Regression / 回归：benchmark-collection-red.xml 7 fail（入口缺失）；boundaries-red 3 fail（未决/超时/计量未接）；review-red 含 3 实际缺陷及 1 测试尚缺钩子的失败；scorer-binding-red 为 1 实际未拒绝；evaluator-binding-red 首次因构造未同步 journal 根而失败，functional-red 校准后复现实际缺陷；negative-red 为 1 实际未拒绝。最终 benchmark-collection-verified.xml 为 120 pass / 1 skip，目录符号链接测试受 Windows 权限跳过。benchmark-cli-smoke-03 最终源码下真实 freeze/baseline/compare、两次 discover、原 ID pending 回读、单连接、三个报告文件及宿主清理通过；01/02 成功记录保留为前序候选。 / Initial failures are retained with honest test scope.
6. Input impact / 输入影响：未发送动作，真实客户端使用 agent_current 并仅 discover；未要求本地模型、密钥或付费 API。原动作确认不变。报告 empirical_acceptance=false，不能将这对协议 A/C 标签计作查询/详情/填写收益。 / No physical input or inference; protocol checks do not establish empirical benefit.

源码范围：新增 CLI 可持续接收 begin/call/finish/stop 并逐次返回结果；断线保留未完成尝试但没有自动恢复/重连。未知模型调用不推算，错误/补救为调用方显式观察，cold/warm、真实模型配置、seed/layout 和路线语义尚未独立核验；完整场景自动化、配对调度、跨采集会话合并、全量成本与收益验收仍未完成。上述缺口保留在目标与下一步。 / The full benchmark runner remains incomplete; see LEARNING_BENCHMARK for the implemented boundary.


## 正向场景落实与当前结果观察 / Realized positive cases and current outcomes

新增 learning_benchmark_cases/learning_benchmark_fixture；扩展原夹具 reset_case/state_snapshot 和 launcher load_case/observe_case，接 benchmark CLI 的 --fixture-root/next。同工作树保存原有修改；没有发布/版本/安装动作。CodeGraph 再次确认本树未初始化，按精确文件读/rg核对。 / Existing execution paths and user edits are preserved.

1. Failure / 失败：上一阶段 case 的 seed/input/layout 只有清单声明；metadata returned 可证明协议却不能证明任务。新接线测试复现缺驱动与缺collector接口；整合时发现生成器布局枚举与UI不匹配、详情由编号直接拼出、失败观察回执缺关联字段导致真实oracle错误被误报身份不符。 / Missing realized cases and integration mismatches were identified.
2. Root invariant / 不变量：冻结案例必须改变实际界面；相同窗口的每轮属于唯一case/epoch，旧选择、详情、验证不可成为新成功。读取当前详情的任务必须根据当前值，不能从输入编号直接得到真值。 / Match actual state and fresh outcomes to each frozen case.
3. Fix location / 修复：验收夹具/控制器/采集判定层；生成60正向case，真实重排三种布局，load/observe沿用原nonce与请求去重，当前epoch事件连续并核对oracle。CLI保留准备和结束快照，离线重新判定，初次请求顺序由冻结routes决定。 / Fixture and collector only; no new executor.
4. Why not app-only / 通用性：case驱动和字段真值属于Record Desk验收适配，不能宣称通用软件已验证；原 MCP、原回执保留和未知模型计量继续复用公共路径。后续第三方应用迁移仍待完成。 / The fixture adapter does not establish generality.
5. Regression / 回归：benchmark-fixture-driver-red.xml 5 fail（驱动缺失）；benchmark-fixture-integration-red.xml 1 fail（collector缺fixture接口）；worker夹具reset RED 2 fail、control RED 1 fail/3 pass、identity RED 1 fail均保留。最终 benchmark-cases-verified.xml 142 pass/1 skip，目录符号链接测试受权限跳过。benchmark-case-layouts 三图由主 Agent 实际查看，控件无截断且位置/排序确实变化。benchmark-cases-cli-smoke-01 使用真实MCP与独立离屏夹具，两轮只有discover，任务成功均为false，原MCP及夹具清理均true；未模拟positive实机或收益。 / Final evidence is scoped to source, offscreen widgets and real read-only transport.
6. Input impact / 输入影响：源测试通过Qt方法驱动离屏控件，不是物理操作；实连只提交discover。夹具控制只准备/观察/关闭本次自建窗口，模型不读取oracle。原确切预览与独立确认继续适用，未新增权限。 / No physical input or model calls were dispatched.

Luna只读审查当前epoch、详情和begin返回边界，未发现具体成功误判或oracle泄露；这是源码审查而非独立物理验收。主 Agent 自行核对差异、回归、实际协议记录、截图和清理。完整A/B/C执行、全量调用方、冷暖/学习/负向/易混/恢复、真实连续复用及独立同候选验收仍未完成，目标保持active。 / Remaining requirements retain their original scope.
## 2026-10-01 固定 C 来源与原协议续接 / C provenance and original continuation

本批在权威 codex/dev-workflow-editor 工作树继续源码整理，不发布。第三批 keyboard handler 全模块迁入 execution、旧路径同对象 alias，字节 SHA 与备份相同。定义/实际覆盖由 benchmark_provenance 审计，manifest 可选 c_workflow 绑定 artifact；collector 对 B/C 同程序、原 read、start 输入/入口、trial 与票据归属进行校验并保存快照。普通 pending trial 不增加门槛。

This slice retains the original keyboard implementation and scoped aliases. Optional benchmark binding separates reviewed definitions and actual coverage, preserving ordinary pending trials and original workflow execution.

新增采集合同首跑 9 failed，随后主 Agent 43→49 项相关检查通过；只读审阅发现合法 Agent 续接和记账被挡、离线重复 start 未拒绝，新增红测试后修复。worker 扩展 175 passed；主 Agent 另复现并修复取消 ACK 悬挂和离线 A/B 无记忆限制遗漏，最终采集/计量/runner/逐类评分 9 文件合并 **207 passed**（collection-final.xml）。helper 的绑定、窗口/输出/图像/动作/终态、剩余 Agent 动作核验和重复票据负例保留全部红绿结果；主 Agent 单独复核 helper、真实服务生成核验回执与记忆执行合同 69 passed（不与合并结果相加）。

Initial contract failures and review findings are preserved. Original Agent continuation and telemetry are restored with exact ownership; replay rejects duplicate starts, drift and forbidden baseline memory. Main fixes cancellation acknowledgement accounting and independently verifies the helper; the collection-side combined run passes 207 checks.

新图片采集合同正/负检查通过：archive 原 JSON/PNG 后，不借用后来变动的 artifact/PNG 复算；篡改快照拒绝。持久 archived-synthetic-fixture 只有合成原回执和图像、1 条正向 C 记录，scope=scored_positive_nonrecovery；model_calls_total=null、empirical_acceptance=false、physical_inputs=0。这不是新的实机学习或收益证据。

Archived synthetic JSON/image checks verify snapshot replay and tamper rejection. A persistent one-case contract fixture remains explicitly synthetic with unknown full calls and no empirical acceptance or physical input.

证据与源码备份：D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-provenance-01，含 keyboard-before、collection-before、continuation-before、首次失败和复测。未改变原授权/动作门控、模型路线、安装候选、版本或远端。R1c 两轮独立确认待答复，R2–R6 仍开放；此前 R1b 的 pending 定义不能被计为已审核 C。

Evidence preserves source backups and first failures. Action gates, routing, installed candidates, version and remote remain unchanged; physical variation, continuity, benefit and transfer acceptance remain open.

主 Agent 最终把第三批键盘与采集/计量/runner/工作流/记忆执行/入口选择合并为 25 文件，**609 passed / 0 failed / 0 skipped，27.53s**（final-source.xml）。不与 207、69、310 或前一批 774 相加。 / The final main run combines 25 affected files and passes 609 checks; overlapping/historical totals are not added.

隔离源码验证复用前一批 isolated-source（882 文件、另列开发基准脚本，不是发布包）：python -I 执行 check_instant_entrypoints 退出 0、passed=true，新旧键盘 handler 与原备份字节一致；input_executed/screenshots_taken/model_inference_tested 均 false。另由该目录的 benchmark_learning_workflow.py --phase compare 在独立工作目录读取归档合成案例并输出 comparison.json/runs.jsonl/report.md，退出 0；完整调用仍 null、empirical_acceptance=false。证据 isolated-source-audit.json、isolated-preflight.json/log、archived-fixture.json、isolated-report/。

The reused isolated development source passes functional dependency preflight and standalone archived comparison under isolated Python. All checks remain source/synthetic coverage with unknown complete usage and no empirical acceptance; no ZIP or installer is built.
