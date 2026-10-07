## 2026-10-05 有限源码试用验收结果 / Bounded source trial result

S1–S3限定验收已通过：Main使用项目维护的截图和动作接口查看三个主页面及运行页，普通页面切换和未连接时禁用执行均正常；此前限定审核修改、保存v4及重开证据保留。S2真实队列接管联调通过；Main T25与同一901项冻结的Sol T26连续教学、变化/重复复用、一次宿主中断与明确恢复、About及正常收尾通过。S4隔离真实功能入口、依赖和空库原生启动已通过；当前说明同步到本地源码候选，最终归档hash以S4报告为准。 / Bounded S1–S3 pass: Main inspects all three pages and the run page through maintained project capture/action APIs, with ordinary navigation and disconnected input disabled. Retain the earlier bounded native edit/save-v4/reopen evidence. Real-queue takeover integration and same-freeze Main T25/Sol T26 continuous journeys pass. S4 isolated real entrypoints, dependencies and empty-library native startup pass; these notes accompany the local source candidate, with the final archive hash recorded in the S4 report.

本轮页面检查的工作台和宿主均正常exit 0、PID/HWND消失；901项源码与735份T25原件hash不变，QA库只保留此前保存的v4。操作者为Main Astra，独立S3执行验收为Sol；human_review=false。正式v0.1.1、UI v14不变，未发布、未对外交付，候选是源码目录/ZIP而非exe；真人空库使用、全部编辑类型、广泛应用/恢复、收益与真实API准确率未验收。本地模型可选，也可使用已有当前Agent、委派或外部视觉API配置；本轮不新增API实测结论。 / The page-check window and host exit normally with PID/HWND absent; all 901 source hashes and 735 T25 originals match, and the QA library retains the earlier v4 only. Main Astra performs UI verification and Sol independently accepts bounded S3; human_review=false. Stable v0.1.1 and UI v14 are unchanged, unpublished and not externally delivered. The candidate is a source directory/ZIP, not an executable. Human empty-state use, all edit types, broad application/recovery guarantees, benefits and live API accuracy are unaccepted. Local models remain optional alongside existing current-Agent, delegated or external-API routes.

Codex原生Computer Use、computer-use@openai-bundled及@oai/sky已禁用，不再作为项目验收前置或排查对象；继续使用项目截图及动作门禁。浏览器unified-computer-use保持原设置。 / Native Codex Computer Use and Sky are disabled and excluded from project acceptance/investigation; maintained project capture and action gates remain in use. Browser unified-computer-use keeps its existing setting.

当前依据：[试用核对](LEARNING_TRIAL_READINESS.md)、[有限收尾计划](../superpowers/plans/2026-10-03-learning-trial-closeout.md)。本地原证据：`.superpowers/sdd/2026-10-05-project-capture-route-correction/native-pages-closeout.json`、T25/T26原回执及`.superpowers/sdd/2026-10-05-learning-trial-delivery/s4-closeout.json`。下方此前“仍待/受阻/下一步”均为当时状态，不覆盖本段；首次失败原件保持。 / The linked review/plan and local closeout records are authoritative. Earlier pending/blocker/next-step wording below is historical and does not override this result; original failures remain preserved.

## 此前状态与开发记录 / Earlier state and development records

## 2026-10-05 当前试用状态 / Current trial state

2026-10-05 当前有限学习试用状态 / Current bounded learning trial: Main T25和同冻结Sol T26限定S3均已通过，原失败记录保留。S4隔离包真实入口/依赖与原生工作台启动检查已通过，本地源码候选可供检查/暂存；完整试用验收及对外交付仍待S1。S1实际桌面截图仍因支持工具超时阻断；原生三主页键盘切换、运行页打开及限定审核状态修改/保存重开已有证据，不记通过、不增加权限或重复不变故障。 / Main T25 and same-freeze Sol T26 pass bounded S3 with original failures retained. S4 isolated real-entry/dependency and native startup checks pass; the local source candidate is available for inspection/staging, while full trial acceptance and external delivery await S1; S1 native desktop images remain tool-blocked; native three-page keyboard navigation, run-page opening and bounded review-state edit/save/reopen are evidenced.

