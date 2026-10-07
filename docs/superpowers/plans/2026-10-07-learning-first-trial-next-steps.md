## 2026-10-07 新独立安装预览接替旧候选；发布尚未完成 / New independent installation previews replace the old candidate; not yet published

当前冻结为执行 source11/Setup10（0.1.2-preview.1）与学习 GUI09/Setup09（0.1.0-preview.1），全部执行516/学习330实装载荷字节已核对。Main N17 全新教学生成二步参数程序，经普通 GUI 人工审核保存；Run A 参数甲 UIA matched，中英文切换、Notice 正常关闭、GUI 正常关闭重开保留英文、同程序及原 run/wait，明确 Continue 后原同步 read PNG 经 Agent 审核输出甲。同 immutable program Run B 参数乙二步 completed、输出乙，GUI原图显示Passed与输出。Main N17 collector53原件检查passed。 / The frozen source11/Setup10 and GUI09/Setup09 pair has verified516/330 installed payload bytes. Main N17 completed fresh two-step teaching, ordinary GUI review/save, input A with UIA matching, locale/Notice/normal GUI close-reopen with original identity retained, explicit continuation and original synchronous read review/output A, then B on the same immutable program with two completed steps and B output. Main's collector verified53 original-evidence checks.

同冻结 independent-native-18 已完成，collector23passed、issues=[]，GUI、fixture、两个host与两个SDK均正常收尾/退出；Main实读完整collector/evidence，实际查看9张独立原图，只读重跑23检查并重hash1260索引，L/native18-main-readback.json 为PASS、exit0。独立A输出有完整原API证据，但没有GUI A输出框截图；B两步Passed为194原图、声明输出为197原图。普通菜单popup仅称菜单弹窗，不称About。 / Same-freeze independent native18 completed with23 collector checks and no issues; GUI, fixture, both hosts and SDKs closed normally. Main read the full collector/evidence, viewed nine originals, reran23 checks read-only and rehashed1260 inventory entries; native18-main-readback.json passed with exit0. A output has original API evidence but no GUI A output-field screenshot; B Passed/output originals are194/197. The ordinary menu popup is not an About-dialog claim.

当前语义纠正：N17原030/032/037/039及N18原030/036的trial execution_strategy均为learned，不是steps_only；输入使用已学习UIA规则，read为agent_read并由Agent作明确判断。此前当前说明的steps_only措辞误判不改写历史结果。仅证明本轮受控Record Desk、同host原run明确继续，不宣称跨host恢复、自动takeover、模型准确率或调用/耗时收益。Main258源码检查、N17的53原件检查、N18的23检查和1260索引核验属于不同且可能重叠的范围，不累加为产品测试总数。 / N17 trial receipts030/032/037/039 and N18 receipts030/036 all use learned strategy: learned UIA input rules plus agent_read and explicit Agent judgment. The prior current steps_only wording was mistaken; historical results are not rewritten. Scope is controlled Record Desk and explicit same-host original-run continuation, without cross-host recovery, automatic takeover or accuracy/call/time benefits. Main258, N17's53, N18's23 and1260 inventory checks are separate scopes, not an additive product-test total.

N17原026竞争select、027普通capture遮挡拒绝及N16整链/read首次失败仍保留，后续成功不改记首次通过。基于用户最新询问旧便携是否可由新包替代的讨论，Main按既有发布目标作出本轮范围决定：旧candidate02已由通过同冻结Main及独立验收的新独立安装候选接替，本次不对外交付旧便携候选。历史首次自行退出根因仍unknown，不宣称已修复；旧库与unique原证据保留。此处记录Main范围决定，不称用户已明确回答此前发布问题。 / Original N17 refusals and N16 first journey/read failures remain preserved. Following the user's latest discussion of replacing the old portable candidate, Main has scoped this release to the new independently installed pair that passed Main and independent acceptance on the same freeze. Candidate02 is superseded and excluded from this delivery; its unexplained first exit remains unresolved, with old libraries and unique evidence preserved. This records Main's scope decision, not an explicit user answer to the earlier release question.

当前新包Main/独立验收、正常清理及实际原件复核已完成；新包实际故障仍必须按RootCause规则闭合。计划Task4/5原checkbox不勾修复，仅旁注本次新包限定交付范围。尚未stage、commit、tag、push或publish，stablev0.1.1不变。下一步最终docs/固定selection419/assets核对后，进行scoped commit/tag/push、prerelease上传及匿名下载SHA核对；这些步骤尚未执行，不提前记发布完成，不再追加桌面批次。 / Main and independent acceptance, cleanup and original-evidence review of the new pair are complete. Any actual defect in the new delivery still requires root-cause closure. Task4/5 checkboxes remain unchanged, with scope notes beside the gates. No staging, commit, tag, push or publication; stablev0.1.1 is unchanged. After final docs/fixed419 selection/assets checks, proceed with the scoped commit/tag/push, prerelease upload and anonymous download hash verification. Those publication steps are still unperformed; no further desktop batch is added.

以下保留此前时点及原始历史 / Earlier status and original history retained below.

## 2026-10-07 N10/N11 限定验收收尾 / Scoped N10/N11 acceptance closeout

Main N10 与 Sol independent-native-11 在 source07/GUI05 上的限定主链通过。Main 已审核 N11 原回执、取消前后三文件 SHA 与队列、同 program 参数甲/乙输出及 cleanup，重新 hash 1223 原件并亲自查看持久甲/乙 PNG；证据为本地 L/main-independent11-review.json、N11/evidence.md 与 acceptance-result.json。取消立即终态释放占用，program、history/outputs、原 ticket 字节与队列保持不变；所有窗口、宿主与 SDK 正常清理，host_alive=false、pending_ids=[]、cleanup_errors=[]。 / Main N10 and Sol independent-native-11 passed the scoped source07/GUI05 journey. Main reviewed original N11 receipts, three-file cancellation hashes/queue, both parameter outputs and cleanup, rehashed 1223 originals and viewed the durable A/B PNGs. Cancellation immediately released terminal ownership while program, history/outputs, ticket bytes and queue stayed unchanged. All windows, hosts and SDKs closed normally with no pending IDs or cleanup errors.

