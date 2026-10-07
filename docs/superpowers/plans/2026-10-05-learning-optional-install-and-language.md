# Optional Learning Trial and Language Switching Implementation Plan / 可选学习测试版与语言切换计划

> **For agentic workers:** Execute this plan only after the user resumes development. Use bounded implementation tasks and relevant checks; the current request authorizes planning only. / 用户恢复开发后再执行；当前仅规划，测试已暂停。

**Goal / 目标:** 执行模式和学习模式分别安装、升级和卸载；执行模式不要求安装学习模式，学习工作台可独立管理本地库，需要采集教学或运行工作流时才接入执行模式。首个学习测试版支持简体中文和英文。 / Ship optional, separately installable learning with independent offline library management and on-demand attachment for teaching capture and execution; support Simplified Chinese and English.

**Architecture / 架构:** 保留现有学习编辑器与执行器，拆分交付清单和安装身份，不重建执行器。学习工作台通过明确的执行安装根、会话及版本能力检查连接现有运行时；第一版连接继续要求同一数据根和确切库身份。国际化使用 Qt 翻译资源与稳定语义值，翻译显示文字，不改用户资产或协议。 / Reuse the editor and executor with separate delivery manifests and install identities. Attach to a validated execution root/session with compatible capabilities and the same data/library identity. Translate presentation with Qt resources while retaining stable semantic values.

**Tech Stack / 技术栈:** Windows、Python、PySide6/Qt、现有 PyInstaller 与维护源码收集器。安装器优先复用项目已有工具；具体工具及两包最终体积尚未核对。 / Reuse existing tooling; installer tooling and final sizes are not yet verified.

**Spec / 依据:** 用户 2026-10-05 最新要求：“和执行模式能够独立安装”“学习模式不是必需品是可选项”“现在学习模式没有语言切换”“先不继续测试”。本文件的目标、边界及交付条件是后续实施依据；此前[便携候选计划](2026-10-05-learning-test-delivery.md)及原始证据保留为历史。 / This user's latest request controls scope and pauses testing; retain the prior portable candidate and evidence.

## Global Constraints / 全局约束

- 当前只写计划和同步状态，不修改产品、运行测试、操作桌面或重新打包。 / Planning and status only; no product changes, tests, desktop actions or builds now.
- 主会话负责设计和整合，执行子 Agent 使用 Sol；有界委派，不拆出新的执行器。 / Main owns integration; Sol handles bounded implementation.
- Codex 原生 Computer Use/Sky 禁用；以后桌面观察与输入仍用项目维护接口及现有门禁。 / Native Computer Use/Sky remains disabled; preserve maintained interfaces and gates.
- 支持当前 Agent、委派和外部视觉 API；本地模型可选。不得为首版强制下载模型、购买 API 或自动改 Agent MCP 配置。 / Existing vision routes remain; local models are optional, with no forced purchase or configuration rewrite.
- 保留独立界面、确切版本的流程图引用、人工审核修改、历史资产和原失败记录。 / Preserve interface-first assets, pinned graph references, review/editing and history.
- 不宣称任意软件、任意中断均稳定，也不把有限通过写成模型用量、准确率或速度收益。 / Bounded evidence does not establish universal stability or measured benefits.
- 后续恢复测试时，离线检查按范围执行；桌面测试沿用有效批准，超出旧范围时再给出具体预览并取得批准。 / On resumption, preserve valid approvals and request approval for expanded desktop scope.
- UTF-8、中英维护说明、输入安全及真实依赖闭合继续有效；不自动提交、推送或发布。 / Preserve UTF-8, bilingual maintenance docs, input safety and dependency closure; no automatic publication.

## Current Evidence / 当前事实

