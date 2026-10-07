# 学习开发历史原件 / Learning development history

本文件保留整理前 README 的完整原文。下方“当前／待完成”等词属于当时阶段，最新状态以 README 和当前验收记录为准；首次失败和未知原因不改记为通过。 / This preserves the previous README verbatim. Earlier current/pending wording is historical; consult the current README and acceptance record. Original failures and unknown causes remain unchanged.

## 2026-10-07 取消生命周期修复与待验收候选 / Cancellation repair and candidate status

Sol 的全新独立验收发现：步骤已由 Agent 审核后立即取消，Trial 已结束，但运行器残留旧票据，后续动作被 `workflow_run_active` 拒绝。源码现已利用同一 Trial 的已审核原票据即时结算，无需额外“继续”；未审核、未知或不匹配的票据仍保持门禁。Main 的相关运行器、队列、Trial 和取消回归共 60 项通过，原回执和输入队列未被重放或改写。 / Fresh independent acceptance found a cancelled Trial with a stale runner ticket blocking later actions. The source now settles the matching reviewed ticket immediately without an extra continue. Unreviewed, unknown or mismatched tickets remain gated. Main passed 60 related runner, queue, Trial and cancellation checks without replaying or rewriting original receipts or inputs.

执行 `source06/Setup05` 与学习 `GUI04/Setup04` 都包含旧共同模块，尚未加载本次修复。两组件新冻结、Main 实装回归与 Sol 同候选复验尚待完成，测试版未发布。语言、编辑保存等此前通过切片保留；不把旧候选整体记为通过。详见 [取消回归说明](docs/verification/LEARNING_CANCEL_LIFECYCLE.md)。 / Both prior components contain the old shared module. New freezes, Main installed regression and independent retesting remain pending; the trial is unpublished. Earlier passed slices remain evidence rather than overall acceptance.

## 此前独立组件验收进展 / Earlier independent component acceptance

执行 source06/Setup05 与学习 GUI04/Setup04 已分别通过普通安装及 516/330 个实际载荷文件核对。中英文设置、三步审核修改、不可变保存和普通关闭重开已核验；同一保存版本在两组新数据上各完成三步，修复候选也完成一次独立新试运行及正常清理。当前路线为 `steps_only`，仍由 Agent 定位、读取和核验，不代表已测得模型、成本或速度收益。Sol 正在用全新数据独立验收同一冻结候选，测试版尚未发布。 / Execution source06/Setup05 and learning GUI04/Setup04 passed ordinary installation and checks of all 516/330 installed payload files. Language persistence, editing/review/save/reopening and changed-data runs are verified; the repaired candidate also completed an independent new trial and graceful cleanup. Steps-only still requires Agent grounding, reading and review, with no efficiency claim. Sol is independently accepting the same freeze with fresh data; the trial remains unpublished.

正式 `read_text` 原 PNG 在返回回执前按 SHA 校验并持久保存至会话 `read-text-evidence/`，不受普通截图缓存回收影响；迁移后的共享终态导入引用也已修复。Main 的相关回归分别 50 项及 85 项通过。新冻结候选实机连续生成 42 次截图、普通缓存回收至 40 张后，原读取请求仍返回同字节图像；正式工作流读取及停止后的严格终态预览也通过。 / Formal read receipts retain the exact validated PNG outside screenshot-cache eviction. The moved terminal-inspector import is corrected. Main passed the relevant 50 and 85 regression checks; native tests preserved the original read frame after 42 captures with a 40-image cache, and verified formal reading and strict terminal preview after shutdown.

等待识图时可正常停止，原未派发步骤按官方 Client 显式结算为取消且未输入，新宿主严格准入与正常清理已通过。`steps_only` 原工作流接管仍返回 `steps_only_agent_review_required`：新试运行不等同恢复旧运行，不能自动继承旧结果或重放输入。历史首次退出原因仍未知，首次失败和未知记录保留；同冻结独立验收及发布未完成。以下此前“当前/仍待”仅描述当时阶段。 / A stop at grounding preserves an explicitly settled cancelled/no-input original step. Strict new-host admission and cleanup pass. Steps-only takeover still requires explicit Agent review; a new trial is not old-run recovery and does not replay input or inherit unverified results. Preserve the unexplained historical exit and original failures. Independent acceptance and publication remain pending; earlier status wording is historical.

## 此前执行Setup03实装与原生菜单卡点 / Earlier Setup03 installation and popup blocker

Main启动恢复回归90项通过；当前执行冻结source04/Setup03（SHA256 `26990626bbe9f17da4ae7ad2214a9ff8bd119af3bfa215aecf6f54005e59f77d`）已正常安装，实际安装入口/版本核验通过。学习GUI01完成全新首次目录选择，保持运行至明确普通关闭、exit0；历史自动退出本轮未复现，根因仍未知。设置菜单与SysShadow实际Windows owner=0，项目截图保守遮罩；正在仅修工作台自身popup关联，不放宽runtime门禁。宿主和SDK正常退出并清理核验；语言/编辑重开/跨安装根连接/工作流连续验收及发布未完成。证据：`.superpowers/sdd/2026-10-05-learning-optional-install-and-language/native-acceptance-02-evidence.md`。

Main passed 90 launch-recovery regressions; current execution source04/Setup03 installed normally and its real installed entrypoints/version passed checks. Fresh first-use learning startup stayed alive until explicit normal close (exit0); the historical spontaneous exit did not reproduce and remains unexplained. Native menu/shadow owner chains are absent and conservatively masked; repair is confined to the owning UI popup adapter. Host/client cleanup passed. Language/editing/reopening, cross-root attachment, workflow continuity and publication remain pending.

## 2026-10-07 首轮真实安装与运行时故障 / Native installation and runtime defect

学习 Setup01 已通过正常界面安装，330个实际载荷文件及真实HKCU/Start Menu记录核验通过；MCP source03 的公开discover无法解除未知启动门禁，执行Setup02尚未启动。已正式停止本轮宿主并核验cleanup_verified；先修公共合同及回归，再继续正常安装/工作台连续验收。原首次退出/popup未闭合，尚未发布。证据：`.superpowers/sdd/2026-10-05-learning-optional-install-and-language/native-acceptance-01-evidence.md`。

The learning candidate passed ordinary native installation and installed-byte/integration checks. Public MCP discovery cannot acknowledge an unknown launch, blocking the next explicit launch; the execution Setup02 has not started. The owned host was stopped with verified cleanup. Repair and regress the common contract before continuing native acceptance. Startup/popup issues and release remain open.

# Agent GUI Runtime

执行模式可以独立使用。学习模式是可选组件：不安装学习工作台，也能按现有方式执行任务。学习工作台已验证独立安装及中英文设置，**测试版尚未发布，完整验收仍在进行**。 / Execution works independently. Learning is optional. Separate installation and language settings are verified; the trial remains unpublished and full acceptance is in progress.

| 使用方式 / Use | 能力 / Capability |
|---|---|
| 仅执行模式 / Execution only | 当前 Agent、委派或外部视觉 API 执行路线；本地模型可选 / Existing Agent, delegated or external visual API routes; optional local models |
| 仅学习工作台 / Learning only | 离线打开、审核、修改、保存和重开学习库；无需执行宿主或模型 / Offline library management without an execution host or model |
| 两组件连接 / Attached components | 明确选择兼容执行安装与已有会话，采集教学、复用已审核工作流 / Explicit attachment for teaching and reviewed workflow execution |

维护源码中的运行页已提供“执行模式安装目录”选择。两个安装目录可以不同；连接仍核对入口、进程、会话、协议能力和同一数据/库身份。连接只读取状态，不执行输入；原请求未结算时禁止切换目标。冻结学习程序须明确选择兼容的执行安装，不能使用旧便携包的同根假设。 / The source Run page now selects an explicit execution installation. Separate roots preserve entry/process/session/protocol/library checks. Attachment reads status only, and unsettled requests block target changes.

工作台提供“设置 → 语言 → 简体中文 / English”及独立语言首选项；只翻译应用文字，保留用户标题、备注、原始输出和固定业务值。安装候选已验证语言切换和关闭重开后的首选项保留；旧 EXE 不会因源码修改自动更新。 / The workbench provides Simplified Chinese and English settings while preserving user content and stable semantics. Installed-candidate language changes persist after reopening; existing executables do not reload source edits.

**不强制本地模型。** 可以使用当前 Agent、连续委派或外部视觉 API；未配置未来决策 API 时沿用现有执行逻辑。真实 API 供应商连通、识别准确率和学习收益需另行测量，本轮不新增结论。 / Local models are optional. Existing Agent/delegated/external-API routes remain available without the future decision API; no new live-provider, accuracy or benefit claims.

用户库放在安装目录外，两个组件分别升级和卸载。卸载保留未知或修改文件；留有环境/缓存时保留已验证归属，允许原目录重装，修改文件碰撞仍拒绝覆盖。当前安装候选已通过普通安装、语言切换、审核保存重开、限定连续运行和正常清理；跨宿主 Agent 工作流接管及历史首次退出仍有上述限制。详见 [工作台说明](docs/WORKFLOW_EDITOR.md) 与 [后续计划](docs/superpowers/plans/2026-10-07-learning-first-trial-next-steps.md)。 / External libraries and preserved unknown/modified files survive component removal; verified retained roots can be reinstalled without overwriting edits. Current native installation, language/reopening and bounded continuous-run checks pass, subject to the takeover and historical-exit limitations above.

以下是旧候选和历史开发记录；其中同根 `runtime/` 的说明只适用于当时的便携候选，不是新独立安装说明。 / The same-root portable instructions below describe the historical candidate only.

## 历史 Windows 便携学习工作台候选 / Historical portable learning workbench candidate


## 2026-10-07 当前冻结与后续测试授权 / Current freeze and test authorization

当前执行冻结为证据根 `L = .superpowers/sdd/2026-10-05-learning-optional-install-and-language` 下的 `execution-source-03`，安装器为 `installers-execution-02/AgentGUIRuntimeExecutionPreview-Setup.exe`，版本 `0.1.2-preview.1`，SHA256 `77b2f0c7524b8b63e04a5b05bce829471af5b256331610266f2d060e1e88a041`。版本对齐及隔离入口证据见 `L/execution-version-alignment-evidence.md`；学习 `learning-candidate-01` 和 `installers-learning-01` 未改。 / The current execution freeze is source03/Setup02 under L, version 0.1.2-preview.1, with the SHA256 above. Version-alignment and isolated-entrypoint evidence is recorded in the cited report. The learning candidate01/Setup01 is unchanged.

用户最新明确授权“允许后面所有操作电脑测试”：后续本项目桌面测试无需逐批重复询问批准。仍使用项目维护截图/动作接口，保留确切预览、窗口/会话身份核对、独立确认及既有动作门禁；Codex 原生 Computer Use/Sky 禁用不变。授权不代表测试已执行或通过。 / The user explicitly authorizes all subsequent computer testing for this project, so desktop test batches do not need repeated approval questions. Maintained capture/action interfaces, exact previews, window/session identity checks, independent confirmation and existing action gates remain in force. Codex native Computer Use/Sky stays disabled. Authorization is not evidence of execution or success.

旧 setup01 的 14 条实际载荷命令和 6 条 QA 版本身份命令结果保留，不能证明 setup02 的安装、正常 GUI/HKCU/快捷方式、跨安装根连接或真实桌面连续使用已通过。source03 的离线版本/依赖核验也不替代这些验收。原首次启动退出根因和原生 popup 截图效果仍未闭合；尚未发布。本轮仅同步文档，没有运行测试、安装器或桌面操作。 / Preserve the historical setup01 results for 14 real-payload commands and six QA version-identity commands; they do not accept Setup02 installation, ordinary GUI/HKCU/shortcuts, cross-root attachment or real desktop continuity. Source03 offline version/dependency checks do not replace native acceptance. The original startup-exit and popup-capture issues remain unresolved, and the trial is unpublished. This documentation slice runs no tests, installer or desktop actions.

以下原有阶段及 setup01 记录保留为历史；其中“待批准”措辞由上方最新测试授权取代，项目动作门禁不变。 / Earlier stage and setup01 records below are retained as history. Their pending-approval wording is superseded by the current testing authorization above; action gates remain unchanged.

## 2026-10-07 setup01 冻结历史 / Historical setup01 freeze

学习组件 `0.1.0-preview.1` 与兼容执行组件 `0.1.2-preview.1` 的两个独立 Setup 已生成；尚未公开发布，正式执行版 `v0.1.1` 未替换。学习冻结包不含执行宿主或模型，执行源包真实入口未导入 Qt。中英文冻结入口在树外新数据根通过。 / Two separate preview installers are built but unpublished. The stable execution release is unchanged; the learning package excludes the host/models and execution entrypoints do not import Qt.

Main 用实际载荷完成临时目录安装、同版本重装、独立卸载、保留环境/缓存后重装及清理共 14 条命令，另用 QA 专用版本身份夹具完成 `.0→.1` 更新及清理 6 条命令，均退出 0。安装后中英文学习入口和执行真实依赖入口通过，另一组件及外置库保留，最后两组件测试目录正常移除。这些命令不是单元测试数量；版本夹具不是历史正式版。 / Real payload checks pass in temporary directories, including independent removal and retained-root reinstall. QA version-identity fixtures are not historical releases.

普通安装 UI、HKCU、开始菜单快捷方式、跨安装根连接和本轮新内容桌面连续学习尚待批准与验收。原首次启动退出根因仍未知，原生 popup 截图效果未闭合；不以离屏或 CLI 通过替代。首次失败保留。当前安装环境检查复用已有解释器，不声称全新执行环境安装已验证。 / Native installation, attachment and fresh continuous learning remain unaccepted; observed native defects and interpreter limits stay explicit.

当前证据与产物见 [候选核对](docs/verification/OPTIONAL_LEARNING_INSTALL_CANDIDATE.md)；下方此前暂停、源码和同根便携候选结论为历史。 / See the current candidate record; earlier notes are historical.

本地便携EXE候选已构建，29项启动/打包/收集回归及树外中文路径两次离屏打开、重开和正常关闭通过；包内真实入口依赖检查通过。包内宿主连接、实际目录选择器与桌面操作仍未验收，未发布。目录为 `AgentLearningWorkbench/AgentLearningWorkbench.exe`，旁边 `runtime/` 保留维护源码与GUI依赖共根；不是新的安装器或正式版本。 / The local executable builds and passes 29 focused checks plus two isolated offscreen startup/reopen/close runs in a Chinese path; real source dependency entrypoints pass. Package-host connection, the interactive picker and desktop input remain unaccepted; unpublished; the executable sits beside a runtime root containing maintained source and GUI dependencies.

启动适配首次无参数启动用QFileDialog选择已存在、可写的Agent数据根，之后从 `%LOCALAPPDATA%/AgentGUIRuntime/learning-workbench.json` 记忆；取消不新建目录或内容。坏记忆或目录丢失须明确报错，可用 `--data-dir "<数据根>"` 显式打开；显式参数优先且不改记忆。`--session-dir "<已有会话目录>"` 可选。GUI只编辑和附着已有会话，不自动启动宿主/模型，不修改MCP。当前维护源码入口仍是 `scripts/run_learning_memory_workbench.py --data-dir ...`，其数据参数必填；新增scripts/start_learning_workbench.py→app.learning_memory.workbench_launch提供无参数选择与记忆适配；EXE离屏隔离已通过，包内连接与桌面仍待验证。 / Proposed first launch selects an existing writable Agent data root and remembers it locally; cancelling creates nothing. Invalid/missing remembered roots report an error. Explicit --data-dir takes precedence without changing memory; --session-dir is optional. The GUI neither starts a host/model nor changes MCP. The current source entry still requires --data-dir; scripts/start_learning_workbench.py delegates selection/memory to workbench_launch; isolated executable startup passes; package-host and desktop validation remain pending.