边界：N11 不包含 GUI 最终 result-table 刷新或 recovery takeover；steps_only 仍由 Agent 判断，无 calls/accuracy/speed 收益主张。101 个临时 capture 引用已回收，其中 74 无独立归档字节，未补造；公共 read 的三张持久 PNG 均保留。Main 的 1223 原件 hash 核验不等于全图档案覆盖或 SDK binary 图验证。首次提前 stop 的一步 handoff 与原 audit 顺序差异等历史原件继续保留。 / N11 did not test final GUI result-table refresh or recovery takeover. steps_only retains Agent judgment without measured call/accuracy/speed benefits. 101 temporary capture references expired; 74 lack independent archived bytes and were not reconstructed. All three public-read durable PNGs remain. Rehashing 1223 originals does not establish complete image archives or SDK binary-image verification. Earlier invocation/audit evidence remains intact.

尚未 commit/tag/push/公开发布，正式 v0.1.1 不变。旧便携 candidate02 首次自行退出根因仍 unknown，其发布边界用户选项仍待答；广泛桌面测试授权不等于该发布决定。下一步仅为最终说明、scoped source 范围及旧故障发布边界核对后进行发布验证。后续项目桌面测试无需重复批次审批，继续使用项目维护接口及门禁，Native Computer Use/Sky 禁用。 / No commit, tag, push or public release yet; stable v0.1.1 is unchanged. The original portable candidate02 exit cause remains unknown and its user release-boundary choice is unanswered; desktop-test authorization does not decide that boundary. Next are final explanations, scoped source review and the historical-fault release boundary, followed by release verification. Project interfaces/gates remain required and Native Computer Use/Sky disabled.

以下保留此前时点及原始历史 / Earlier status and original history retained below.

## 当前收尾顺序 / Current closeout order

本次更新仅同步已取得证据与执行重心：执行 source07/Setup06 和学习 GUI05/Setup05 已普通升级、核验全部实装载荷。Main N10 已完成新教学自动生成参数草稿、普通人工修改与两步审核保存、关闭重开、独立安装根连接、审核后立即取消、同一程序参数甲/乙两轮和正常清理；Sol independent-native-11 正在复验同候选。 / The installed pair is byte-verified. Main's fresh generation/edit/review/save/reopen, attachment, reviewed cancellation, two parameter runs and cleanup pass; Sol is retesting the same freeze.

参数案例调整：直接由真实教学的 variable review 和 synthesis 生成运行参数，再通过普通GUI人工修改步骤并审核保存，而非先造常量再转参数。当前证明自动生成、人工可改、确切版本换值复用；不声称本轮已实机修改常量绑定按钮。 / The case generates the parameter from actual variable review/synthesis and tests ordinary human editing and review, rather than introducing an intermediate constant. It proves generation/editing/exact-version parameter reuse, not a new live constant-conversion-button test.

下一步仅剩：完成并核对 Sol 新内容独立原件及正常清理 → 按最终结果同步公开快速开始/验收/版本说明 → 复核选定维护源码清单与文档路径/隐私 → 明确旧便携未知退出的发布边界 → 选定源码提交、精确tag和公开资产上传下载SHA核验。正式 v0.1.1 不替换，不新增学习收益承诺。 / Finish independent acceptance, synchronize final documentation, audit scoped source/privacy, resolve the historical-exit release boundary, then verify the exact commit/tag and published asset bytes while preserving stable v0.1.1.

非文档生产源码已和source07/GUI05冻结匹配；当前主会话发布helper23项离线通过，无实际网络发布。README已移除堆叠开发状态，原全文保存在LEARNING_DEVELOPMENT_HISTORY.md及本地字节备份。已有源码60与独立副本60是同取消回归的两个范围，不合计总验收。所有后续桌面测试已有授权，仍保留项目原图/身份/动作门禁且禁用原生CUA。 / Production sources match the frozen pair; publisher23 passes offline without publication. Development history is preserved. Keep test scopes separate and retain maintained desktop gates.

以下保留此前时点与首次失败；其“下一步/待完成”不覆盖本段。 / Earlier stages and failures below are historical.

## 当前取消缺陷优先收尾 / Current cancellation repair priority

独立 N7 的 261/262/263 保留首次失败：Agent 已审核首步后 cancel，Trial cancelled/pending=null 而 runner cancel_requested，阻止后续输入；264 原 wait 继续仅结算，不新增输入。B2 被 Main 暂停，不记完整通过。Main 已修复共同 `workflow_runner.cancel`，仅结算同一 Trial 中匹配的已审核原票据；未决、未知、不匹配与恢复门禁保留。真实 Trial/队列回归先 RED 3 failed/1 passed，再相关 5 文件 GREEN 60 passed（3.20s）；首次测试字段误用与其纠正、最初 GREEN 59 项原记录均保留。 / N7 exposed a stale runner ticket after cancellation; the original wait settled it without new input. B2 is incomplete. Main repaired matching reviewed-ticket settlement while retaining all unresolved-input and recovery gates. The real Trial/queue regression failed first, then 60 related checks passed; initial test corrections and earlier results remain preserved.