- 已有学习便携 EXE 候选 candidate-02，启动边界、包内真实依赖及树外中文路径离屏启动/重开已有有限通过证据。它目前包含同根执行源码，**不是已经完成的独立安装方案**。 / A bounded portable candidate exists; it still includes same-root execution source and is not independent installation acceptance.
- 学习工作台已有离线编辑基础，不必启动宿主或模型；目前首次提示仍是“选择当前 Agent 的数据目录”。 / Offline editing already exists, but initial directory wording assumes an Agent data root.
- `WorkflowRunClient` 按自身源码根定位宿主脚本；两个独立安装根尚未验证。不能直接删除路径身份检查来让连接通过。 / Host validation assumes the client's own source root; cross-install attachment is unverified and must preserve identity checks.
- 未找到现成的学习工作台国际化层，按钮、菜单、状态和错误存在直接中文字符串。 / No existing workbench localization layer was found.
- 最新桌面批次已获批准并部分执行：首次目录选择后一度自行退出，用户确认没有手动关闭；另一次全新目录进入后页面切换正常。原退出根因仍未知。 / An approved desktop batch is partial: one first-launch disappearance is unexplained and confirmed non-manual; another fresh startup and navigation worked.
- 审核下拉弹窗 HWND 未呈现主窗 owner 关系，项目截图的遮挡保护将其区域盖住；截图与原生元数据已有证据，修复路径尚未确定，未盲选。编辑保存重开、包内连接及完整桌面收尾尚未完成。 / Popup ownership is not proven and capture masking blocks option inspection. No blind selection occurred; editing, attachment and full closeout remain incomplete.
- 用户现已暂停测试；不得将本次暂停记成正常收尾通过。 / Testing is paused; pause is not successful cleanup evidence.

## Review Focus / 重点条件

1. 只安装任意一个组件；另一个缺失不应阻止其独立功能。 / Either component must retain its standalone functions.
2. 两安装根不同、执行版本不兼容、同库关系不成立或 PID 过期：明确拒绝连接/输入，不绕过身份检查。 / Reject incompatible or stale attachments with clear reasons.
3. 切换语言时存在未保存编辑、选中步骤或待处理运行回执：状态保留，不重新发送动作。 / Language switching preserves edits and requests without replay.
4. 安装目录只读或卸载/升级发生：用户库及旧版本资产保留在安装目录外。 / Keep user data outside installation paths across upgrades and removal.
5. 原生目录选择和 Qt 弹窗：真实失败与离屏通过分别结算，不能用截图绕行掩盖所有权缺陷。 / Validate native failures separately and preserve popup safety.

---

### P0: Freeze the product boundary / 确定产品边界

**Files / 文件:** `RELEASE_SCOPE.md`、`FRIEND_SETUP.md`、`docs/WORKFLOW_EDITOR.md`、`scripts/build_instant_bundle.py`、`scripts/build_learning_workbench.py`、`packaging/learning_workbench.spec`。

- [ ] 定义两个交付物：执行模式安装包；学习工作台测试版安装包。独立目录、快捷方式、安装/卸载身份和更新目标。已有执行正式版继续独立使用；仅在连接能力确有缺口时安排最小兼容更新。 / Define independent packages and update targets; retain the existing execution release unless a proven compatibility gap requires a patch.
- [ ] 明确功能：执行模式单独完成现有操作；学习工作台单独打开/建立库、审核、修改、保存和查看版本；通过项目截图/动作接口采集教学及执行工作流需要连接兼容执行模式。 / Separate standalone execution, offline learning management and attached teaching/execution through maintained interfaces.
- [ ] 两包使用同一维护源码中的确切依赖清单。执行包无需安装学习 GUI/Qt；学习包不复制完整执行器或模型，实际必要的共享协议/库依赖必须闭合。 / Use precise manifests, with no mandatory learning UI in execution or duplicated full executor in learning.
- [ ] 不删除仅因名称含 `learn` 的当前执行共享依赖；按真实调用及独立入口检查决定保留范围。 / Audit live dependencies instead of deleting by directory name.

**Exit / 出口:** 文档和包清单明确可选关系；独立安装不等于复制两套执行器。 / Explicit optional packaging without duplicate executors.

### P1: Make offline use ordinary / 完成独立学习入口

**Files / 文件:** `app/learning_memory/workbench_launch.py`、`scripts/run_learning_memory_workbench.py`、`app/learning_memory/workflow_run_panel.py`、相关编辑 pane；`tests/test_learning_workbench_launch.py`。

- [ ] 首次入口改为选择/创建学习库目录，不要求用户先有 Agent 会话。新建路径只建立学习数据，不自动创建执行宿主。 / Offer a learning library root independently of Agent availability.
- [ ] 未连接时允许完整查看、审核、修改和保存；运行页清楚说明需要执行模式，并提供“连接执行模式”入口。 / Keep offline library functions available and expose explicit execution attachment.
- [ ] 数据和首选项存安装目录外；已有数据目录记忆格式继续可读，损坏设置明确报错，不静默切换到另一库。 / Preserve existing settings/data with explicit errors instead of silent library substitution.
- [ ] 明确安装/升级/卸载行为：默认保留用户库；卸载学习组件不动执行组件及其配置。 / Preserve data and the other component on removal.