Main通过Sky原生键盘及只读Qt焦点诊断，用普通“运行工作流”按钮Space打开运行页，未连接且执行按钮禁用；在T25学习库隔离副本中将step-1审核状态reviewed→pending，以普通保存按钮Space保存v4，正常重开仍为4步/3已审核/1待审核。旧3版本及其余原件、T25原735文件和901源码冻结不变，三窗正常exit 0/PID-HWND消失；首次Return无效果保留。无pointer/text输入、宿主连接或产品修改，不计真人或所有编辑类型验收。实际桌面图仍缺，S1/完整试用仍未通过。证据：`.superpowers/sdd/2026-10-05-native-focus-observation/native-controls-closeout.json`。 / Main uses Sky native keyboard input and read-only Qt focus diagnostics to open the run page with Space on the ordinary button; disconnected execution remains disabled. In an isolated copy of T25 learning content, step-1 review changes from reviewed to pending, the ordinary save button saves v4, and normal reopen retains four steps with three reviewed and one pending. Old versions, other originals, all 735 T25 files and the 901-source freeze stay unchanged; three windows exit 0 with PID/HWND absent. Preserve the ineffective first Return. No pointer/text input, host connection or product change; this covers neither human review nor all edit types. Actual desktop images remain missing, so S1/full trial acceptance is incomplete.

现有新截图/窗口绑定、原回执一致性、ready准入、零输入暂停接管与明确继续合同保持；已知输入/观察不可用不等于任务成功，不允许未知输入自动重放。同冻结有限实机恢复已核验，范围外恢复不声称通过。 / Freshness, identity, original receipts, ready admission and explicit continuation remain enforced; known input without observation grants no task success or automatic replay.

正式v0.1.1、UI v14及产品版本不变，尚未发布或对外交付；不是exe，本轮仅构建一次源码候选，源码候选保存在本地；归档校验状态以s4-closeout为准；human_review=false，收益和API实测/准确率未知，不增加收益、API购置或额外安全大开发门槛。 / Stable version and v14 are unchanged; no publication/external delivery or executable package, human review or measured benefit/API accuracy claim.

原证据 / Original evidence: `.superpowers/sdd/2026-10-05-known-observation-rerun/live/main-s3-closeout.json`；`.superpowers/sdd/2026-10-05-sol-independent/main-independent-audit.json`；`.superpowers/sdd/2026-10-05-native-workbench-visibility/source-visibility.json`。

下方均为保留的历史记录，其“当前/下一步/仍待”仅描述当时状态，不覆盖上面结论；历史test.8不代表本轮学习已发布。 / Dated history below does not override the current conclusion or publish this learning candidate.

# 明确新会话准入：本轮证据 / Explicit epoch admission evidence

2026-10-01；开发树 `codex/dev-workflow-editor`。学习源码未发布、未改版本；独立正式树 v0.1.1 保持不变。/ Learning source remains unreleased, with stable v0.1.1 unchanged in its separate tree.

## 改动 / Changes

2026-10-05 T23实机：原S84第二步在grounding等待正常中断，原命令cancelled/action_executed=false/零派发；原run结算recovery_paused。同一准入请求starting→ready/new_epoch_ready=true后才绑定同一原7-Zip窗口。普通预览/提交成功，提交结果takeover_ready/active_command_id=null；明确继续后完成其余三步，再次完整复用成功。原260文件不变、正常清理。About阴影截图失败使整体连续仍不计通过，不能把这份准入成功等同完整S3验收。 / Live T23 proves no-input interruption, ready admission, paused explicit takeover and subsequent successful continuation/reuse on the original window. A later menu-capture failure still prevents full continuous acceptance.

`instant_recovery_preview` 组合原资源死亡证明与原输入终态。异步输入读取原接收回执、worker、派发记录和末次执行回执；同步输入、组合及 grounding 使用原动作事实。响应存在或 failed 不代表没有输入。目录集合与原字节固定 SHA，未知派发、孤立证据、漂移或未结算 Trial 明确拒绝。/ Preview composes original resource and input evidence, rather than inferring completion or zero input from an acceptance/error response.

