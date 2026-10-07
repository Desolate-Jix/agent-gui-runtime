## 2026-10-07 可选学习与独立连接 / Optional learning and independent attachment

学习工作台是执行模式的可选组件。单独打开库进行审核、修改、保存和重开不要求执行宿主或模型；采集教学和运行工作流才需要明确连接兼容执行安装与既有会话。第一版两组件安装根可以不同，但数据根和确切库必须一致。 / Offline library management is independent; teaching/execution attach explicitly across installation roots with the same data/library identity.

在“任务步骤 → 运行”中先选择“执行模式安装目录”，再选择会话或“连接当前 Agent 会话”。连接只读取状态，安装描述、入口、协议能力、进程/会话及库身份仍须通过检查。冻结工作台缺少执行安装选择时保持离线；原请求未结算时不能切换连接目标，不会向新目标重发旧动作。关闭工作台不停止执行宿主。 / The Run tab selects the installation before a session; connection reads status only and preserves pending requests and host ownership.

源码中的“设置 → 语言”支持简体中文/English，独立记忆选择；切换保留选中项、未保存修改和待处理请求。只翻译应用标签/本地校验说明，不翻译用户内容、原日志或固定协议值。系统原生对话框文字跟随 Windows。 / Language switching preserves state and translates presentation only.

运行中的 read 准备绑定确切选中目标；普通 read 不自动激活其他窗口。明确等待或终态保持静止，不持续轮询；已经提交的原运行在 ready 过渡期间继续只读回读。未明确运行的 prepared-ready 不自动启动。关闭重开后需显式连接并 Continue 原运行，不保证自动跨宿主续跑。 / Execution read preparation binds the exact selected target; ordinary read does not automatically activate another window. Stable waits and terminal states stop polling; a submitted run's transitional ready state keeps read-only polling. Prepared-ready does not auto-run. Reopening requires explicit attachment and Continue, without guaranteed cross-host continuation.

本页描述该版本的安装、使用与限定验收；[发行入口](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/learning-v0.1.0-preview.1)。 / This page describes this version's installation, use and bounded acceptance; [release entry](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/learning-v0.1.0-preview.1).

### 可选启动诊断 / Optional startup diagnostics

正常启动适配 `scripts/start_learning_workbench.py`（以及使用该适配的工作台入口）可显式传入 `--startup-trace ABS_NEW_FILE`；默认关闭，不自动生成日志。路径必须是绝对路径，父目录须已存在；以独占新建方式写 UTF-8 JSONL，已存在的文件不会覆盖或续写。`--check-startup` 使用独立离屏报告分支，即使同时传入 `--startup-trace` 也不创建 trace 文件。 / Normal startup through `scripts/start_learning_workbench.py`, or a workbench entry using that adapter, optionally accepts `--startup-trace ABS_NEW_FILE`. Tracing is off by default. Use an absolute path with an existing parent directory; the UTF-8 JSONL file is created exclusively, never overwritten or appended. `--check-startup` takes the separate offscreen-report branch and does not create a trace file, even when the trace option is supplied.

日志 schema 为 `workbench_startup_trace.v1`，逐行记录 UTC 时间和顺序号，以及启动器、QApplication 就绪、目录选择/选择器前后、进入/返回工作台和最终退出码。Qt 观察边界包括顶层窗口 Show/Hide/Close、Quit 事件、`lastWindowClosed` 与 `aboutToQuit`；窗口字段仅有技术类型、objectName 和可见状态。目录记录只含“是否显式指定/是否选择”的布尔值，不记录目录值、窗口标题、截图、用户输入、库内容或原始异常正文。 / Each `workbench_startup_trace.v1` line carries a UTC timestamp and sequence number for launcher/application readiness, directory selection and picker boundaries, workbench entry/return, and final exit code. Qt observations include top-level Show/Hide/Close, Quit, `lastWindowClosed`, and `aboutToQuit`; window fields contain only technical type, objectName, and visibility. Directory fields are selection/explicit-option booleans, not directory values. The trace does not record window titles, screenshots, user input, library content, or raw exception text.

创建、写入或关闭日志失败会明确报告启动失败，不能静默当作成功。Qt 回调中的首个写入失败先保留，在下一同步边界或日志关闭时抛出；观察器不接受/拒绝 Close、不强制退出，也不改变原窗口与应用的关闭/退出策略。 / Trace creation, writing, or closing failures explicitly report startup failure. The first write failure in a Qt callback is retained and raised at the next synchronous boundary or trace close. The observer does not accept/reject Close, force an exit, or change window/application shutdown policy.

这只是补充故障证据的可选入口，不代表原首次启动自行退出已修复。保留原失败及其证据；获批新候选的启动日志和实际进程退出码仍须用于定位根因，原生 popup 截图效果也仍待验证。 / This optional evidence path does not establish that the original first-launch exit is fixed. Retain the original failure and evidence; diagnosis still requires an authorized new candidate's trace and actual process exit code. Native popup capture remains unverified.

以下同根 runtime 操作是历史候选说明。 / Same-root portable instructions below are historical.

## 历史 Windows 便携学习工作台候选 / Historical portable learning workbench candidate

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

当前依据：[试用核对](verification/LEARNING_TRIAL_READINESS.md)、[有限收尾计划](superpowers/plans/2026-10-03-learning-trial-closeout.md)。本地原证据：`.superpowers/sdd/2026-10-05-project-capture-route-correction/native-pages-closeout.json`、T25/T26原回执及`.superpowers/sdd/2026-10-05-learning-trial-delivery/s4-closeout.json`。下方此前“仍待/受阻/下一步”均为当时状态，不覆盖本段；首次失败原件保持。 / The linked review/plan and local closeout records are authoritative. Earlier pending/blocker/next-step wording below is historical and does not override this result; original failures remain preserved.

## 此前状态与开发记录 / Earlier state and development records

当前试用状态 / Current trial status: Main T25和同冻结Sol T26限定S3均通过；S4隔离真实入口/依赖与原生工作台启动检查已通过，本地源码候选可供检查/暂存；完整试用及对外交付仍待S1，S1实际桌面图因支持工具超时阻断；原生三主页导航、运行页和限定审核保存重开已有证据。普通Agent离屏审核不是真人；未发布，版本/UI v14不变，收益/API未测。当前结论见[试用核对](verification/LEARNING_TRIAL_READINESS.md)及[收尾计划](superpowers/plans/2026-10-03-learning-trial-closeout.md)。 / Main and same-freeze Sol pass bounded S3; isolated entrypoint/startup checks pass; external delivery awaits tool-blocked native desktop images; bounded native controls are evidenced. No human, benefit/API or publication claim.

Main通过Sky原生键盘及只读Qt焦点诊断，用普通“运行工作流”按钮Space打开运行页，未连接且执行按钮禁用；在T25学习库隔离副本中将step-1审核状态reviewed→pending，以普通保存按钮Space保存v4，正常重开仍为4步/3已审核/1待审核。旧3版本及其余原件、T25原735文件和901源码冻结不变，三窗正常exit 0/PID-HWND消失；首次Return无效果保留。无pointer/text输入、宿主连接或产品修改，不计真人或所有编辑类型验收。实际桌面图仍缺，S1/完整试用仍未通过。证据：`.superpowers/sdd/2026-10-05-native-focus-observation/native-controls-closeout.json`。 / Main uses Sky native keyboard input and read-only Qt focus diagnostics to open the run page with Space on the ordinary button; disconnected execution remains disabled. In an isolated copy of T25 learning content, step-1 review changes from reviewed to pending, the ordinary save button saves v4, and normal reopen retains four steps with three reviewed and one pending. Old versions, other originals, all 735 T25 files and the 901-source freeze stay unchanged; three windows exit 0 with PID/HWND absent. Preserve the ineffective first Return. No pointer/text input, host connection or product change; this covers neither human review nor all edit types. Actual desktop images remain missing, so S1/full trial acceptance is incomplete.

本地源码候选（未发布，非exe） / Local source candidate (unpublished, not exe): `.superpowers/sdd/2026-10-05-learning-trial-delivery/agent-gui-learning-trial-source`；公开验收与S1限制见[试用核对](verification/LEARNING_TRIAL_READINESS.md)。