执行 source06 与 GUI04 的实际 PYZ 都包含该旧共同模块。下一顺序改为：集中冻结两个新候选并隔离检查 → Main 单项取消及相关连续实装回归、正常清理 → Sol 同一新候选复验 → 下列参数复用和发布收尾。减少重复打包，保留旧候选及原失败；不得先发布后补验收。 / Both frozen components include the old shared runner. Consolidate new candidates, check isolated entrypoints, complete Main native cancellation and continuous regression with cleanup, then independent retest and remaining parameter/release work.

用户已授权后续全部项目桌面测试；保留原图、窗口身份、动作门禁以及原生 Computer Use 禁用。历史便携首次退出发布边界仍待用户答复，桌面授权不替代该发布决策。 / Project desktop tests are authorized; original-frame, identity and action gates remain. The separate release-boundary decision about the unexplained earlier exit is still pending.

## 此前执行顺序与真实缺口 / Earlier sequence and remaining acceptance gaps

当前冻结为执行 `source06/Setup05`（0.1.2-preview.1）和学习 `GUI04/Setup04`（0.1.0-preview.1）。两组件普通安装及实际516/330载荷、HKCU和快捷方式已核验；Main已完成新教学、生成三步草稿、普通GUI修改/审核/不可变保存、关闭重开、中英文和三页检查、两组新数据的连续运行及正常清理。正式读图在缓存回收后保留原字节、严格终态预览及迁移导入修复已复验。Sol正在用全新库独立验收同一冻结候选。 / Both frozen components are installed and byte-verified. Main completed the supported fresh learning/edit/review/save/reopen and continuous-use journey, language/pages, durable read evidence and cleanup. Sol's fresh independent acceptance is in progress.

用户已授权后续本项目全部桌面测试，无需重复批次批准；仍使用项目维护接口、原图和动作门禁，禁止原生Computer Use/Sky。以下历史中的旧冻结、待安装和待批准状态不覆盖本段。 / Subsequent project desktop tests are authorized under the maintained capture/action gates; historical pending approvals and freezes are superseded.

下一步按以下顺序闭合，不能提前记发布成功： / Close the following in order without claiming publication early:

1. 完成并回读Sol独立三步连续旅程和最终清理原件。 / Finish and inspect independent continuous-use and cleanup evidence.
2. Main补一个全新低风险输入框的参数案例：真实教学生成草稿，明确将常量改为运行参数，重新审核保存，同一确切程序以A/B两值运行；连接实际独立执行安装根与已安装学习GUI。此前root-a/b是外部导航setup、`inputs={}`，不能算这一项已通过。 / Accept actual workflow input substitution through the two installed components; earlier external directory setup is not runtime parameter coverage.
3. 保留中断原件和取消/零输入结算。`steps_only`跨宿主接管实际返回`steps_only_agent_review_required`；新trial不等同恢复旧run。只在有明确支持及真实现场规则的范围验收恢复，不放宽未知输入门禁。 / Preserve cancellation evidence and the honest steps-only takeover limit; test recovery only through supported current-state contracts.
4. 历史首次自行退出准确对象是更早便携candidate02/PID48456，Windows日志及原启动控制审查均未取得其退出码或Close来源；后来安装GUI01的trace对应明确gated正常关闭，不能冒充原故障根因。当前GUI04首次picker非复现也不代表因果修复。原未知故障仍按Task4/5保留为发布卡点。 / The earlier portable-process exit remains unexplained. A separately identified intentional close and later non-reproduction do not establish a causal fix; retain the release gate.
5. 门槛闭合后核对精确源码/测试/说明清单，排除本地库、截图、模型和凭据；只在公开资产及下载hash核验后完成发布。执行正式v0.1.1保持独立。 / Audit scoped source and documentation, then verify actual published assets and hashes. Preserve the stable execution release.

当前证据索引：`L/native06r-main-frozen-acceptance.md`、`L/native06r-read-retention-evidence.md`、`L/native-startup01-root-cause-review.md`、`L/release-source-inventory-readonly.md`（L为本轮证据根）。尚未提交、推送、创建标签或公开发布；不承诺已降低模型调用、成本或延迟。 / Local evidence is indexed above; there is no commit, push, tag, publication or measured-efficiency claim.

## 以下为保留的历史阶段 / Preserved historical stages below

Main当时回读GUI03双语isolated检查及330文件通过，N6/003已launch学习Setup03；当时尚未安装完成或进行正式旅程。 / At that earlier stage, Main read GUI03 checks and launched Setup03; installation and journey acceptance were then incomplete.

# source07 popup primary 闭合与当前交付 / Popup primary closure and delivery

Main在N5/source07完成实际复验：020/024/028三次popup HWND 9243584/63571976/9440192的owner/root均7277030，实际PNG选项清楚；035语言submenu两个popup归属正确，043重开两个新HWND仍正确，044/045 Escape，048正常关闭/helper2837 exit0。source06 trace已否定weakref为实机原因，实际widget旧HWND8850368与QWindow新HWND2952096不一致；当前QWindow修复Main61 passed（2.97s，XML已存）。 / Main closed the source07 popup primary path through repeated native opening, clear captured choices, correct submenu owners and normal cleanup. The source06 trace showed stale QWidget versus current QWindow HWND, not a weakref cause; Main passed 61 checks in 2.97s.

N4 source05/source06均正常关闭，080宿主cleanup true、081 bridge exit0；N5 Setup04显示Installed successfully，013 OK、014安装器消失，051宿主cleanup true、052 bridge exit0。执行实装现为source05/Setup04。GUI03已构建并通过离屏双语检查（worker构建，不是Main原生GUI03验收）；N6针对实装source05的SDK已创建但未start。正式三步保存/重开复用/恢复仍未跑。 / N4 and N5 closed normally; execution source05/Setup04 installed through its ordinary completion UI. GUI03 is built with bilingual offscreen checks, not natively accepted. N6 SDK exists but is not started; the formal three-step save/reopen/reuse/recovery journey remains pending.