2026-10-05 T21：同步agent_current read_text有原队列/返回回执但无worker；Main错误查询其worker产生专用command_unknown。旧消费者把worker缺席错误扩大为原队列也须缺席，导致恢复预览拒绝。修复只结算严格负查询；原命令存在时独立核对真实终态并保留其输入事实。缺回执、未知输入、worker冲突、控制循环、deferred及continue/cancel均不获此例外。RED 2 failed/23 passed→GREEN 25 passed，Main和Sol分别106相关通过，不相加；修复后新进程只读复验原T21记录通过、原SHA不变。原MCP未热加载，完整新数据实机恢复仍待。 / A synchronous read can have a terminal queue receipt without an asynchronous worker. T21 exposes the validator's incorrect conflation; the repair independently checks any existing original terminal result while strict malformed/unknown/control cases remain rejected. Regression and unchanged-record replay pass; fresh full live recovery remains open.

`instant_recover_session(request_id, preview_sha256)` 复用原操作员配置、owner 锁与隐藏 launcher。持久事务依次为 prepared → launch_started → host_created → pointer_published → ready。创建前写失败不创建；启动后缺少持久身份保持 launch_unknown，不再创建。创建/发布中断后同 ID 核对原身份再完成同一发布；不同 ID 不绕过未完成记录。新 ready 由原 report、journal、实际入口、来源/配置、launcher/runner 创建时间及父子关系核验。/ The explicit transaction reuses the maintained launcher and validates real readiness; interrupted calls do not imply no host exists or authorize another spawn.

普通 `instant_start(new_session=True)` 的正常清理门控保持。新 epoch 不继承旧命令、worker 或目标，`workflow_takeover_completed=False`。launch_unknown 的本次资源/输入证明为 False，历史证明单独保留；MCP 预期恢复错误返回 `host_launch_attempted=null`，不猜测零启动。/ Normal restart policy remains intact. Readiness is separate from takeover, and unknown launch facts remain unknown.

发布新 pointer 后，原结算通过严格持久准入记录执行 `status_admitted` 只读核对：原来源、report/journal SHA、program/ticket/receipt/worker/settlement 仍逐项验证。普通 status/preview/settle 不取得跨 epoch 写入能力，也不临时恢复旧 pointer。已结算 verify 在观察、核验或写盘前拒绝。/ Archived settlement checks remain read-only, bound to the admitted successor, and cannot grant settlement or input authority.

2026-10-05 T22：同一instant_recover_session请求依次starting→ready，嵌套new_epoch_ready=true后才同窗select。普通接管preview_ready，commit以workflow_takeover_new_input_changed失败且未继续；原目录SHA不变。根因为同事务预览完成更新report聚合字段，公共scoped_input_files现仅规范化原回执证实的同scope投影，完整终态/窗口/当前效果/真实输入约束保留。Main156相关检查通过；T23新冻结实机及独立验收仍待。 / T22 completes admission before target binding, then fails takeover on self-derived report drift without input. Strict original-receipt normalization passes related checks; fresh live and independent acceptance remain open.

## 实际检查 / Actual checks

| 检查 / Check | 结果 / Result |
|---|---|
| Main 相关合同及来源/启动回归 / Related contracts and startup routes | **482 passed / 29.38s**，`main-final-contracts.xml`；包含真实持久原 settlement 的完整准入及同 ID 回读，OS/启动边界为替身。/ Persisted settlement integration passes with simulated OS/launch boundaries. |
| 原 InstantSession 连续宿主 / Original host continuity | `live-03`：三次连续硬终止原 runner、三次明确准入；第三次原 pointer 写入注入失败保留 host_created，同 PID/创建时间恢复，最终正常 stop 与 cleanup_verified=True。/ Three abrupt exits and recoveries, including interrupted publication and verified cleanup. |
| 原 STDIO 恢复入口 / Original STDIO recovery | `stdio-recovery-01`：九工具发现、真实硬终止、普通 restart 拒绝、只读预览、明确准入、同 ID 回读、最终清理；响应 text 与 structuredContent 一致。/ Actual public recovery calls pass over one STDIO connection. |
| 原常规 STDIO 探针 / Existing STDIO smoke | 九工具、坏请求队列前拒绝、同连接恢复、原 ID 不重放、停止和重连只读回执通过。/ Normal protocol smoke passes after updating its tool inventory. |
| 原文件与进程 / Original files and processes | `live-03` 存完整旧目录前后 SHA；旧 report 不补 finished_at，新就绪队列为空。冻结 612 个 app/scripts Python 文件未改；各测试登记身份退出。/ Old directories, frozen source and owned process cleanup are verified. |