Agent宿主必须从同一包的 `runtime/` 安装/配置，并使用与GUI完全相同的数据根；不要接旧安装目录的宿主或其他库。保留WorkflowRunClient对确切root、身份及同库的验证。以当前Agent路线为例，在便携目录中运行：
```powershell
.\runtime\scripts\setup_instant.ps1 -RecognitionSource agent_current -DataDirectory "D:\AgentLearningData"
# 已有包内环境时，仅重新生成配置：
.\runtime\scripts\configure_instant.ps1 -RecognitionSource agent_current -DataDirectory "D:\AgentLearningData"
```
setup需要已有uv并联网安装依赖，Agent路线使用包内 `runtime/.venv-agent`；configure也可用 `-Python "<该包内解释器>"`。两脚本按既有语义生成管理员MCP、本地真实输入启用配置；由操作者审阅生成的单个连接项、合并到Agent并重连，UAC由用户确认。它们不是GUI自动配置步骤，也不代表新安全策略。 / Install/configure the host under this same runtime root and use the exact same data root. Setup requires uv/network and creates runtime/.venv-agent; configure can take an explicit package-local Python. Existing scripts generate supervised administrator MCP/local-input configuration, which the operator reviews and merges before reconnecting and confirming UAC. The GUI does not perform these steps.

现有脚本有效 `-RecognitionSource` 值为 `agent_current|agent_delegate|external_api|local`。`agent_delegate` 另需 `-DelegateProfile`，`external_api` 另需 `-ApiProfile`；local另需 `-ModelDirectory`，setup按需才加 `-DownloadModel`，本地模型可选。已有API/委派/本地路由沿用，真实供应商连通与准确率未在本轮验收。 / Supported script routes are agent_current, agent_delegate, external_api and local, with their existing profile/model flags. Local models are optional;  No live-provider or accuracy validation is claimed.

空库可打开“任务步骤”中的“运行”页签，选择“连接当前Agent会话”；会话仍由原Agent建立，未连接时执行按钮禁用。真实教学、审核、保存及复用见下方既有工作台说明；该候选仍需按批准范围进行桌面验收。 / In an empty library, open the Run tab within Task Steps and connect the current Agent session. The Agent establishes that session; disconnected execution stays disabled. Approved desktop acceptance remains required.

## 2026-10-05 有限源码试用验收结果 / Bounded source trial result

S1–S3限定验收已通过：Main使用项目维护的截图和动作接口查看三个主页面及运行页，普通页面切换和未连接时禁用执行均正常；此前限定审核修改、保存v4及重开证据保留。S2真实队列接管联调通过；Main T25与同一901项冻结的Sol T26连续教学、变化/重复复用、一次宿主中断与明确恢复、About及正常收尾通过。S4隔离真实功能入口、依赖和空库原生启动已通过；当前说明同步到本地源码候选，最终归档hash以S4报告为准。 / Bounded S1–S3 pass: Main inspects all three pages and the run page through maintained project capture/action APIs, with ordinary navigation and disconnected input disabled. Retain the earlier bounded native edit/save-v4/reopen evidence. Real-queue takeover integration and same-freeze Main T25/Sol T26 continuous journeys pass. S4 isolated real entrypoints, dependencies and empty-library native startup pass; these notes accompany the local source candidate, with the final archive hash recorded in the S4 report.

本轮页面检查的工作台和宿主均正常exit 0、PID/HWND消失；901项源码与735份T25原件hash不变，QA库只保留此前保存的v4。操作者为Main Astra，独立S3执行验收为Sol；human_review=false。正式v0.1.1、UI v14不变，未发布、未对外交付，候选是源码目录/ZIP而非exe；真人空库使用、全部编辑类型、广泛应用/恢复、收益与真实API准确率未验收。本地模型可选，也可使用已有当前Agent、委派或外部视觉API配置；本轮不新增API实测结论。 / The page-check window and host exit normally with PID/HWND absent; all 901 source hashes and 735 T25 originals match, and the QA library retains the earlier v4 only. Main Astra performs UI verification and Sol independently accepts bounded S3; human_review=false. Stable v0.1.1 and UI v14 are unchanged, unpublished and not externally delivered. The candidate is a source directory/ZIP, not an executable. Human empty-state use, all edit types, broad application/recovery guarantees, benefits and live API accuracy are unaccepted. Local models remain optional alongside existing current-Agent, delegated or external-API routes.

Codex原生Computer Use、computer-use@openai-bundled及@oai/sky已禁用，不再作为项目验收前置或排查对象；继续使用项目截图及动作门禁。浏览器unified-computer-use保持原设置。 / Native Codex Computer Use and Sky are disabled and excluded from project acceptance/investigation; maintained project capture and action gates remain in use. Browser unified-computer-use keeps its existing setting.

当前依据：[试用核对](docs/verification/LEARNING_TRIAL_READINESS.md)、[有限收尾计划](docs/superpowers/plans/2026-10-03-learning-trial-closeout.md)。本地原证据：`.superpowers/sdd/2026-10-05-project-capture-route-correction/native-pages-closeout.json`、T25/T26原回执及`.superpowers/sdd/2026-10-05-learning-trial-delivery/s4-closeout.json`。下方此前“仍待/受阻/下一步”均为当时状态，不覆盖本段；首次失败原件保持。 / The linked review/plan and local closeout records are authoritative. Earlier pending/blocker/next-step wording below is historical and does not override this result; original failures remain preserved.

## 此前状态与开发记录 / Earlier state and development records

当前学习模式为尚未发布的源码有限试用候选，Main T25和同冻结Sol T26限定S3已通过；当前限制和顺序见[试用核对](docs/verification/LEARNING_TRIAL_READINESS.md)及[收尾计划](docs/superpowers/plans/2026-10-03-learning-trial-closeout.md)。 / Learning remains an unpublished bounded source trial candidate; Main and same-freeze Sol pass bounded S3. See the linked review and plan for current limits and order.

## 2026-10-05 当前试用状态 / Current trial state

2026-10-05 当前有限学习试用状态 / Current bounded learning trial: Main T25和同冻结Sol T26限定S3均已通过，原失败记录保留。S4隔离包真实入口/依赖与原生工作台启动检查已通过，本地源码候选可供检查/暂存；完整试用验收及对外交付仍待S1。S1实际桌面截图仍因支持工具超时阻断；原生三主页键盘切换、运行页打开及限定审核状态修改/保存重开已有证据，不记通过、不增加权限或重复不变故障。 / Main T25 and same-freeze Sol T26 pass bounded S3 with original failures retained. S4 isolated real-entry/dependency and native startup checks pass; the local source candidate is available for inspection/staging, while full trial acceptance and external delivery await S1; S1 native desktop images remain tool-blocked; native three-page keyboard navigation, run-page opening and bounded review-state edit/save/reopen are evidenced.

Main通过Sky原生键盘及只读Qt焦点诊断，用普通“运行工作流”按钮Space打开运行页，未连接且执行按钮禁用；在T25学习库隔离副本中将step-1审核状态reviewed→pending，以普通保存按钮Space保存v4，正常重开仍为4步/3已审核/1待审核。旧3版本及其余原件、T25原735文件和901源码冻结不变，三窗正常exit 0/PID-HWND消失；首次Return无效果保留。无pointer/text输入、宿主连接或产品修改，不计真人或所有编辑类型验收。实际桌面图仍缺，S1/完整试用仍未通过。证据：`.superpowers/sdd/2026-10-05-native-focus-observation/native-controls-closeout.json`。 / Main uses Sky native keyboard input and read-only Qt focus diagnostics to open the run page with Space on the ordinary button; disconnected execution remains disabled. In an isolated copy of T25 learning content, step-1 review changes from reviewed to pending, the ordinary save button saves v4, and normal reopen retains four steps with three reviewed and one pending. Old versions, other originals, all 735 T25 files and the 901-source freeze stay unchanged; three windows exit 0 with PID/HWND absent. Preserve the ineffective first Return. No pointer/text input, host connection or product change; this covers neither human review nor all edit types. Actual desktop images remain missing, so S1/full trial acceptance is incomplete.

正式v0.1.1、UI v14及产品版本不变，尚未发布或对外交付；不是exe，本轮仅构建一次源码候选，源码候选保存在本地；归档校验状态以s4-closeout为准；human_review=false，收益和API实测/准确率未知，不增加收益、API购置或额外安全大开发门槛。 / Stable version and v14 are unchanged; no publication/external delivery or executable package, human review or measured benefit/API accuracy claim.

原证据 / Original evidence: `.superpowers/sdd/2026-10-05-known-observation-rerun/live/main-s3-closeout.json`；`.superpowers/sdd/2026-10-05-sol-independent/main-independent-audit.json`；`.superpowers/sdd/2026-10-05-native-workbench-visibility/source-visibility.json`。

本地源码候选（未发布，非exe） / Local source candidate (unpublished, not exe): `.superpowers/sdd/2026-10-05-learning-trial-delivery/agent-gui-learning-trial-source`；公开验收与S1限制见[试用核对](docs/verification/LEARNING_TRIAL_READINESS.md)。

下方均为保留的历史记录，其“当前/下一步/仍待”仅描述当时状态，不覆盖上面结论；历史test.8不代表本轮学习已发布。 / Dated history below does not override the current conclusion or publish this learning candidate.

2026-10-05 T23：新教学、普通离屏编辑重开、首轮复用、同窗零输入中断与明确接管续跑、再次完整复用及正常清理通过；原260文件不变。About测试发现菜单阴影被误作外部遮挡，停止点击并保留首次失败，所以本轮不计完整连续通过。公共菜单归属修复仅补GUI_INMENUMODE状态，Main58项相关回归通过；T24新冻结实机、同候选独立验收及交付仍待。 / T23 passes fresh teaching, offscreen editing/reopen, initial reuse, same-window no-input interruption and explicit takeover continuation, repeat reuse and normal cleanup, with original bytes unchanged. A masked menu shadow blocks About acceptance; retain the first failure. The shared menu-state repair passes Main's 58 related checks; fresh T24 continuous, independent and delivery acceptance remains open.

开发候选截图现包含经Windows原生API核验的应用菜单，仍排除透明边框、标题按钮与系统菜单；截图和输入共用新鲜原点。完整实机待验，正式v0.1.1未更新。 / The development candidate captures verified attached app menus with a shared fresh origin; full live validation is pending and stable v0.1.1 is unchanged.

恢复 API 的新命令入队现受原准入 ready 状态约束；原已接收回执仍可回读。源码修复不代表完整实机恢复通过，详见当前状态。 / Recovery command admission now requires the original admission to be ready; original receipts remain readable. This source repair does not accept full live recovery.

2026-10-05：T21全新四步教学、普通离屏编辑保存重开和首轮完整复用通过；变化目标在计划内中断后，暴露同步读取ID被误作worker缺席校验的恢复阻断。公共校验修复与106项相关回归、原记录只读复验通过；完整中断恢复和同候选独立验收仍待，未发布。 / T21 passes fresh teaching, offscreen editing/reopen and one complete reuse. The recovery validator now distinguishes a synchronous queue command from an absent worker; 106 related checks and unchanged-record replay pass. Full interrupted recovery and independent acceptance remain open, without publication.

以下 T7/T6 及其他阶段记录均为历史证据；其中“下一步”或“下一主线”只反映记录当时的顺序。当前顺序与限制以 [试用核对](docs/verification/LEARNING_TRIAL_READINESS.md)和[有限试用收尾计划](docs/superpowers/plans/2026-10-03-learning-trial-closeout.md)为准。 / The T7/T6 and other stage records below are historical evidence. Their next-step statements describe the order at that time; use the linked trial review and closeout plan for the current order and limits.

## 2026-10-03 T7独立限定旅程已核验 / T7 independent bounded journey verified

T7独立限定旅程经Main核验 PASS_WITH_RECORDED_CALLER_FAILURES：全新四步教学、普通Qt参数/ensure_selected语义修改pending、Agent审核四步、三版保存重开，以及V56/V56重复/W90三轮completed、编辑态零输入拒绝和正常清理均通过；884冻结文件一致，human_review=false。 / Main verifies T7 independent bounded journey as PASS_WITH_RECORDED_CALLER_FAILURES: fresh four-step teaching, ordinary Qt parameter/ensure_selected semantic editing to pending, four-step Agent review, three-version save/reopen, three completed V56/V56-repeat/W90 runs, no-input editing refusal and normal cleanup; all 884 frozen files match, with human_review=false.

仅此独立场景通过，非真人、全产品、收益或发布验收。下一主线收拢普通入口、桌面/真人易用性与试用结果；更广已审核→语义修改失效传播实机覆盖及独立界面完整旅程仍待。收益unknown后置，正式v0.1.1/UI v14不变，不打包发布；499早于最后窄改，后续57窄测不累加。 / This is a bounded independent pass, not human/full-product/benefit/release acceptance. Next consolidate ordinary entry, desktop/human usability and trial results; broader live review invalidation after semantic editing and the complete standalone-interface journey remain open. Benefits stay unknown and deferred; stable v0.1.1/UI v14 are unchanged, with no packaging/publication. The 499 run precedes the last narrow edit; subsequent 57 checks are not added.

[Main原审计 / Main original audit](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-transfer-07-independent-selection/main-final-audit.json)

## 2026-10-03 Main T6限定场景通过 / Main T6 bounded scenario passes

Main T6限定场景已通过：全新四步教学、普通Qt参数化ensure_selected、Agent审核保存重开；M63、重复M63、P91三轮四步completed，首步真实输入true/false/true，rename状态明确零输入拒绝并结算failed，正常清理。884冻结文件未变，审计固定867本轮文件SHA；保留schema extra target未入队及stale wait拒绝两项调用方失败，不声称首次全部无错。 / Main passes the bounded T6 scenario: fresh four-step teaching, ordinary Qt ensure_selected parameter editing, Agent review/save/reopen, three completed four-step runs with actual first-step input true/false/true, explicit no-input rename refusal settled failed, and normal cleanup. All 884 frozen files remain unchanged; the audit hashes 867 current-round files. Retain the unqueued extra-target schema rejection and stale-wait caller rejection; no error-free first attempt is claimed.

下一步是同一冻结候选独立复测；真人易用性、普通桌面视觉、试用结果与交付仍待，收益unknown后置。499项合并回归早于最后窄改，随后57项窄测不累加；正式v0.1.1/UI v14不改，不打包发布。 / Independent retest of the same frozen candidate is next; human usability, ordinary desktop visuals, trial results and delivery remain open, with benefit unknown and deferred. The 499-check regression predates the final narrow edit; the subsequent 57 checks are not added to it. Stable v0.1.1/UI v14 remain unchanged, without packaging or publication.

[Main原审计 / Main original audit](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-transfer-06-selection/main-final-audit.json)

T7限定独立复测已完成；普通操作说明已补齐，剩余普通入口/桌面/真人与试用结果待验。 / T7 bounded independent retest completes; the ordinary walkthrough is available, while ordinary-entry/desktop/human and trial-result gates remain open.

[普通操作说明 / Ordinary walkthrough](docs/WORKFLOW_EDITOR.md)

## 2026-10-03 ensure_selected 接线已实现，待实机连续回归 / Wiring implemented; live continuous regression pending

ensure_selected源码接线已实现，零输入事实与命令成功分开，普通click不变；Main 499 passed/65.62s 后又发现额外业务条件归档遗漏，RED 1 failed→修复后57 passed/1.06s，两批不累加、不称最终冻结。 / Source wiring now preserves no-input facts separately from command success without changing ordinary clicks; the 499-check run is followed by a one-failure RED for omitted archive business conditions and 57 passing checks after repair, without adding counts or claiming a final freeze.

T6仅准备、未启动，无修复后实机/独立通过；下一优先序是Main全新实机单项与同会话连续回归（重复M63、换P91、rename拒绝和收尾）→同一冻结候选独立复测。T5原失败及T4限定范围保留；UI v14/独立正式v0.1.1不变，不打包发布，未到试用发布。 / T6 is prepared but unstarted, with no post-fix live or independent pass. Main fresh single-operation and same-session continuous regression must precede independent retest of the same frozen candidate. Preserve T5 failures and T4's scoped pass; v14/separate stable v0.1.1 remain unchanged, without packaging/publication or trial-release readiness.

[当前细节与待实机计划 / Current details and pending live plan](docs/verification/LEARNING_NATIVE_TRANSFER.md)

## 2026-10-03 三态探针完成，显式选择实现中 / Three-state probe complete; explicit selection in progress

三态探针已完成并正常清理：SelectionItem=true仍可能处于rename，虚拟Edit焦点不能判定编辑状态。正在实现明确的 click.selection_intent=ensure_selected，经原gated路径：已选且无编辑可无输入完成，未选中重验后再输入，未知拒绝；当前源码已不等同v20冻结，尚无修复后实机或独立通过。正式v0.1.1和UI外观未改，不发布；T5原失败及六部分分析保留，T4仅在限定范围通过。 / The three-state probe completes with normal cleanup: SelectionItem=true does not exclude rename, and virtual Edit focus cannot identify editing. Explicit click.selection_intent=ensure_selected is being implemented through the original gated path: selected without editing may complete without input, unselected requires revalidation before input, and unknown is rejected. Current source no longer equals frozen v20; no post-fix live or independent pass is claimed, with unchanged stable v0.1.1/UI appearance and no publication. Original T5 failures and their six-part analysis remain recorded, alongside the limited T4 pass.