后续优先Main启动正式N6并核对实装身份→GUI03首次目录选择/语言/popup重开→本轮新三步审核保存确切program、关闭重开和支持步骤原回执。formal press_key/固定double locator不支持仍steps_only；N3旧unknown与恢复阻断保留，不能用新会话或清理标志转绿。 / Next verify the installed identities in N6, accept GUI03 first-use and popup reopening, then complete the fresh saved-program journey with honest steps-only limits. Historical unknown input and recovery blockers remain separate.

原020/045/073 mask失败记录保留；067为Main请求schema错误not queued，068取消明确，不归为产品失败。GUI01历史首次无主动关闭退出根因仍未知，不能写修复；当前源码popup闭合不等于完整候选连续旅程、独立验收或发布完成。 / Preserve original masked captures. Request067 was an operator schema error and was not queued;068 was explicitly cancelled. The historical GUI01 first-launch exit remains unexplained; popup closure does not establish full candidate acceptance or release.

## 2026-10-07 当前交付与未闭合复验 / Current delivery and unresolved recheck

Main随后058/059/060已核验source05正常关闭、helper exit0；N4仍live。本状态取代下文“source05仍运行”的当时观察，原证据不改。 / Main subsequently verified normal source05 close and helper exit0 through058/059/060; N4 remains live. This supersedes the earlier source05-running observation without changing original evidence.

Main lifetime15 passed、terminal90 passed、producer→owner→inspector joint35 passed。execution-source05/Setup04已构建未安装；strict516文件和Setup SHAffe1f45145ecc31aef6630b74bb188a2a0d468040b25fb04cc8df697a381ca58复核通过，原树外入口报告passed/isolated、无host/input/Qt，未重跑入口。证据L/execution-source05-delivery-readonly-check.json。 / Main passed 15 lifetime, 90 terminal and 35 joint checks. Source05/Setup04 is built but uninstalled; strict516 files and Setup hash match. The saved isolated report passed without host/input/Qt; entrypoints were not rerun.

当前实装仍source04/Setup03和GUI02。N3宿主一小时退出来自固定3600总寿命，是正常退出非crash；源码已去deadline。069原unknown缺producerproof继续拒绝恢复，原件不改、不重放。N3bridge正常退出，GUI02、旧本轮7Zip、source04正常关闭；Main报告source05和N4仍运行，worker未关闭。 / Installed identities remain source04/Setup03 and GUI02. N3 stopped normally at its fixed one-hour lifetime; historical069 still refuses recovery without producer proof or replay. Bridge/GUI02/earlier current-round 7Zip/source04 closed normally. Main reports source05 and N4 still running.

source05 combo首开41正常，但二开45 newHWND owner0仍被mask，46 Escape关闭；不能记修复或冻结GUI03。N4是隔离源码复验，不是N3恢复/正式完整验收。公共primary owner续接须源码重开通过；原45/020/113失败保留，不放宽mask。 / Opening41 passed, reopening45 remained owner0 and masked, and Escape46 closed it. GUI03 freezing and repair success remain blocked; N4 is source rechecking, not N3 recovery or full acceptance.

原三步draft已打开但尚未保存、重开、连续复用或恢复；steps_only Agent新图/判断、List1001 agent_read仅有限路线，无根目录参数或模型调用减少承诺，按键unsupported。GUI03集中构建待later修复及native重开闭环，不立即build。历史首次退出根因未知，发布未完成。 / The opened draft remains unsaved and untested for reuse/recovery. Keep bounded Agent-assisted semantics; no root parameter or fewer-call claim. Consolidated GUI03 awaits source/native closure.

用户后续项目电脑测试广泛授权持续无需批次问，项目新图/目标/风险、确切预览/独立确认及无关权限不变；原生Computer Use/Sky禁用。本轮仅只读交付与文档，无测试/桌面/构建/发布。下方历史保留。 / Broad testing authorization continues under maintained gates. This slice is read-only delivery validation and documentation; history remains preserved.

## 2026-10-07 首轮真实安装与运行时故障 / Native installation and runtime defect

学习 Setup01 已通过正常界面安装，330个实际载荷文件及真实HKCU/Start Menu记录核验通过；MCP source03 的公开discover无法解除未知启动门禁，执行Setup02尚未启动。已正式停止本轮宿主并核验cleanup_verified；先修公共合同及回归，再继续正常安装/工作台连续验收。原首次退出/popup未闭合，尚未发布。证据：`.superpowers/sdd/2026-10-05-learning-optional-install-and-language/native-acceptance-01-evidence.md`。

The learning candidate passed ordinary native installation and installed-byte/integration checks. Public MCP discovery cannot acknowledge an unknown launch, blocking the next explicit launch; the execution Setup02 has not started. The owned host was stopped with verified cleanup. Repair and regress the common contract before continuing native acceptance. Startup/popup issues and release remain open.

# Optional Learning First Trial Implementation Plan / 可选学习首个测试版后续计划

## 2026-10-07 当前冻结与后续测试授权 / Current freeze and test authorization

当前执行冻结为证据根 `L = .superpowers/sdd/2026-10-05-learning-optional-install-and-language` 下的 `execution-source-03`，安装器为 `installers-execution-02/AgentGUIRuntimeExecutionPreview-Setup.exe`，版本 `0.1.2-preview.1`，SHA256 `77b2f0c7524b8b63e04a5b05bce829471af5b256331610266f2d060e1e88a041`。版本对齐及隔离入口证据见 `L/execution-version-alignment-evidence.md`；学习 `learning-candidate-01` 和 `installers-learning-01` 未改。 / The current execution freeze is source03/Setup02 under L, version 0.1.2-preview.1, with the SHA256 above. Version-alignment and isolated-entrypoint evidence is recorded in the cited report. The learning candidate01/Setup01 is unchanged.

