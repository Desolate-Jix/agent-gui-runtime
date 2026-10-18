# 2026-10-07 当前release-ready状态 / Current release-ready status

第三批source14/GUI12已完成匹配冻结与实装限定验收，状态为release-ready。Main与独立Sol各记录2个教学事件、6个预期连续场景（5个正例完成，负例一次点击后判失败，无重复输入）；GUI Save原job为completed并返回captured状态的动作后截图，关闭重开后图像关闭选项保持，最终cleanup完成。第一批终态JSON读取失败及第二批空标题清除绑定失败原记录保留；旧便携candidate02未知退出未宣称修复，stablev0.1.1保持原发布。网络发布与下载核对单独记录在对应发行页。 / The matched third source14/GUI12 pair is release-ready after bounded installed acceptance. Main and independent Sol each recorded two teaching events and six expected continuous cases: five positive completions and one negative failure after a single click without replay. The original GUI Save job completed with captured post-action evidence; image disablement persisted across close/reopen and cleanup completed. Both earlier failures and the unexplained excluded portable exit remain historical. Stablev0.1.1 is unchanged; publication and download verification are recorded separately on the release page.

当前安装包含默认图像规则提议、人工区域编辑及可关闭图像核验；不确定保留原请求交Agent审核，不重放输入。流程图引用图钉固定的界面版本，附加成员不自动创建跳转。GUI页签为“结果与读取”。本地模型权重可选；本轮没有新增真实API供应商测试，不宣称通用准确率、速度或模型用量收益。 / Current installers include default image proposals, editable regions and persistent disablement. Uncertain evidence retains the original request for Agent review without replay. Graphs pin interface versions and membership does not create transitions. The GUI tab is Results and readback. Local weights are optional; no new real API-provider tests or general accuracy, speed or usage claims.

| 组件 / Component | 版本 / Version | 冻结批次 / Frozen pair | Setup SHA256 |
|---|---|---|---|
| 执行 / Execution | `0.1.2-preview.1` | source14 / installers-execution-13 | `fc8e343549d84d3deceb3d116451bc739729402fdefc2b5a1ba5a097e96ea5e7` |
| 可选学习 / Optional learning | `0.1.0-preview.1` | GUI12 / installers-learning-12 | `d67443fdb9c77d60db4063a66b501e1be1ae45baf9c2af2b2a8cbecad86728b9` |

[最终限定验收 / Final bounded acceptance](verification/LEARNING_PREVIEW_RELEASE_ACCEPTANCE_20261007.md)。下方原段落为原冻结时点历史记录；版本与限制以本节及最终验收为准，不覆盖首次失败。 / Original sections below describe historical freezes; use this section and final acceptance for current scope while preserving first failures.

---

# 可选学习工作台测试版使用说明 / Optional learning preview guide

学习组件 `0.1.0-preview.1`、兼容执行组件 `0.1.2-preview.1` 分别安装，学习是可选组件。 / Install the learning and compatible execution components separately; learning is optional. 本页描述候选的安装、使用与限定验收；[预定发行地址](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/learning-v0.1.0-preview.1)尚未发布，当前安装器不含最新图像改动。 / This page describes prior candidate installation and bounded acceptance. The planned release URL is unpublished; those installers lack the latest image changes.

## 选择组件 / Choose components

| 需要做什么 / Goal | 安装什么 / Component |
|---|---|
| 仅执行任务 / Execute tasks | 执行组件；学习工作台不是必需品 / Execution; learning is optional |
| 离线审核与修改库 / Offline library editing | 学习工作台；不需要执行宿主或模型 / Learning; no host or model |
| 采集教学与复用流程 / Teach and reuse workflows | 两组件，并连接兼容的已有执行会话 / Both, attached to a compatible existing session |

两个安装目录可以不同。学习 EXE 包含其界面运行依赖，不包含执行宿主、模型或用户库。执行安装器提供维护运行时，仍需按 [安装配置说明](../FRIEND_SETUP.md) 准备所选路线的环境与 MCP 配置。 / The two installation roots may differ. Learning bundles its UI dependencies, but no host, model or user library. Configure the execution runtime and MCP using the setup guide.

**本地模型可选。** 外部视觉 API、当前支持图像的 Agent、客户端明确配置的视觉委派都可使用；只有 `local` 路线要求本地模型权重。API 的端点、模型与密钥环境变量由用户配置。尚未接入的未来决策 API 不影响现有路线。 / Local models are optional. Only local grounding requires weights. Configure an external API or an image-capable current/delegated Agent explicitly; the future decision API is not required.

## 打开学习库 / Open a library

首次打开工作台，选择一个已有、可写的数据根目录，例如 `D:/AgentLearningData`。程序在其中使用 `memory-library`；重开仍选择原数据根，避免把子目录误当新根。将数据放在安装目录外，分别升级或卸载组件时保留自己的库。 / Select an existing writable data root. Reopen that root rather than its memory-library subfolder, and keep it outside the installation.

“设置 → 语言 → 简体中文 / English”切换界面语言并记忆选择。用户标题、备注、输入值、日志和截图保留原文。 / Settings → Language switches and remembers the UI locale; user content and original evidence are unchanged.

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

当前同冻结 Main 与独立 Sol 两组参数均完成填写、原图读取与结果核验，并正常清理；Main已复核原件。 / Main and independent Sol completed both parameter runs, original-image reading, result review and cleanup on the same frozen pair, with Main reviewing originals.

尚无减少模型调用、提高准确率、提速或任意应用兼容的结论。真实 API 服务商连通与准确率没有在本轮新增测试。旧便携候选首次自行退出原因未知；新候选正常启动不代表该根因已修复。 / No efficiency, accuracy, universal application or new live-provider claim is established. The historical portable exit remains unexplained.

参见 [实装验收记录](verification/LEARNING_PREVIEW_NATIVE_ACCEPTANCE.md)、[工作流接口](WORKFLOW_EDITOR.md)、[外部 API 接入](development/EXTERNAL_VISION_API.md)。 / See the installed acceptance record, workflow interface and API guide.