[三态原证据 / Three-state findings](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-row-selection-probe-01/THREE_STATE_FINDINGS.md) · [T5失败分析 / T5 failure analysis](docs/verification/LEARNING_NATIVE_TRANSFER.md)

## 2026-10-03 T5 independent acceptance failed / T5 独立验收未通过

T5独立验收未通过：已选中目录名称再次点击进入rename，fresh double动作派发成功但未打开目录；此前调用方断边失败也保留。T4学习源码实测仍只在原范围通过，正式版v0.1.1独立、v14外观不变；先修复并Main回归后独立复测，不打包发布。详情见 [迁移记录](docs/verification/LEARNING_NATIVE_TRANSFER.md)。 / T5 independent acceptance fails: re-clicking an already-selected folder name enters rename, and a dispatched fresh double-click does not open it; the earlier caller adjacency failure remains recorded. T4 remains a source-validation pass within its scope, separate from stable v0.1.1 and unchanged v14; repair and Main regression precede independent retest, with no packaging/publication. See the linked transfer record.

审核下拉与摘要现已由Main改为“已审核”，仅workflow_steps_pane.py两处文字；离屏无连接只读重渲染exit0、Main看图正确且库/队列不变，普通桌面整窗视觉仍未验。当前源码仅此1个UI文件与v20实机候选不同，原v20清单未改，无运行语义或版本/包装变更。 / Main has changed both review labels to Reviewed in the single UI file workflow_steps_pane.py; disconnected read-only offscreen rerender exits zero with correct inspected images and unchanged library/queue. Ordinary desktop whole-window visual acceptance remains open; this one UI file differs from the v20 live candidate, whose original freeze stays intact, without runtime/version/packaging changes.

## 2026-10-03 T4 v20 Main 迁移完成 / T4 v20 Main transfer completed

本轮完成的是 v20 学习源码实测：全新7-Zip教学、普通控件离屏编辑/Agent审核、保存重开及R57/S83连续复用和清理已有原证据。正式版 v0.1.1 仍独立，v14 外观不变，未打包发布；收益 unknown、字体问题已定位离屏环境，实际桌面视觉验收仍待，真人/独立验收不能由离屏 Agent 操作替代。详情见 [迁移记录](docs/verification/LEARNING_NATIVE_TRANSFER.md)。 / This is a source-only v20 learning validation covering fresh teaching, ordinary offscreen editing/Agent review, reopen, two changed-data runs and cleanup. Stable v0.1.1 remains separate, accepted v14 appearance stays unchanged, and nothing is packaged or published; benefit is unknown and font rendering is traced to the offscreen environment; desktop visual acceptance remains open. See the linked transfer record; offscreen Agent work does not replace human or independent acceptance.

## 2026-10-03 学习开发状态 / Learning development status

v20 修复原生行名称待审提议与来源重验：同帧唯一 List/ListItem 下，原执行点必须位于名称等于该行名称的唯一 Edit 子控件；初始 row_name 规则以本次行名为 constant，普通编辑可改为 folder_name 参数。HeaderItem 锚只用于此原生关系；不开放普通 Edit 点击，不加 fallback。Main 120 passed / 43.86s，XML 零 failure/error/skip，冻结876文件（source-freeze-native-v20.json）；相对v19只改 target_recipe_proposal/action_evidence 两生产文件，新增原生行提议回归，并将旧不支持双击样例改为 right。T3 完整四步教学成功，但目标规则为空，未完成普通编辑/复用；Main 的 read_spec 缺 target 且误附 agent_judgment 导致 needs_correction，原失败保留。T3 正常清理见 teaching-gap-audit.json。T4 已开始原 MCP 启动，尚无新实机结论；新教学、普通修改/Agent审核、保存重开、同会话换数据连续复用和收尾仍待验。v14 外观与正式v0.1.1保持，本轮不打包或发布。 / v20 repairs pending native row-name proposals and source revalidation: one same-frame List/ListItem must contain exactly one same-name Edit child hit by the original execution point. Initial row_name constraints use the observed row name as a constant and ordinary editing can parameterize folder_name. HeaderItem anchors are limited to this native relation; ordinary Edit clicks and fallback remain unsupported. Main passes 120 checks in 43.86s with zero XML failures/errors/skips and freezes 876 files. Two production files change from v19, with a new native-row regression and the obsolete unsupported-double test changed to right. T3 completes four teaching steps but has no target recipe, so ordinary editing/reuse remains unverified; the caller's malformed read_spec/agent_judgment correction failure is retained alongside verified cleanup. T4 has begun original MCP startup without new live conclusions. Fresh teaching, ordinary Agent editing/review, reopen, continuous changed-data reuse and cleanup remain open; accepted UI and stable release are unchanged, with no packaging/publication.

沿用用户确认的 v14 工作台外观，正式执行版 v0.1.1 不变。本批已验证新教学生成工作流、普通入口修改/Agent 审核/保存重开、换编号读取当前详情复用，以及填写完成后宿主中断的明确接管、最后核验和完整清理。恢复不会自动重放已完成填写；仍需先读取同一准入到 ready，再重新选窗并核验当前效果。 / The accepted UI stays. Fresh teaching, ordinary editing/persistence, changed-data reuse and bounded completed-fill recovery pass; the stable release is unchanged and completed input is not replayed.

151 项相关源码检查通过。真人审核、第三方软件迁移、独立完整实机验收和交付仍待；本轮不能证明任意时刻崩溃均可恢复，模型用量/准确率/速度收益仍未确认。[范围及原失败记录](docs/verification/LEARNING_RECOVERY_V17.md)。 / Focused checks pass; human, third-party, independent and delivery acceptance remain open, and benefits are unmeasured.

以下候选记录保留为历史；当前优先事项以本节及主线计划为准。 / Older candidate notes below are historical.

## 2026-10-02 当前候选与下一出口 / Current candidate and next outcome

## 2026-10-02 最新执行重心 / Latest execution focus

用户最新要求：收益暂且不论，先核验每次运行的稳定性并检查窗口激活失败。当前只关闭有证据的具体缺口，不承诺任意 Windows 状态下每次成功。顺序改为窗口激活与连续选择 → 同窗口完整异常恢复及清理 → 修改规则的完整复用与第三方流程；模型/准确率/速度对照后置，原标准和历史结果不改。 / The user prioritizes stable execution and activation diagnosis. Validate focus, bounded continuous recovery and cleanup before edited reuse and transfer; defer benefit sampling without changing its standards or historical results.

已完成：P1 本批普通学习、同会话两轮复用、缺失停止、普通修正和清理；v9 修复合法 Agent continue 的终态关联，Main 96 项通过，原 live-04 的 165 个文件只读重放未改。P4 规则语义编辑后待审、保存重开及旧版保留已验，明确审核和新现场复用未验。原 live-04 的准入失败和逻辑清理未通过保持原结论；源码修复不等于完整恢复验收。 / Scoped P1 and the v9 continuation-proof source repair are verified. The ordinary rule draft persists and invalidates review correctly, but explicit review and fresh reuse remain open. Original failures stay unchanged and full recovery has not passed.

激活调查：两份原宿主日志先记录连接 Shell 前台线程 47200 的 AttachThreadInput error 5，随后才是 SetForegroundWindow 拒绝。用户未开菜单；事后同 HWND 的 menu=false、DWM cloaked=2 不能倒推故障瞬间的桌面状态。SetForegroundWindow 不保证扩展错误码，不能据5判定目标需管理员权限。已在共同层保留附件线程及阶段证据、清除旧 LastError并标明此错误码不可靠；原前台核验与输入门控不变。 / Original logs identify denied attachment to the Shell foreground thread before foreground rejection. Later desktop observations do not reconstruct the failed instant. The shared diagnostic now preserves earlier thread errors and marks unguaranteed foreground error codes without weakening verification.

本轮验证：Main 44 项相关检查通过；同一原 MCP/宿主、两个自建窗口连续 7 次选窗及截图成功，其中 7 次为确切跨窗口切换，正常清理通过。它不是完整学习任务/恢复验收，也未复现旧 Shell 前台条件。更早 v9 的单窗选窗加三次截图成功时，目标本来就在前台，只证明相应有限路径。 / Main passes 44 focused checks. One original MCP session passes 7 selections/captures with 7 actual cross-window transitions and cleanup. This does not establish full workflow/recovery stability or resolution of the original Shell condition.

证据与限制 / Evidence and limits: [窗口激活稳定性记录](docs/verification/WINDOW_ACTIVATION_STABILITY.md)。正式 v0.1.1 不变；本轮未打包、提交或发布。下方按候选保存的旧“当前/下一步”段均为历史，以本节和主线计划为准。 / The stable release is unchanged. Earlier candidate-specific current/next entries below are historical; this section and the mainline plan control priority.


历史保持：live-03仅准备，零尝试/输入且清理通过；v4/live-04 的 A 实际任务成功，但 Main 给 finish 多传 attempt_id 导致采集器退出，原0行/1unfinished，观察到清理318.975秒；v4/live-05 的 C 到step2，原异步回执被collector错误拒绝，原0行/1unfinished，观察到清理93.068秒。两现场原宿主/runner/窗口均退出，清理核验通过；未补造 finish、未重评分或拼接到v5。v5首C前 Main 只读核验误解 outputs 键的 KeyError 单列调用方错误，之后按真实键更正，耗时未扣除。 / Preparation, unfinished attempts, verified cleanup and caller errors remain separate; no original scores are rewritten or combined across candidates.

现有 agent_current/workflow_metrics、调用方 record_model_call 和公开任务摘要只能提供局部或调用方上报计量，完整规划/定位/核验/补救总量仍未闭合；A普通路线也没有工作流计量范围。总调用/token继续未知，不把工具数、等待或局部0次当总调用。不为计量购置API或换模型，继续测正确率和耗时。 / Existing hooks provide partial coverage only; complete actual call coverage remains open without replacing missing totals with tool counts or buying providers.

执行顺序调整为：立即结算已结束的原任务，不在计时窗口插入无关调查/文档；只修真实来源覆盖阻断并新冻结 → 首对原结果/replay/未决请求检查 → 余下五对与三项分别诊断 → 同窗口一次弹窗/一次宿主中断及收尾 → 按实测瓶颈优化，完成语义编辑后待审/复用、第三方应用迁移及完整计量缺口 → 再扩大正式三类对照和同候选独立验收。泛化重构、决策API接入、大型UI重做和重复打包后置；正式v0.1.1独立，当前不改版本、不推送或发布。 / Settle completed tasks promptly without inserting unrelated investigation into the attempt clock, repair the proven provenance blocker and freeze anew. Then validate the first pair, finish the pilot, bound recovery and complete measured optimization, edited reuse, transfer and telemetry before formal scale.

[异步回执故障与验证](docs/verification/LEARNING_BENCHMARK_ASYNC_ENVELOPE.md)。

## 2026-10-02 当前重心与实测进度 / Current focus and live progress

学习主线保持“真实教学生成→可审核修改→保存重开→换数据复用→实测收益”。P0 已完成。本批 P1 普通闭环已核验：live-p1-02 六步教学、Agent 整理和可见编辑重开；live-p1-03 在同一原窗口/会话不复位完成 R-381、R-590 两轮六步复用，均填写当次读取详情。原图固定引用和旧程序保留。审核者是 Agent，human_review=false。 / This batch verifies teaching, visible editing/reopening and two continuous fresh-data reuses, with pinned graph/program versions and truthful Agent attribution.

R-000 缺失目标在 step-3 停止，原 action_executed=false、dispatch_attempts=[]，未执行下游读取/填写；普通输入框改为 R-362 后完整六步完成。原宿主和窗口正常退出，cleanup_verified=true、pending_ids=[]。普通界面能看出失败步骤并重新输入，但具体 request_absent 原因目前仅在原回执，作为易用性限制保留。本批不是任意应用、完整 R1/R2 或独立验收。历史超时、遮挡拒绝、驱动错误、取消和多余 continue 拒绝均不改写为首次成功。 / Missing-target stopping, ordinary correction and cleanup pass within the declared scope; detailed failure wording and wider acceptance remain open.

当前 P2：source-v5/cohort-05 的首 A/C 原任务和 finish 都成功，A328.390326秒、C564.687463秒；C本次 step-4.current_detail 绑定 step-5 填写且最终显示 Matches current detail。但C来源覆盖因重复引用为partial，首对继续采集检查点尚未通过；保留原两行结果，停止本候选采余下五对。此计时包含执行者、工具往返、汇报、Main 核验和结算；C最终completed返回后至finish为344.305728秒，主会话收尾明显拖慢，不能归因于模型推理。 / Both first tasks originally succeed, but duplicate provenance references block the collection checkpoint. Keep original rows and stop this candidate before repair; caller settlement accounts for substantial elapsed time and does not identify model inference latency.

共同采集修复已核验：异步returned/running只读准入与真正终态分开；同session原路径规范化去重，原Windows规则引用沿只读索引读取；memory plan绑定原动作goal，附加视觉提示不替代动作语义。Main最终266 passed/10.67s，真实v5原件只读复查coverage=complete、errors=[]，58个唯一快照及原图SHA一致，旧journal/原分未改。部分步骤仍为Agent核验，全规则资格false、总调用/token未知；runtime/client/输入门控和终态评分不变。 / Bound asynchronous retrieval, canonical snapshots and original action semantics are verified by related regressions and actual retained files. Mixed Agent judgment, unknown usage and unchanged original scores remain explicit.

source-v6/cohort-06（849文件、种子2026100206、每路线计划6例/600秒）现已完成4对/8次任务并正常清理；原首对检查点通过，C四例来源coverage=complete、errors=[]，全规则资格仍false。A首次成功4/4，C3/4；C04调用方读取格式化错误经原请求reread补救，最终任务8/8完成，原首次失败与全部耗时保留。稳定两对中位耗时A298.986秒/C246.596秒，描述性节省17.5226%，未达30%目标；模型总调用/token未知，准确率提升未证实。A04后只读审计误展开评分records，执行worker隔离失效；停止余下2对layout，不记失败、不补分、不续采旧清单。原8行、missing4、零unfinished和cleanup证明保留；正式配额不抵扣、真人/独立验收未完成，正式v0.1.1独立不变。 / The closed candidate retains four pairs, eight completed tasks and its original first-success/recovery scores; two layout pairs remain unstarted after post-task oracle exposure. Stable descriptive timing saves 17.5226%, below the target. Call coverage and correctness improvement remain unproven; no formal credit or release change follows.

总模型调用/token 仍未知，省模型、正确率和速度收益均未证明。工具/交接数与等待不冒充模型调用或推理耗时；满分基线只报持平。正式 v0.1.1 独立保持；当前学习源码未发布、未改版本或打包。P1及P2 v2/v3/v4的候选证明分别保存，原失败不移入新候选，也不补改旧记录。 / Benefits and full usage remain unproven; the stable release is separate, and each candidate proof and original failure remains tied to its own frozen revision.

