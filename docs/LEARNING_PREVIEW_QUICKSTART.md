# 2026-10-09 preview.3 安装与使用 / Preview.3 setup and use

学习 `0.1.0-preview.3` 与兼容执行 `0.1.2-preview.3` 使用两个独立安装器：[preview.3 发行页与下载](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/learning-v0.1.0-preview.3)。源码限定验收及 Main 新安装版实机通过；安装器 SHA、最终独立验收和发布核对状态见[发布记录](verification/CONTINUOUS_EXECUTION_RELEASE_20261009.md)。 / The preview.3 pair uses separate installers. Scoped source and Main installed acceptance passed; use the release record for exact hashes and final installed-independent/publication status.

临时计划一次提交 1–8 个线性步骤，经声明结果核验后推进，不需要学习工作台；异常保留原请求，审核后原 wait 显式继续，不重放未知输入。源码 10 对预热两步 fixture 原生定位中位为 6.50→2.07 秒，不包含冷启动、准备、清理或 Main 推理；不是通用速度保证。见[合同](development/TASK_PLAN.md)与[源码验收](verification/CONTINUOUS_EXECUTION_ACCEPTANCE.md)。 / Bounded plans advance verified steps and retain original evidence on uncertainty. The matched source fixture timing is scoped warm-run evidence, not universal performance.

# 2026-10-08 preview.2 历史使用说明 / Historical preview.2 quickstart

学习 `0.1.0-preview.2` 与兼容执行 `0.1.2-preview.2` 分别安装：[preview.2 下载](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/learning-v0.1.0-preview.2)。本页说明安装与使用方式；本轮测量、安装验证范围及保留的首次失败详见[验收报告](verification/DECISION_API_RELEASE_ACCEPTANCE_20261008.md)。 / Learning and compatible execution preview.2 install independently. This guide describes setup and use; see the current report for measurements, installed validation scope and retained first failures.

[上一版 preview.1 安装器](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/learning-v0.1.0-preview.1) 已于 2026-10-07 发布，包含其已验收的本地图像核验；下方版本、SHA 和验收是该历史版本，不能当作 preview.2 结果。稳定 `instant-v0.1.1` 保留。 / The previous published preview.1 includes its accepted local image checks. Version/hash/acceptance records below belong to that historical pair, not preview.2; stable execution remains available.

# 2026-10-07 preview.1 历史冻结与验收 / Historical preview.1 freeze and acceptance

第三批source14/GUI12已完成匹配冻结与实装限定验收，状态为release-ready。Main与独立Sol各记录2个教学事件、6个预期连续场景（5个正例完成，负例一次点击后判失败，无重复输入）；GUI Save原job为completed并返回captured状态的动作后截图，关闭重开后图像关闭选项保持，最终cleanup完成。第一批终态JSON读取失败及第二批空标题清除绑定失败原记录保留；旧便携candidate02未知退出未宣称修复，stablev0.1.1保持原发布。网络发布与下载核对单独记录在对应发行页。 / The matched third source14/GUI12 pair is release-ready after bounded installed acceptance. Main and independent Sol each recorded two teaching events and six expected continuous cases: five positive completions and one negative failure after a single click without replay. The original GUI Save job completed with captured post-action evidence; image disablement persisted across close/reopen and cleanup completed. Both earlier failures and the unexplained excluded portable exit remain historical. Stablev0.1.1 is unchanged; publication and download verification are recorded separately on the release page.

当前安装包含默认图像规则提议、人工区域编辑及可关闭图像核验；不确定保留原请求交Agent审核，不重放输入。流程图引用图钉固定的界面版本，附加成员不自动创建跳转。GUI页签为“结果与读取”。本地模型权重可选；本轮没有新增真实API供应商测试，不宣称通用准确率、速度或模型用量收益。 / Current installers include default image proposals, editable regions and persistent disablement. Uncertain evidence retains the original request for Agent review without replay. Graphs pin interface versions and membership does not create transitions. The GUI tab is Results and readback. Local weights are optional; no new real API-provider tests or general accuracy, speed or usage claims.

| 组件 / Component | 版本 / Version | 冻结批次 / Frozen pair | Setup SHA256 |
|---|---|---|---|
| 执行 / Execution | `0.1.2-preview.1` | source14 / installers-execution-13 | `fc8e343549d84d3deceb3d116451bc739729402fdefc2b5a1ba5a097e96ea5e7` |
| 可选学习 / Optional learning | `0.1.0-preview.1` | GUI12 / installers-learning-12 | `d67443fdb9c77d60db4063a66b501e1be1ae45baf9c2af2b2a8cbecad86728b9` |