这些检查覆盖重叠，不相加。实机路线均为 agent_current、空模型清单、零 GUI 输入；不证明视觉模型、供应商 API、真实输入后工作流恢复或任务收益。实际旧 pending settlement 的跨 epoch 核验本轮是合同测试，不冒充实机 pending 工作流。/ Counts overlap. Real lifecycle tests contain no model resources or GUI input; they do not establish live workflow takeover, provider accuracy or benefits.

## 首次失败与修复 / Retained failures

- 已结算 verify 原本先调用核验再被拒绝，RED **2 failed**；守卫移至首次观察前，相关回归及 Main 最终检查通过。/ The settled-verification write boundary was reproduced and repaired.
- published retry 原本被旧 pointer 绑定拒绝；新增严格只读准入路径前 RED **6 failed**，原普通服务仍拒绝新 pointer。launch_unknown 错报当前证明与 model-directory/runner 目录缺口分别保留红绿证据。/ Archived binding, unknown proof and configuration regressions are retained separately.
- Main 初始八项 RED 包含一个 SDK 导入替身问题，修正预加载后真正的接口/工具缺失 RED **8 failed**；公共响应最初 **2 failed/8 passed**，修正结构化回执和启动后未知错误后通过。/ Initial fixture and actual contract failures are distinguished.
- 持久 settlement 集成首次缺少已初始化库锁，**1 failed/10 passed**；改用原 MemoryWorkspace 初始化新测试库后 **11 passed**。/ The fixture now uses the maintained workspace initializer.
- 实机首次目录计数把 `.log` 当会话；首轮失败和脚本保留，所有该轮登记宿主已退出。第二次准备阶段未建新证据父目录，创建任何宿主前失败；修正测试驱动后 fresh live-02/live-03 通过。常规 STDIO 原探针仍断言七工具，工具发现阶段失败、未启动宿主；更新维护探针后通过。/ Harness failures are retained and are not relabeled as first-attempt product successes.

本机证据根 / Local evidence root: `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-epoch-admission-01`。首次失败、各 RED/GREEN XML、完整协议回执及原数据不进入公开包。/ Raw evidence remains local.

## 剩余验收 / Remaining acceptance

Task4c：新宿主选定当前窗口、采集新截图并核验旧动作当前效果；仅在新 Trial/Runner 账本消费旧步骤来源，跨 epoch 唯一接管索引阻止重复消费。再完成活动工作流弹窗、无复位连续状态/中断/恢复/收尾和 Main → 同冻结候选独立实机验收。/ Effect-verified takeover and full live workflow continuity remain open.

R4 正式人工审核 C、公平 A/B/C 和完整调用/冷暖/学习成本，R5 实测优化、R6 第三方新环境迁移仍未完成。总模型调用/token、模型节省、准确率及速度收益仍未知。/ Reviewed comparisons, measurement, optimization and transfer remain unfinished; benefits and total usage are unknown.
2026-10-05 T24更新：原中断已结算recovery_paused，准入因另一条grounding_continue的returned_observation_unavailable误拒绝，未建立新epoch。公共校验现接受确切schema/operation及完整worker/grounding/dispatch/receipt一致性证明，保留failed/action_executed=true和效果未确认，不自动重试。Main120项相关检查及原399文件不变的只读重放通过；完整修后实机归T25，旧T24失败保留。 / Strict proof distinguishes known input from unavailable observation without claiming task success or permitting replay; fresh full live validation remains open.