[当前执行计划](docs/superpowers/plans/2026-10-01-learning-mainline-refocus.md)；Main 证据：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261002-learning-mainline-01/live-p1-03/p1-main-audit.json`。以下日期段均为历史，不覆盖当前顺序。 / The plan and raw evidence control current status; dated sections below are historical.

## 2026-10-01 明确新会话准入已接线 / Explicit epoch admission wired

学习开发源码未发布、未改版本；正式 v0.1.1 独立保留。下面原有日期段保留为阶段历史。/ Learning source remains unreleased; stable v0.1.1 remains separate. Earlier dated sections are historical.

新增实验性 instant_recovery_preview 与 instant_recover_session：旧资源及输入/结算证明齐全才复用原 launcher 创建新会话；同 ID 回读不重建，普通 start 清理门控不变。此接口只证明新宿主可用，不接管工作流。Main 482 项、全新原宿主三轮异常恢复及真实 STDIO 恢复通过；全部零 GUI 输入，未证明学习收益。/ Experimental preview/admission tools reuse the maintained launcher with durable idempotence. Contract, host and STDIO checks pass; GUI takeover and measured benefits remain open.

详见 [本轮证据与限制](docs/verification/LEARNING_EPOCH_ADMISSION.md)。/ See the current evidence and limits.

## 2026-10-01 恢复资源基础已验证 / Verified recovery-resource foundation

学习开发树仍未发布、未改版本；正式版 v0.1.1 在独立正式树，保持不变。本轮补 R3 的持久资源拥有权和只读清理证明，没有放宽原 new-session gate，也未实现工作流接管。/ Learning remains unreleased and unchanged in version. Stable v0.1.1 stays in its separate tree. This slice adds durable ownership and read-only cleanup evidence; it does not relax admission or implement takeover.

原 runner 在创建 coordinator 前绑定原 pointer、来源、launcher PID/created、实际 runner PID/create_time_ns 和确切入口/目录，持久化 session-resources.v1。Journal 沿原 FormalModelService、Windows Job 和挂起启动器，在 scope/launch/resume/ready/request/close 边界登记；原四字段策略和累计 cleanup identities 保留，closed_from_phase 不补造缺失启动身份。写盘失败不启动或重放输入，且不丢唯一成员身份。/ The maintained runner pins the original owner and epoch before coordinator creation. Journal writes occur at original model and suspended-launch boundaries, retain the native four-field Job policy and cumulative cleanup identities, and preserve incomplete startup facts after close. Persistence failures cannot launch, replay or discard sole identity evidence.

observe_session_resource_cleanup 只解析同一份原字节并固定 SHA，前后复核原文件和进程 incarnation；owned Job 用原观察器、terminate=False、remove_owned_pid_file=False、三次零观察及专用 PID 文件不存在才能证明。scope_starting/launch_starting 的身份缺口保持 indeterminate；外部服务不被打开 Job 或终止，未决外部请求不通过。本 Job 已退出只证明本地资源，不清除原 pending/票据，不结算业务；input_terminal_settlement_verified/new_epoch_ready 在观察 API 固定 False。/ Read-only proof binds hashes to the same decoded bytes and rechecks identities and snapshots. Owned resources require the original non-terminating observer, stable emptiness and absent PID artifacts. Incomplete launches and unresolved external requests remain indeterminate. Local resource proof never settles input, clears original tickets or admits a new epoch.

已结算 Trial 的直接 cancel、Runner cancel/resume 和原 ticket admit 均在写入或放行前拒绝；原 session JSON、preview 和重复结算保持。Main 最终相关源码回归 498 passed。全新原 InstantSession 的两次正常退出、一次硬终止均完成无输入生命周期验证：两次正常 cleanup_verified=True；硬终止的原 normal cleanup=False，独立资源证明=True，但 start(new_session=True) 仍以 previous_session_not_resolved 拒绝。610 个 app/scripts Python 文件在实测前后哈希相同，11 条原进程身份均已退出。/ Settled controls reject mutation and admission while retaining evidence and idempotence. Main passes 498 related checks. Two normal stops and one abrupt stop use fresh original sessions with zero input. Abrupt-stop resource evidence does not forge normal cleanup or bypass the existing restart gate. All 610 frozen source files and 11 original process identity observations are verified.

原挂起 model wrapper/Job helper 的实际无窗口测试子进程另验证成功启动与登记失败不 resume，两者真实收尾通过；它是 stdlib 等待进程，不是视觉模型、外部 API 服务或学习 GUI 验收。首轮探针错误地把 venv launcher 和实际解释器当作同一 PID，原失败目录与脚本保留；修正为原 Job 成员关系后用第二个全新目录复测通过。源码合同首次失败、夹具目录/锁/超时错误和 Main 原字节绑定失败均与复测分开保留。/ Real suspended-launch boundaries and cleanup also pass with a windowless stdlib fixture, not a vision provider or GUI-learning acceptance. Initial launcher/interpreter assumptions and fixture/contract failures remain separate from successful reruns.

仍待：资源证明与原终态/结算共同约束的新宿主 admission、固定程序/新窗口/新 capture 的明确接管与当前效果核验、活动工作流弹窗及完整同候选连续恢复/收尾，随后独立实机验收。正式人工审核 C、R4 匹配收益、R5 实测优化和 R6 第三方迁移仍未完成；模型总调用/token 与省模型、准确率、速度收益仍未知。历史 session-02 没有此清单，不补写、不把本轮证明移植给旧记录。/ Admission, explicit effect-verified takeover, dialog scope and full same-candidate recovery remain open before independent live acceptance. Reviewed C, matched benefits, measured optimization and third-party transfer are unfinished; usage and benefits remain unknown. Old sessions are not backfilled with new evidence.

合同 / Contract：docs/superpowers/specs/2026-10-01-recovery-resources-design.md；计划 / Plan：docs/superpowers/plans/2026-10-01-recovery-resources.md。证据 / Evidence：D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-recovery-admission-01/main-final-contracts.xml、main-resource-lifecycle.json、main-resource-scope.json、main-owned-identity-audit.json。

## 2026-10-01 新鲜实机学习与原终态结算 / Fresh live learning and original-terminal settlement

本学习开发树仍未发布、未改版本；已发布的正式版 v0.1.1 来自独立正式树。全新 Record Desk 窗口在同一会话中完成实际学习填写、原事件与图像核对、同源合成、不可变程序保存及规则核验的正常复用；第三次填写完成后硬杀原宿主，再用正常审核面板明确结算原终态。/ This learning tree remains unreleased and unchanged in version; stable v0.1.1 comes from the separate formal tree. A fresh Record Desk session covers actual teaching, original-event/image review, source-bound synthesis, immutable program saves and rule-verified reuse, followed by original-host termination and explicit ordinary-panel settlement.

共享测试客户端修正控制请求 ID 与原输入 worker ID 的区分，避免已输入后的 continue/status 被误报身份不符；轮询只读取原请求，不重发输入。Main 相关源码检查 245 passed；实机冻结的 608 个 app/scripts Python 文件在收尾后哈希未变。/ The shared test client distinguishes outer control IDs from the original input worker ID and polls without resending input. Main verifies 245 relevant source checks; all 608 frozen app/scripts Python files remain byte-identical after the live case.

原 command/acceptance/worker 字节、runner、pointer/report、history/outputs 保持，Trial 只增加 recovery_settlement。同 ID 幂等、不同 ID 拒绝，刷新和重开禁用输入；窗口事件只有三次指定填写及关闭。原已知输入 True 不被旧接收 running/False 降级，业务结果仍未知。/ Original command/acceptance/worker bytes, runner, pointer/report, history and outputs are preserved; the Trial only adds settlement. Same-ID settlement is idempotent, conflicting IDs are rejected, and reopening stays read-only. Three intended field changes and closure are the only fixture events. Known input True survives stale acceptance facts; task effect remains unknown.

所有本轮已登记进程身份均已退出，fixture 退出 0、窗口消失；正常 cleanup_verified 仍为 False，close 保留 benchmark_cleanup_not_verified。这不证明新宿主接管、完整 R3、人工正式审核 C 或公平收益；总模型调用和 token 未知。首轮身份错误、外部 AnyIO 任务归属、候选引用/请求层级错误、硬杀 launcher 自动退出后的 NoSuchProcess 及首次离屏字体限制均与复测分开保留。/ All recorded owned process identities exit and the fixture closes normally, but normal cleanup remains false with its original timeout. New-host takeover, full R3, human-reviewed C, model usage and comparative benefits remain unverified. Initial product-client and external probe/caller/font failures are retained separately from corrected checks.

证据 / Evidence：D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-terminal-live-01/main-final-live-audit.json、main-fixed-contracts.xml、session-02/recovery-proof/summary.json、session-02/cleanup.json。

## 2026-10-01 原终态结算切片 / Original-terminal settlement slice

正式版 v0.1.1 已从独立正式树发布；本学习开发树仍未发布、未改版本。本轮只补 R3 已保存终态的显式结算，没有宣称完整恢复。/ Stable v0.1.1 was released from the separate formal tree. This learning tree remains unreleased and unchanged in version; this slice implements terminal settlement, not complete recovery.

原会话客户端新增只读 `preview_recovery` 与专用 `settle_recovery`。绑定原 run/step/program/EID、command/acceptance/worker 字节哈希、完整 trial 状态及 pointer/report 进程身份；只允许原进程已停止的真终态。结算在现有锁内单次原子写回，保留原票据、历史、输出、runner 和回执，不重放、不推进分支、不把输入事实当业务成功。普通面板先核对再明确结算，失败重用同一恢复 ID；重开显示恢复暂停。/ Dedicated preview and settlement bind original identities, exact bytes, complete trial state and inactive original execution processes. One existing-lock transaction records action facts without replay, branch advancement or inferred task success. The ordinary panel previews, explicitly settles and retains the original recovery ID on failure; reopening stays paused.

Main 相关源码回归 216 passed，包含不替换项目 reader 的真实持久格式依赖回归；它先复现只读入口简化对象缺少固定图加载方法，改用完整记忆库短事务后通过。原子写前/后两个实际子进程硬杀、同 ID 重试和两个 Qt 离屏重开已核对原字节与账本。硬杀探针使用合成 program/receipt 和项目适配，真实 GUI 输入为 0；首次缺中文字库及独立审计漏合成项目适配的记录保留，修正只在外部探针。/ Main related source regression: 216 passed, including persisted-project dependency coverage without a replacement reader. It reproduces and fixes the simplified preview facade's missing graph dependency by using the full workspace transaction. Two actual process terminations around commit and offscreen reopenings preserve original evidence. The hardkill probe uses synthetic fixtures and establishes no live input acceptance; initial font and auditor-fixture limitations are retained.

未知 dispatch 仍未决；已知 True 不降级，业务结果/token/总模型调用不补造。进程停止明确不等于资源清理完成。活动工作流弹窗、新宿主 epoch 接管、全新窗口真实单项/连续恢复及完整清理、同候选外部验收、正式人工审核 C 和公平收益仍待完成。下一步按此顺序推进，不再增加重复执行器。/ Unresolved dispatch remains unresolved; known True is preserved and unknown effect/usage stays unknown. Process inactivity is not resource cleanup. Active dialogs, explicit new-host takeover, fresh-window live continuity and cleanup, same-candidate independent acceptance, reviewed C and matched benefits remain open.

合同 / Contract：`docs/WORKFLOW_INTERRUPTION_CONTRACT.md`；切片计划 / Slice plan：`docs/superpowers/plans/2026-10-01-terminal-settlement.md`；证据 / Evidence：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-terminal-settlement-01/main-final-audit.json`、`main-final-source.xml`、`hardkill-commit-02/summary.json`。

## 2026-10-01 单步执行归层与预留接口 / Local-step boundary and extension contracts

开发源码第五批整理：单步执行与只读恢复观察归入 `app/execution/local_direct_step.py`、`post_action_recovery.py`，旧路径保留同一模块对象兼容。原输入门控、线程所有者和学习票据传递保持。/ Slice 5 moves local-step orchestration and read-only recovery observation into execution, retaining module identity and the original gate, owner and learning tickets.

后续 yes/no 决策 API 复用 `app/core/outcome_judgment.py`；当前尚无生产供应商接线，默认关闭或未连接不采集证据、不调用模型。现有 API、本地模型及 Agent 识图路线继续按原配置使用。学习沿原 event_id/command_sha256 与工作流队列接入，不增加执行器。接线位置及限制见 [可选判断接口](docs/OPTIONAL_JUDGMENT_AND_MODEL_USAGE.md)。/ Future yes/no judgment reuses the shared optional contract. Its inactive state performs no capture or model call; existing vision routes retain their configuration. Learning retains the original event/hash and workflow queue, without another executor.

本批相关回归 352 passed，隔离源码入口检查通过；这是源码与依赖验证，本批未做真实 GUI 输入或供应商 API 测试。未改版本、打包发布或更新现有宿主。/ 352 related checks and isolated entrypoint validation pass; this is source/dependency coverage, not live GUI or provider acceptance. No version, publication or existing-host update.

## 2026-10-01 中断事实修复 / Durable interruption facts

共同输入层现在先持久化 attempt，再以同一快照保存原回执和动作事实。死宿主 API 不再用旧接收回执的 False 表示未输入；另提供原 worker 路径/hash 的只读诊断，普通面板标注已保存状态。/ Shared dispatch now persists attempt boundaries and atomically closes them with original receipts. Dead-host reads expose bound saved-worker diagnostics rather than treating stale acceptance False as proof of no input.

Main 合并合同 304 passed；9 个真实子进程硬终止诊断及两个 Qt 离屏重开通过。输入层使用替身，真实 GUI 输入为 0；没有验证完整硬死亡恢复、新宿主启动或公平收益。未改版本、打包或发布。/ 304 source contracts, nine process-interruption diagnostics and two offscreen panels pass. No real GUI input, complete recovery or comparative-benefit claim. No version/build/release.

合同与证据界限见 [WORKFLOW_INTERRUPTION_CONTRACT.md](docs/WORKFLOW_INTERRUPTION_CONTRACT.md)。/ See the interruption contract and evidence limits.

## 2026-10-01 目标规则修订与只读恢复 / Target edits and read-only recovery

`WorkflowRunClient` 现分离只读 attachment 核验与派发前 live gate。宿主实际退出后，新客户端及新开的普通 main 可读取本轮原结果、输出和回执，执行/继续/取消按钮禁用，账本与命令字节未变。活宿主仍完整验证 PID、创建时间及 runner；`control`、原回执绑定和动作门控保持原实现。 / Validated read-only attachment now works after the original host exits; dispatch still requires the original live identity and gate. Ordinary reopening preserves the ledger and disables action controls.

这只证明退出后的只读重连，不是原宿主进程重启续跑。活动 workflow 切换独立顶层弹窗仍不支持：admit 只放行原 ticket 的确切 EID/command，不能放宽竞争 select 代替窗口迁移合同。死宿主的原 worker 仍不能从磁盘自动恢复，未知结果不能当作未输入而重放。 / Read-only reconnection does not restore a dead worker or permit competing window selection; active dialogs and process restart remain open.
普通工作台完成目标规则收紧、应用、保存和重开：保留 `contains input record_id`，增加同一行文字的 `contains constant " · Record"`；仅 step-3 重新待审，其余步骤保持。旧程序、旧规则和旧 ready trial 在编辑期间逐字节不变，旧 trial 随后取消且无步骤输入。两个不同编号/布局的新运行各完整六步通过，并使用各自当前详情；12 个原 EID、26 个核心图像引用及原门控回执核对通过，宿主和窗口清理成功。 / Ordinary controls verify target-rule tightening, save/reopen, scoped review invalidation and immutable old pins. Two new six-step runs succeed with their current details; original receipts, images and cleanup are verified.

审核标记为测试失效传播而设置，`human_review=false`、`formal_C=false`；新目标仍待审。本批不是人工正式审核、公平收益或完整恢复验收。每轮五个输入命中规则，但仍有四个 Agent 读取/结果判断；总模型调用和 token 未知。原场景间有复位，不冒充无复位的连续状态累积。 / QA review markers do not establish reviewed C or benefits. Scenario resets limit continuity evidence; total model usage remains unknown.
验证：目标编辑预检 31 passed；Main 合并检查 93 passed；只读恢复相关 worker 回归 250 passed。集合重叠，不相加。只读修复首次红阶段 5 failed / 41 passed 保留；实际输入首次完成两轮。审计先把 runner 投影误当原 trial、随后构造器参数写错，两个失败报告保留；改为原 public runner.status 全量核对后通过，未重放输入。 / Overlapping checks are reported separately. First failures remain retained; audit repairs required no input replay.