**Future checks / 后续检查:** 无执行安装、无模型及无执行 Python 环境下，真实学习入口建库→编辑→保存→重开；取消目录选择不创建数据；中文路径/只读目录/旧设置行为。 / Verify isolated standalone entrypoints and directory/settings boundaries after resumption.

### P2: Attach across installation roots safely / 两安装根按需连接

**Files / 文件:** `app/learning_memory/workflow_run_client.py`、`app/learning_memory/workflow_run_panel.py`、现有执行安装配置与会话报告生产者；拟新增 `app/learning_memory/execution_installation.py` 和对应合同测试。

- [ ] 执行安装提供可校验的安装描述及能力信息；学习端通过用户明确选择或受控发现取得执行安装根。记录协议版本、工作流能力和确切入口，不只凭进程名判断。 / Resolve an explicit execution installation and verify its entrypoint and capabilities.
- [ ] 将当前“Client 自身根等于宿主根”的假设替换为已校验的执行安装根；继续核对 PID、创建时间、父子进程、入口命令、会话及同库关系。 / Support separate roots while preserving runner, process, session and library proofs.
- [ ] 第一版连接继续共用确切数据根；学习独立打开的库必须与执行会话指定库一致，不新增跨库静默映射。 / Require the same data/library root for the first release.
- [ ] 不兼容或找不到执行模式时，提示安装/选择兼容版本；离线学习继续可用。连接、状态读取和实际运行权限分开，连接不能触发输入。 / Provide actionable attachment errors without blocking offline use or dispatching input.
- [ ] 保留后续决策 API 和学习复用入口；未配置决策 API 时沿用当前执行逻辑，不把接入新模型列为首版前置。 / Preserve optional future decision APIs without requiring them for this trial.

**Future checks / 后续检查:** 两目录真实连接和只读状态；错误根/伪造描述/旧 PID/不同库/不兼容能力拒绝；断开不关闭非本工作台拥有的宿主；真实输入另按批准范围验收。 / Verify attachment and refusals without weakening ownership or input gates.

### P3: Add complete language switching / 补齐中英文切换

**Files / 文件:** 拟新增 `app/learning_memory/workbench_i18n.py`、`app/learning_memory/translations/`；修改 `workbench_launch.py`、`workbench_window.py`、`scripts/run_learning_memory_workbench.py`、三主页及运行页/编辑弹窗；新增国际化合同测试，调整 `--check-startup` 检查。

- [ ] 首版语言为 `zh-CN` 与 `en-US`，设置中显示“简体中文 / English”。首次按系统支持语言选择，否则英文；后续优先使用用户保存的选择。 / Support Simplified Chinese and English with remembered selection.
- [ ] Qt `QTranslator` 与 `.ts/.qm` 资源负责应用文字；建立语言变更刷新入口，切换无需丢弃当前库、选中项和未保存编辑。 / Translate with Qt resources and refresh presentation without losing state.
- [ ] 覆盖标题栏、菜单、按钮、三主页、运行状态、审核选项、字段帮助、空状态、关闭提示、应用错误及开发者入口。系统原生文件选择器文字跟随 Windows；应用提供的标题/提示使用应用语言。 / Cover the complete application surface; OS-managed dialog text follows Windows.
- [ ] 审核状态、动作类型、参数键、资产 ID 和错误码保留固定内部值；显示标签翻译后仍可保存和复用。用户工作流名称、备注、截图文字和原始日志不自动翻译。 / Translate labels, not persisted semantics or user content.
- [ ] 语言首选项单独存于 `workbench-preferences.json`，避免向目前只接受 `data_dir` 的旧设置文件强加字段。启动目录选择前加载语言，旧目录记忆保持兼容。 / Store language preferences separately from the strict legacy data-directory settings.
- [ ] `--check-startup` 按稳定页面身份和选择语言核验，不再把中文标题当固定业务合同；打包清单包含翻译资源。 / Make startup verification locale-aware and include translation resources.