用户最新明确授权“允许后面所有操作电脑测试”：后续本项目桌面测试无需逐批重复询问批准。仍使用项目维护截图/动作接口，保留确切预览、窗口/会话身份核对、独立确认及既有动作门禁；Codex 原生 Computer Use/Sky 禁用不变。授权不代表测试已执行或通过。 / The user explicitly authorizes all subsequent computer testing for this project, so desktop test batches do not need repeated approval questions. Maintained capture/action interfaces, exact previews, window/session identity checks, independent confirmation and existing action gates remain in force. Codex native Computer Use/Sky stays disabled. Authorization is not evidence of execution or success.

旧 setup01 的 14 条实际载荷命令和 6 条 QA 版本身份命令结果保留，不能证明 setup02 的安装、正常 GUI/HKCU/快捷方式、跨安装根连接或真实桌面连续使用已通过。source03 的离线版本/依赖核验也不替代这些验收。原首次启动退出根因和原生 popup 截图效果仍未闭合；尚未发布。本轮仅同步文档，没有运行测试、安装器或桌面操作。 / Preserve the historical setup01 results for 14 real-payload commands and six QA version-identity commands; they do not accept Setup02 installation, ordinary GUI/HKCU/shortcuts, cross-root attachment or real desktop continuity. Source03 offline version/dependency checks do not replace native acceptance. The original startup-exit and popup-capture issues remain unresolved, and the trial is unpublished. This documentation slice runs no tests, installer or desktop actions.

以下原有阶段及 setup01 记录保留为历史；其中“待批准”措辞由上方最新测试授权取代，项目动作门禁不变。 / Earlier stage and setup01 records below are retained as history. Their pending-approval wording is superseded by the current testing authorization above; action gates remain unchanged.

## 2026-10-07 setup01 冻结历史 / Historical setup01 freeze

学习组件 `0.1.0-preview.1` 与兼容执行组件 `0.1.2-preview.1` 的两个独立 Setup 已生成；尚未公开发布，正式执行版 `v0.1.1` 未替换。学习冻结包不含执行宿主或模型，执行源包真实入口未导入 Qt。中英文冻结入口在树外新数据根通过。 / Two separate preview installers are built but unpublished. The stable execution release is unchanged; the learning package excludes the host/models and execution entrypoints do not import Qt.

Main 用实际载荷完成临时目录安装、同版本重装、独立卸载、保留环境/缓存后重装及清理共 14 条命令，另用 QA 专用版本身份夹具完成 `.0→.1` 更新及清理 6 条命令，均退出 0。安装后中英文学习入口和执行真实依赖入口通过，另一组件及外置库保留，最后两组件测试目录正常移除。这些命令不是单元测试数量；版本夹具不是历史正式版。 / Real payload checks pass in temporary directories, including independent removal and retained-root reinstall. QA version-identity fixtures are not historical releases.

普通安装 UI、HKCU、开始菜单快捷方式、跨安装根连接和本轮新内容桌面连续学习尚待批准与验收。原首次启动退出根因仍未知，原生 popup 截图效果未闭合；不以离屏或 CLI 通过替代。首次失败保留。当前安装环境检查复用已有解释器，不声称全新执行环境安装已验证。 / Native installation, attachment and fresh continuous learning remain unaccepted; observed native defects and interpreter limits stay explicit.

当前证据与产物见 [候选核对](../../verification/OPTIONAL_LEARNING_INSTALL_CANDIDATE.md)；下方此前暂停、源码和同根便携候选结论为历史。 / See the current candidate record; earlier notes are historical.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans when implementation resumes. The latest goal continuation resumes candidate preparation and offline checks; native actions still require concrete approval. / 计划交付后按持续目标恢复候选与离线阶段；桌面操作仍需具体批准。

**Goal / 目标:** 学习模式是可选、独立安装的工作台，执行模式不依赖安装或打开学习工作台；工作台提供简体中文和英文即时切换，连接兼容执行模式后可教学和运行已审核工作流。

**Architecture / 架构:** 保留现有编辑器与执行器，通过独立交付清单、安装身份和轻量共同合同拆分两组件。学习工作台单独管理外置内容库，采集和执行按需附着明确的执行安装根及同库会话，不复制执行器。国际化只改变应用显示，不改变用户内容、资产版本、请求或动作门禁。 / Separate component lifecycles with lightweight shared contracts, offline library management and explicit executor attachment. Localize presentation without changing business identity or authorization.

**Tech Stack / 技术栈:** Windows、Python、PySide6/Qt、QTranslator `.ts/.qm`、PyInstaller、现有 .NET Framework C# 编译器；复用已有工具，不为写计划安装依赖。

**Spec / 依据:** 用户要求“和执行模式能够独立安装”“学习模式不是必需品是可选项”“现在学习模式没有语言切换”“后续计划给我先，先不继续测试”。此前详细设计和历史证据见 `2026-10-05-learning-optional-install-and-language.md`；本文件确定首版交付边界、剩余顺序及当前停点。 / The latest request controls this planning-only turn; retain the earlier design and evidence.

## Global Constraints / 全局约束（计划交付时；后续阶段见上方）