当前操作语义 / Current semantics: 工作流逐步“审核状态”可明确修改；独立界面库查看、修改、保存生成版本，没有普通单独审核按钮。pending 可试运行，未保存修改和缺本次 run 输出分别阻断。 / Workflow review is explicit per step; standalone content supports inspection, edits and versioned saving without a separate review button. Pending trials are allowed; dirty definitions and missing current-run outputs block separately.

T9 已验证：用普通控件同步修改已有规则与动作目标，保存后重新待审、Agent 审核、重开，再换本次输入执行。独立界面返回确切版本的语义提示，不返回历史框；Agent 读取后仍需新截图定位并走原动作门禁。另建恢复运行会从空输出开始，不能把原失败记成成功。 / T9 verifies ordinary rule/goal edits, pending save, Agent review, reopen and changed-input execution. Standalone content returns pinned semantic hints without stored boxes; the Agent must ground a fresh observation through the existing action gate. A distinct recovery run starts with empty outputs and does not rewrite a failed run.

T10 独立复测的两次换数据四步任务完成，但重复运行被 Agent 读图误判为失败；原失败不改写，独立界面未跑。Main 查看原 PNG 未证实产品截图故障，T11 全新数据限定独立复测现已由 Main 核验通过（规则复用、独立界面语义提示与正常清理）。 / Two changed-data four-step T10 tasks complete, but an Agent misreads the repeat observation and submits failure. That failure remains unchanged; standalone reuse was not run. Main's original-PNG inspection does not establish a product capture fault; Main now verifies T11's fresh-data bounded pass for edited-rule reuse, standalone semantic hints and normal cleanup.

[试用核对 / Trial review](verification/LEARNING_TRIAL_READINESS.md)

## 2026-10-03 T7历史独立限定旅程 / Historical T7 independent bounded journey

T7独立限定旅程经Main核验 PASS_WITH_RECORDED_CALLER_FAILURES：全新四步教学、普通Qt参数/ensure_selected语义修改pending、Agent审核四步、三版保存重开，以及V56/V56重复/W90三轮completed、编辑态零输入拒绝和正常清理均通过；884冻结文件一致，human_review=false。 / Main verifies T7 independent bounded journey as PASS_WITH_RECORDED_CALLER_FAILURES: fresh four-step teaching, ordinary Qt parameter/ensure_selected semantic editing to pending, four-step Agent review, three-version save/reopen, three completed V56/V56-repeat/W90 runs, no-input editing refusal and normal cleanup; all 884 frozen files match, with human_review=false.

仅此独立场景通过，非真人、全产品、收益或发布验收。下一主线收拢普通入口、桌面/真人易用性与试用结果；更广已审核→语义修改失效传播实机覆盖及独立界面完整旅程仍待。收益unknown后置，正式v0.1.1/UI v14不变，不打包发布；499早于最后窄改，后续57窄测不累加。 / This is a bounded independent pass, not human/full-product/benefit/release acceptance. Next consolidate ordinary entry, desktop/human usability and trial results; broader live review invalidation after semantic editing and the complete standalone-interface journey remain open. Benefits stay unknown and deferred; stable v0.1.1/UI v14 are unchanged, with no packaging/publication. The 499 run precedes the last narrow edit; subsequent 57 checks are not added.

[Main原审计 / Main original audit](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-transfer-07-independent-selection/main-final-audit.json)

## 学习模式试用操作 / Learning-mode trial walkthrough（2026-10-03）

当前是源码候选的操作说明，工作台沿用已选 UI v14；独立正式版 v0.1.1 不变。Main T25与同冻结Sol T26限定连续实机已通过，保留首次失败；本轮项目通道已验证三个主页面与运行页实际画面及普通切换。下列按钮和操作来自维护源码；真人空库易用性及安装包入口尚未验收。本节不把 Agent 审核或离屏操作记为真人审核。

### 从学习到复用

1. **让 Agent 建立本轮执行连接并打开工作台。** 告诉 Agent 要学习的软件、任务与目标窗口。工作台使用同一个数据目录和原执行会话；它自己不会启动执行宿主或模型。首次空库时，可以先学习一个独立界面；需要连续任务时明确要求生成工作流。可以对 Agent 说：“学习这个窗口中选择目标、打开、读取当前内容并返回的流程；完成后打开草稿供我检查。”
2. **完成一次真实教学。** Agent 记录本次动作、原截图和实际结果。学习停止并且记录完整后，在“任务步骤”点“刷新最近学习”，再点“打开学习草稿”。动作已经结束但记录仍待结算时，让 Agent 回读原结果、恢复记录；不要再执行一遍动作来补记录。
3. **逐步检查动作和跳转。** 在步骤列表选中一步，查看“动作与分支”“条件与输出”“结果与读取”和“目标规则”。核对单击、双击、读取、填写等语义，以及成功、失败、不确定后去哪里。列表上移、下移不会自动创建跳转；没有分支的地方会暂停。截图中的框用于定位规则的编辑和预览，外部应用动作从运行入口发出。
4. **把变化的内容设为本次输入或当前读值。** 在“工作流输入”添加需要每次填写的参数，例如目标名称 `folder_name`，再把对应目标规则的名称约束绑定到这个输入。填写动作的固定文本可以用“改为每次输入”。需要从页面取得的值，在“结果与读取”指定本步读值，再让后续步骤引用这个文本输出；每轮读取本轮当前页面，不把教学时的值固定为下次结果。
5. **选择合适的点击语义。** 列表行的选择步骤可显式设为“确保选中该行”，前提是当前规则能唯一证明受支持的原生行及其状态。已选且不处于编辑状态时可零输入完成；未选中时重新验证并实际选择；编辑中或状态未知时拒绝。其他按钮、普通点击和双击继续按它们本身的语义执行，不自动猜测跳过。
6. **保存、审核，再保存。** 点“保存任务步骤”保存语义修改，受影响步骤会重新变为“待审核”。确认实际目标、动作、分支与结果规则后，将相应步骤设为“已审核”并再次保存。这个标记表示这次审核已保存；本轮实测是 Agent 审核，真人是否已审核须按实际操作者记录。旧版本保留，已有运行仍引用开始时的确切版本。可以关闭并重开工作台核对保存结果。
7. **连接原会话并试运行。** 点“运行工作流”，进入“运行”页后点“连接会话”。同一数据目录有最近会话时可直接连接；否则用“选择文件夹”选择已有会话。对于 Agent 识图路线，只在实际具备截图处理能力时勾选相应能力声明。先填本次参数并“运行单步”，确认结果后再“连续运行至等待”。等待需要判断或读取时，由原 Agent 看本次新截图并提交当前结果，再“刷新状态”“继续原运行”；不要另起一个运行替代还没结算的运行。
8. **看本次结果并完成收尾。** 查看运行页的当前步骤、等待原因、本次步骤结果和输出。“输入已派发”和“任务通过”分开显示。宿主中断或输入结果未明确时，用“核对已保存结果”和原 Agent 的恢复入口核验；先保留原请求，不能把未知当作未输入重发。工作台关闭只结束编辑窗口；任务终态、待处理请求和执行宿主的正常停止由原会话完成。

中断后先让原 Agent 用同一恢复请求完成新 epoch 准入，再连接恢复后的会话。在接管区选择“原任务”和“恢复方式”，点“核对当前效果”；核对后明确点“提交接管（保持暂停）”，再按需点“继续原运行”。未知输入保持暂停，不重发；执行宿主的正常收尾仍由原 Agent 完成。 / After interruption, have the original Agent complete new-epoch admission through the same recovery request before connecting the recovered session. Select **原任务** and **恢复方式**, click **核对当前效果**, explicitly click **提交接管（保持暂停）** after inspection, then **继续原运行** when appropriate. Unknown input stays paused without replay; the original Agent still owns normal host cleanup.

### 本轮支持范围与限制