证据 / Evidence：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-target-rule-edit-01/main-live-audit-final.json`、`live-01/dead-host-reopened.json`、`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-recovery-boundary-01/main-integrated.xml`。未改版本、打包、发布或替换安装候选。 / No version, build, publication or installed-candidate replacement.

## 2026-10-01 目标反例与普通识图入口 / Target negatives and ordinary vision declaration

开发源码完成第四批执行边界整理：单步线程所有者逐字节归入 `app/execution/single_step_runtime_owner.py`，旧入口保持同对象兼容。普通学习运行页补充显式会话识图声明，默认未知；换会话清空，启动时固定，运行/等待期间不可修改。API 和本地路线保持原用法。 / The canonical owner moves byte for byte, retaining legacy identity. The learning run page now accepts an explicit session vision declaration, defaulting to unknown; it is cleared on session change and pinned at start. API/local routes are unchanged.

主合并回归 **255 passed**；执行线程切片的独立源码依赖预检通过（880 文件，无输入/截图/推理）。同一新宿主中完成目标行消失和重复两个实机反例：原步骤进入识图等待，Main 看原图回交 absent/ambiguous，第三步未输入并终止，下游未执行；窗口事件无 Open/detail/填写/Verify。正常清理已核验。原程序仍全部待审，两个场景之间复位，不构成正式 C、公平收益或完整 R3 验收。 / Main integration passes 255 tests. Isolated execution dependency preflight and two physical negative cases pass within their stated scope; neither establishes reviewed C, comparative benefits or complete continuity acceptance.

首次未声明能力时返回 `capability_unknown`，普通运行页此前无声明入口；修复的是客户端接线，后端未知能力拒绝规则保留。首次实机/脚本/审计错误与复测分开保存，模型总调用/token 继续未知。本轮不改版本、不打包、不发布。 / The first failure is retained; the fix adds the missing client declaration path without relaxing backend validation. Total model usage remains unknown; version and delivery are unchanged.

证据 / Evidence：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-target-negatives-01/live-02/main-audit.json`、`20261001-learning-ui-vision-declaration-01/main-regression.xml`。后续仍补目标规则替换、活动工作流弹窗、宿主重连及收益对照；以下日期段保留历史快照。

## 2026-10-01 当前开发目标 / Current development target

最新开发验收已完成自建窗口两种布局/新编号的六步复用、读取语义修改后新版本执行，以及取消后继续使用；普通工作台通过实际 main 的离屏控件测试，目标输入走真实门控。活动工作流弹窗、剩余反例、公平收益和第三方迁移仍待验收；模型总调用/token 未知。源码与发布包分开，版本未变；下面日期段保留历史状态。详见[当前证据](docs/verification/LEARNING_WORKFLOW_BENEFIT.md)。 / Current source acceptance verifies owned-window variation, an edited program and post-cancel continuation. The workbench runs offscreen while target input is physical and gated. Broader recovery, benefits and transfer remain open; this does not update the published package or establish total model usage.

本轮源码继续整理：键盘派发的唯一实现迁入 `app/execution`，旧入口保持同对象兼容。学习基准新增冻结程序、审核状态与实际规则证据的采集合同；这属于源码能力，不是实测提速或准确率提升。普通待审版本仍可试跑，未配置可选判断模型时沿用现有流程。详见[基准使用](docs/LEARNING_BENCHMARK.md)与[定义和运行证据](docs/WORKFLOW_DEFINITION_AND_RUN_EVIDENCE.md)。 / Keyboard dispatch now has one canonical execution owner. Benchmark provenance separates pinned review, actual coverage and measured benefit; ordinary draft trials and unconfigured optional judgment remain compatible.

第三批与上述基准、计量及原工作流/执行接线合并 **609 passed**，首次失败及修复记录保留。此次为源码/合同检查，仍未验收新的真实 GUI 任务或学习收益，未改版本或发布。 / The current combined scoped run passes 609 checks, preserving first failures; it does not establish physical task acceptance or measured benefit, and no version/publication changed.

按用户要求整理正式版源码，先不发布；学习模式继续完成变化、恢复与收益验收。执行服务的首批边界整理范围和兼容要求见[模块边界](docs/EXECUTION_MODULE_BOUNDARIES.md)。API、当前 Agent、委派 Agent 与本地模型路线继续可选，不强制安装本地权重。 / Clean up maintained source without publishing, while continuing learning acceptance. Model routes remain optional and API/Agent use does not require local weights.

首批已把填写编排、表单填写和条件观察的唯一实现迁入 `app/execution`；旧导入路径指向同一模块，MCP/视觉作业/宿主使用新入口。主 Agent 执行相关合同与学习接线回归 477 passed；独立源码目录的真实功能入口依赖预检通过，未派发输入或运行模型。 / The first move passes 477 scoped checks and isolated source dependency preflight without input/model execution.

收益评分新增逐任务类结论及全部任务类汇总，防止合并平均掩盖局部退步；主 Agent 复核 53 passed。该检查不证明实际省调用、提速或准确率改善，详见[基准口径](docs/LEARNING_BENCHMARK.md)。下方日期段保留历史快照，以本段及当前原始证据为准。 / Per-family scoring passes scoped checks; empirical benefits remain open. Dated sections below retain historical snapshots.

第二批将动作字段合同与唯一键盘请求类型归入 execution，原键盘派发函数保留；工作台新增已保存定义的审核/规则概览。最终合并回归 **774 passed**，包括上述切片。源码白名单补齐当前说明文档；实际本轮运行、R1c/R2–R6 及全量模型收益仍未通过，详见[证据边界](docs/WORKFLOW_DEFINITION_AND_RUN_EVIDENCE.md)。 / Shared action contracts and a descriptive definition overview are integrated; 774 combined checks pass, with physical/benefit acceptance still open.

## 2026-09-30 调用方计量与判断接口 / Caller telemetry and judgment extension

开发源码新增可选逐调用用量入口：原工作流/草稿整理回执绑定、幂等保存，并在状态中单列调用方汇总；不可见的主 Agent 调用与 token 仍为未知。执行/学习共用的判断模型程序接口已预留，默认关闭，未连接供应商或自动结果结算。未配置时继续现有使用方式。 / Unreleased source adds receipt-bound, idempotent caller telemetry with separate partial summaries; hidden agent usage remains unknown. A shared judgment extension is reserved and disabled by default, with no provider or automatic settlement integration.

字段、调用示例和接入边界见[接口说明](docs/OPTIONAL_JUDGMENT_AND_MODEL_USAGE.md)，验证见[开发记录](docs/verification/LEARNING_WORKFLOW_BENEFIT.md)。未改版本、打包或发布。 / See the contract and verification record; version and delivery remain unchanged.

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

> **2026-09-30 动态行源码修复 / Dynamic-row source fix:** 无名列表可用稳定 ID 选择，行内控件可明确取消记录专属 ID 限制，并保持唯一匹配；编辑、保存重开及相关 41 项检查通过，真实 UIA 树只读回放通过。完整任务的新增操作仍待确认，学习版未发布。见[操作说明](docs/WORKFLOW_EDITOR.md)。 / Dynamic-row editing is source-verified; full physical acceptance remains pending.

> **2026-09-30 学习源码进展 / Learning source progress:** 新数据同窗口的学习、草稿修改、保存重开和参数复用已通过，原生字段核验与清理成功，复用无需手工协议恢复。修复字段光标闪烁引起的瞬态核验失败，相关 52 项通过；本次实机没有触发重采分支。完整动态任务及模型用量、速度和准确率收益仍待验证，学习版未发布。见[验证记录](docs/verification/LEARNING_WORKFLOW_BENEFIT.md)。 / Same-window R1a passes on unreleased source; full-task and measured benefit gates remain open.

> **2026-09-30 源码恢复修复 / Source recovery fix:** 已准备的任务遇到执行请求未入队时，队列恢复后可由普通按钮继续原任务，不重新创建或自动重发输入。相关 65 项源码检查通过，实机连续性与收益目标仍待验收。见[验证记录](docs/verification/LEARNING_WORKFLOW_BENEFIT.md)。 / Prepared trials survive queue admission failures; physical continuity and measured benefits remain unverified.

> **2026-09-29 已授权两次填写与恢复边界 / Authorized fills and recovery limits（源码）:** 已完成学习甲值、保存重开后以参数复用乙值，并由本次 UIA 规则核验；过程中修复公共故障并保留首次失败。原窗口连续性、普通 UI 无手工恢复及收益验收仍未完成；最终锁/报告修复仅有源码回归，未在原宿主热加载。API/Agent 不强制本地模型。详见[验证记录](docs/verification/LEARNING_WORKFLOW_BENEFIT.md)。 / Approved fills are verified after recovery; full continuity and measured benefits remain open.

> **2026-09-27 后续源码，未发布 / Unreleased source follow-up:** `external_api` 已接入现有执行链；配置完整 API 端点、视觉模型和密钥环境变量名后，可用原有单步与组合命令，API 自动定位，执行仍走公共检查。已发布 test.8 ZIP 仍仅预留 API 适配器，不能按本段当成已更新。 / External API grounding is now wired into the common execution path in source. The published test.8 ZIP remains adapter-only and has not been replaced.

# Agent Review Instant


> **真实宿主连接与工作台重开 / Live host attachment and workbench recovery（2026-09-29，源码）:** 已修复 Windows 虚拟环境宿主连接误判及旧运行显示残留。新数据的实际宿主与工作台只读保存、重开、继续和第二轮运行通过，相关检查 71 项通过。完整点击填写和收益验收仍待完成；API/Agent 不强制本地模型。详见[工作流说明](docs/WORKFLOW_EDITOR.md)及[验证记录](docs/verification/LEARNING_WORKFLOW_BENEFIT.md)。 / Source-only attachment/recovery fixes are verified; physical tasks and measured benefits remain open.




> v0.1.0-test.8：源码与隔离候选各 2025 项通过，本方 local、当前 Agent、实际 Luna 委派的单项及连续操作与清理通过；同候选独立 local、visual 与 cleanup 均已完成。首次失败、恢复与具体覆盖见验收记录。独立 API 仍仅预留接口，宿主禁用。 / Source and isolated candidate each passed 2025 checks. Main-agent local/current/actual-Luna single and continuous journeys passed; same-candidate independent local, visual and cleanup gates are complete. Initial failures and scope remain documented. External API remains interface-only with its host route disabled.
**Windows GUI execution runtime for MCP agents / 面向 MCP Agent 的 Windows 图形界面执行框架**

Agent 负责理解任务、决定下一步和判断结果；框架负责观察真实界面、定位目标、派发操作、返回证据与管理本地资源。它不是另一个自主决策 Agent，也不是网页管理面板。

The connected agent plans and judges outcomes. This runtime observes real Windows interfaces, grounds targets, dispatches actions and returns evidence. It is an execution layer, not an autonomous planner or web management console.

> **当前版本：v0.1.0-test.8 · 执行模式测试版。**
> **Current version: v0.1.0-test.8 · execution-mode test release.**
>
> **本次只更新执行模式，学习模式不发布。** 文末介绍是后续方向，不代表下载包已支持。
> **Execution only. Learning is not shipped.** The roadmap below is not an available feature list.
>
> 测试版，不是生产稳定版。快捷配置启用管理员宿主、真实键鼠输入，关闭自动风险拦截。请有人看护，不用于付款、发送、删除或最终提交；UAC、窗口身份与坐标有效性检查仍存在。
> Supervised test software. Quick setup enables elevated real input with automatic risk interception disabled. Do not use it for payment, sending, deletion or final submission. UAC and window/coordinate integrity checks remain.

## 1. 下载与文档 / Downloads and documentation

