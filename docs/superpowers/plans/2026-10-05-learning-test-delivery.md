# Learning test delivery / 学习模式测试交付

> **2026-10-05 latest scope / 最新范围:** 用户已暂停测试，要求先规划独立、可选安装与中英文切换。后续以[新计划](2026-10-05-learning-optional-install-and-language.md)为准；下面是便携候选阶段记录。桌面批次此前已获批准并部分执行，出现一次非手动启动退出及审核下拉弹窗所有权/截图遮挡问题，尚未完成编辑重开、连接和完整收尾。下方“待批准/未跑”是此前时点，不能当作当前状态。 / Testing is paused for optional installation and localization planning. Retain the portable-candidate history; the approved desktop batch is partial, with an unexplained launch exit and popup-visibility issue, and no completed edit/attachment/cleanup acceptance.

**Goal / 目标:** 在已通过的有限学习源码候选上补齐可双击的 Windows 便携工作台和准确安装说明，完成包内隔离检查，再按用户批准范围做桌面验收。 / Add a double-clickable portable Windows workbench and accurate setup guidance to the accepted bounded source candidate; verify it in isolation before approved desktop acceptance.

**Architecture / 架构:** 原 v14 工作台与 WorkflowRunClient/现有执行器不变。启动器只选择并记住学习数据目录；便携包的 GUI 依赖及维护源码共用 `runtime` 根目录，保留 Client 对宿主确切入口和同库校验。当前 Agent、委派和外部 API 沿用既有配置，本地模型可选。 / Keep the workbench, client and executor. The launcher selects a data root; frozen GUI dependencies and maintained source share the runtime root, preserving exact host-entry and same-library checks. Existing vision routes remain available with optional local models.

**Spec / 依据:** 用户要求继续朝测试版推进；此前明确的 EXE 库入口、v14 UI 与[操作说明](../../WORKFLOW_EDITOR.md)。[此前有限收尾](2026-10-03-learning-trial-closeout.md)已完成，原失败及证据保留。 / Continue toward a test release using the previously requested library executable, accepted UI and linked guide; retain prior acceptance and failures.

## Constraints / 约束

- 不调用或排查 Codex 原生 Computer Use/Sky；桌面观察与动作使用项目维护接口。 / No native Codex Computer Use/Sky; use maintained project capture/action APIs.
- 不改工作流/接管协议、宿主校验或动作门禁，不自动启动宿主/模型或改 Agent 的 MCP 配置。 / Keep protocols, host identity and input gates; do not automatically start hosts/models or edit Agent MCP settings.
- 复用既有 Python 与独立 PyInstaller 工具；本轮只构建一个必要候选，不复制模型、秘密或历史数据。 / Reuse existing Python/build tools and build one necessary candidate without models, secrets or prior data.
- 当前阶段是本地候选准备；产品版本、安装器和公开发布不自动变更。 / Prepare a local candidate; versioning, installers and publication are separate.
- 离线检查不需要桌面批准；需要新一批真实桌面操作时，先给出已构建候选及具体范围。 / Offline checks proceed; present the built candidate and exact scope before a new desktop-input batch.

## Tasks / 工作

- [x] 核对现有工具、入口与真实交付缺口：无参数数据目录、Qt依赖和包内同根宿主合同。 / Audit tools, no-argument data selection, Qt dependencies and shared-root host identity.
- [x] 最小启动器：首次选择/记忆目录，显式路径优先，取消/错误清晰；12项启动边界与3次源码真实入口离屏检查通过。连同新增打包合同、源码收集检查修复Windows环境键大小写后共29项通过（范围有重叠，不与历史计数相加）。 / Add selection/persistence, explicit priority and clear errors; 12 launch tests and three source offscreen checks pass, with 29 combined launch/package/collector checks.
- [x] 复用维护源码包收集器与既有 PyInstaller 工具构建轻量 EXE；Qt GUI与维护源根一致，记录工具、产物及hash。 / Build the executable using the maintained collector and existing tooling; record shared-root layout and hashes.
- [x] 在树外目录、干净环境、全新数据运行 EXE 的离线启动检查，检查包内实际功能入口及依赖；不把离屏检查记为桌面或真实输入通过。 / Verify the executable offscreen and real dependency entrypoints from outside the source tree with fresh data, without claiming desktop/input acceptance.
- [x] 同步普通使用说明：双击入口、数据目录/已有会话、Agent环境与GUI环境、API/本地可选及具体限制。 / Synchronize ordinary launch, data/session selection, runtime environments and route limitations.
- [ ] 给出候选位置及下一批桌面测试的具体预览范围，取得用户所要求的批准后再执行。 / Present the candidate and exact next desktop-test scope before user-required approval.

**Exit / 出口:** 本地 EXE 和维护运行时准备好、隔离检查通过、文档准确；真实桌面和完整包内连接未跑时明确列出，不宣称已发布或所有客户端兼容。 / The local executable/runtime are prepared and isolated checks/docs pass; report unrun desktop/package connection checks without claiming publication or universal compatibility.

**Verification / 验证:** candidate-01工具启动前环境键大小写失败，原件保留；新增回归先失败再修复，candidate-02构建成功，29项相关检查通过。冻结EXE在树外中文路径首次/重开均exit 0，三页面、未连接禁用及正常关闭通过，1418项载荷hash不变，无个人设置写入或桌面输入。包内实际入口依赖通过；包内宿主连接和桌面批次仍待批准/验收。 / Preserve the initial pre-build failure; the focused regression and candidate-02 pass. Two isolated Chinese-path executable checks exit normally with pages/input state correct and 1418 payload hashes unchanged. Actual source dependency entrypoints pass; package-host and desktop acceptance remain pending.