| 项目 | 当前结论 |
| --- | --- |
| 第三方原生应用 | Main T25已在全新7-Zip场景完成教学、编辑、三轮复用、限定恢复、About和清理；同冻结Sol T26独立复测已通过，保留调用方失败。不能推广为所有软件均已验收。 |
| 视觉与模型 | 可沿用现有当前 Agent、客户端委派、外部视觉 API 或本地模型配置；本地模型是可选项。T25/T26本轮使用当前 Agent 识图与读原图，其他路由没有在本轮重新实测；不以接口存在推定识别准确率。 |
| 变化与重复使用 | T25/T26已验证更换目标、当次读值和已满足选择零输入；双击打开、读取和返回仍使用本次新截图与 Agent 判断。 |
| 异常与恢复 | Main T25与Sol T26已验证一次宿主中断、原回执结算、明确暂停接管/继续及About弹窗和正常收尾。任意应用重启、任意输入中途崩溃和所有弹窗组合尚未证明。 |
| 普通用户入口 | 现有源码工作台有任务步骤、流程项目、独立界面库和运行页；尚未交付新的学习模式安装包，也没有完成真人空库旅程验收。 |
| 减少模型使用 | 完整调用总量与 token 覆盖仍未知；已选状态少一次输入不等于整个任务少一次模型调用。 |
| 提高准确率 | 限定任务完成和预期拒绝已有证据，准确率改善尚未证明。 |
| 加快速度 | 正式速度收益尚未证明，不能用零输入选择或局部耗时代表完整任务收益。 |

当前源码入口使用项目已配置的 Python 环境：
```powershell
python scripts/run_learning_memory_workbench.py --data-dir "<本轮数据目录>" --session-dir "<原执行会话目录>"
```
首次学习和运行连接仍由原 Agent 会话建立；这里只打开库和工作台。没有执行会话时仍可编辑已有内容。试用交付、隔离依赖验证与发布按主线计划分别完成。

### English walkthrough and scope

This is a source-candidate guide for the accepted v14 workbench. Stable v0.1.1 is unchanged. Main T25 and same-freeze Sol T26 pass bounded continuous journeys with original failures retained. Main verifies all three ordinary pages and the run page through project desktop captures/actions. Human empty-state usability and an installed learning entrypoint remain open. Agent/offscreen review is not human acceptance.

1. Ask the Agent to establish the current execution connection, identify the task/window and open the workbench with the same data directory and original session. The editor starts no host or model. Standalone interface learning remains separate; explicitly request a workflow for a sequential task.
2. Complete fresh teaching. After stopping with complete recording, use **刷新最近学习** and **打开学习草稿**. If recording is pending after an action ends, recover the original receipt only; do not repeat the input.
3. Inspect each step's action, success/failure/uncertain branches, conditions, current outputs and target recipe. Reordering the list creates no edges. Screenshot boxes edit/preview targeting; execution comes from the run entry.
4. Add per-run parameters under **工作流输入**, bind target-name constraints to them, and use **改为每次输入** for variable fill text. Bind later steps to this run's freshly read text output.
5. Explicit **确保选中该行** is limited to supported uniquely proven native rows: selected/non-editing may finish without input, unselected requires revalidated selection, and editing/unknown state is rejected. Ordinary clicks and double-clicks retain their semantics.
6. Save semantic edits, inspect the affected pending steps, explicitly review them and save again. Preserve the actual review actor and immutable old versions; reopening checks persistence.
7. Open **运行工作流**, connect the original session, declare actual Agent vision capabilities when required, enter current parameters and start with **运行单步** before **连续运行至等待**. Fresh visual/read judgments come from the original Agent. Refresh and continue the original current wait instead of starting a replacement run.
8. Inspect current step verdicts, waits and outputs. Dispatched input is separate from success. Use **核对已保存结果** and original-session recovery for interruption or unresolved input; unknown outcomes are never replayed. Closing the editor does not stop the execution host.

Current evidence covers Main's fresh 7-Zip navigation/read journey, changed targets, repeated selection without input, editing refusal and normal cleanup. T25/T26 pass changed/repeated inputs, one host interruption with explicit recovery, About and normal cleanup; human/full-product/benefit/release acceptance remains open. Current-Agent vision was used; existing API/local/delegated configurations are optional but not revalidated in this round, and local weights are not mandatory. Broader restart/dialog guarantees, human usability and executable packaging remain open; the local source candidate passes isolated entry/dependency/startup checks. Complete model-call/token reduction, accuracy improvement and formal task-speed improvement are not established.

The source entry above requires the project's configured Python environment. It opens the library/editor; original Agent setup provides the execution session. Packaging, isolated dependency closure and publication are separate plan stages.

---

## 2026-10-01 中断事实修复 / Durable interruption facts

死宿主重开/刷新显示已保存状态与未决输入提示，执行/继续/取消仍禁用，保留原 run/wait/EID，不重发、不自动结算。此轮未新增程序字段或弹窗编辑能力。/ Dead-host reopening explicitly displays saved state and unresolved input, retaining original IDs and disabled action controls. No dialog scope/editor field is added.

详见 [WORKFLOW_INTERRUPTION_CONTRACT.md](WORKFLOW_INTERRUPTION_CONTRACT.md)。/ See the interruption contract.

## 2026-10-01 普通目标规则修改验收 / Ordinary target-rule edit acceptance

普通工作台完成目标规则收紧、应用、保存和重开：保留 `contains input record_id`，增加同一行文字的 `contains constant " · Record"`；仅 step-3 重新待审，其余步骤保持。旧程序、旧规则和旧 ready trial 在编辑期间逐字节不变，旧 trial 随后取消且无步骤输入。两个不同编号/布局的新运行各完整六步通过，并使用各自当前详情；12 个原 EID、26 个核心图像引用及原门控回执核对通过，宿主和窗口清理成功。 / Ordinary controls verify target-rule tightening, save/reopen, scoped review invalidation and immutable old pins. Two new six-step runs succeed with their current details; original receipts, images and cleanup are verified.

审核标记为测试失效传播而设置，`human_review=false`、`formal_C=false`；新目标仍待审。本批不是人工正式审核、公平收益或完整恢复验收。每轮五个输入命中规则，但仍有四个 Agent 读取/结果判断；总模型调用和 token 未知。原场景间有复位，不冒充无复位的连续状态累积。 / QA review markers do not establish reviewed C or benefits. Scenario resets limit continuity evidence; total model usage remains unknown.
新增条件的预览样例用归档学习截图中的 R-599，仅参与预览；真实运行输入分别 R-731、R-284，样例不作为固定参数保存。step-4 没有 step-3 输出依赖，step-5 仅引用 step-4，因此此目标修订不能伪造对 4/5 的审核失效传播。 / Archived preview values are not saved as runtime parameters. Actual dependency structure determines review invalidation.

`WorkflowRunClient` 现分离只读 attachment 核验与派发前 live gate。宿主实际退出后，新客户端及新开的普通 main 可读取本轮原结果、输出和回执，执行/继续/取消按钮禁用，账本与命令字节未变。活宿主仍完整验证 PID、创建时间及 runner；`control`、原回执绑定和动作门控保持原实现。 / Validated read-only attachment now works after the original host exits; dispatch still requires the original live identity and gate. Ordinary reopening preserves the ledger and disables action controls.

这只证明退出后的只读重连，不是原宿主进程重启续跑。活动 workflow 切换独立顶层弹窗仍不支持：admit 只放行原 ticket 的确切 EID/command，不能放宽竞争 select 代替窗口迁移合同。死宿主的原 worker 仍不能从磁盘自动恢复，未知结果不能当作未输入而重放。 / Read-only reconnection does not restore a dead worker or permit competing window selection; active dialogs and process restart remain open.
验证：目标编辑预检 31 passed；Main 合并检查 93 passed；只读恢复相关 worker 回归 250 passed。集合重叠，不相加。只读修复首次红阶段 5 failed / 41 passed 保留；实际输入首次完成两轮。审计先把 runner 投影误当原 trial、随后构造器参数写错，两个失败报告保留；改为原 public runner.status 全量核对后通过，未重放输入。 / Overlapping checks are reported separately. First failures remain retained; audit repairs required no input replay.