[preview.1 历史限定验收 / Historical preview.1 acceptance](verification/LEARNING_PREVIEW_RELEASE_ACCEPTANCE_20261007.md)。原失败保留；下面使用说明面向本轮 preview.3 目标，历史安装通过不转计。 / Preserve original failures; the usage guide below describes the preview.3 target, separately from historical installed results.

---

# 可选学习工作台测试版使用说明 / Optional learning preview guide

学习组件 `0.1.0-preview.3`、兼容执行组件 `0.1.2-preview.3` 分别安装、升级和卸载，学习是可选组件。发布与新安装候选验收以顶部本轮记录为准，preview.2/preview.1 的链接及验收保留为历史。 / The preview.3 learning and execution targets have separate lifecycles. Learning is optional; use this run's record for publication and installed acceptance, retaining previous releases separately.

## 选择组件 / Choose components

| 需要做什么 / Goal | 安装什么 / Component |
|---|---|
| 仅执行任务 / Execute tasks | 执行组件；学习工作台不是必需品 / Execution; learning is optional |
| 离线审核与修改库 / Offline library editing | 学习工作台；不需要执行宿主或模型 / Learning; no host or model |
| 采集教学与复用流程 / Teach and reuse workflows | 两组件，并连接兼容的已有执行会话 / Both, attached to a compatible existing session |

两个安装目录可以不同。学习 EXE 包含其界面运行依赖，不包含执行宿主、模型或用户库。执行安装器提供维护运行时，仍需按 [安装配置说明](../FRIEND_SETUP.md) 准备所选路线的环境与 MCP 配置。 / The two installation roots may differ. Learning bundles its UI dependencies, but no host, model or user library. Configure the execution runtime and MCP using the setup guide.

**本地模型可选，Decision API 也可选。** 外部视觉 API、当前支持图像的 Agent、客户端明确配置的视觉委派都可使用；只有 `local` 定位路线要求本地模型权重。未配 Decision API 仍正常使用，结果沿用原审核；可选判断不替代定位模型。 / Local models and Decision API are optional. Only local grounding requires weights. Explicit API/current/delegated vision routes remain available; ordinary unconfigured use preserves review and optional decisions do not replace grounding.

普通 Luna 的 12 案有界识图评估已结束，未执行返回点击点；本轮后续使用本地识图是个人选择，不关闭已有公开 API 路线，也不修改用户视觉配置。 / The twelve-case Luna image evaluation ended without executing returned points. This run's local profile does not disable existing API routes or change user-selected vision settings.

## 可选结果判断 / Optional outcome decisions

在独立执行安装中，将 `configs/decision-profile.example.json` 复制到自己的配置目录，在已审核的 Python `scripts/configure_instant_mcp.py` 命令中增加 `--decision-profile <绝对 JSON 路径>`；保持原视觉来源及输入授权参数。Key 仅通过配置指定、实际宿主可见的命名环境变量提供，不写入 JSON。完整步骤见 [Decision 配置](development/DECISION_API.md)。 / Copy the execution installation's profile example and add its absolute path to the reviewed Python configurator command, retaining existing vision/input settings. Provide the key only through the configured host-visible environment variable, not JSON. See the configuration guide.

默认 `shadow` 只给建议、保留审核；学习步骤的 `agent_judgment` 可设置审核过的明确 `decision_condition`。自动采用必须显式 `auto`，条件与 `auto_conditions` 完全一致，且原截图、窗口、执行绑定及回执有效。本地图像匹配成功的结果核验零 Decision 请求；不合格证据不能转交 API 绕过检查。判断只给结果谓词，不生成坐标或动态读取值，不重放未知输入。 / Default shadow advises while retaining review. Learned agent_judgment may declare a reviewed explicit decision_condition. Auto requires an exact allowlisted condition and valid original image/window/execution/receipt bindings. Local image success sends zero Decision requests. Invalid evidence cannot bypass checks; decisions supply predicates rather than coordinates or dynamic reads and never replay unknown input.

## 打开学习库 / Open a library

首次打开工作台，选择一个已有、可写的数据根目录，例如 `D:/AgentLearningData`。程序在其中使用 `memory-library`；重开仍选择原数据根，避免把子目录误当新根。将数据放在安装目录外，分别升级或卸载组件时保留自己的库。 / Select an existing writable data root. Reopen that root rather than its memory-library subfolder, and keep it outside the installation.

首次没有语言偏好时默认 English，不跟随系统语言；“设置 → 语言 → 简体中文 / English”可切换并保存选择，保存的偏好优先。用户标题、备注、输入值、日志和截图保留原文。 / First launch defaults to English regardless of system locale. Settings → Language switches and saves the UI language; saved preferences take priority. User content and original evidence are unchanged.