**Future checks / 后续检查:** 两种语言完整入口及关键弹窗；旧设置加载；待审草稿切换后保存语义不变；未保存编辑/待处理请求不丢失或重放；重开记忆语言；英文较长文字无明显截断。 / Verify both locales, preservation, persistence and layout.

### P4: Close the observed failures / 闭合现有故障

**Files / 文件:** `workbench_launch.py`、`app/core/window_manager.py`、`app/core/screenshot.py`、Qt 窗口/弹窗适配及对应窄回归；实际修复位置必须由原证据确定。 / Choose the actual fix layer from evidence.

- [ ] 首次启动异常退出：复核原进程/窗口记录，恢复开发后增加必要生命周期诊断，定位具体退出路径；不能凭离屏通过认定正常，也不能猜测 `quitOnLastWindowClosed` 后直接改行为。 / Diagnose the actual first-launch exit rather than speculate.
- [ ] 下拉弹窗遮挡：核实 Qt 弹窗与主窗的真实所有权/关联，修复正确的窗口或共同层合同。禁止仅凭同 PID 放行全部弹窗、关闭遮挡保护或盲点选项。 / Repair verified popup relations while preserving masking and ambiguity rejection.
- [ ] 对真实修复建立窄回归；保留原首次失败和修复后的单项、连续结果，不互相覆盖。 / Preserve original failures and separate retest evidence.

**Exit / 出口:** 两项有根因、实际修复证据及相应回归；若仍未知，明确作为交付卡点。 / Proven fixes and regressions, or explicit blockers.

### P5: Consolidate acceptance and deliver / 集中验收与交付

**Files / 文件:** 两包构建/安装清单、相关合同测试、`README.md`、`FRIEND_SETUP.md`、`docs/WORKFLOW_EDITOR.md`、本地进度文档。

- [ ] 先集中完成源码合同、隔离入口和翻译检查，再构建一个必要新候选；测试/文档变化不反复打包。 / Consolidate source checks before a necessary new candidate.
- [ ] 验收安装组合：仅执行、仅学习、分别安装后连接、升级或卸载其中一个；均从全新数据和树外环境进入。 / Validate independent and combined installation lifecycles.
- [ ] 冻结同一候选，完成 Main 普通入口和连续使用，再由 Sol 独立验收；桌面输入先明确范围。 / Main validates the frozen candidate before independent Sol acceptance.
- [ ] 学习闭环：新教学生成→审核/修改→保存重开→同会话换数据复用→一次限定中断/弹窗处理→明确恢复→正常清理。模型收益、广泛软件及所有故障保证另行报告。 / Accept a bounded complete journey and report broader claims separately.
- [ ] 两语言说明写清可选安装、连接条件、API/本地模型选择、已知限制与数据保留；产物、版本、哈希及证据对应同一候选。 / Synchronize bilingual optional-install guidance and candidate evidence.
- [ ] 满足出口后提交具体测试版交付方案；公开发布、安装器版本和签名状态分别确认，不把本地 EXE 当已经发布。 / Distinguish local candidate, installer readiness and publication.

## First-trial exit / 第一个测试版交付条件

- 执行模式单独可用，学习工作台单独可管理库；双组件跨安装根可按需连接，输入门禁不变。 / Standalone functions and safe optional cross-root attachment pass.
- `zh-CN/en-US` 的普通入口、关键状态和弹窗可用，切换/重开保留数据及选择。 / Both locales work with preserved state and preferences.
- 原启动退出和弹窗所有权问题闭合；新冻结候选完成有限连续闭环、独立验收及正常清理。 / Observed failures and bounded frozen-candidate acceptance are closed.
- 卸载/升级不破坏另一组件或用户库，包内真实依赖闭合，不强制本地模型。 / Independent lifecycle and real dependency closure pass without mandatory local models.

**Priority / 顺序:** P0 → P1/P2 与 P3 有界并行 → P4 修复并回归 → P5 集中冻结验收。P4 的只读根因调查可在实施阶段并行，但问题未闭合不得交付。 / Define boundaries, implement optional installation and localization, close failures, then freeze and accept. Diagnosis may overlap implementation, but unresolved failures block delivery.

**Current next step / 当前下一步:** 用户先审阅此计划；本轮保持测试暂停，不执行以上复选项。 / Review this plan; testing remains paused and all implementation tasks remain unexecuted.
