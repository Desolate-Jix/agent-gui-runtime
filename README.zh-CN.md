执行版 **0.1.9** 修复任务计划的维护结算。受影响的 0.1.8 用户可先用新版核验器结算，再正常确认升级，见[恢复步骤](docs/RUNTIME_018_SETTLEMENT_RECOVERY.md)。[发布与下载](docs/releases/EXECUTION_019_20261027.md)。Amadeus **0.0.6 连接器**更新推荐 Runtime；[商店审核 #11](https://github.com/Code-Amadeus/Amadeus-Extensions/pull/11) 与发行下载分别处理。Host 扩展确认更新需使用包含 [PR #261](https://github.com/Code-Amadeus/Amadeus/pull/261) 的构建。学习开发保持暂停，见[封存说明](docs/LEARNING_PAUSED.md)。

<div align="center">

[English](README.md) · **简体中文**

<h1>
  <picture>
    <source media="(max-width: 600px)" srcset="docs/assets/readme-hero.zh-CN.mobile.svg">
    <img src="docs/assets/readme-hero.zh-CN.svg" width="1120" alt="Agent Review Instant — 计划、定位、核验、执行、确认">
  </picture>
</h1>

**执行版 0.1.9 — 执行有核验，更新由你确认。**

支持图像的 Agent 读取目标与结果。<br>
Runtime 保留原始证据、输入门禁和动作回执。

**[下载执行版 0.1.9](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.9/AgentGUIRuntimeExecution-Setup.exe)** · [实录演示](#demos) · [快速开始](#quick-start) · [运行架构](#architecture) · [实测表现](#evaluation)

**保留的 API 路线恢复：** 点击前两层模型均未接受目标时，Main 可查看绑定截图、明确审核，再单独继续同一任务；已结算文字输入的审核续行也继续保留，不重复输入。[验收与限制 →](docs/verification/MAIN_PRE_ACTION_REVIEW_20261023.md)

</div>

Agent Review Instant 是面向 MCP Agent 的 Windows 桌面执行运行时。Agent 给出一份明确的线性计划，它就可以在应用中导航、点击目标、替换文字、按键和滚动。受支持的步骤在同一会话中执行并核验结果，减少每次成功操作后都返回主 Agent 的等待。

选择 **使用当前 Agent**，由已连接且支持图像的主 Agent 定位、核验；或选择 **使用外部模型 API**，由 Runtime 调用服务完成视觉核验。两者均不需要本地模型权重或 GPU。本地模型与委派识图保留为高级选项。

**当前 Agent 模式（0.1.7 引入）：** `--current-agent` 提供持久的基础点击闭环，无需另配 Runtime 视觉或 Decision API，仍依赖承载 Agent 的服务并消耗其额度。文字输入、按键、滚动、任务计划和管理员模式不在该适配层支持范围。[配置与能力矩阵](docs/development/CURRENT_AGENT_MODE.zh-CN.md)。

## 0.1.9 新增内容

- **按原计划证据结算：** 对已完成、已证明取消的任务计划，维护入口核对冻结计划、runner 和输入回执；活动／未知输入及证据不完整仍阻止安装。
- **处理受影响的 0.1.8 安装：** 从独立核验的新发行目录运行维护脚本检查旧安装，再正常确认升级，不删除任务登记。见[恢复流程](docs/RUNTIME_018_SETTLEMENT_RECOVERY.md)。
- **Amadeus 连接器 0.0.6：** 推荐 Runtime 0.1.9，连接设置、权限和同会话 Main 审核续行不变。见[发布范围与验证](docs/releases/EXECUTION_019_20261027.md)。不新增速度、准确率或 token 节省结论。

## 上一版：0.1.8

- **自动检查，确认后安装：** 启动时在后台检查稳定版，每天最多一次，可关闭。通过 `update_runtime.ps1 -Action stage` 下载核验，再用 `-Action apply` 明确确认确切目标后安装。
- **保留运行中的任务：** 安装级锁和原会话清理证据阻止客户端、宿主、模型 worker 或未结算输入尚存时进行维护，更新器不会为了安装而关闭任务。
- **恢复已验证版本：** 保留备份与持久事务日志，进行无输入安装健康检查，失败时回滚；中断更新提供外部恢复入口，未知状态保留备份并阻止继续。兼容补丁不要求更换 Amadeus wheel。[命令与边界](docs/RUNTIME_UPDATES.zh-CN.md) · [发布记录](docs/releases/EXECUTION_018_20261024.md)。

## 上一版本：0.1.7

- **原图与原任务闭环：** prepare → 读取原图 → resolve → continue → 读取后图 → verify；同一连接、单输入所有者，pending 只读原 ID，不重放未知输入。
- **源码实测：** 7-Zip 同连接 20 步通过；错 hash、不确定判断、完成后输入均被阻止，定位等待中的取消到达真实 cancelled、未输入且清理通过。未使用独立视觉／Decision 配置或服务密钥。[实机证据](docs/verification/CURRENT_AGENT_LIVE_20261024.md)。安装版 0.1.7 另测计算器 C → 1 → + → 2 → = 显示 3，逐帧由 Agent 读取核验；动作后取消、定位等待取消及清理均通过。[安装证据与发布记录](docs/releases/EXECUTION_017_20261024.md)。
- **更新边界：** 兼容的 HTTP 合同不要求每个 Runtime 补丁重装未变化的 wheel。Runtime 与 Amadeus 扩展分别发布和管理版本。

## 上一版本：0.1.6

- **通过 HTTP MCP 接入 Amadeus：** 保留 stdio，新增仅绑定本机、带鉴权的服务入口。可选的 0.0.4 扩展为 Pi 提供连接声明和执行 Skill；Runtime 仍需单独安装、启动。[扩展安装说明](integrations/amadeus/agent-review-instant/README.zh-CN.md)。
- **点击前也可由 Main 兜底：** Decision 与普通 Luna 均未通过时，返回原候选和绑定的操作前截图，供 Main 明确审核、单独继续同一任务。已完成输入不会重放，输入授权、截图新鲜度和取消检查继续保留。
- **修复队列续行：** 临时命令队列锁竞争不再被误记为永久任务绑定失效。Decision／Luna 的阈值、提示词和默认服务均未改动。
- **限定范围验收：** 本体五步、原生 Amadeus／Pi 四步流程均在显式 TEST 双拒、实际 Main 看图审核后完成。Python 3.11 和 3.12 各通过 188 项相关回归。这些是功能恢复结果，不是新的速度、准确率或 token 节省结论。[证据与已知限制](docs/verification/MAIN_PRE_ACTION_REVIEW_20261023.md)。

<a id="demos"></a>

## 实录演示（0.1.4）

以下为 **0.1.4** 已发布视频的压缩预览，降低尺寸与帧率，**不加速播放**。浏览器与记事本片剪去了开头等待，GIF 长度不代表性能。[完整视频与真实计划耗时 →](#evaluation)

<p align="center">
  <a href="https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Browser.mp4">
    <img src="docs/assets/demos/browser-0.1.4.gif" alt="浏览器：Google URL、搜索 java、首个普通结果">
  </a>
</p>

Google URL → 搜索 java → 打开首个普通结果。[完整 MP4](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Browser.mp4)

<p align="center">
  <a href="https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Notepad-FullWindow.mp4">
    <img src="docs/assets/demos/notepad-0.1.4.gif" alt="记事本：编辑便笺、打开 File、Save">
  </a>
</p>

编辑便笺 → File → Save。[完整 MP4](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Notepad-FullWindow.mp4)

<p align="center">
  <a href="https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-7Zip.mp4">
    <img src="docs/assets/demos/7zip-0.1.4.gif" alt="7-Zip：导航目录及预制 ZIP">
  </a>
</p>

导航 A → nested → Up → root → B → bundle.zip。[完整 MP4](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-7Zip.mp4)

## 能做什么

| 能力 | 实际作用 |
| --- | --- |
| **连续完成一个任务** | 在同一会话中连续执行多步任务，例如打开搜索引擎、输入关键词、进入搜索结果。 |
| **只核验当前步骤** | 从截图定位目标，用裁剪和标注后的证据，让 Decision 检查目标位置或本步是否达到要求。 |
| **交回原 Agent 处理异常** | Decision 未通过时，普通 Luna 对同一证据复核一次。仍未解决则携带证据交回原主 Agent；审核后可明确续行，避免重复已完成动作。 |

<a id="quick-start"></a>
## 快速开始

需要 **Windows x64、[uv](https://docs.astral.sh/uv/getting-started/installation/)** 和支持 MCP 的 Agent。**API／Agent 路线推荐 Python 3.12**，可继续使用已有的 3.11 环境；**本地模型路线仍使用 Python 3.11**。安装器提供源码及配置脚本，首次配置时安装依赖，不附带密钥或模型权重。

1. **[下载并安装执行版 0.1.9](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.9)。** 下载、摘要及验证见[发布记录](docs/releases/EXECUTION_019_20261027.md)。0.1.7 及更早版本需手动安装；受影响的 0.1.8 任务计划登记需先按[结算流程](docs/RUNTIME_018_SETTLEMENT_RECOVERY.md)处理。
2. **选择下方运行方式。** 使用外部 Luna + Decision 时，复制[视觉配置](configs/vision-api-openai-luna.example.json)和 [Decision 配置](configs/decision-profile.visual-execution.example.json)，让 MCP 进程能够读取 `OPENAI_API_KEY`。当前 Agent 点击流程使用 0.1.7 入口，并声明客户端真实图像／视觉能力。
3. **运行配置脚本，接入 Agent。** 按[安装命令](docs/EXECUTION_GUIDE.zh-CN.md#安装与配置)操作，将生成的 `agent-review-instant` MCP 条目合并到客户端后重新连接，保留其他服务器条目。

| 主要方式 | 谁负责定位与核验？ | 配置入口 |
| --- | --- | --- |
| **使用当前 Agent** | 已连接的主 Agent；不另配 Runtime 视觉／Decision API，消耗承载 Agent 的服务额度。 | [0.1.7 入口与支持的点击闭环](docs/development/CURRENT_AGENT_MODE.zh-CN.md) |
| **使用外部模型 API** | Runtime 调用已配置的视觉与 Decision 服务，按服务商实际用量收费。 | [API 配置与凭证](docs/development/EXTERNAL_VISION_API.md) |

高级选项：[本地 VISTA-4B](FRIEND_SETUP.md) 需要权重和本地依赖；[委派识图](AGENT_GUIDE.md) 使用选定且持续复用的视觉 Agent 会话。

默认视觉组合输入需要 Decision 的 auto 模式可用。不配置 Decision 时，仍可使用基础动作和显式 legacy／原生路线，由主 Agent 核验；运行时不会静默切换路线。所有路线都需要本机 Windows 运行时，API 服务商按实际用量收费。

**0.1.6 的服务配置：** Decision 与普通模型复核均可独立配置接口、模型和密钥环境变量，默认仍为 OpenAI Decisions + 普通 Luna；替换服务须兼容 Decisions／Responses 协议。这些设置首次包含于 2026-10-15 重打包的 0.1.3 安装器。[配置方法与兼容范围 →](docs/development/DECISION_PROVIDERS.zh-CN.md)

**Amadeus／Pi：** 下载 [HTTP MCP＋Skill 连接器 0.0.6](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/amadeus-extension-v0.0.6/amadeus_agent_gui_runtime-0.0.6-py3-none-any.whl)，按[连接器安装指南](integrations/amadeus/agent-review-instant/README.zh-CN.md)配置。Runtime 需另外安装、启动，推荐使用 0.1.9。请核对实际版本及必要的 HTTP／审核能力。目录审核期间可手动导入 wheel。[旧 0.0.2 stdio 指南](integrations/amadeus/agent-review-instant/README.stdio-0.0.2.zh-CN.md)继续封存，不能直接套用其配置。

<a id="evaluation"></a>
旧 wheel 与下载地址保持原字节。0.0.6 连接器更新推荐 Runtime，连接键和权限不变，不代表已验证 Amadeus 当前 Agent 模式。见[当前发布范围](docs/releases/EXECUTION_019_20261027.md)、[0.0.5 历史验证](docs/verification/AMADEUS_CONNECTOR_005_20261026.md)及 [Runtime 更新说明](docs/RUNTIME_UPDATES.zh-CN.md)。停用或卸载连接器不会停止或卸载外部 Runtime。

## 工程验证与实测

**0.1.7 当前 Agent 源码实测：** 同连接 7-Zip 20 步及独立负控通过，详见[原图、回执与取消记录](docs/verification/CURRENT_AGENT_LIVE_20261024.md)。独立安装态计算器五次点击、取消负控与清理也已通过，见[发布记录](docs/releases/EXECUTION_017_20261024.md)；本轮不形成性能、成本节省比例或通用成功率结论。

**0.1.5 同版本更新 — 构建 20261017-01：** Enter 后自适应观察，当前结果复核与下一步只读定位并行。新安装包使用同一冻结载荷完成以下任务：

| 安装态任务 | 第一轮 | 第二轮 | 两轮 API 请求合计 | 两轮已报告 token 合计 |
| --- | ---: | ---: | ---: | ---: |
| 记事本：编辑 → File → Save | **20.744 秒** | **18.191 秒** | 21 | 37,482 |
| Edge：Bing → 搜索 → 维基百科文章 | **27.043 秒** | **27.430 秒** | 27 | 42,111 |
| 7-Zip：目录／预制 ZIP 浏览 | **25.918 秒** | **24.324 秒** | 18 | 47,585 |

**六个计划／18 步均首次自动完成。** Main 验收记事本和 Edge，独立 Sol 验收 7-Zip；原始截图、记事本磁盘内容精确核对及本轮窗口／宿主收尾均通过。表中每轮是包含视觉核验的完整三步计划，耗时不含启动、轮间人工查看和收尾。7-Zip 未测试压缩或解压。

安装态共 **66 次 API：定位 18＋Decision 46＋普通复核 2；127,178 个已报告 token**，无缺失用量。预取消费副本只计一次，不含 Main／工作 Agent 套餐用量；限定场景通过不等于通用成功率。

**真实动作间隔，源码 A → B：** **记事本 5.803→5.597 秒、7-Zip 7.805→7.254 秒、Edge 10.786→9.280 秒**。按相邻逻辑步骤的首次真实鼠标按下统计中位数，每应用／组四个匹配区间。A 已含此前普通点击／SSL 优化，B 再加入 Enter 观察和并行，并非旧安装器与新安装器的直接对照。Edge 的一轮 B 比 A 慢，模型、网络和缓存波动未受控。**尚未达到四秒操作间隔目标。** 模型、提示词及通过规则不变。

**验证：** 395 项相关检查通过；竞态修复后 82 项重叠检查通过，不相加为独立测试数。实测前后 **659 个安装载荷文件哈希**一致；新建隔离 Python 3.11 环境，安装 **45 个锁定 API 路线依赖**，真实功能入口验证通过。[完整测量、源码对照用量与限制 →](docs/verification/EXECUTION_015_REFRESH_20261017.md) · [日期安装包与校验文件 →](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5)

**0.1.5 原构建的已安装 Amadeus／Pi 路线：** 两项正常合成记事本任务完成六步、磁盘精确核对与收尾；无 Main 语义接管，外层自纠错仍保留。最终源码回归 **135 项通过**。最终安装包另经独立验收，三步记事本计划首次通过，**27.70 秒／10 次 API 请求**，文件内容与收尾通过。这是单个限定样本，总 token 数未知。[范围与限制 →](docs/verification/AMADEUS_PI_MAIN_REVIEW_20261015.md) · [发布说明与校验文件 →](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5)

**0.1.4 历史安装态任务，浏览器之外：** 通过维护的视觉执行路线，在记事本和 7-Zip 中使用全新内容。

| 任务 | 实际结果 | 计划耗时 |
| --- | --- | ---: |
| 记事本第一轮：编辑 → File → Save | 3 步全部自动完成，保存的 UTF-8 alpha 内容完全匹配 | 30.621 秒 |
| 记事本同窗口第二轮 | 3 步全部自动完成，保存的 UTF-8 beta 内容完全匹配 | 22.873 秒 |
| 7-Zip：A → nested → Up → root → B → bundle.zip | 6 步全部自动完成，压缩包内 package 目录可见 | 69.515 秒 |

安装版 12 步全部无 Main 审核完成，一次普通复核自动解决。本轮窗口关闭及宿主收尾通过。独立 Sol 随后完成全新记事本 3 步和 7-Zip 3 步任务，磁盘／原图核对及收尾通过。7-Zip 范围为目录及预制 ZIP 导航，没有测试压缩或解压。

**0.1.4 历史实录演示：** [记事本，完整窗口](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Notepad-FullWindow.mp4) · [浏览器](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Browser.mp4) · [7-Zip](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-7Zip.mp4)。新记事本／浏览器片剪掉首次等待，保留首次输入前约 1 秒；后续动作和等待均为 **1× 原速**，无旁白。成片为 **19.8 秒／27.2 秒**，原始完整三步计划耗时为 **28.0 秒／31.4 秒**。[录制范围与剪辑说明 →](docs/verification/DEMO_RECORDING_20261015.md)

另有历史 0.1.4 source02 的 **12 步计划及后续 4 步**证据。非空线性计划不设固定步数上限，预算及证据检查继续有效。此前源码误拒及公共客户端回执上限导致的失败，继续记为失败。[本轮结果、精确计时及失败历史 →](docs/verification/MULTI_APP_EXECUTION_20261015.md) · [长计划回归 →](docs/verification/UNBOUNDED_TASK_PLANS_20261015.md)

**0.1.3 历史浏览器任务：** 安装候选在同一窗口／会话中两轮完成 Bing → Rust collections 文档，耗时 **30.809 秒／27.354 秒**，使用 **41,097 个 API token**，无 Main 接管或普通 Luna 复核。这些是历史指定任务耗时，不构成受控提速比较；token 不含 Main／worker 套餐用量。[计时与恢复证据 →](docs/verification/EXECUTION_SPEED_20261015.md) · [逐操作拆分 →](docs/verification/EXECUTION_OPERATION_TIMINGS_20261015.md)

0.1.3 历史提示词评测包含 **39 张真实界面截图、30 个场景族**。保留集三分类标签一致率由 **92.5% 提升至 95.0%**，Decision 输入 token 减少 **1.64%**。通过／不通过准确率仍为 95%；两级最终结果仍为 149/160，当前提示词下包含 7 次误放和 1 次误拒。标签由 AI 复核，**这些数据不等于通用 GUI 任务成功率**。[查看方法、数据划分与失败案例 →](docs/verification/DECISION_PROMPT_BENCHMARK_20261015.md)


<a id="architecture"></a>
## 如何运行

**用户下达任务 → 主 Agent 给出计划 → 定位 → 核验 → 执行 → 确认结果 → 继续**

当前 Agent 模式由已连接的 Agent 读原图、定位并判断后图。已配置的 API 路线由视觉模型提供坐标，OpenAI Decisions API 通过 Choice 核验目标或本步结果。有效通过则继续；未通过时由普通 Luna 复核一次，仍未解决再交回原主 Agent。Decision 不替代主 Agent 规划任务。

运行时将证据绑定到请求、窗口和截图，校验坐标与截图新鲜度。默认执行走视觉路线，UIA 保留为显式原生路线。持续复用同一会话，同一时间仅保留一个桌面输入执行者。

**0.1.3 的改进：** 复用观察结果、预装计划、保留 HTTP 连接，减少重复准备；安装版两轮任务减少了 10 次外层重复截图。主 Agent 可基于绑定证据审核已完成步骤并续行，无需重复该动作。

**历史 0.1.5 — 文字输入 Main 审核：** 已结算文字输入后的双模型非通过判断通过认证后，读取绑定原图，明确继续同一命令，不重复输入。余下提交动作仍保留 fresh-target 与结果核验门禁。旧 live04 在未发布载荷上使用显式 TEST 注入，不是自然误拒或性能结果。[合同 →](docs/development/MAIN_FIELD_REVIEW_RESUME.md) · [验收与限制 →](docs/verification/AMADEUS_PI_MAIN_REVIEW_20261015.md)

[详细执行流程 →](docs/EXECUTION_GUIDE.zh-CN.md#decision-和视觉模型如何配合) · [任务计划协议 →](docs/development/TASK_PLAN.md) · [Choice 协议 →](docs/development/DECISION_CHOICE.md)

## 当前限制

- **当前 Agent 适配层仅支持基础点击。** 不支持文字输入、按键、滚动、任务计划、自动跨窗、重启续跑或管理员／UAC；既有 API／legacy 功能保留各自合同。

- **自 0.1.4 起的线性计划：** 非空计划不设固定步数上限；唯一步骤 ID、逐步核验、内容大小限制、证据检查、取消和 API／时间预算继续有效。已有 0.1.3 安装在升级前保留构建时协议。[源码验证](docs/verification/UNBOUNDED_TASK_PLANS_20261015.md)

- 模型可能误拒，也可能误放。第一层误放会跳过二次复核，这是已知限制；不承诺任意任务都能无人干预完成。
- 安装器未签名。API 依赖已在隔离 Python 3.12 环境检查；未新增全新机器配置及正常注册表／快捷方式集成验收。Pi 完整回执仍较冗长，本版不宣称节省 token。[发布范围与历史记录](docs/EXECUTION_GUIDE.zh-CN.md#发布边界与历史记录)

## 文档导航

| 开始使用 | 理解架构与接入 |
| --- | --- |
| [安装指南](FRIEND_SETUP.md) | [执行详细指南与完整流程图](docs/EXECUTION_GUIDE.zh-CN.md) |
| [Agent / MCP 指南](AGENT_GUIDE.md) | [Decision API 配置](docs/development/DECISION_API.md) |
| [外部视觉 API](docs/development/EXTERNAL_VISION_API.md) | [视觉文字输入](docs/development/VISUAL_EXECUTION_INPUT.md) |
| [0.1.9 发布记录与校验文件](docs/releases/EXECUTION_019_20261027.md) | [0.1.4 历史多应用证据](docs/verification/MULTI_APP_EXECUTION_20261015.md) |

---

[ISC 许可证](LICENSE)。依赖和模型权重遵循各自许可证。横幅为工作流程示意，不是实机录屏。

## 可选 benchmark 数据

[Benchmark 备份](https://github.com/Desolate-Jix/agent-gui-runtime-benchmarks) 保存在独立的**公开仓库**，可按需下载。冻结套件包含 **39 张原图、30 个界面族、254 个标注案例**。数据集图片、标注和原始评测记录不随执行安装器分发，安装时也不会自动下载；需要时单独克隆。