- 本轮只核对文件、整理和保存计划；不改产品代码，不运行新测试，不编译翻译、不打包、不安装、不发布。后续恢复依据用户最新指令；桌面测试仍需具体范围批准。 / Planning only; preserve concrete approval for later desktop acceptance.
- 主会话负责架构、整合和最终验收；执行子 Agent 使用 Sol。 / Main owns integration and acceptance; Sol performs bounded implementation.
- 禁止 Codex 原生 Computer Use/Sky；桌面观察与输入仅使用项目维护接口及既有门禁。 / Native Computer Use remains disabled.
- 学习与执行各自拥有安装根、快捷方式、升级和卸载身份，用户内容库在安装目录之外；一个组件变化不得损坏另一个或删除用户库。 / Independent installation identities and external user data.
- 保留已选 UI、独立界面资产、流程图固定版本引用，以及自动生成、人工审核、人工修改工作流的主线。 / Preserve the selected UI and editable, reviewable interface-first workflows.
- 保留当前 Agent、连续委派会话、外部视觉 API 和可选本地模型路线；学习工作台离线管理不要求模型或执行宿主，未来决策 API 未接入时正常使用。 / Model routes stay optional; offline management requires neither a provider nor an executor.
- 不自动覆盖 Agent/MCP 配置、不自动启动执行宿主、不强制下载模型或购买 API。 / No automatic configuration rewrite or provider purchase.
- 保留首次失败与修复后结果；哈希只证明文件一致性，不冒充发布者签名。 / Preserve original failures and distinguish integrity from publisher authentication.
- 首版按限定完整流程验收，不承诺任意软件稳定；收益 benchmark、准确率和速度收益不作为本轮发布前置。 / Bounded acceptance without universal stability or benefit claims.

## Current State / 计划交付时状态（后续候选见上方）

源码进度与安装版验收分开结算。 / Source readiness is separate from installed-product acceptance.

| 项目 / Item | 已有 / Existing | 仍需完成 / Remaining |
|---|---|---|
| 独立组件 / Components | 源码收集、执行专用依赖组、安装描述、执行兼容源载荷 | 新学习冻结载荷、两个实际安装器与普通安装 |
| 离线管理 / Offline use | 目录入口、独立偏好、离线编辑和启动检查源码 | 新 EXE 普通首次入口、保存及重开 |
| 按需连接 / Attachment | Client、共同合同、运行页执行根/会话入口及未决请求保护 | 两个分离安装之间的实际连接 |
| 中英文 / Languages | 设置菜单、即时切换、记忆选择、每语言 1176 条已编译译文 | 新候选语言入口、英文布局与实际弹窗 |
| 安装生命周期 / Lifecycle | 独立身份、回滚、外置数据保留和残留根重装合同 | 实际载荷、普通 GUI/HKCU/快捷方式 |
| 已知故障 / Defects | Qt popup 关联源码、可选启动生命周期记录 | 首次退出根因仍未知；原生截图效果未验证 |
| 发布 / Release | 保留历史候选及首次失败证据 | 同一新候选完整验收、说明和测试版发布 |

本轮只读取现存报告：`main-learning-final.xml` 为 84 项通过，`main-installer-retained.xml` 为 37 项通过，均无失败、错误或跳过。没有运行这些检查；两批范围分别为源码/离屏与合成安装器合同，不相加为总覆盖，也不替代实际安装或桌面验收。 / Existing reports were inspected, not rerun; their scopes do not establish native acceptance.

中英文源码已具备，不代表当前旧 EXE 已更新。新学习冻结 EXE、实际两组件普通安装和发布尚未完成；原首次启动自行退出仍为发布卡点。 / The old executable is not updated by source changes, and the unexplained startup exit remains a release blocker.

## User Journeys / 第一版用户怎么用

1. **只使用执行模式：** 单独安装执行模式，按原方式连接 Agent 和执行操作，无需安装或打开学习工作台。 / Standalone execution.
2. **只管理学习库：** 安装学习工作台，选择或新建库目录，查看、审核、修改、保存和重开内容；不要求执行宿主、API 或本地模型。空库给出开始入口，不伪造学习结果。 / Offline library management.
3. **教学和复用：** 在工作台连接入口选择兼容执行安装与对应同库会话，确认状态后采集教学或运行已审核工作流；未连接明确说明原因，库管理继续可用。 / Explicit optional executor attachment.
4. **切换语言：** 设置 → 语言 → 简体中文 / English，即时刷新并记忆选择；不丢未保存编辑、选中项目或原请求，不翻译用户标题、备注、OCR 或日志。原生文件对话框文字由 Windows 决定。 / Persistent language switching without changing user content or requests.

## Review Focus / 重点验收条件

1. 分别安装、升级、卸载和重装：另一组件及用户库仍可用，未知或修改文件保留。 / Independent lifecycles preserve the other component and data.
2. 错执行根、旧 PID、入口修改、不兼容协议或不同库：明确拒绝，不放宽门禁，不破坏当前编辑。 / Invalid attachment identity is rejected safely.
3. 未保存编辑或未决请求期间切换语言：不丢内容、不重复发动作；同名用户文字不误翻译。 / Locale changes preserve edits and request identity.
4. 首次目录取消、中文路径、旧/损坏设置、只读目录：不静默换库，不出现无法解释的退出。 / Directory and settings failures remain explicit.
5. 界面变化、弹窗遮挡、中断或结果未知：先核对证据，不能盲点或重放。 / Explicit state verification and recovery.

---

### Task 1 — Independent installation / 独立安装交付

**Files / 文件:** `scripts/build_component_sources.py`、`scripts/build_learning_workbench.py`、`scripts/build_execution_component.py`、`scripts/check_execution_component.py`、`packaging/learning_workbench.spec`、`packaging/component_installer.cs`、`scripts/build_component_installer.py`、`scripts/setup_instant.ps1`、`pyproject.toml`、`uv.lock`；`FRIEND_SETUP.md`、`RELEASE_SCOPE.md`。

