<div align="center">

[English](README.md) · **简体中文**

<h1>
  <picture>
    <source media="(max-width: 600px)" srcset="docs/assets/readme-hero.zh-CN.mobile.svg">
    <img src="docs/assets/readme-hero.zh-CN.svg" width="1120" alt="Agent Review Instant — 计划、定位、核验、执行、确认">
  </picture>
</h1>

**让你的 AI Agent 连续执行 Windows 桌面任务。**

视觉模型定位目标，Decision 核验当前步骤。<br>
通过后继续执行；未解决的问题交回原主 Agent。

**[下载 v0.1.3](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.3/AgentGUIRuntimeExecution-Setup.exe)** · [快速开始](#quick-start) · [运行架构](#architecture) · [实测表现](#evaluation)

</div>

Agent Review Instant 是面向 MCP Agent 的 Windows 桌面执行运行时。Agent 给出一个短计划，它就可以在应用中导航、点击目标、替换文字、按键和滚动。受支持的步骤在同一会话中执行并核验结果，减少每次成功操作后都返回主 Agent 的等待。

**使用外部视觉 API，不需要本地模型权重或 GPU。** 你可以选择外部视觉 API、支持图像的 Agent，或者本地模型。**执行正式版 0.1.3** 可独立安装；**学习工作台 0.1.0-preview.3** 是可选组件。

## 能做什么

| 能力 | 实际作用 |
| --- | --- |
| **连续完成一个任务** | 在同一会话中运行受支持的 1–8 步计划，例如打开搜索引擎、输入关键词、进入搜索结果。 |
| **只核验当前步骤** | 从截图定位目标，用裁剪和标注后的证据，让 Decision 检查目标位置或本步是否达到要求。 |
| **交回原 Agent 处理异常** | Decision 未通过时，普通 Luna 对同一证据复核一次。仍未解决则携带证据交回原主 Agent；审核后可明确续行，避免重复已完成动作。 |

<a id="quick-start"></a>
## 快速开始

需要 **Windows x64、Python 3.11、[uv](https://docs.astral.sh/uv/getting-started/installation/)** 和支持 MCP 的 Agent。安装器提供源码及配置脚本，首次配置时安装依赖，不附带密钥或模型权重。

1. **[下载安装执行版 0.1.3](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.3)。** 发布页同时提供校验文件。
2. **选择视觉来源。** 使用外部 Luna + Decision 时，复制[视觉配置](configs/vision-api-openai-luna.example.json)和 [Decision 配置](configs/decision-profile.visual-execution.example.json)，让 MCP 进程能够读取 `OPENAI_API_KEY`。
3. **运行配置脚本，接入 Agent。** 按[安装命令](docs/EXECUTION_GUIDE.zh-CN.md#安装与配置)操作，将生成的 `agent-review-instant` MCP 条目合并到客户端后重新连接，保留其他服务器条目。

| 视觉来源 | 需要本地模型吗？ | 配置入口 |
| --- | --- | --- |
| 外部 API | 不需要 | [API 配置与凭证](docs/development/EXTERNAL_VISION_API.md) |
| 当前 Agent 或持续复用的视觉子 Agent | 不需要 | [Agent 接入](AGENT_GUIDE.md) |
| 本地 VISTA-4B | 需要 | [本地配置](FRIEND_SETUP.md) |

默认视觉组合输入需要 Decision 的 auto 模式可用。不配置 Decision 时，仍可使用基础动作和显式 legacy／原生路线，由主 Agent 核验；运行时不会静默切换路线。所有路线都需要本机 Windows 运行时，API 服务商按实际用量收费。

**源码更新（版本仍为 0.1.3）：** Decision 与普通模型复核均可独立配置接口、模型和密钥环境变量，默认仍为 OpenAI Decisions + 普通 Luna。替换服务须兼容 Decisions／Responses 协议；2026-10-15 重打包的 0.1.3 安装器已包含这些配置，已有安装需要重新下载安装。[配置方法与兼容范围 →](docs/development/DECISION_PROVIDERS.zh-CN.md)

<a id="evaluation"></a>
## 工程验证与实测

**同一个完整浏览器任务，连续运行两轮：** 打开 Bing → 搜索“Rust standard library collections documentation”→ 打开第一个普通结果。两轮均使用已安装的 0.1.3 候选，沿用同一窗口和会话。

| 完整计划耗时 · 第一／二轮 | API token · 两轮合计 | 发布前回归 |
| :---: | :---: | :---: |
| **30.8 秒／27.4 秒** | **41,097** | **1,029 项检查通过** |
| 精确值：30.809 秒／27.354 秒 | 20 次 Decision + 6 次定位 | 52 个选定测试文件 |

两轮均没有主 Agent 接管，也没有调用普通 Luna 复核。这是指定任务的完整计划用时，**不是与旧版进行受控对比得出的提速数据**。API token 不含主 Agent 和工作子 Agent 的套餐用量。检查数量是 0.1.3 发布时的快照，不代表实时 CI 状态。[查看计时、取消与恢复证据 →](docs/verification/EXECUTION_SPEED_20261015.md)

提示词评测包含 **39 张真实界面截图、30 个场景族**。保留集三分类标签一致率由 **92.5% 提升至 95.0%**，Decision 输入 token 减少 **1.64%**。通过／不通过准确率仍为 95%；两级最终结果仍为 149/160，当前提示词下包含 7 次误放和 1 次误拒。标签由 AI 复核，**这些数据不等于通用 GUI 任务成功率**。[查看方法、数据划分与失败案例 →](docs/verification/DECISION_PROMPT_BENCHMARK_20261015.md)

<a id="architecture"></a>
## 如何运行

**用户下达任务 → 主 Agent 给出计划 → 定位 → 核验 → 执行 → 确认结果 → 继续**

视觉模型提供坐标，OpenAI Decisions API 通过 Choice 核验目标或当前步骤的结果。有效通过则继续；未通过时由普通 Luna 复核一次，仍未解决再交回原主 Agent。Decision 不替代主 Agent 规划任务。

运行时将证据绑定到请求、窗口和截图，校验坐标与截图新鲜度。默认执行走视觉路线，UIA 留给学习模式和显式原生路线。持续复用同一会话，同一时间仅保留一个桌面输入执行者。

**0.1.3 的改进：** 复用观察结果、预装计划、保留 HTTP 连接，减少重复准备；安装版两轮任务减少了 10 次外层重复截图。主 Agent 可基于绑定证据审核已完成步骤并续行，无需重复该动作。

[详细执行流程 →](docs/EXECUTION_GUIDE.zh-CN.md#decision-和视觉模型如何配合) · [任务计划协议 →](docs/development/TASK_PLAN.md) · [Choice 协议 →](docs/development/DECISION_CHOICE.md)

## 可选的学习工作台

采集可复用界面和工作流，在复用前由人工审核、修改。**学习工作台 0.1.0-preview.3** 有独立安装器，执行模式不依赖它；本次执行版更新不包含学习版更新。

[学习版快速开始](docs/LEARNING_PREVIEW_QUICKSTART.md) · [下载学习版](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/learning-v0.1.0-preview.3)

## 当前限制

- 模型可能误拒，也可能误放。第一层误放会跳过二次复核，这是已知限制；不承诺任意任务都能无人干预完成。
- 安装器未签名。本轮验收使用已有 Python 环境，尚未验证全新机器的首次依赖安装。[发布范围与历史记录](docs/EXECUTION_GUIDE.zh-CN.md#发布边界与历史记录)

## 文档导航

| 开始使用 | 理解架构与接入 |
| --- | --- |
| [安装指南](FRIEND_SETUP.md) | [执行详细指南与完整流程图](docs/EXECUTION_GUIDE.zh-CN.md) |
| [Agent / MCP 指南](AGENT_GUIDE.md) | [Decision API 配置](docs/development/DECISION_API.md) |
| [外部视觉 API](docs/development/EXTERNAL_VISION_API.md) | [视觉文字输入](docs/development/VISUAL_EXECUTION_INPUT.md) |
| [发布说明与校验文件](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.3) | [计时与验收记录](docs/verification/EXECUTION_SPEED_20261015.md) |

---

[ISC 许可证](LICENSE)。依赖和模型权重遵循各自许可证。横幅为工作流程示意，不是实机录屏。