已知限制：English 默认界面中少量历史来源状态标签仍显示中文（“新学内容”“有修改”）。 / Known limitation: a few legacy origin-status badges remain Chinese in the English UI.

## 教学、审核、修改、保存 / Teach, review, edit and save

1. 需要采集或试运行时，在“运行”页选择真实的执行安装目录及已有会话，再连接。会话与库必须属于同一数据根；连接读取状态，不自动开始动作。 / Select the actual execution installation and an existing session sharing the data root. Attachment reads status without starting actions.
2. Agent 通过公开学习接口开始教学，执行目标动作并审核原始前后图与回执。停止教学前完成事件审核，再通过同一学习段的整理接口生成草稿。 / Teach through the public learning interface, review original observations before stopping, and synthesize the same segment into a draft.
3. 点击“刷新最近学习 → 打开学习草稿”。检查每步目标、输入来源、输出、结果判断与跳转。稳定步骤可以保留；每次变化的值使用工作流输入或上游结果。 / Open the latest draft and inspect targets, input bindings, outputs, verification and branches. Use parameters or upstream results for changing data.
4. 修改后重新核对审核状态，再点击“保存任务步骤”。语义修改可使步骤回到待审核；保存产生确切不可变版本，旧发布引用不自动前移。 / Recheck review status after edits and save an immutable version; existing pinned references do not advance automatically.
5. 关闭重开，检查版本与内容。通过“运行工作流”入口填写本轮参数，再使用保存版本试运行；未保存的编辑不参与执行。 / Reopen to check the saved version, supply this run's parameters and execute that exact version.

单个界面的学习默认产生独立界面内容，不强制建流程图；Agent 或人工明确指定归属，加入成员不自动创建跳转。已有流程图、原图和版本记录继续保留。 / Single-interface learning is standalone by default. Membership is explicit and creates no implicit edges; graphs, original images and version history remain available.

## 运行与中断 / Run and interrupt

`learned` 使用审核过的目标规则。可判别的已学跳转默认提议本地图像核验：在“任务步骤 → 结果规则”核对原图，调整稳定模板区域、搜索区域与阈值，或关闭后保存。明确匹配时继续；不匹配或证据不确定时保留原请求，由 Agent 审核。图像匹配不要求本地模型权重，读取仍可使用 `agent_read`。`steps_only` 是可选策略，不使用这些图像规则。 / Learned execution uses reviewed target rules and proposes local image checks for distinguishable transitions. Inspect or disable the rule under Task Steps → Result Rules. A clear match proceeds; inconclusive evidence retains the original ticket for Agent review. Local model weights are unnecessary for matching. Steps-only omits these image rules.

原等待续接使用原请求，不重放未知输入，不保证自动跨宿主或重开自动继续；小样本结果不构成普遍准确率、模型调用、费用或速度保证。 / Resume original requests without replaying unknown input. Limited evidence does not establish universal reliability or efficiency.

取消停止后续调度；已经发生的输入不会撤销。未审核或效果未知的原票据必须先按现有合同核对，不能用新运行替代原运行。正常重开后需显式连接已有会话，再 Continue 原运行；自动跨宿主接管、工作台重开后自动续跑尚无保证。 / Cancellation prevents further scheduling without undoing prior input. Preserve unresolved original tickets. After reopening, explicitly attach to the existing session and Continue the original run; automatic cross-host or UI-restart continuation is not guaranteed.

## 已验证与限制 / Evidence and limits

本轮[源码验收](verification/CONTINUOUS_EXECUTION_ACCEPTANCE.md)与[安装验收/发布记录](verification/CONTINUOUS_EXECUTION_RELEASE_20261009.md)分别报告。Main 安装版执行与学习限定流程通过，首次零输入失败及修复保留；旧 [preview.2 验收](verification/DECISION_API_RELEASE_ACCEPTANCE_20261008.md)和 preview.1 结果均属历史。 / Main passed scoped installed execution and learning journeys; original zero-input failures and repairs are retained separately from previous preview evidence.

有限实测不构成通用模型用量、准确率、速度或任意应用兼容的保证，具体已测与未测范围见本轮报告。旧便携候选首次自行退出原因未知，其他版本正常启动不代表该根因已修复。 / Bounded measurements do not establish universal model-usage, accuracy, speed or application compatibility. Use the report for tested and untested scope; the historical portable exit remains unexplained.

参见 [上一版实装验收](verification/LEARNING_PREVIEW_RELEASE_ACCEPTANCE_20261007.md)、[工作流接口](WORKFLOW_EDITOR.md)、[外部视觉 API 接入](development/EXTERNAL_VISION_API.md)。 / See previous installed acceptance, workflow interfaces and external vision configuration.