**Interfaces / 接口:** 学习入口 `AgentLearningWorkbench.exe`；执行组件复用维护入口和 setup 流程；执行安装描述为 `execution_installation.v1`，包含版本、协议、能力、入口及文件哈希。两个独立安装身份分别管理自己的文件。 / Separate installation identities and an explicit execution descriptor.

- [x] 已有源码层组件边界、执行专用依赖及安装生命周期合同；必要共享模块不等同必须安装学习 GUI。
- [ ] 恢复后收拢实际清单，生成两个正常安装入口，学习组件不携带完整执行器或模型；执行组件不要求学习 GUI/Qt。
- [ ] 用实际载荷先验证临时目录生命周期，再在获批桌面阶段验收普通安装、升级、卸载和残留根重装；GUI/HKCU/快捷方式单独结算。
- [ ] 文档分别说明学习 EXE 与执行端现有 Python/MCP 环境要求，数据位置及卸载保留行为，不能把执行 setup 脚本写成自包含执行 EXE。

**Verification after resumption / 恢复后检查:** `python -B -X utf8 -m pytest tests/test_component_installer.py tests/test_execution_component.py tests/test_agent_setup_scripts.py -q`；期望相关合同通过，实际载荷验证报告无漏包。普通安装通过还须另有原生证据。

**Exit / 出口:** 两个可单独安装、升级、卸载的组件；另一组件和外置库保留。 / Independently managed components with preserved data.

### Task 2 — Offline management and attachment / 离线管理与按需连接

**Files / 文件:** `app/learning_memory/workbench_launch.py`、`workflow_run_panel.py`、`workflow_run_client.py`、`execution_installation.py`；相关 launcher/client/panel 测试及 `docs/WORKFLOW_EDITOR.md`。

**Interfaces / 接口:** `WorkflowRunClient(session_dir, library_root, transport=None, *, execution_root=None)`；`load_execution_installation` 校验明确安装根；冻结工作台不把自身目录当作执行安装。 / Explicit validated cross-root attachment.

- [x] 源码已有执行根/会话选择、状态读取、错误说明及未决请求保护；连接只读状态，不触发真实输入。
- [ ] 在新候选普通入口验证离线空库、目录选择/取消、编辑、保存重开；这些操作不访问模型或启动宿主。
- [ ] 从两个实际安装根连接同库会话；错误版本、修改入口、过期进程或不同库明确拒绝，离线管理继续可用。
- [ ] 旧执行版本仍可单独使用；缺连接合同只提示兼容升级条件，不强迫执行用户安装学习模式。

**Verification after resumption / 恢复后检查:** `python -B -X utf8 -m pytest tests/test_learning_workbench_launch.py tests/test_execution_installation.py tests/test_workflow_run_client_installation.py tests/test_workflow_run_panel.py -q`；期望离线和身份合同通过。真实分离安装连接另行验收。

**Exit / 出口:** 离线管理独立可用；教学/执行按需连接，失败原因明确。 / Offline use plus explicit optional attachment.

### Task 3 — Language delivery / 中英文交付

**Files / 文件:** `app/learning_memory/workbench_i18n.py`、`translations/*.ts`、`translations/*.qm`、工作台页面与相关纯 UI 弹窗；`tests/test_workbench_i18n.py`、`tests/test_workbench_i18n_journey.py`。

**Interfaces / 接口:** `LanguageManager.set_language(locale, persist=True)`；`zh-CN/en-US`；独立 `workbench-preferences.json`，旧 `data_dir` 设置格式保持。 / Separate persistent locale preferences.

- [x] 源码和资源已有语言菜单、即时刷新及记忆选择；业务值、用户内容、原日志与请求身份保持。
- [ ] 新候选包含当前资源，从普通入口检查中文 → 英文 → 重开记忆，同时保留未保存草稿和待处理请求。
- [ ] 检查标题栏、菜单、页面、按钮、审核/恢复弹窗、空状态和错误提示；英文长文案不被裁剪。
- [ ] 实际启用的异步分支发现遗漏时只补对应显示绑定并复测相关路径，不把后台原始日志全文翻译。

**Verification after resumption / 恢复后检查:** `python -B -X utf8 -m pytest tests/test_workbench_i18n.py tests/test_workbench_i18n_journey.py tests/test_workflow_run_panel.py -q`；期望语言持久、状态保留及用户内容保护通过。安装候选与原生布局单独验收。

**Exit / 出口:** 用户在安装后的工作台实际找到语言菜单，切换和重开正常，无编辑丢失或动作重放。 / Visible, persistent installed-app language switching.

### Task 4 — Startup and popup stability / 启动与弹窗稳定性

**Files / 文件:** `app/learning_memory/workbench_launch.py`、`workbench_startup_trace.py`、`workbench_window.py`、`workbench_popup_ownership.py`；故障证据指向的共同窗口/截图层及对应窄回归。

**Interfaces / 接口:** 可选 `--startup-trace ABS_NEW_FILE` 默认关闭，独占新建 UTF-8 JSONL，记录目录选择及 Qt 关闭/退出边界，不记录截图或用户输入，不改退出策略。 / Optional startup lifecycle evidence without changing behavior.

- [x] 源码已补可选生命周期记录与 popup 关联；离屏检查不能证明原退出和原生归属已解决。
- [ ] 获批后在新候选保留首次启动日志和进程退出码，定位自行退出的具体路径；不猜测或先改退出策略。
- [ ] 核对实际 popup/阴影原生关系、项目截图与选点合同；不按同 PID 泛化放行、不关闭遮挡保护、不盲选。
- [ ] 实际故障须有根因、最小修复、对应回归及相关复测；未知就保留为发布卡点。