- [GitHub Releases / 已发布版本](https://github.com/Desolate-Jix/agent-gui-runtime/releases)
- [已发布 test.8 ZIP / Published test.8 download](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.0-test.8/AgentReviewInstant-v0.1.0-test.8.zip)
- [安装、模型下载与配置 / Setup and models](FRIEND_SETUP.md)
- [Agent 使用指南 / Agent guide](AGENT_GUIDE.md)
- [可编辑工作流源码说明 / Editable workflow source guide](docs/WORKFLOW_EDITOR.md)：步骤版本、局部试运行与 `learning_workflow` 控制接口；尚未发布。 / Step revisions, local trials and the `learning_workflow` control interface; not shipped.
- [学习模式完整计划 / Complete learning plan](docs/superpowers/plans/2026-09-29-learning-workflow-benefit.md) · [最终成功标准 / Success criteria](docs/LEARNING_WORKFLOW_SUCCESS_SPEC.md)：自动生成、人工修改、动态目标、连续复用与公平收益验收；当前是开发计划，尚无提速或准确率提升结论。 / Generation, editing, changing targets, continuous reuse and matched benefit acceptance remain in development.
- [Codex 视觉会话适配 / Codex visual-session adapter](skills/codex-vision-session/SKILL.md)：Codex 委派识图连续复用同一个子 Agent；其他 MCP 客户端不受影响。 / Reuse one Codex visual worker across consecutive screenshots without changing other MCP clients.
- [test.8 验收与限制 / Acceptance and limits](docs/verification/TEST8_CANDIDATE_ACCEPTANCE.md)
- [Agent 视觉路由与组合协议 / Agent routing and batch protocol](docs/development/AGENT_VISION_BACKENDS_DESIGN.md) · [组合协议细节 / Batch protocol](docs/development/AGENT_BATCH_PROTOCOL.md) · [独立 API 预留接口 / Reserved API adapter](docs/development/EXTERNAL_VISION_API.md)
- [调用方调度 / Caller scheduling](AGENT_GUIDE.md#执行契约--execution-contracts)：已知字段先合批、及时读取 pending 结果、直接核对回执原图；属于调用指引调整，尚无本轮实机提速数据。 / Batch known fields, promptly retrieve pending results and inspect inline evidence; caller guidance only, without a new live speed measurement.
- [发布范围 / Release scope](RELEASE_SCOPE.md) · [变更记录 / Changelog](CHANGELOG.md)
- [历史网页与学习工作台归档 / Historical workbench archive](https://github.com/Desolate-Jix/agent-gui-runtime/tree/codex/archive-learning-workbench)

这是小型源码包，不是独立 EXE 安装器。不包含模型权重、Python 环境、用户截图、账号或本机 MCP 配置。程序、模型、数据分开存放；升级不要覆盖未清理的运行会话。

This is a source bundle, not a standalone installer. Prepare dependencies, weights and configuration locally. Keep application, model and data directories separate and preserve unresolved sessions.

## 2. 功能 / Capabilities

**本地兼容能力 / Local compatibility:** 保留原有 VISTA 操作与 1–32 项 `form_fill`；新增视觉来源仍使用同一执行器。具体范围见 [发布范围](RELEASE_SCOPE.md)。 / Existing local VISTA actions and 1–32-field form filling remain available through the shared executor.

**test.8 新增 / New in test.8:** 当前 Agent、客户端显式委派 Agent、原图交接、可恢复组合命令与原图文字阅读；外部 API 仅预留接口。 / Current/delegated Agent grounding, resumable batches and image-based reading; external API is interface-only.

| Agent 路由 / Agent route | 行为与边界 / Behavior and boundary |
|---|---|
| `agent_current` | 使用当前具备图像能力的 Agent；无本地模型/VISTA/OCR 权重要求。当前 Agent 不具备所需视觉能力时为 unknown/unsupported 并停止该视觉路径，不静默转调本地模型或 API。 / Uses the current image-capable agent; no local model/VISTA/OCR weights. Unknown or unsupported capability stops this route; no silent local/API fallback. |
| `agent_delegate` | 仅由客户端按显式配置/profile 选择和调用视觉子 Agent，例如 Astra 主 Agent 显式委派给 Luna；宿主不继承 API/key，也不自动创建或切换子 Agent。 / The client explicitly selects/invokes a delegate (e.g. Astra planner to Luna vision); no host credential inheritance or automatic model switching. |
| `read_text` on Agent routes | 返回当前原图供 Agent 阅读，不运行本地 OCR。 / Returns the current original image for the Agent; does not run local OCR. |
| resumable batch | grounding 等待通过 pending/status/resume 继续原命令，保留已完成项并禁止自动重放。 / Pending grounding suspends and resumes the same command without replaying completed fields. |
| external API | 仅保留 adapter/config/mock 协议检查；宿主路由禁用，无 key/live-provider 验收要求，也不宣称服务商支持。 / Adapter/config/mock checks only; host route disabled, no key or live-provider requirement, and no provider-support claim. |

Historical candidate01 isolated verification: source and frozen candidate each passed 2010 checks, with 283 module origins and 715 manifest hashes. These are historical results, not the current candidate03 results. / candidate01 历史隔离验证：源码与冻结包各 2010 项，283 个模块来源与 715 项 manifest 摘要均已核对，这些不是当前 candidate03 结果。

| 功能 / Capability | 执行模式 / Execution mode |
|---|---|
| Agent 接入 / Connection | MCP stdio，7 个工具；客户端须支持工具调用及图片内容，逐客户端验证 / Seven tools; image/client compatibility requires verification |
| 窗口 / Windows | 发现、启动、选择、聚焦、最大化，正常关闭本会话启动的确切窗口 / Discover, launch, select, focus, maximize, owned-window close |
| 观察 / Observation | 原始窗口截图、可见内容 OCR、文字框、before/after 原图与 SHA-256 / Original images, visible OCR, text boxes and hashes |
| 点击 / Clicking | 自然语言定位单击、双击、右击；使用当次截图和窗口身份 / Grounded single/double/right click with current evidence |
| 输入 / Input | 文本填写与替换、23 种编辑导航键、定点滚动 / Text entry/replacement, 23 editing/navigation keys and scoped scrolling |
| 组合动作 / Input sequence | 定位输入框 → 填写 → 读当前焦点字段核对 → 可选回车搜索 → 后图 / Focus, type, verify field value, optional search, observe |
| 回执 / Receipts | 一次返回精简结果与原图，按需读取完整诊断，不自动重放 / Compact result plus images; full diagnostics; no automatic replay |
| 模型 / Models | 显式准备、驻留复用、释放与清理验证 / Prepare, reuse resident models, release and verify cleanup |

### 本地兼容能力 / Local compatibility

以下本地能力继续保留；逐版本历史单独归档，不替代本轮新视觉来源验收。 / Local capabilities remain supported; historical acceptance does not substitute for this release’s new visual-route checks.

- 自动发现开始菜单／桌面快捷方式及 Windows App Paths；按名称、发现 ID 或本地 `.exe/.lnk` 路径启动。同名返回候选，默认复用唯一现有窗口。
- `desktop_capture` / `desktop_click` 无需调用方预先绑定；运行时自动确认桌面图标宿主，沿用现有识别执行链。
- 模型启动错误包含阶段、错误码和日志位置；清理错误包含进程身份、Job、PID 文件与采样证据。
- 关闭失败进入 `cleanup_pending`，保留原 owner，允许显式重试清理；旧会话未解决时返回结构化启动拒绝。
- 修正模型下载参数及跨机器配置说明。
- `form_fill` supports 1–32 text/date/dropdown/radio/checkbox fields with partial receipts and no automatic final submission. See [form-fill contract](docs/verification/EXECUTION_FORM_FILL.md); historical test.7 acceptance remains separately archived.

The published test.7 live acceptance and its retained failure details are historical evidence for that exact package, not test.8 acceptance. See [test.7 acceptance](docs/verification/TEST7_CANDIDATE_ACCEPTANCE.md). The test.8 candidate record is the only source for current candidate verification; do not infer universal website/widget support.

## 3. 系统架构 / System architecture

```text
Connected Agent / 外部 Agent（计划、决策、结果判断）
    | MCP stdio: instant_* / JSON + original PNG
    v
MCP adapter / 协议层               app/instant_mcp.py
    | 参数验证、请求 ID、命令与回执落盘
    v
Session host / 会话宿主            scripts/run_local_step_session.py
    | 串行命令、目标状态、进程采样
    v
Coordinator + Runtime owner / 协调器与串行运行线程
    |-- Window/app lifecycle / 应用发现、窗口准备
    |-- Capture + OCR + UIA / 原图、文字、可访问性结构
    |-- Explicit grounding route / 显式定位路线
    |     |-- local: VISTA worker / 本地模型
    |     |-- agent_current: caller reads original image / 当前 Agent 读原图
    |     `-- agent_delegate: client-selected vision delegate / 客户端显式委派
    |-- Pending grounding -> resolve -> resume / 暂停→回传→续接
    |-- Existing action API / 点击、输入、按键、滚动
    |-- After observation / 操作后截图与诊断
    v
Receipts + original images + cleanup evidence / 回执、原图、清理证据
    +---------------------> Agent judges success / failure / uncertain
```

### 各层职责 / Responsibilities

1. **MCP 层**验证参数、管理请求 ID、落盘与查询回执。管理员入口通过 stdio 中继连接提权宿主，UAC 由用户确认，不给整个 Agent 提权。
2. **会话／执行层**串行处理命令，维护目标窗口和进程身份。专用线程维持原生资源生命周期；不要求每次点击都关闭、重载模型。
3. **观察／定位层**以截图提供当前像素，OCR 提供文字与框，UIA 提供可用控件和焦点；识别来源必须显式选择。`local` 可用 VISTA；`agent_current` 由当前图像 Agent 读取原图；`agent_delegate` 由客户端按指定 profile 调用视觉子 Agent。unknown/unsupported 只停止所选路径，不隐式回退。Agent 路线的 `read_text` 返回图像，不运行本地 OCR。
4. **动作层**复用现有窗口与输入实现，不为每个网站另写点击引擎。输入已派发、后图有变化、任务成功分别表达。
5. **证据／资源层**持久化命令、pending grounding、续接状态、回执、原图和清理记录。暂停/恢复续用同一命令并保留已完成项，不能自动重放。`verified=null` / `awaiting_agent_review` 把任务判定交给 Agent；进程资源清理则按自身证据验证。

The adapter validates/persists requests; the serial coordinator owns native resources; capture, OCR, UIA and VISTA supply distinct observations; existing handlers dispatch input. Dispatch, observed change, task success and cleanup success are separate concepts. Elevation applies to the host, not the whole client.

| 代码位置 / Location | 职责 / Role |
|---|---|
| `app/instant_mcp.py`, `app/instant_receipt.py` | MCP tools, admission, compact/full receipts |
| `scripts/start_instant_mcp.py`, `scripts/start_instant_mcp_admin.py` | Normal/elevated entrypoints |
| `scripts/run_local_step_session.py` | Session loop and evidence |
| `app/execution/` | Shared input-sequence, form-fill and conditional-observation services |
| `app/desktop_review/` | Coordinator, ownership, app preparation, recovery and review UI; compatibility imports |
| `app/core/`, `app/agent/` | Capture, Win32/UIA, input, target identity |
| `app/vision/`, `modules/ocr/` | Model service/worker and OCR contracts |
| `app/api/`, `app/application_profiles/` | Maintained action handlers and shared dependencies |
| `tests/`, `docs/verification/` | Regression and acceptance evidence |

部分历史命名模块仍为执行模式的共用依赖，不能因目录名含 `learn` 就删除。它们本身不代表学习产品已启用。**已发布 test.8 包**的学习启动入口与工具范围保持原样；**当前未发布源码**另有学习工作台与工作流工具，不能混用两者能力说明。

Historically named modules may remain shared dependencies. Their presence alone does not enable learning. The published test.8 scope is unchanged; unreleased source separately contains the learning workbench and workflow tools.

## 4. 模型与环境 / Models and environment

- Windows x64、**Python 3.11**，使用仓库 `uv.lock`，不随意替换版本。
- 视觉定位使用官方 [inclusionAI/VISTA-4B](https://huggingface.co/inclusionAI/VISTA-4B)，走 Transformers 格式，不是 GGUF；保留配置、分词器、处理器、模板与全部权重。
- OCR 是另一个本地组件，UIA 是 Windows 可访问性接口，决策大模型由外部 Agent 提供。因此“只下载一个 VISTA 目录”不等于只有一个算法，**也无需额外部署三套大模型**。
- 锁定 GPU 路径使用 CUDA 13.0 PyTorch；CPU／AMD／所有 NVIDIA 驱动组合尚未认证。本机最近生命周期测试使用 RTX 4070 SUPER 12 GB，不代表该显存满足所有截图与并行负载。
- 模型约 9.1 GB；Python、依赖、缓存和截图另外占空间。可按 32 GB RAM、16 GB VRAM、35–45 GB 空闲磁盘做试用规划，**不是已验证最低配置**。

Use Windows x64, Python 3.11 and locked dependencies. VISTA grounds visual targets; OCR/UIA and the external planning agent have different roles. Hardware numbers are trial-planning estimates, not certified minima. See [full setup guidance](FRIEND_SETUP.md).

## 5. 安装与配置 / Install and configure

安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，解压到例如 `D:\AgentReviewInstant`。路径均为示例，请按本机修改。/ Install uv, extract the source and adjust paths.

```powershell
Set-Location "D:\AgentReviewInstant"
.\scripts\setup_instant.ps1 -ModelDirectory "D:\AgentReviewModels\VISTA-4B" -DataDirectory "D:\AgentReviewInstantData" -DownloadModel -WhatIf
.\scripts\setup_instant.ps1 -ModelDirectory "D:\AgentReviewModels\VISTA-4B" -DataDirectory "D:\AgentReviewInstantData" -DownloadModel
```

已有环境与模型，只生成配置 / Reuse existing environment and weights:
```powershell
.\scripts\configure_instant.ps1 -ModelDirectory "D:\AgentReviewModels\VISTA-4B" -DataDirectory "D:\AgentReviewInstantData"
```

手动下载官方模型 / Manual official download:
```powershell
.\.venv\Scripts\hf.exe download inclusionAI/VISTA-4B --local-dir "D:\AgentReviewModels\VISTA-4B" --include "*.json" --include "*.safetensors" --include "*.jinja"
```

每种模式重复 `--include`，不要把后两项写成位置参数。完整手动安装、无输入 smoke、普通／管理员配置见 [安装指南](FRIEND_SETUP.md)；CLI 语义见 [官方说明](https://huggingface.co/docs/huggingface_hub/guides/cli#download-to-a-local-folder)。

将生成的 `mcp-config.local.json` 或 `.toml` 中 **`agent-review-instant` 单个条目**合并到客户端，保留其他服务器，已有同名条目就更新。脚本不会自动修改 Agent 全局设置。随后重新连接，必要时新开客户端会话加载工具。

Repeat `--include` per pattern. Merge the generated server entry without replacing other servers or copying another machine's paths. Reconnect or start a fresh client conversation as required.

## 6. Agent 使用流程 / Agent workflow

| Tool | 用途 / Purpose |
|---|---|
| `instant_start` | 启动／重连原会话 / Start or reattach |
| `instant_status` | 宿主、目标、待处理 ID、清理状态 / Host, target, pending IDs, cleanup |
| `instant_run` | 推荐：提交、有限等待、返回结果和图 / Submit, wait, return receipt/images |
| `instant_submit` | 分离式异步提交 / Separate asynchronous admission |
| `instant_result` | 按原 ID 查询结果，可带图与完整诊断 / Retrieve original result |
| `instant_image` | 读取绑定的 before/after 原图，不重新截图 / Retrieve fixed evidence |
| `instant_stop` | 停止；支持清理失败后显式重试 / Stop and cleanup recovery |

1. `instant_start` → 轮询到 `ready`。
2. `discover` → `launch` 或 `select` → `capture`，检查目标和原图。
3. 需要识别时 `prepare_models`，同一会话保持驻留，不要每步关模型。
4. `instant_run` 执行一项动作或一个支持的 `input_sequence`。
5. 根据回执与后图判断 success / failure / uncertain，再决定下一步。
6. 正常关闭本轮创建的测试窗口 → `instant_stop` → `cleanup_verified=true` 且宿主退出，再断连。

Start/reattach, inspect the target, prepare models, execute and inspect each result. Keep one connection and one desktop controller. Finish with verified owned-window and resource cleanup.

已选定并确认目标后，以下是 `instant_run` 参数示例，只提交搜索，不自动点击结果。/ After selecting and inspecting the target, this example submits a search only.

```json
{
  "request_id": "search-001",
  "command": {
    "kind": "input_sequence",
    "request": {
      "field_goal": "Search input",
      "text": "Google Maps",
      "clear_existing": true,
      "submit_search": true
    }
  },
  "images": "both",
  "detail": "compact",
  "wait_ms": 25000
}
```

组合输入需要读取当前焦点字段；UIA 不可读或核对失败时返回已完成部分，不表示完全没操作。`wait_ms` 到期不取消命令；按返回的 `next` 查询同一 ID，**不要换 ID 重发**。完整参数见 [AGENT_GUIDE.md](AGENT_GUIDE.md)。

Unreadable fields or mismatches return partial progress. Wait expiry is not cancellation; follow `next` with the same ID and inspect evidence before another input.

## 7. 诊断、数据与边界 / Diagnostics, data and limitations

| 现象 / Symptom | 检查 / Inspect |
|---|---|
| Agent 没有工具 / Missing tools | stdio 配置、本地路径、客户端重连 / Config, paths, reconnect |
| 应用未注册／未发现 / App unavailable | 支持名称／绝对路径及同名消歧；不是 MCP 未注册 / App resolution differs from MCP registration |
| 模型拒绝连接 / Model connection refused | preflight/launch/readiness 阶段、日志和退出码，不只猜防火墙 / Stage, logs, exit status |
| 清理失败 / Cleanup failure | diagnostics、cleanup-evidence.json、PID/Job 观察，不能只看显存 / Resource evidence, not VRAM alone |
| cleanup_pending | 保留原会话，解除阻塞后 stop 只重试清理 / Retain owner; resolve blocker, retry cleanup only |
| 候选歧义／遮挡 / Ambiguity/occlusion | 原图、完整诊断、明确目标或恢复窗口，不盲点 / Inspect, clarify or restore |
| verified=null | 等待 Agent 判断，不是已经成功 / Await agent judgement |

- 数据目录保存命令、回执、截图、进程采样与清理记录。可能含用户输入；只用无敏感内容测试，反馈最小必要脱敏片段。
- MCP 图片可能由客户端发送给模型服务；“本地执行”不等于“所有数据永不离机”。
- 不提供全页 DOM、所有后台窗口可靠截图、任意热键／拖拽、无人值守或全部软件兼容保证。
- 未知结果、宿主退出、无画面变化分别处理；API 返回成功、画面变化或显存下降都不等于业务成功。
- 保留未清理会话与唯一失败证据；不要终止用户原有窗口，或删除指针来强行重开。

Data can contain private text/images and may reach the client's model provider. Visible OCR is not full-page extraction. Preserve unresolved state and unique failures; this is not a promise of universal or unattended automation.

## 8. 验证状态 / Verification status

**candidate01 历史 / Historical candidate01:** 原源码与隔离包各 2010 项，283 个模块、715 项清单；两轮 Luna 混合表单为 139.013 / 126.147 秒，含调用方等待。首次 CaptureVisibilityError 和 AionUi PARTIAL 均保留。当前交付依据为 candidate03，结果见验收文档。 / Preserve the original 2010-check candidate, its initial capture failure and PARTIAL independent report. These are historical; current delivery is based on candidate03 acceptance.


Published test.7 results, failures and scope remain in the [test.7 acceptance record](docs/verification/TEST7_CANDIDATE_ACCEPTANCE.md); do not treat them as test.8 evidence. See [test.8 candidate acceptance](docs/verification/TEST8_CANDIDATE_ACCEPTANCE.md) and the [form contract](docs/verification/EXECUTION_FORM_FILL.md) for current evidence and limits.

## 9. 开发中的轻量学习模式 / In-development lightweight learning

2026-10-02 外框与字体补齐（源码预览 v14）：新增圆角外框、统一标题栏和窗口按钮；字体明确采用 Segoe UI／微软雅黑 UI，正文 14 个逻辑像素。窗口关闭保留未保存保护，小窗口可滚动编辑。51 项相关检查通过，Windows 窗口状态和实际字形验证通过；物理拖拽尚未验收，安装版未更新。见[验证记录](docs/verification/WORKBENCH_SHELL_TYPOGRAPHY.md)。 / Source preview v14 completes the shell and typography. 51 related checks and native window-state/font checks pass; physical drag acceptance and the installed update remain pending.

2026-10-02 工作台外观优化（源码预览 v13）：三个页面统一浅色圆角、线性图标和按钮层级；切页立即完成，导航指示条采用 160ms 动画，可通过“视图 → 减少动画”关闭。运行页支持内部滚动，小窗口不再被隐藏内容撑高。84 项相关源码/离屏检查通过，已核对两种尺寸截图；未更新正式版和安装包。见[验证记录](docs/verification/WORKBENCH_UI_POLISH.md)。 / Source preview v13 adds consistent rounded surfaces and icons, an optional 160ms navigation indicator, and a scrollable run page. 84 related checks and two-size render inspection pass; the release and installed package are unchanged.

2026-10-02 界面响应修复（源码候选 v12）：独立界面库改为后台读取证据，快速切换只保留最后待选，加载失败禁编辑并明确报错。同一库 12 次选择回调从约 0.88–1.04 秒降到不足 1 毫秒；完整目标证据仍约 1 秒，未降低校验。这是界面响应测量，不代表模型或整条工作流提速；旧窗口需重新启动源码预览才加载新代码，正式版未更新。176 项相关源码/离屏检查通过。见[验证记录](docs/verification/INTERFACE_SWITCH_RESPONSIVENESS.md)。 / Source v12 reads standalone evidence in the background and coalesces selection. Measured callbacks fall below 1ms; evidence still takes about one second with validation intact. This measures UI response, not model or workflow gains, and does not update the release.

2026-10-02 源码修复：学习目标现在自动显示为可选择的框。“独立界面库”上方选择已学步骤目标，点击“修改此步骤的定位规则”进入对应步骤；拖框选择另一唯一控件后，预览、应用并保存新的定位规则。动态行仍按本次输入或上游输出选行，运行时使用当前控件位置。独立界面标注与具体工作流规则的保存入口有明确提示；已有版本保持固定引用。168 项源码/离屏检查通过，当前库 5 个执行目标可显示，49 个原资产文件未变；本次未做修改后真实输入和连续运行验收。详见[学习目标框修复记录](docs/verification/LEARNED_TARGET_BOXES.md)。 / Source now projects learned targets into selectable boxes and links them to exact workflow steps. Box selection creates an editable locator revision through the existing preview/apply/save path, preserving dynamic row bindings and current geometry. Independent annotations and executable rules have distinct, explicit save semantics. 168 source/offscreen checks pass; physical input and continuous-run acceptance of this change remain open.

当前开发计划（2026-09-29，源码开发中）：[产品目标与成功标准](docs/LEARNING_WORKFLOW_SUCCESS_SPEC.md) · [完整实施计划](docs/superpowers/plans/2026-09-29-learning-workflow-benefit.md) · [本轮验证记录](docs/verification/LEARNING_WORKFLOW_BENEFIT.md)。目标规则已接入原执行入口，模板/UIA 命中先于本地模型准备和 API/Agent 识图请求；输入框定位也保留同一规则引用。离线契约验证覆盖当前截图、上下文、不可变证据与原输入门控，尚未完成真实桌面和整条任务收益验收。动态列表、当次输出、连续调度、自动生成与界面整合仍在开发，不能据此宣称已提速或提高准确率。 / Implementation is underway: target recipes reach the existing execution route before local model preparation or API/Agent grounding, including input-field focus. Offline checks cover current capture/context, immutable evidence and the original input gate. Live desktop and whole-task benefit acceptance remain pending; dynamic data, verification, scheduling, generation and UI integration are incomplete. This is not shipped or a measured speed/accuracy claim.

**源码已有实验性步骤编辑与局部试运行，本次不发布；真实连续使用验收仍在进行。 / Experimental step editing and local trials exist in source but are not shipped; real continuous-use acceptance is still in progress.**

最新源码进度：固定文字可直接改为每次输入，已有输入与上游文本结果可从列表选择；保存重开后，在“运行工作流”入口填写本次参数。必填/类型错误保留在对话框内，失效引用不会自动换成其他值；缺少结果时说明来源步骤。实际 main、真实参数对话框及原队列相关检查 128 passed，强化队列旅程 2 passed（重叠）；此前全套 2670/1 为本批 UI 修改前基线。A/B/C 策略接线及先前真实只读证据保持，完整真实输入、调用方成本和连续收益仍未证明，安装版未更新。见[工作流操作说明](docs/WORKFLOW_EDITOR.md)、[计划](docs/superpowers/plans/2026-09-29-learning-workflow-benefit.md)和[证据](docs/verification/LEARNING_WORKFLOW_BENEFIT.md)。 / Guided parameters, prior-output choices, typed dialogs and original-queue integration are source-checked; physical and empirical acceptance remain open.

核心：**Agent 决策，框架提供可编辑、可复用的界面与流程记忆，继续使用同一个执行器。** 不再建一套点击引擎，也不每步重复读取完整历史。

The agent remains the decision-maker. Learning adds editable interface/process memory above the same executor, with scoped retrieval rather than full-history replay.

1. **学习段**：Agent 正常操作时记录前后界面、目标、动作和真实跳转。
2. **界面与流程分开**：单页面学习产生独立界面；连续学习按实际跳转成图。输入值作为变量，不因换搜索词重复造页面。
3. **人工修改**：在原图上修改控件框、标签、含义；已有界面可加入／移出流程，持续保存编辑，不强制定稿。
4. **轻量复用**：按需读取节点、目标控件、下一跳与变量，使用明确版本引用；仍核对当前界面，不照搬旧坐标。
5. **局部截图定位**：固定样式按钮保存局部模板，在当前图里比较定位。重复匹配、缺失、缩放／布局变化要明确返回，不伪装成命中。
6. **反馈与版本**：可人工修正或交 Agent 重学，保留来源和修订，避免新修改静默污染旧流程。

当前学习源码已有原生步骤编辑器、不可变工作流、动作前证据与固定 UIA 提议。同会话整理入口已完成真实只读生成和复用；完整普通用户路径及真实连续收益仍待验收。原始截图、流程图和旧版本保留，API/Agent 路线不强制本地模型。见[完整计划](docs/superpowers/plans/2026-09-29-learning-workflow-benefit.md)及[工作流说明](docs/WORKFLOW_EDITOR.md)，本批未改版本或打包。

Learning source includes immutable workflows, captured UIA proposals and a resumable synthesis handoff exercised by the current agent in a read-only native journey. The full normal-user path, physical continuous acceptance and comparative benefits remain open. Historical evidence and versions are retained; API/agent routes require no local vision model. No version or package update is included.

先把执行模式稳定性、操作覆盖和跨 Agent 使用打磨好，再把学习接到稳定执行链上。历史网页／工作台仅供参考，不把旧截图和旧流程当成新版验收数据。

Execution stability and coverage come first. Learning requires separate acceptance with fresh content; the historical workbench is not the current product download.

## License / 许可证

[ISC License](LICENSE). Dependencies and model weights retain their own licenses and are obtained from official sources.
最新进度（2026-10-05 T24）：菜单/父窗口About、全新教学/离屏修改审核重开及首轮四步复用通过；零输入中断结算后，准入误拒绝另一条已返回输入/观察不可用回执，完整连续仍未通过。公共终态修复Main120项相关检查及原399文件不变的只读重放通过。先T25新冻结完整实机，再同候选Sol独立验收、S1实际桌面证据和S4隔离交付；以下T23记录保留为历史。 / Latest T24 evidence is partial. The strict terminal repair passes regression and immutable replay; fresh full live, independent, native and isolated delivery checks remain open.


---

# 整理前发布范围原件 / Previous release scope

## 2026-10-07 首个可选学习测试版范围 / First optional learning trial scope

目标是独立执行组件与可选学习工作台：离线库管理独立，真实教学/执行按需连接兼容宿主；中英文切换、外置用户库、独立安装/升级/卸载及同一候选完整连续闭环是交付要求。本地模型可选，未来决策 API 和模型收益测量不阻止首版。 / The trial requires independent component lifecycles, offline management, safe attachment, both locales and a bounded continuous journey.

源码与离线进度不等于安装通过。新独立候选和普通 GUI/HKCU/快捷方式尚待验收，原启动退出和原生 popup 问题仍待根因/效果闭合；正式 v0.1.1 保持原状态，未发布新版本。 / Native installation/failure/continuous acceptance remains pending; stable release is unchanged.

以下为历史候选状态。 / Earlier release records are historical.

## 2026-10-05 EXE测试交付进度 / Executable test delivery progress

已补最小启动适配：首次选择并记忆已有可写Agent数据目录，显式参数优先，不自动创建宿主、加载模型或修改MCP。GUI和维护源码共用便携包runtime根，现有身份/同库/动作门禁保持。29项窄回归、包内真实功能入口依赖及树外中文路径冻结EXE两次离屏打开/重开/正常关闭通过；原901项中900项不变，唯一修改的是交付收集器；运行、学习与动作路径源码不变。 / The launcher selects/remembers an existing writable data root; explicit arguments take priority without starting hosts/models or modifying MCP. GUI and maintained source share the portable runtime root, preserving identity, library and action gates. All 29 focused regressions, isolated real source dependency entrypoints and two Chinese-path frozen offscreen startup/reopen/close checks pass; 900 of the original 901 sources are unchanged; only the delivery collector changes, with execution/learning/action code intact.

本地构建candidate-01在工具启动前因Windows环境键大小写失败，已补回归修复；candidate-02为本轮唯一实际冻结构建，首次失败保留。产品版本、UI v14、原T25/T26限定源码验收与原失败记录不变。新包尚未连接宿主或进行桌面动作，不等同EXE完整验收/公开发布；真人空库、广泛应用、收益和真实API准确率仍未知。 / Preserve candidate-01's pre-build environment-key failure; the regression fixes it and candidate-02 is the sole actual frozen build. Version, UI v14 and bounded T25/T26 source acceptance remain unchanged. Package-host connection/desktop input and public delivery are pending; human empty-state use, broad apps, benefits and live API accuracy remain unknown.

本地候选：`.superpowers/sdd/2026-10-05-learning-test-build/candidate-02/dist/AgentLearningWorkbench`。证据：该构建目录build-result.json与isolated-check/closeout.json；窄测试报告在本工作树`.superpowers/sdd/2026-10-05-learning-launch-audit/package-contracts-rerun.xml`。下一步先取得新EXE桌面批次批准，使用项目维护的截图/动作接口完成普通入口、选择数据根、编辑保存重开和包内宿主连接，再决定测试版交付；不调用原生Computer Use。 / Evidence resides in the build and isolated closeout reports and focused JUnit. Next obtain approval for the new executable's desktop batch, then validate ordinary selection/edit/reopen and same-package host attachment through maintained project interfaces before deciding test delivery; native Computer Use stays disabled.

以下源码候选及更早记录为当时证据，不能替代新EXE桌面验收。 / Earlier source-candidate/history evidence does not accept the new executable's desktop behavior.

## 2026-10-05 有限源码试用验收结果 / Bounded source trial result

S1–S3限定验收已通过：Main使用项目维护的截图和动作接口查看三个主页面及运行页，普通页面切换和未连接时禁用执行均正常；此前限定审核修改、保存v4及重开证据保留。S2真实队列接管联调通过；Main T25与同一901项冻结的Sol T26连续教学、变化/重复复用、一次宿主中断与明确恢复、About及正常收尾通过。S4隔离真实功能入口、依赖和空库原生启动已通过；当前说明同步到本地源码候选，最终归档hash以S4报告为准。 / Bounded S1–S3 pass: Main inspects all three pages and the run page through maintained project capture/action APIs, with ordinary navigation and disconnected input disabled. Retain the earlier bounded native edit/save-v4/reopen evidence. Real-queue takeover integration and same-freeze Main T25/Sol T26 continuous journeys pass. S4 isolated real entrypoints, dependencies and empty-library native startup pass; these notes accompany the local source candidate, with the final archive hash recorded in the S4 report.

本轮页面检查的工作台和宿主均正常exit 0、PID/HWND消失；901项源码与735份T25原件hash不变，QA库只保留此前保存的v4。操作者为Main Astra，独立S3执行验收为Sol；human_review=false。正式v0.1.1、UI v14不变，未发布、未对外交付，候选是源码目录/ZIP而非exe；真人空库使用、全部编辑类型、广泛应用/恢复、收益与真实API准确率未验收。本地模型可选，也可使用已有当前Agent、委派或外部视觉API配置；本轮不新增API实测结论。 / The page-check window and host exit normally with PID/HWND absent; all 901 source hashes and 735 T25 originals match, and the QA library retains the earlier v4 only. Main Astra performs UI verification and Sol independently accepts bounded S3; human_review=false. Stable v0.1.1 and UI v14 are unchanged, unpublished and not externally delivered. The candidate is a source directory/ZIP, not an executable. Human empty-state use, all edit types, broad application/recovery guarantees, benefits and live API accuracy are unaccepted. Local models remain optional alongside existing current-Agent, delegated or external-API routes.

Codex原生Computer Use、computer-use@openai-bundled及@oai/sky已禁用，不再作为项目验收前置或排查对象；继续使用项目截图及动作门禁。浏览器unified-computer-use保持原设置。 / Native Codex Computer Use and Sky are disabled and excluded from project acceptance/investigation; maintained project capture and action gates remain in use. Browser unified-computer-use keeps its existing setting.

当前依据：[试用核对](docs/verification/LEARNING_TRIAL_READINESS.md)、[有限收尾计划](docs/superpowers/plans/2026-10-03-learning-trial-closeout.md)。本地原证据：`.superpowers/sdd/2026-10-05-project-capture-route-correction/native-pages-closeout.json`、T25/T26原回执及`.superpowers/sdd/2026-10-05-learning-trial-delivery/s4-closeout.json`。下方此前“仍待/受阻/下一步”均为当时状态，不覆盖本段；首次失败原件保持。 / The linked review/plan and local closeout records are authoritative. Earlier pending/blocker/next-step wording below is historical and does not override this result; original failures remain preserved.

## 此前状态与开发记录 / Earlier state and development records

## 源码有限学习试用候选（未发布） / Unpublished bounded learning source trial

2026-10-05 当前有限学习试用状态 / Current bounded learning trial: Main T25和同冻结Sol T26限定S3均已通过，原失败记录保留。S4隔离包真实入口/依赖与原生工作台启动检查已通过，本地源码候选可供检查/暂存；完整试用验收及对外交付仍待S1。S1实际桌面截图仍因支持工具超时阻断；原生三主页键盘切换、运行页打开及限定审核状态修改/保存重开已有证据，不记通过、不增加权限或重复不变故障。 / Main T25 and same-freeze Sol T26 pass bounded S3 with original failures retained. S4 isolated real-entry/dependency and native startup checks pass; the local source candidate is available for inspection/staging, while full trial acceptance and external delivery await S1; S1 native desktop images remain tool-blocked; native three-page keyboard navigation, run-page opening and bounded review-state edit/save/reopen are evidenced.

Main通过Sky原生键盘及只读Qt焦点诊断，用普通“运行工作流”按钮Space打开运行页，未连接且执行按钮禁用；在T25学习库隔离副本中将step-1审核状态reviewed→pending，以普通保存按钮Space保存v4，正常重开仍为4步/3已审核/1待审核。旧3版本及其余原件、T25原735文件和901源码冻结不变，三窗正常exit 0/PID-HWND消失；首次Return无效果保留。无pointer/text输入、宿主连接或产品修改，不计真人或所有编辑类型验收。实际桌面图仍缺，S1/完整试用仍未通过。证据：`.superpowers/sdd/2026-10-05-native-focus-observation/native-controls-closeout.json`。 / Main uses Sky native keyboard input and read-only Qt focus diagnostics to open the run page with Space on the ordinary button; disconnected execution remains disabled. In an isolated copy of T25 learning content, step-1 review changes from reviewed to pending, the ordinary save button saves v4, and normal reopen retains four steps with three reviewed and one pending. Old versions, other originals, all 735 T25 files and the 901-source freeze stay unchanged; three windows exit 0 with PID/HWND absent. Preserve the ineffective first Return. No pointer/text input, host connection or product change; this covers neither human review nor all edit types. Actual desktop images remain missing, so S1/full trial acceptance is incomplete.

正式v0.1.1、UI v14及产品版本不变，尚未发布或对外交付；不是exe，本轮仅构建一次源码候选，源码候选保存在本地；归档校验状态以s4-closeout为准；human_review=false，收益和API实测/准确率未知，不增加收益、API购置或额外安全大开发门槛。 / Stable version and v14 are unchanged; no publication/external delivery or executable package, human review or measured benefit/API accuracy claim.

原证据 / Original evidence: `.superpowers/sdd/2026-10-05-known-observation-rerun/live/main-s3-closeout.json`；`.superpowers/sdd/2026-10-05-sol-independent/main-independent-audit.json`；`.superpowers/sdd/2026-10-05-native-workbench-visibility/source-visibility.json`。

本地源码候选（未发布，非exe） / Local source candidate (unpublished, not exe): `.superpowers/sdd/2026-10-05-learning-trial-delivery/agent-gui-learning-trial-source`；公开验收与S1限制见[试用核对](docs/verification/LEARNING_TRIAL_READINESS.md)。

下方均为保留的历史记录，其“当前/下一步/仍待”仅描述当时状态，不覆盖上面结论；历史test.8不代表本轮学习已发布。 / Dated history below does not override the current conclusion or publish this learning candidate.

> **2026-09-27 后续源码，未发布 / Unreleased source follow-up:** `external_api` 已接入现有执行链；配置完整 API 端点、视觉模型和密钥环境变量名后，可用原有单步与组合命令，API 自动定位，执行仍走公共检查。已发布 test.8 ZIP 仍仅预留 API 适配器，不能按本段当成已更新。 / External API grounding is now wired into the common execution path in source. The published test.8 ZIP remains adapter-only and has not been replaced.

# v0.1.0-test.8 发布范围 / Release scope

> v0.1.0-test.8：源码与隔离候选各 2025 项通过，本方 local、当前 Agent、实际 Luna 委派的单项及连续操作与清理通过；同候选独立 local、visual 与 cleanup 均已完成。首次失败、恢复与具体覆盖见验收记录。独立 API 仍仅预留接口，宿主禁用。 / Source and isolated candidate each passed 2025 checks. Main-agent local/current/actual-Luna single and continuous journeys passed; same-candidate independent local, visual and cleanup gates are complete. Initial failures and scope remain documented. External API remains interface-only with its host route disabled.

执行模式的有人看护测试版，不是稳定版；学习模式不发布。/ Supervised execution-mode test release, not production-stable. Learning is excluded.

**验收范围 / Acceptance scope:** 同一 candidate03 运行时经本方三来源连续测试及同候选独立 local、visual 与 cleanup 复验；最终包仅更新文档，所有非文档源文件与冻结候选逐字节一致。 / The same candidate03 runtime passed main-agent three-source journeys and independent local, visual and cleanup checks. Only documentation changed for delivery; every non-document source matches the frozen candidate byte for byte.

test.8 新增 `agent_current`、`agent_delegate` 路由和可恢复 Agent 组合命令。Agent 路线不需本地 VISTA/模型/OCR 权重；`read_text` 返回原图给 Agent，不运行本地 OCR。能力 unknown/unsupported 时停止所选路线，不隐式回退。委派模型由客户端明确选择（例如 Astra 委派给 Luna），宿主不继承 API 凭据。独立 API 仅保留 adapter/config/mock 协议检查：宿主路由禁用、不要求 key 或 live-provider，也不宣称服务商兼容。这些新增能力要求 test.8。详见 [test.8 候选验收](docs/verification/TEST8_CANDIDATE_ACCEPTANCE.md)、[Agent 组合协议](docs/development/AGENT_BATCH_PROTOCOL.md) 与 [Agent 视觉设计](docs/development/AGENT_VISION_BACKENDS_DESIGN.md)。

Test.8 adds `agent_current` and `agent_delegate` routes and resumable Agent commands. Agent routes require no local VISTA/model/OCR weights; `read_text` returns the original image for the Agent instead of running local OCR. Unknown or unsupported capability stops the selected route without implicit fallback. Delegate model selection is explicit and client-owned (for example, Astra delegates to Luna); the host does not inherit API credentials. External API support is reserved to adapter/config/mock protocol checks: host route disabled, no key or live-provider requirement, and no provider compatibility claim. These additions require test.8. See [test.8 candidate acceptance](docs/verification/TEST8_CANDIDATE_ACCEPTANCE.md), [Agent batch protocol](docs/development/AGENT_BATCH_PROTOCOL.md) and [Agent vision design](docs/development/AGENT_VISION_BACKENDS_DESIGN.md).

## Included / 包含

- MCP stdio runtime with seven tools, including `instant_run` and bounded `input_sequence`.
- Fresh visible-image OCR, compact original-image receipts, 23 editing keys, window/session lifecycle and explicit cleanup verification.
- Conditional observation for a known UIA text/control marker; default waits and confirmation boundaries are unchanged.
- Bilingual setup and agent guidance, plus verification reports under `docs/verification/`.
- Installed desktop app discovery and launch by name/ID/path; automatic desktop target resolution. / 安装应用发现与名称/ID/路径启动，桌面目标自动解析。
- Structured model startup/cleanup diagnostics, retained-owner cleanup retry and unresolved-session start rejection. / 模型诊断、保留原 owner 的清理重试与结构化启动拒绝。
- `form_fill` through existing tools: 1–32 text/date/dropdown/checkbox/radio fields with partial receipts and remaining indexes. Optional `tab_sequence` verifies each named writable text field after Tab; default `recognize_each` supports mixed fields. Unique current UIA text geometry may precede visual inference. / 通过既有工具组合填写 1–32 项，返回完成与剩余索引；可选 Tab 续填逐项核对标签，默认逐项识别支持混合字段，唯一当前文本框几何可先于视觉定位。See / 参见 [form-fill contract / 表单契约](docs/verification/EXECUTION_FORM_FILL.md).
- Shared label, popup, date and native-file-dialog fixes; JSON-quoted labels preserve embedded quotes and backslashes rather than selecting a truncated name. No new MCP tool, spreadsheet editing, automatic final submission or replay. / 通用标签、弹窗、日期及原生文件选择修复；转义标签不再截断为另一字段名。不新增 MCP 工具、电子表格编辑、自动提交或重放。
- Learning GUI/STDIO startup entrypoints are excluded. Shared historically named runtime dependencies remain; no new lightweight-learning code or tools are included. / 排除学习 GUI/STDIO 启动入口，保留共用依赖；不带入新轻量学习代码和工具。

## Evidence and limits / 证据与边界

- Source live evidence includes repeated mixed eight-field forms, named-text Tab batches, invalid-option interruption/recovery and native synthetic-file selection/cancel/reopen. See [batch acceptance](docs/verification/BATCH_FORM_LIVE_ACCEPTANCE.md). These source results are not frozen-candidate or independent acceptance. / 源码实测包括混合八项连续填写、具名 Tab 组合、非法选项中断恢复、虚构附件选择及取消重开；不能代替冻结包与独立验收。
- Source and isolated candidate03 each passed 1759 checks. Codex completed two four-field rounds and native choose/cancel/reopen/reselect; AionUi independently repeated the same frozen runtime. Earlier failures and the stale-dialog capture limitation remain in the [acceptance record](docs/verification/TEST7_CANDIDATE_ACCEPTANCE.md). / 源码与隔离候选03各1759项；Codex和AionUi同包分别完成两轮四字段与原生选择/取消/重开/重选，保留首次失败及失效窗口截图限制。
- Visual multi-select, custom date widgets, automatic option scrolling and arbitrary websites are not universally supported. Model localization may refuse a target; partial completion must be inspected rather than automatically replayed. / 视觉多选、自定义日期控件、自动滚动选项和任意网站尚非通用支持；定位可拒绝，需检查部分结果而非自动重放。
- Final documentation may differ from the frozen candidate; all non-document runtime/configuration/test files must match its manifest before archiving. / 最终文档可更新，归档前所有非文档运行时／配置／测试文件必须与冻结验收包摘要一致。
- This does not claim cross-site accuracy, whole-page completion, unattended automation, long-term stability, universal hardware support, or support for payment, sending, deletion or final submission.
- Models, dependencies and user data are not shipped. Use [FRIEND_SETUP.md](FRIEND_SETUP.md), then run no-input smoke before explicitly authorizing supervised low-risk input.

The package builder is `scripts/build_instant_bundle.py`. The bundle is expected to contain the maintained source, `README.md`, `AGENT_GUIDE.md`, `FRIEND_SETUP.md`, `RELEASE_SCOPE.md`, `CHANGELOG.md`, `docs/verification/` and scripts; package validation must precede any publication claim.


## 2026-10-07 README同步前完整前缀 / Complete README prefix before final sync

## 2026-10-07 当前源码与发布准备 / Current source and release preparation

图像规则明确匹配即继续；已审核的学习步骤由共同编译入口设置零额外渲染等待，图像观察按约100 ms间隔、两秒启动预算轮询，不确定保留原请求交 Agent。普通执行及无图像规则的原等待设置保留。当前不再继续速度优化。 / Reviewed image steps use the shared compiler and bounded polling with immediate success; inconclusive checks retain the original ticket for Agent review. Other wait settings remain. Further speed tuning is deferred.

Main 最终269项相关回归通过；同连接三轮正常图像流程、一次延迟流程、Agent审核对照及不跳转负例完成并正常清理，独立证据核对通过。两步正常流程中位5.651秒，较此前另一新样本批次9.884秒减少42.8%；只代表自有合成窗口，未证明普遍准确率或安装版收益。 / Main's final related regression passed269 checks; continuous normal/delayed, Agent and negative cases closed cleanly with independent evidence review. The owned-app full-flow median fell from9.884s in the prior fresh cohort to5.651s; this is limited before/after evidence.

第二批source13/GUI11实装已记录两个教学事件，六个连续场景按预期处理；工作台保存确已完成，但保存后公共窗口刷新因一次空标题清除既有绑定，导致观察回执失败，该批仍不通过。已绑定HWND/PID严格一致时允许空标题刷新的公共修复，经Main55项回归及独立只读审查通过；第三批匹配冻结、实装保存后观察及连续复测、同冻结独立验收仍待完成。第一批终态JSON读取失败记录保留，未提交/tag/公开发布；正式v0.1.1不替换。旧测试安装器和重复ZIP已删除，日志与manifest保留。 / The second source13/GUI11 installed pair captured both teaching events and handled six continuous cases as expected. GUI Save persisted, but a transient empty title cleared its known binding and failed the post-action observation; this pair remains failed. The common refresh repair requires the same verified HWND/PID and passed Main55 checks plus independent read-only review. A third matched freeze, installed Save observation/continuous retest and independent acceptance remain pending. The first JSON-read failure stays recorded; no source/tag/public release yet, stablev0.1.1 is unchanged, and obsolete installer/ZIP files were removed while logs/manifests remain.

详见[等待优化证据](docs/verification/LEARNING_IMAGE_WAIT_EARLY_EXIT_20261007.md)及[发布缺口清单](docs/verification/LEARNING_PREVIEW_RELEASE_READINESS_20261007.md)。以下是此前时点记录，当前策略及顺序以本节为准。 / See the evidence and readiness reports; entries below retain earlier states.

精简的 Agent/API 执行依赖包含 NumPy 和 OpenCV，用于确定性的图像匹配，不要求本地模型权重或 Qt。包检查会实际运行参考 PNG 匹配、共同编译与恢复消费；学习 EXE 的 `--check-image-feature REPORT.json` 使用临时合成库离屏验证图像预览、修改保存重开和关闭选项持久化，不连接宿主或派发输入。 / The lightweight Agent/API environment includes NumPy/OpenCV for deterministic matching, without local model weights or Qt. Dependency checks exercise PNG matching, compilation and recovery. The learning EXE's offline image-feature check uses a temporary synthetic library without a host or real input.

## 2026-10-07 图像核验流程与耗时验证 / Image-check flow and timing evidence

同一源码窗口/连接完成三对两步流程：图像与逐步 Agent 审核均 3/3 completed，中位完整流程为 9.884 秒与 29.778 秒，本轮耗时下降 66.8%。图像路线已记录的两步核验阶段合计约 29 ms，不能把完整流程称为图像匹配耗时。未跳转负例只有一次点击，保留原请求后由 Agent 判失败，未重复输入；Main 218 项相关回归及独立 Sol 证据审阅完成，正常清理有原件。 / Three paired source runs per route completed; full-flow medians were 9.884 s and 29.778 s. Recorded local verification totaled about 29 ms per two-step run. A blocked transition retained its original request for Agent failure review without input replay; Main regression and independent evidence audit completed with normal cleanup.

仅是自有合成窗口小样本，不能宣称准确率提高、总模型调用/token 节约或每次运行保证；两路线都复用相同定位，完整安装版及外部软件效果未测。尚未打包/发布，正式 v0.1.1 不变。详见 [本轮流程与性能报告](docs/verification/LEARNING_IMAGE_FLOW_PERFORMANCE_20261007.md)。 / Limited owned-app evidence does not establish improved accuracy, full model/token savings, or general reliability. Both routes reuse the same locator; installer/external-app effects remain untested. No packaging or publication; stable v0.1.1 unchanged.


瓶颈追查：本例每次点击后仍有固定 2000 ms 渲染等待，两步约四秒；另有约 4.248 秒端到端余量尚未分类。优化顺序是有界状态观察及成功早退出，然后补全计时；本轮未改等待策略。 / Bottleneck trace shows a fixed 2000 ms post-action grace per click and about 4.248 s unclassified wall time. Priorities are bounded state checks with early completion and full timing; wait policy is unchanged.

## 2026-10-07 默认图像核验与 Agent 审核 / Default image checks with Agent review

学习工作流维护源码已加入默认图像规则提议、人工区域编辑和不确定时的 Agent 审核。新学习仅对有判别证据的跳转提议规则，草稿仍待审核；用户关闭后保存重开不会补回。当前安装预览尚未更新，也未发布或改版本。说明见 [图像核验](docs/LEARNING_IMAGE_VERIFICATION.md)。 / Maintained learning source now proposes image checks by default for distinguishable transitions, supports manual region editing and retains Agent review when inconclusive. Draft review and persistent disablement remain; installed previews are unchanged and unpublished. See the linked guide.



## 同步前可选学习小节 / Optional preview section before final sync

## 可选学习工作台测试版 / Optional learning preview

学习模式是可选组件，执行模式可以独立安装和使用。学习工作台 **0.1.0-preview.1** 与兼容执行组件 **0.1.2-preview.1** 分别交付；正式执行版 `v0.1.1` 保持原发布状态。 / Learning is optional and execution works independently. The preview components are delivered separately; stable execution v0.1.1 retains its published status.

本页描述该版本的安装、使用与限定验收；[发行入口](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/learning-v0.1.0-preview.1)。 / This page describes this version's installation, use and bounded acceptance; [release entry](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/learning-v0.1.0-preview.1). Main 与独立 Sol 已在同一冻结独立安装版完成限定新内容连续验收和正常清理，Main已复核原件。新安装版接替旧便携包；旧包不交付，其未知退出保留为历史未解决问题，不宣称修复。 / Main and independent Sol passed bounded fresh continuous acceptance and cleanup on the same installed pair, with Main reviewing originals. The installers replace the old portable package; its unexplained exit remains historical and unresolved.

| 安装组合 / Installation | 用途 / Use |
|---|---|
| 仅执行组件 / Execution only | 正常执行任务，可选 API、当前 Agent、视觉委派或本地模型 / Execute through a configured API, current Agent, visual delegate or optional local model |
| 仅学习工作台 / Learning only | 离线打开、审核、修改、保存和重开学习库，无需执行宿主或模型 / Manage the library offline without a host or model |
| 两组件 / Both components | 明确选择执行安装及已有会话，采集教学与试运行审核后的工作流 / Explicitly attach for teaching and reviewed workflow trials |

工作台支持“设置 → 语言 → 简体中文 / English”。数据根目录位于安装目录外；重开时选择原数据根，不要选择其中的 `memory-library` 子目录。 / Settings supports both locales. Store data outside the installation; reopen the original data root rather than its memory-library subfolder.

当前验证使用 `learned`：填写由学到的 UIA 规则解析，读取使用 `agent_read`，结果由 Agent judgment 审核。`steps_only` 是可选策略，仍需 Agent 当前定位；不承诺减少模型调用、费用或提升准确率、速度。 / Current validation uses learned UIA input rules, agent_read and Agent judgment. Steps-only remains an optional strategy requiring current Agent grounding; no model-call, cost, accuracy or speed benefit is claimed. 普通重开后需明确连接并继续；不保证自动跨宿主恢复。 / Reopening requires explicit attachment and continuation; automatic cross-host recovery is not guaranteed.

2026-10-07 的六对受控先导中，界面结果 A/C 均6/6正确；原采集首轮完成为A6/6、C5/6。四对无中断/恢复且采集完整的对照，中位逐对提速32.9%，其中固定场景仅2.9%；准确率提升、通用速度收益及每次运行稳定性仍未证明。当前六步含三个原生定位规则、两处 Agent 识图和四处 Agent 判断/读取，不能称为完全确定性复用。总调用/token未知，正式配额抵扣0；详见[收益先导报告](docs/verification/LEARNING_ACCURACY_SPEED_PILOT_20261007.md)。 / The controlled six-pair pilot has correct GUI outcomes A6/6,C6/6, but original collector first-attempt completion A6/6,C5/6. Four clean complete pairs show32.9% median paired time savings; the stable pair improves only2.9%. Accuracy improvement, general speed and every-run stability remain unproven. Three native target rules coexist with two visual groundings and four agent judgment/read steps; usage is unknown and formal quota credit is zero.

[测试版使用说明 / Preview guide](docs/LEARNING_PREVIEW_QUICKSTART.md) · [本轮验收与限制 / Acceptance and limits](docs/verification/LEARNING_PREVIEW_NATIVE_ACCEPTANCE.md) · [工作流接口 / Workflow interface](docs/WORKFLOW_EDITOR.md)。较早开发状态与首次失败保存在 [历史记录 / Development history](LEARNING_DEVELOPMENT_HISTORY.md)，不覆盖本段当前状态。