证据 / Evidence：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-target-rule-edit-01/main-live-audit-final.json`、`live-01/dead-host-reopened.json`、`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-recovery-boundary-01/main-integrated.xml`。未改版本、打包、发布或替换安装候选。 / No version, build, publication or installed-candidate replacement.

## 2026-10-01 学习运行的识图声明 / Vision declaration in learning runs

普通工作台连接 `agent_current` 会话后可勾选“此会话的 Agent 能接收并识别截图”；`agent_delegate` 显示客户端指定视觉子 Agent、转交截图并取得结果的声明。只在实际具备能力时声明，不根据模型名称推断。默认未勾选=未知；local/API 不显示此项也不发送能力字段。该选择不是动作授权。 / Declare actual client/Agent image capabilities explicitly. Default is unknown; local/API routes do not use this option. A capability declaration is not action authorization.

声明在明确启动时固定到原 run，自动 start 接续也使用同一份；换会话/来源清空，运行和等待期间禁改。继续原运行或恢复原回执不把当前 UI 选择重新套到旧票据。MCP 调用方仍可通过原 `request.vision_capabilities` 显式声明，没有新增 API。 / Explicit starts pin the declaration; continuation and recovery preserve the original request. The existing MCP field remains unchanged.

学习目标规则未命中后，已声明能力的原请求可进入当前截图识图等待。不存在目标回交 `grounding.v1` 的 absent；重复候选回交 ambiguous、至少两个当次图候选且不选择。没有选择时不得要求继续点击或新建替代输入。原 worker 以 request_absent/request_ambiguous 失败终止属于预期拒绝；仍核对原 run/EID、实际输入状态和清理。 / Non-target facts stop the original worker without selected input; inspect original identities and cleanup rather than replaying a replacement action.

本批 Main 已按原图验证两个实机反例；首次普通入口缺少声明导致 capability_unknown 的记录保留。此结论不证明模型准确率或学习收益，也不关闭活动工作流弹窗与宿主重连验收。

最新普通编辑与真实运行检查已通过；低风险实机测试已获批准，下方待确认/未执行段为历史快照。范围和剩余项以[最新验收记录](verification/LEARNING_WORKFLOW_BENEFIT.md)及本文件的“普通编辑与实机续接”段为准。 / Current authorized checks supersede historical pending-approval notes; see the latest scoped evidence and remaining work.

## 2026-10-01 定义审核概览 / Definition review overview

任务步骤页顶部显示载入定义的已审核/待审核数量、点击或填写步骤中的定位规则、结果规则及明确指定的 Agent 判断。已保存版本与未保存草稿分开标注；编辑中的审核选择只有保存后才进入已保存概览。语义修改保存后，受影响步骤继续按原规则重新待审。切换、空项目、加载与读取失败不沿用旧计数。

The workbench summarizes the loaded definition, distinguishes saved versions from unsaved edits, and updates persisted review counts only after save. Semantic edits retain existing invalidation behavior; loading, failure and project changes do not reuse stale counts.

该概览只描述定义，本次定位、核验和已记录用量在运行页查看；不会自动审核步骤或增加试运行门槛。详见[定义与运行证据](WORKFLOW_DEFINITION_AND_RUN_EVIDENCE.md)。新增检查先 3 failed，相关离屏回归 51 passed；最终合并源码/合同回归 774 passed（包含此前切片，不能加总）。全新合成内容的实际 main 截图已核对，未派发物理输入。 / This descriptive view changes neither review nor action authority. Fresh offscreen main-window evidence is checked; the combined 774 checks overlap earlier slices and are not physical acceptance.

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

## 2026-09-30 审核等待时钟 / Verification wait clocks

`WorkflowRunner` 持久化每个原执行请求的审核等待起点及关闭记录；与可重复的 wait/continue 状态分离，完成审核或取消只关闭一次。进程时钟身份变化时保留 `clock_changed`，不混用时钟或重放命令。`workflow_metrics` 核对原 run/step/request、命令摘要和回执后，将有效区间投影为 `phase=wait`、`source=workflow_verification_wait`；`verification_waits` 分别报告 measured/unmeasured/pending 数量。 / Persist wait clocks independently from controls and project validated original-ticket evidence into wait events; process changes preserve explicit missing duration.

计时包含等待审核及继续/结算延迟，不是推理时长；原生核验、视觉交接和未知模型总量仍分开。135 项相关检查通过，目录符号链接能力用例跳过 1 项；详见 `docs/verification/LEARNING_WORKFLOW_BENEFIT.md` 的本轮记录。源码已更新，尚未在新实机候选验收；历史 R1b 记录不回填。 / Wait time is separate from inference and unavailable total usage. Focused checks pass, with one platform capability skip; new physical candidate acceptance is pending.

### R1c 变化预览与源码预检 / Variation preview and source preflight

后续两轮限定自建 Record Desk：相同已保存程序分别查询 R-731、R-284，使用同名记录、不同次序及 detail_above_rows / search_below_rows 布局和新详情。两场景已冻结并逐张核对实际截图；执行前仍须重新定位。只调用 select/capture，预览宿主和窗口已清理，用户确认待答复。首次预览因采集器只读白名单不含 select 而未派发；修正预览调用配置后复用原冻结数据成功，不重抽场景。 / Two exact variation previews are frozen and inspected without desktop input; approval is pending and preview resources are stopped. The initial select-admission failure remains recorded, with the same cases retained.

`r2-r3-source-preflight.xml`：动态目标、程序依赖、宿主变量绑定、普通上游输出入口、取消结算、运行页恢复和无名列表共 43 passed。仅源码/隔离及离屏检查，不能替代 R1c/R2/R3 实机通过。证据根目录 / Evidence root: `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20260930-learning-variation-02`。 / All 43 scoped checks pass; physical variation, recovery and benefit gates remain open.

## 2026-09-30 完整教学与换编号复用通过 / Full teaching and new-ID reuse passed

R1b 在同一全新 Record Desk 窗口和原 MCP 宿主内完成六步教学：查询 R-599 → 唯一行 → 打开详情 → 读取当次 Detail → 填写 → Verify value。普通工作台用真实控件修改上游输出绑定和动态行规则，保存新版本、关闭重开，再以 R-953 连续运行六步；新详情 `detail-73178a74a55a` 替换旧详情 `detail-a52e0dfef4be`，字段 UIA 核验及窗口 Matches current detail 均成功。 / R1b completes six-step teaching, ordinary editor changes, immutable save/reopen and same-session six-step reuse with a new record and fresh downstream detail.

五个复用输入动作全部命中当前学习规则：四个 memory_uia、一个 memory_visible_row；视觉定位交接 0。读取步骤由当前 Agent 查看原截图后回交本次输出，Find/Open/Verify 三个结果使用已声明的 Agent 判断，原运行通过工作台“继续原运行”按钮续接。不是完全无需 Agent 的规则链；未观测的总模型调用和 token 继续为未知，也没有公平对照的提速或准确率收益结论。 / All five input targets resolve from current learned rules without vision-grounding handoffs. One current-agent read and three declared agent result judgments remain; total calls/tokens and comparative benefit are unproven.

工作台驱动为实际 main 的离屏控件，目标窗口输入是真实 gated 输入。原始回执审计验证六个步骤、当次输出、当前候选和固定窗口身份、旧/新程序版本可加载、无输入重放及完整清理；宿主 exec 13540、工作台 exec 89403 退出 0，fixture 退出 0。最初先停止学习再审核使整理读到旧图，返回 needs_review；审核后通过原 learning_stop 提交新图后整理成功，没有重放输入。审计脚本首次误把 input_check 当作 steps 中一项；核对真实回执后改为检查独立 input_check 及值哈希，复核通过。 / Receipt and version audits plus cleanup pass. Preserve the pre-review synthesis response and initial audit-schema mistake separately; neither caused input replay.

证据 / Evidence: `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20260930-learning-full-task-02/live-task-01/full-task-audit.json`、原回执、workbench-saved-program.json、reuse-completed.json、截图与 cleanup.json。本轮沿用已通过 41 项检查的源码，四个文件哈希复核一致；未改产品源码、版本或发布包。 / This physical run uses the previously checked source, with four source hashes unchanged; no product code or release changes occurred.

R1b 主链已通过；R1c 的重新排序/状态变化集合、R2–R3 异常与编辑失效、R4 冻结配对计分、R5 按瓶颈优化、R6 外部应用迁移及同候选独立验收仍未完成。本轮两次完整流程授权已执行完毕，新增真实输入须给出新的确切预览；源码与离屏检查继续推进。 / R1c and R2–R6 remain open, including measured benefits and independent acceptance. The approved two flows are consumed; further physical inputs need their own exact preview while source/offscreen work can continue.

## 无名列表与变化的控件 ID / Unnamed lists and changing control IDs

“目标规则”现在可选择没有名称、但有非空自动化 ID 的列表容器，容器仍须唯一。行内控件 ID 若含记录编号，在选择“当前可见唯一行”后，可取消“限定所选属性的固定 ID”及“限定所选动作的固定 ID”，再指定任务输入或上游输出作为行条件，填写样例并预览。取消属性 ID 后每行必须恰有一个可读 Text；取消动作 ID 后按行内名称和类型查找，仍须唯一。多属性或多动作时保留准确 ID 或修正规则，不能跳过歧义。 / An unnamed container can be selected by its nonempty automation ID. Explicitly clear the child-ID checkboxes when IDs vary by record, bind the row condition, and preview. Each row must still have one readable property and one matching action; ambiguity is refused.

已有规则保留原 ID；修改、应用及保存生成新版本，重开不会把预览样例保存为运行参数。41 项源码检查及真实 UIA 只读回放通过；完整物理任务仍待确认和验收。R1a 同窗口学习、保存重开、参数复用已完成，不能替代完整动态任务或收益指标。 / Existing IDs remain until explicitly edited. Save creates a new revision; preview samples are not persisted as runtime inputs. Source and read-only checks do not replace pending full-task acceptance.

# 可编辑工作流与局部试运行 / Editable workflows and local trials

## 2026-09-29 已授权两次填写与恢复边界 / Authorized fills and recovery limits

用户已明确确认原预览中的两次填写。原 `teach-fill` 成功写入“学习样本甲”，保留实际前后截图并生成带 `value` 参数、UIA 目标和 `field_equals` 规则的草稿；普通工作台已修改标题、保存、重开。重开测试窗口后，工作流原请求 `trial-exec-267b8898992184a9b30bb8b9685e6771` 成功写入“复用样本乙”。两次均只执行 focus/type/check_input，没有 Enter 或提交。第二次目标记忆命中，未产生视觉定位交接或外部识图调用；模型调用总量与 token 仍未知。 / Both approved fills occurred once. The second used the learned target and current parameter without a vision-grounding request; total model usage remains unknown.

第二次原运行 `trial-df4b4f2855053b039f06cb0d23c37de2a9a1d807cec90075a6265e930cec2526` 经原 wait_id 继续后，由本次 UIA 实值核验为 success/completed；只读重开工作台没有新增命令，所有自建宿主及测试窗口清理通过。 / The original run was reconciled using its original wait and a fresh UIA field value, without input replay; owned resources were cleaned.

**范围未闭合：** 首次查询脚本误用了 `learning_session_id`（事件查询应为 `learning_id`），导致原窗口提前清理；因此这是重开后的复用，第二次输入前新窗口字段为空，不能算“同一窗口由甲替换成乙”的连续通过。后续还需手动 MCP 恢复，R1a 普通用户无干预链与同窗口连续性仍待复验，R1b/R1c 及 R2–R6 未完成；没有提速或准确率提升结论。 / Reopened reuse is verified; same-window continuity, hands-off normal UI recovery and full benefit acceptance remain open.

本轮修复合法目标记忆被缺省视觉能力挡住、无 result 失败回执不能结算、记忆库短事务抢锁和同步恢复后旧错误提示残留。主 Agent 源码回归 157 passed，加宿主报告/客户端回归 55 passed（有重叠，不能相加为唯一用例数）。锁和报告修复没有热加载到已运行宿主；现场完成截图仍保留旧错误提示，不能把源码通过写成新候选实机通过。 / Source fixes pass focused checks; the existing live host did not hot-load the final lock/report changes, and its stale visible error is preserved as evidence.

证据 / Evidence: `D:/AgentReviewAcceptance/20260929-learning-benefit-01/live-physical-learning-02/physical-checkpoint-verification.json`、`workbench-completed.json`、`recovery-cleanup-02.json`；首次失败及各次工作台产物分别保留。未打包、推送、改版本或调用付费模型 API。 / First failures remain separate; no release or paid-model test occurred.

普通参数化操作 / Guided parameter editing:

1. 打开学习草稿，选中填写步骤。固定文字需要每次变化时，点“改为每次输入”；名称已自动生成，也可在这里命名一次。 / Convert a literal into a declared run input with one action.
2. “工作流输入”可选择现有文本参数；“上游输出”可选择较早步骤声明的文本结果。失效引用保留为“不可用”，需要修正名称、类型或步骤顺序；不会自动换成列表第一项。 / Select an existing input or earlier text output; unavailable dependencies remain explicit.
3. 在“结果与读取”检查独立的成功条件。参数化只改变填写来源，不猜改其他步骤或结果规则中的固定值；需要随输入变化的预期值也应选择相应输入。 / Review outcome rules explicitly; parameterization does not guess unrelated dependencies.
4. 保存任务步骤后点“运行工作流”，连接原会话，选择单步或连续运行，在对话框填写本次值。文本、数字、是/否及必填状态明确显示；错误时保留已填内容，取消不会派发。 / Save, open the run page, connect and supply validated current values.
5. 运行页显示当前步骤及等待原因。缺少上游结果时说明来源步骤，应从来源步骤重新运行，或修改为本次输入后另存版本；旧运行结果不会自动补位。 / Resolve missing current outputs explicitly rather than borrowing from an older run.

“高级 · 局部试运行仅准备请求”保留给开发使用；准备出的 JSON 不是已执行结果。固定文字及运行文本保留原有前后空格。API/Agent 使用不要求本地模型。 / Advanced preparation remains distinct from execution, literal whitespace is preserved and local models remain optional.


**开发状态 / Development (2026-09-29):** 普通参数化、输入/前序文本输出选择、类型化运行对话框及实际 main 保存重开已接通；本批相关检查 128 passed，强化原队列旅程 2 passed（重叠）。原有运行恢复、同会话纠错和复合目标编辑保留。物理输入与完整收益待验；此前全套 2670/1 是本批 UI 修改前基线。 / See the [plan](superpowers/plans/2026-09-29-learning-workflow-benefit.md) for scoped evidence and remaining gates.

**状态 / Status:** 2026-09-27 的未发布源码；版本仍为 `v0.1.0-test.8`，未重新打包。步骤服务和原生页面已有源码、契约、离屏交互检查，以及新建原生表单的真实单项、三步连续变量传递、重开与清理记录；覆盖边界和首次失败见[验证记录](verification/2026-09-27-workflow-editor.md)。独立 API 没有付费供应商实测。 / Unreleased source as of 2026-09-27; versions and packages are unchanged. Checks cover contracts, offscreen UI, a fresh native single-operation and three-step dataflow journey, reopen and cleanup. See the linked verification record for retained failures and coverage limits. There is no paid-provider live API test.

## 在原生工作台编辑 / Edit in the native workbench

从源码运行 `scripts/run_learning_memory_workbench.py --data-dir <data-root>`。首个“任务步骤”页显示项目的步骤列表和同一份定义的关系页；原“流程项目”和“独立界面库”仍可使用。可修改标题、动作目标、输入绑定、成功／失败分支、有限条件、输出及人工审核状态；添加、移除或移动步骤不会暗中建立跳转。被引用的步骤须先修复引用再删除。保存后才有可试运行的固定程序版本。 / Run the source workbench with `--data-dir <data-root>`. Its first tab edits steps and shows branches from the same definition, while the graph and standalone interface library remain available. Reordering or adding steps creates no implicit edge. Repair references before deleting a referenced step; save to create a fixed program version before a trial.

“关系”保留关系表和同源程序图；排序不暗中补分支。“目标规则”支持固定控件或可见行的1–8条已有策略排序、增删，以及最多16个行条件；常量、本次输入和上游文本输出可绑定。预览只读原学习截图，样例不保存；未知策略原文保持，不降格。未应用修改仍阻止切步和保存。 / Edit supported ordered strategies and compound row conditions while preserving source evidence and unsupported rules.

提供同一数据目录下已有学习会话的 `--session-dir` 后，“刷新最近学习”只读最近学习段和整理结果；显示录制中、等待当前 Agent、记录不完整、内容需补充、草稿可审核或已有保存版本。草稿就绪时点“打开学习草稿”，在原步骤页修改并保存。刷新期间有未保存编辑则保留编辑；库不匹配或来源损坏会显示原因，不新建宿主、不自动重问模型。 / With an existing session in the same data root, refresh synthesis state and open a ready draft in the normal editor; reads preserve edits and never create hosts or model requests.

草稿在点击保存前不会生成正式程序版本。放弃修改恢复原载入版本，既有人工版本和原证据保持。最近学习入口只读状态；“运行”页单独核验现有宿主身份并显式提交控制，两者不能混作已完成真实输入验收。 / Draft editing and verified runtime attachment are distinct entrypoints; neither source test alone proves physical success.

若要准备局部试运行，另传 `--session-dir <existing-instant-session>`；没有会话连接时页面仅可编辑，不启动执行宿主。页面显示命令预览、实际试运行状态和取消入口。“准备单步试运行”只写入一个待执行票据，**不调用键鼠**。人工可审核步骤，但审核并非准备请求的强制门槛。 / Pass `--session-dir <existing-instant-session>` to prepare a local trial. Without a session the editor remains available and does not start a host. Preparation creates one pending ticket and preview, never desktop input. Human review is available but is not a mandatory gate for preparation.

独立界面、原始截图、观测图和旧版本仍保留。步骤程序引用确切项目快照；人工更改已观测步骤会标明编辑来源，不能覆盖原始证据。新修订和旧试运行彼此独立，项目或界面引用不会因编辑静默前移。 / Standalone interfaces, original screenshots, observed graphs and prior revisions remain intact. A program pins a project snapshot; editing an observed step records editorial provenance instead of rewriting its evidence. New revisions do not silently advance old references or inherit an old trial's result.

动作、条件、分支或变量声明发生语义变化时，受影响步骤重新标为待审核；确认新内容后可单独保存人工审核状态。阻塞状态和原因会落盘，重开或刷新后仍可读取。 / Semantic changes reset affected steps to pending review; a subsequent review-only save can mark them reviewed. Blocked status and reasons persist across reopening.

## 普通运行与重开恢复 / Normal execution and recovery

新捕获可包含当前窗口已验证的原生应用菜单，客户区控件在新图中的y相应变化；只使用当次capture绑定的目标和坐标，旧版本/旧截图坐标不能直接重放。 / New captures may include verified native application menus, shifting client-relative image positions. Use only the current capture-bound coordinates; never replay old screenshot positions.


新 epoch 必须先用同一 instant_recover_session 请求完成 recovery_admission.phase=ready、new_epoch_ready=true，才允许任何新命令入队。公共 InstantSession.submit 在原 ID 回读之后、原队列写入之前只读核对准入与当前会话/宿主/指针；未完成返回 state_rejected/recovery_admission_not_ready 和原请求的 next，绑定无效返回 recovery_admission_invalid。该检查不完成准入、不启动宿主、不重试；instant_status 的 ready 不替代此合同。 / Before new commands, the same recovery request must establish ready admission. Public submit checks the current record and bindings after original-ID reread and before enqueue, returning the original recovery request for incomplete admission. It performs no admission, host launch or retry; host status alone is insufficient.


**真实宿主连接与工作台重开 / Live host attachment and workbench recovery:** Windows 虚拟环境可能由启动器创建实际 Python 宿主，工作台会核对它的直接父进程、启动入口与本会话路径，不再要求两个 PID 相同。切换会话后旧输出和悬停明细立即清空；回执的运行 ID 不符会报错并保留原请求回读，不会将结果转移到其他运行。 / Verified launcher children are accepted; displayed data and control receipts retain the correct session/run identity.

本轮实际宿主 + main 离屏控件已完成两步只读保存、单步等待、关闭重开后继续及新一轮运行，原请求未重发且清理成功；71 项源码回归通过。只读任务不代表点击、填写、动态内容或收益验收完成。 / The read-only live journey and focused source regressions pass; physical and benefit acceptance remains open.


在“运行”页点击“连接会话”，未指定路径时读取同一数据目录中当前 Agent 的会话；也可选择现有会话。连接核对同库、latest 指针、PID/创建时间、宿主 ready 和配置，不启动新宿主或模型。保存后选择起点，输入本次参数，再选择单步或连续运行至等待。 / Connect to an existing session, save a pinned program, choose its start and inputs, then explicitly run.

当前输出显示实际值；缺少模型/usage 覆盖时显示总量未知。等待项提示回原 Agent 对话处理定位/判断；继续使用原 wait_id。修改会话路径会禁用旧连接上的执行按钮；恢复的 ready 运行固定原程序和起点。关闭工作台只停止本地观察，不结束原 MCP/宿主。 / Unknown metrics stay unknown; controls bind the selected connection and pinned start, and closing the editor does not own host cleanup.

提交前持久控制标记，重开按原 ID/命令/回执核对。start 已返回但尚未运行时，只恢复准备结果，用户明确选择运行后才继续；未知结果不换 ID 重发。已知队列未入队可明确显示，多个未决记录不猜顺序。该机制不是另一个执行账本，输入事实仍以原命令和原回执为准。 / Recovery preserves original admission and receipt facts without replay.

## `learning_workflow` 控制接口 / Control contract

使用原有 `instant_run`／`instant_submit`，命令形状为 `{"kind":"learning_workflow","request":{"action":"…",…}}`；每次外层调用使用新的 `request_id`，结果通过原 `instant_result` 查询。服务按动作严格校验字段，未列字段会被拒绝。实现见 [`workflow_control.py`](../app/learning_memory/workflow_control.py)。 / Use the existing Instant tools with `kind: learning_workflow`. Give each outer call a fresh request ID and read its result through `instant_result`. Requests reject unknown fields.

| `action` | 必填 `request` 字段 / Required request fields | 作用 / Effect |
| --- | --- | --- |
| `synthesis_prepare` | `learning_session_id` | 固定来源并返回 `synthesis_request`；已有程序不覆盖 / Prepare a source-bound request without overwriting programs |
| `synthesis_status` | `synthesis_id` | 恢复原请求或已生成草稿；查询不调用模型 / Read a resumable handoff or draft |
| `synthesis_complete` | `synthesis_id`, `source_sha256`, `parameter_bindings`, `annotations`；续接后另需 `resume_request_id` | 核对来源、轮次及预算，写待审草稿；不输入 / Validate a source/round-bound reply |
| `synthesis_resume` | `synthesis_id`, `source_sha256`, `after_reply_request_id`, `user_instruction` | 用户明确补充后续接原学习；幂等重放不补预算 / Resume after explicit user input |
| `compile` | learning_session_id；可选 parameter_bindings、annotations / optional | 只读返回 definition、unresolved_items、proposed_target_recipes；已有人工版本不覆盖 / Read-only draft and proposals preserve edited versions |
| `read` | `workflow_id`; 可选 `program_id` / optional `program_id` | 读取当前或指定固定步骤版本；未保存时返回 `program_id: null` 草稿 / Read latest or a pinned version; an unsaved draft has a null program ID |
| `save` | workflow_id、expected_sha256、definition；可选 target_recipes / optional | 仅传提议中的 recipe 对象列表；校验来源、动作和引用后保存不可变规则与程序；摘要过期拒绝，新推断仍 pending / Validate proposed recipes before saving a new revision; reject stale edits |
| `start` | `workflow_id`, `program_id`, `start_step_id`, `inputs` | 固定本次程序与起点，创建试运行；输入类型与必填项必须匹配 / Pin version and starting step for this trial; validate declared inputs |
| `prepare` | `run_id`; 可选 `observations`, `vision_capabilities` / optional | 检查前置条件并返回一个 `execution_request_id`、`suggested_command`；不派发 / Check preconditions and return one execution ticket and command; no dispatch |
| `run` | `run_id`, `mode`; 可选 `vision_capabilities` / optional | 活宿主按 `single` 或 `until_wait` 经原队列推进；先用 start 固定程序 / Advance a started trial through the live host's original queue |
| `continue` | `run_id`, `wait_id` | 继续确切等待项；不接受替换命令或旧输出 / Resume the exact wait without arbitrary commands or outputs |
| `status` | `run_id` | 回读当前步骤、待执行票据和历史 / Read current step, pending ticket and history |
| `review` | `run_id`, `execution_request_id`, `verdict`, `observations`, `outputs` | 核对原命令与终态回执后记账；`verdict` 为 `success`、`failure` 或 `uncertain` / Verify original command and terminal receipt before recording a verdict |
| `verify` | `run_id`, `execution_request_id` | 活宿主只读采集当前 UIA 结果，按已保存规则核验并记账；不重新输入、不让调用者提供成功证据 / The live host captures current evidence and records a deterministic result without input replay |
| `cancel` | `run_id` | 请求取消；若票据仍待执行，返回 `cancel_requested`，不宣称输入已撤销 / Request cancellation; pending input remains unresolved until checked |

`definition` 包含 `title`、带类型与必填标记的 `inputs`、`outputs` 以及 `steps`。步骤包含动作、前置与成功条件、输出、来源、人工审核状态和 `success`／`failure`／`uncertain` 分支。文本可绑定常量、工作流输入或**本次试运行中已验证的上游输出**；从中途开始且缺上游值会阻止准备，不读取旧运行补齐。条件仅接受 `exists`、`eq`、`not_eq`、`contains` 和由 Agent 提供布尔判断的 `agent_assertion`。缺观察值会阻止当前准备；`uncertain` 判定会暂停试运行，分支固定为空。当前拒绝循环分支，避免一次运行重复步骤并混用输出。 / A definition contains typed inputs, outputs and steps. Text bindings resolve constants, this trial's inputs or verified upstream outputs from this same trial. Missing values or observations block preparation. Conditions use the five finite operators above. An uncertain verdict pauses the trial with no uncertain branch, and cyclic branches are rejected.

## 当前 Agent 一次整理 / One synthesis pass in the current agent

完整 workflow 停止会返回 `synthesis`；`awaiting_agent` 中的 `synthesis_request` 固定事件、来源摘要和回复合同。当前 Agent 根据原图和经原回执核对的临时 input_examples 填写参数/注释，以同一整理身份回交。只有可编译步骤才请求整理；独立界面保持独立，未完成录制不冒充完成。无 Agent 回复时保持等待，状态查询不新建会话。 / The current agent consumes one persisted request; standalone/incomplete learning retains its original semantics.

成功为 `draft_ready`，仍需原 save 和审核；错误注释返回 `needs_correction` 的事件/字段，来源与存储故障直接报错。重复成功回复幂等，已有编辑版本保持。交接指标只覆盖本次请求/回复和编译时间，包含等待的交接墙钟不能等同模型耗时。普通工作台已提供状态和草稿审核入口，固定目标/多条件行编辑已有离屏覆盖，普通运行已接线，完整真实用户链仍待完成；证据见[验证记录](verification/LEARNING_WORKFLOW_BENEFIT.md)。 / Pending generation is separate from review. Normal draft controls exist, while native-host acceptance and the complete user journey remain unfinished.

纠错依据 conversation：initial_reply 初次回复，correct_once 允许一次修正；耗尽后 status=awaiting_user，工作台显示具体字段和等待补充。调用方收到真实用户补充后才用 synthesis_resume，后续 complete 带回 resume_request_id；重复查询、prepare、重开和重复续接都不补预算。历史缺顺序记录只读展示，不猜最后回复。来源损坏直接报错，已完成草稿也不能隐藏来源错误。 / Bounded correction and explicit resumption persist across reconnects without input replay.

## Agent 执行与回读 / Agent execution and review

`prepare` 返回的是建议命令，不是执行结果。Agent 应先核对当前窗口与目标，再以票据中的 **`execution_request_id` 作为原执行请求 ID**，将 `suggested_command` 交给既有 `instant_run` 路由；若返回 pending，沿原 ID 等待并读取终态，不重复派发。之后调用 `review`，服务核对落盘命令、真实终态回执、派发事实、条件和输出，再决定成功／失败分支。未知回执、仍在运行或未成功派发不能记为成功；失败和不确定结果不会自动重试。 / Preparation is advice, not execution. The Agent verifies the current target, submits the suggested command through the existing `instant_run` route under the ticket's execution request ID, then reads that exact receipt before `review`. Pending or unknown input is never replayed automatically. Review checks the saved command and terminal receipt; an unsuccessful dispatch cannot be marked successful.

动作由原执行器现场定位；步骤定义不保存旧点击坐标。`press_key` 当前缺少实时目标坐标时明确阻塞，不生成可执行命令。缺少可验证读取规则的 `read_text` 继续由 Agent 判断并记录来源。原执行器的风险与最终提交限制继续适用。 / Actions use the existing executor's live grounding, never stored click coordinates. `press_key` blocks without a live target. Reads without supported evidence rules still require Agent judgment; existing execution gates remain.

## 自动目标提议的当前范围 / Current automatic proposal scope

普通 step 与 input_sequence 的首次聚焦可把原作业票据、派发前候选、截图、窗口/应用和完整 UIA 写入学习回执并按摘要归档；非学习调用不采集此额外信息。compile 从可核对的唯一控件和独立文本锚点产生 fixed UIA recipe，重复/缺失/不完整证据给出具体 unresolved。save 不等于审核通过，人工修改仍产生新版本。

The recorded route supplies source evidence; compilation proposes fixed UIA recipes without writing assets, and explicit save keeps inferred rules pending.

同状态多个动作可共用较早代表界面 pin；target_recipe.v2 另固定确切动作前证据。人工修改生成 v3 editorial/unverified，内嵌原 v2 上下文，固定原 scope/pin/证据并复核编辑目标及动作类型；不宣称原动作验证了新目标。旧规则和程序保持，保存时核验目标参数/上游输出，变更依赖使相关审核待定。截图预览不证明现场动作成功。

Multi-action source evidence remains immutable. Editorial v3 changes retain the original v2 context, validate action/control types and typed dependencies, and remain unverified until actual use. Offscreen editing and attached-run evidence do not establish physical execution or comparative benefit.

## 当前目标与结果规则 / Current target and result rules

`click`、`input_sequence` 可选 `target_memory={recipe_id,interface_key,state_key}`。recipe 固定界面版本、动作含义与实际定位规则，库路径只能由宿主配置。原 `execute_recognition_plan` HTTP 入口单独收到该引用时返回 `target_memory_host_required`，不会忽略引用而偷偷改用模型。目标准备和结果观察都沿用公共桌面操作锁，不能在另一单步输入过程中改绑窗口。 / Optional target references are resolved only by the configured host; direct unsupported HTTP use fails explicitly. Read-only binding/capture honors the same global desktop step lock as input.

步骤的 `verification` 支持 `field_equals`、`text_equals`、`text_contains`、`target_present`、`target_absent`、`agent_judgment`。除 `agent_judgment` 外须有 `target={control_type,name?,automation_id?}`，至少一个 name/automation_id。相等或包含规则须有 `expected`，可引用常量、本次输入或本次上游输出。可选 `output_name` 必须对应步骤声明的输出类型。 / Verification uses finite checks, closed observation selectors and declared typed outputs.

`read_spec={method,target,output_name}` 支持 `uia_value`、`visible_text`、`agent_read`。当前 `uia_value` 从本次完整 UIA 树唯一选中 Edit/ComboBox，以新鲜截图中的目标框、RID/类型和原窗口身份只读两次稳定值；目标无需持有键盘焦点，身份或截图漂移则返回不确定，`visible_text` 读取真实 UIA Name，不能把静态 accessible name 当成屏幕上变化的正文。`agent_read` 或 `agent_judgment` 返回 `verification_required`；证据不完整返回不确定。框架不安装 OCR、不假造模型回复，也不以“按钮点击成功”代替结果成功。 / Current UIA value reads bind the uniquely selected control rather than keyboard focus; identity or frame drift remains uncertain. Unsupported or agent-based checks request judgment without inventing evidence or loading OCR.

`verify` 保存的观察绑定原执行 ID、run、step、窗口进程、本轮截图摘要和读取来源；规则判定经原 Trial 账本重新计算。离线控制接口拒绝 `verify/run/continue`，这些操作需要活宿主。`run` 的三步原 MCP 只读链已通过；真实连续输入仍待验收。重开和 status 只读状态，不能自动重放。队列繁忙且确定未入队时沿原 ID 延后；未知写入/派发继续回读原回执。取消请求也必须核对原终态后才能结算。 / A native read-only run is verified, while physical continuous use remains pending. Queue deferral applies only to proven non-admission; unknown input and cancellation still reconcile original receipts.
## 2026-10-01 普通编辑与实机续接 / Ordinary editing and physical continuation

本轮实际 main 的离屏控件验证：仅改步骤标题保留六步审核状态、动作来源与五个目标引用；只改 step-4 读取目标使 step-4 和依赖其输出的 step-5 重新待审，step-6 无数据依赖不失效。分别保存/关闭重开，旧版本与已创建 ready run 的 pin 不变；单独复核后，新版本原门控六步执行及当前详情填写核验通过。QA 库审核标记仅用于测试，不能当作人工审核或正式 C。 / Actual offscreen controls verify cosmetic versus read-semantic edits, scoped dependency invalidation and immutable versions. The re-reviewed QA version completes physical gated execution; QA marks do not prove human review or formal C.

两种布局的新编号复用、原 wait/EID 工作台重开续接、取消结算后的新任务均有原回执和清理证据。低风险实机测试已获用户批准，下方旧的待确认/未执行段为历史快照。目标规则替换、消失/重复反例和活动工作流跨窗口恢复仍待验收。详见[本轮记录](verification/LEARNING_WORKFLOW_BENEFIT.md)。 / Original receipts support bounded variation and recovery, with owned cleanup. Historical approval notes are superseded; remaining target edits and window transitions stay open.


## 2026-10-02 学习目标框 / Learned target boxes

学习目标的显示、人工修改与执行引用断点已在源码补齐：新导入自动标注，旧空标注资产只读恢复；独立界面可选择具体步骤目标并打开原目标编辑器，框选唯一控件后预览、应用、保存新规则。动态行条件与固定版本引用保留，未保存/未应用修改和过期引用有保护。Main 最终 168 项源码/离屏检查通过；当前库 5 个执行目标可显示，49 个原资产摘要未变。源码候选 v11；修改后的真实外部输入及完整连续运行仍待验收，稳定性继续优先，收益后置。本次没有发布、打包或改产品版本。 / Source now connects learned boxes to exact editable and executable locators, preserves dynamic bindings and immutable references, and guards drafts/stale links. The main final source/offscreen run passed 168 checks; five targets display without altering 49 existing assets. Candidate v11 still needs physical continuous acceptance; stability precedes benefits.

详情及原始证据见 `docs/verification/LEARNED_TARGET_BOXES.md`。 / See the verification record for scope, evidence and limits.

## 2026-10-02 独立界面切换响应 / Standalone interface switching

独立界面库切换现在后台读取目标与证据：标题和选择立即响应，截图加载期间显示“正在读取界面证据”，此时不能修改或保存。连续点击只保留最后待选，不把上一界面的框放到新选择上。完整校验仍需约 1 秒；加载失败会显示原因，重新选取或刷新可重读。已学动作之间切换只使用这次载入的截图字节。 / Standalone selection stays responsive during evidence loading, disables editing until complete, coalesces repeated selection and rejects stale results. Evidence still takes about one second; reload validates again.

新代码只在重新启动的源码窗口生效。不要直接销毁仍在读取的窗口；正常关闭会等待读取结束。保持已有未保存编辑后再使用新预览。详见[响应验证](verification/INTERFACE_SWITCH_RESPONSIVENESS.md)。 / Changes require a new source process; ordinary close guards active jobs and existing drafts remain preserved.

最终主回归 176 passed in 91.07s，失败/错误/跳过为 0；保留首次失败与退出记录。 / Final main source/offscreen regression: 176 passed, no failures/errors/skips; initial failures remain recorded.


## 2026-10-02 工作台外观优化 / Workbench presentation polish

学习源码预览 v13 统一三个页面的浅色圆角样式、按钮层级与线性图标；沿用截图、流程图和右侧修改布局。导航只对指示条做 160ms 动画，页面立即切换；“视图 → 减少动画”可关闭，启动时读取 Windows 客户区动画偏好，也可设置 `AGENT_REVIEW_REDUCED_MOTION=1`。运行页改为内部滚动，隐藏页面不再撑大整窗。 / Source preview v13 unifies rounded light surfaces, button hierarchy and line icons. Only the navigation indicator animates for 160ms; content switches immediately. Reduced motion follows the initial Windows preference or the environment override and can be toggled in View. The run page scrolls internally instead of forcing the whole window taller.

Main 84 项源码/隔离/离屏检查通过（47.99s），包含快速切页、键盘、减少动画、两种窗口尺寸、原编辑保存重开、目标框、后台读取及运行页恢复；已检查 1440×960 和 1100×760 的三个页面截图及小窗运行页滚动截图。首次缺图标、过高窗口和测试几何断言失败均保留，不算首次全部通过。 / The final main run passes 84 source/isolated/offscreen checks, including navigation, editing, target boxes, background selection and run recovery. Both window sizes and the scrolling run-page render were inspected; initial failures remain recorded.

本轮未派发外部输入、未做物理连续运行验收，未改产品版本、打包或发布；v13 只是源码预览标识。旧窗口不热更新。完整变化/中断/恢复与收尾验收继续作为学习试用版主线，收益验证仍后置。详见 `docs/verification/WORKBENCH_UI_POLISH.md`。 / No external input, physical continuous acceptance, product-version change, package or publication. v13 is only a source-preview label; existing processes retain old code. Physical continuity/recovery/cleanup remains the trial mainline, with benefits deferred.


## 2026-10-02 外框与字体补齐 / Window shell and typography

源码预览 v14 补齐 v13 遗漏的窗口外层：使用原生 Qt 无边框窗口、自绘 12px 圆角和统一标题栏，菜单及最小化/最大化/关闭按钮进入同一栏；最大化时取消圆角与边距。拖动/缩放接 Qt 系统接口，关闭仍调用原 closeEvent，未保存草稿不会被窗口按钮绕过。 / Source preview v14 completes the outer shell with a rounded Qt frameless window and unified title/menu/control row. Maximized windows have no radius or inset. Move/resize uses Qt system APIs and close retains existing draft guards.

工作台进程明确使用 Segoe UI 与 Microsoft YaHei UI，正文 14 个逻辑像素；标题保留层级，不安装字体或修改系统设置。实际 Windows 字形排版确认中文使用 Microsoft YaHei UI、英文使用 Segoe UI，无缺字。输入参数页补为滚动容器，增大字体后不再因隐藏页最低高度撑大窗口。 / The workbench process selects Segoe UI plus Microsoft YaHei UI at 14 logical pixels, without installing fonts or changing OS settings. Native glyph runs verify both scripts. A scrolling input-parameter page prevents hidden-page minimum height from enlarging the window.

Main 51 项源码/隔离/离屏检查通过；补充目标选中后的属性布局检查 3 passed，与主集合重叠。实际 Windows 平台自建窗口的最大化、还原、最小化、关闭状态通过程序化验证，新预览窗口正常响应并使用新字体。真实鼠标拖拽/边缘缩放未实测，只验证事件到系统接口的调用；未覆盖所有 DPI 和多屏组合。本轮未派发外部输入，未发布或改产品版本。 / Main passes 51 checks plus an overlapping three-test inspector rerun. Native window-state transitions and font shaping pass programmatic checks. Physical dragging/resizing and all DPI/multi-screen combinations remain unverified; no external input or release change.

详见 `docs/verification/WORKBENCH_SHELL_TYPOGRAPHY.md`。v14 只是源码预览标识，旧窗口未热更新。 / v14 is a source-preview label; old processes retain their original code.