**本次交付范围限定 / Current delivery scope:** 本次新独立安装预览仅交付已通过同冻结Main与独立验收的新包；历史便携candidate02不交付，其原故障作为历史未解决事项保留，不能凭新包通过宣称旧根因闭合。当前新包实际故障仍须按RootCause规则完成根因、修复与相关复测。此限定是用户最新替代讨论下Main的范围决定，不记为用户明确答复此前发布问题。 / Deliver only the new independent installation previews accepted by Main and the independent agent on the same freeze. Do not deliver portable candidate02; retain its original defect as historically unresolved, without claiming old root-cause closure. Any actual defect in the new pair still requires root-cause repair and relevant regression. This is Main's scope decision following the replacement discussion, not an explicit user answer to the earlier release question.

**Verification after resumption / 恢复后检查:** `python -B -X utf8 -m pytest tests/test_workbench_startup_trace.py tests/test_workbench_popup_ownership.py tests/test_learning_workbench_launch.py -q`；期望源码合同通过，原生问题另有具体证据闭合。

**Exit / 出口:** 已知故障有证据闭合，不能凭后来重开成功抹掉首次失败。 / Evidence-backed defect closure.

### Task 5 — One frozen candidate / 集中冻结候选

**Files / 文件:** 构建脚本、实际交付清单、候选哈希报告、`packaging/learning_readme.md`。

**Interfaces / 接口:** Task 1 的两组件清单与安装描述，Task 2 的显式连接，Task 3 的当前语言资源；冻结后主会话与独立验收使用同一载荷。 / One coherent candidate for both acceptance stages.

- [ ] 用户恢复后仅为新增改动、失败或未闭合依赖做必要窄检查；无新变化不重复跑全套以累计数量。
- [ ] 集中构建一个学习候选及对应两个安装器，记录版本、文件清单、SHA256 和签名状态；稳定执行发布不因学习候选自动替换。
- [ ] 在树外、新数据根验证真实功能入口与冻结 EXE 两种语言；原工作树不能补齐漏包，现有解释器环境限制分别说明。
- [ ] 可先冻结诊断候选定位 Task 4，故障未闭合不能公开交付；只有产品运行时修复确需冻结复验才再集中构建。

**本次交付范围限定 / Current delivery scope:** 本次新独立安装预览仅交付已通过同冻结Main与独立验收的新包；历史便携candidate02不交付，其原故障作为历史未解决事项保留，不能凭新包通过宣称旧根因闭合。当前新包实际故障仍须按RootCause规则完成根因、修复与相关复测。此限定是用户最新替代讨论下Main的范围决定，不记为用户明确答复此前发布问题。 / Deliver only the new independent installation previews accepted by Main and the independent agent on the same freeze. Do not deliver portable candidate02; retain its original defect as historically unresolved, without claiming old root-cause closure. Any actual defect in the new pair still requires root-cause repair and relevant regression. This is Main's scope decision following the replacement discussion, not an explicit user answer to the earlier release question.

**Exit / 出口:** 新候选与源码、翻译及实际清单一致，可用于后续获批验收；尚不等同发布。 / A coherent acceptance candidate, not a completed release.

### Task 6 — Bounded learning journey and publication / 完整学习流程与发布

**Files / 文件:** 新候选验收记录、安装生命周期记录、`README.md`、`FRIEND_SETUP.md`、`docs/WORKFLOW_EDITOR.md`、`CURRENT_STATE.md`、`NEXT_STEPS.md`、`PROJECT_SUMMARY.md` 及发布清单；按影响更新架构说明。

- [ ] 候选就绪后展示两个具体安装器、目录和桌面操作范围，再申请桌面批准；只使用本轮全新数据，不读旧学习资产作验收。
- [ ] 验收只执行、只学习、分别安装后连接，以及单组件升级/卸载/重装；包含中英文关键入口。
- [ ] 主会话在同一候选完成新教学 → 自动生成 → 人工审核/修改 → 保存重开 → 变量换值复用 → 限定界面变化/弹窗/中断 → 明确恢复 → 正常清理。
- [ ] 固定步骤交给工作流，变化数据作为参数；目标或界面证据不再匹配时重新核对或暂停，不把旧坐标当正确结果。
- [ ] 主会话单项和连续使用通过后，Sol 独立验收同一候选；失败先核对原证据、修复并完成相关回归。
- [ ] 更新中英文说明，突出学习可选、API/本地模型可选、连接条件、数据保留和限定范围；核对实际公开资产及哈希后才记发布完成。

**Exit / 出口:** 外部用户可安装的首个测试版；组件生命周期与限定学习闭环有证据，已知限制公开。 / An installable optional trial with complete bounded acceptance.

## Priority and Stop Point / 顺序与当前停点

源码边界、连接入口和语言资源已有基础。后续按“收拢实际清单 → 集中冻结一个候选及两个安装器 → 获批后验收独立安装、语言、连接和学习流程，同时定位启动/弹窗 → 修复与相关复测 → 同一候选独立验收 → 发布”推进。 / Finalize payloads, freeze, obtain native approval, close defects, independently accept the same candidate, then publish.

首版不安排收益 benchmark、多模型组合实验、未来决策 API 接入或大范围架构重写作为发布前置；保留需要的接口。 / Defer benefit experiments and future integrations while preserving interfaces.

**计划交付回合停点（历史）。**没有继续测试、构建、安装、桌面操作或发布。此前恢复目标及检查结果属于历史，不能覆盖当前“先不继续测试”的要求。 / This turn stops at plan delivery.
