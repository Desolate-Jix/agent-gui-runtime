# Agent Review Instant

> **不强制使用本地模型。** 可以选择外部视觉 API、当前支持图像的 Agent，或客户端指定的视觉子 Agent；这些路线都不需要下载 VISTA 权重。只有选择 `local` 时，才需要安装本地识别依赖并准备模型。使用 API 仍需在本机运行执行框架，但识图由所配置的服务完成。
> **Local models are optional.** Choose an external vision API, the current image-capable agent or an explicitly selected vision delegate without downloading VISTA weights. Only `local` requires local recognition dependencies and weights. The execution runtime still runs on your PC when using an API; the configured service handles visual grounding.

| 使用方式 / Mode | 本地模型是否必需 / Local model required? | 需要准备 / Setup |
|---|---|---|
| 外部视觉 API / `external_api` | **不需要 / No** | 支持图像与 JSON 协议的服务端点、视觉模型 ID、密钥环境变量 / Image/JSON endpoint, vision model ID and secret environment variable |
| 当前 Agent 或视觉子 Agent / `agent_current`, `agent_delegate` | **不需要 / No** | 支持图像的当前 Agent，或客户端显式配置的视觉委派 / Image-capable current agent or client-configured vision delegate |
| 本地模型 / `local` | **需要 / Yes** | VISTA 权重、本地识别依赖与相应硬件 / VISTA weights, local recognition dependencies and suitable hardware |



## 可选学习工作台测试版已发布 / Optional learning preview released

2026-10-07 已发布学习工作台 **0.1.0-preview.1** 与兼容执行组件 **0.1.2-preview.1**：[下载两个独立安装器 / Download independent installers](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/learning-v0.1.0-preview.1)。稳定执行版 `v0.1.1` 继续保留。 / The optional learning preview and compatible execution preview are published; stable execution v0.1.1 remains available.

| 安装器 / Installer | 用途 / Purpose |
|---|---|
| `AgentGUIRuntimeExecutionPreview-Setup.exe` | 独立执行框架；可使用外部视觉 API、当前 Agent、视觉子 Agent 或本地模型 / Standalone execution with configured API, current/delegated Agent or local grounding |
| `AgentLearningWorkbenchPreview-Setup.exe` | 可选学习库界面；生成的工作流可审核、修改、保存和重开，支持简体中文与 English / Optional bilingual workbench for review, editing, saving and reopening learned workflows |

**学习模式不是执行模式的必需品，本地模型也不是必需品。** 学习工作台可以离线管理库；采集教学或运行任务时，显式连接兼容执行组件的已有会话。API / Agent 识图与本地图像匹配均不要求 VISTA 权重。 / **Learning and local models are optional.** Edit libraries offline; explicitly attach to compatible execution for teaching/trials. API/Agent vision and local template matching need no VISTA weights.

有判别证据的学习跳转默认提议图像核验；审核后明确匹配便继续，不匹配或不确定时保留原请求交给 Agent 审核。用户可修改稳定区域和阈值，或关闭后保存。 / Distinguishable learned transitions propose image checks by default. Reviewed matches advance; unmatched/uncertain evidence preserves the original request for Agent review. Users can edit stable regions/thresholds or persistently disable checks.

[预览安装与使用 / Preview quickstart](https://github.com/Desolate-Jix/agent-gui-runtime/blob/3cd9b989c11592595ae5e63bd6dd183d33554068/docs/LEARNING_PREVIEW_QUICKSTART.md) · [图像核验说明 / Image checks](https://github.com/Desolate-Jix/agent-gui-runtime/blob/3cd9b989c11592595ae5e63bd6dd183d33554068/docs/LEARNING_IMAGE_VERIFICATION.md) · [验收范围与限制 / Acceptance and limits](https://github.com/Desolate-Jix/agent-gui-runtime/blob/3cd9b989c11592595ae5e63bd6dd183d33554068/docs/verification/LEARNING_PREVIEW_RELEASE_ACCEPTANCE_20261007.md)

同一最终安装载荷完成 Main 与独立 Sol 的全新教学、连续使用、保存后截图、关闭重开和正常清理；仅为本轮受控场景，不宣称通用准确率、速度或模型用量收益，本轮没有新增真实 API 供应商测试。 / Fresh same-payload acceptance covers teaching, continuous use, Save observation, reopening and cleanup within controlled cases; no general accuracy, performance, model-usage or new live-provider claim.

本 `main` 分支保留稳定执行版源码；学习预览源码以 `learning-v0.1.0-preview.1` 标签为准。下方执行配置说明主要针对稳定源码版，预览 EXE 的安装方法见上方使用说明。 / This main branch retains stable execution source; use the learning preview tag for preview source. The execution setup below primarily describes the stable source bundle; see the quickstart above for preview EXE installation.

> v0.1.1 执行模式正式补丁：源码与隔离包各 2086 项、STDIO 七工具检查通过。本方与独立 Agent 在同一冻结运行时完成全新原生连续使用、429 恢复和最终清理，双方原始回执／PNG／trace 审计通过。首次 identity 拒绝原因未定；Note 定位 fixture 修复经 19 项离线检查、长中英前缀本方回归及独立复测通过，未修改冻结运行时。见 [验收记录](docs/verification/V011_RELEASE_ACCEPTANCE.md)。 / v0.1.1 execution patch: source and isolated bundle each passed 2086 checks, plus seven-tool STDIO. Main-agent and independent fresh native continuous journeys, 429 recovery and cleanup passed on the same frozen runtime, with original receipt/PNG/trace audit. The initial identity-rejection cause remains unresolved; the Note-target fixture correction passed 19 offline checks, long Chinese/English-prefix regression and independent retesting without changing the frozen runtime.
**Windows GUI execution runtime for MCP agents / 面向 MCP Agent 的 Windows 图形界面执行框架**

Agent 负责理解任务、决定下一步和判断结果；框架负责观察真实界面、定位目标、派发操作、返回证据与管理本地资源。它不是另一个自主决策 Agent，也不是网页管理面板。

The connected agent plans and judges outcomes. This runtime observes real Windows interfaces, grounds targets, dispatches actions and returns evidence. It is an execution layer, not an autonomous planner or web management console.

> **稳定执行版：v0.1.1 · 学习测试版：0.1.0-preview.1（可选独立安装）。**
> **Stable execution: v0.1.1 · optional learning preview: 0.1.0-preview.1.**
>
> **稳定 v0.1.1 包只包含执行模式；学习测试版已经发布，使用上方两个独立安装器。**
> **Stable v0.1.1 is execution only; the learning preview is published through the separate installers above.**
>
> 真实键鼠操作必须有人看护。快捷配置启用管理员宿主并关闭自动风险拦截；UAC、窗口身份与坐标有效性检查仍存在。不得用于付款、发送、删除或最终提交。
> Supervise all real input. Quick setup enables an elevated host and disables automatic risk interception; UAC, window identity and coordinate checks remain. Do not use it for payment, sending, deletion or final submission.

## 1. 下载与文档 / Downloads and documentation

- [GitHub Releases / 已发布版本](https://github.com/Desolate-Jix/agent-gui-runtime/releases)
- [学习测试版与兼容执行组件 / Learning and compatible execution preview](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/learning-v0.1.0-preview.1)
- [v0.1.1 发布与下载 / Release and downloads](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.1)
- [安装、模型下载与配置 / Setup and models](FRIEND_SETUP.md)
- [Agent 使用指南 / Agent guide](AGENT_GUIDE.md)
- [Codex 视觉会话适配 / Codex visual-session adapter](skills/codex-vision-session/SKILL.md)：Codex 委派识图连续复用同一个子 Agent；其他 MCP 客户端不受影响。 / Reuse one Codex visual worker across consecutive screenshots without changing other MCP clients.
- [v0.1.1 验收与限制 / Acceptance and limits](docs/verification/V011_RELEASE_ACCEPTANCE.md)
- [v0.1.0 历史验收 / Historical acceptance](docs/verification/V010_RELEASE_ACCEPTANCE.md)
- [Agent 视觉路由与组合协议 / Agent routing and batch protocol](docs/development/AGENT_VISION_BACKENDS_DESIGN.md) · [组合协议细节 / Batch protocol](docs/development/AGENT_BATCH_PROTOCOL.md) · [外部视觉 API 接入 / External vision API](docs/development/EXTERNAL_VISION_API.md)
- [调用方调度 / Caller scheduling](AGENT_GUIDE.md#执行契约--execution-contracts)：已知字段先合批、及时读取 pending 结果、直接核对回执原图；属于调用指引调整，尚无本轮实机提速数据。 / Batch known fields, promptly retrieve pending results and inspect inline evidence; caller guidance only, without a new live speed measurement.
- [发布范围 / Release scope](RELEASE_SCOPE.md) · [变更记录 / Changelog](CHANGELOG.md)
- [历史网页与学习工作台归档 / Historical workbench archive](https://github.com/Desolate-Jix/agent-gui-runtime/tree/codex/archive-learning-workbench)

稳定 v0.1.1 下载为小型源码包；学习 0.1.0-preview.1 与执行 0.1.2-preview.1 提供独立 EXE 安装器。不包含模型权重、用户库、原始截图、账号或本机 MCP 配置。程序、可选模型与数据分开存放；升级不要覆盖未清理的运行会话。

Stable v0.1.1 uses a source bundle; the learning/execution preview pair provides separate EXE installers. Weights are required only for local grounding. Keep application, optional model and data directories separate and preserve unresolved sessions.

## 2. 功能 / Capabilities

**本地兼容能力 / Local compatibility:** 保留原有 VISTA 操作与 1–32 项 `form_fill`；新增视觉来源仍使用同一执行器。具体范围见 [发布范围](RELEASE_SCOPE.md)。 / Existing local VISTA actions and 1–32-field form filling remain available through the shared executor.

**视觉来源 / Vision sources:** 当前 Agent、客户端显式委派 Agent，或配置的外部视觉 API；定位结果均进入现有公共执行器。Agent 路线的 `read_text` 返回原图，不运行本地 OCR。外部 API 路线会把截图发送给所配置服务，且不要求本地模型权重。 / Use the current Agent, a client-selected delegate or a configured external vision API. Grounding uses the shared executor. Agent-route `read_text` returns the original image without local OCR; the API route sends screenshots to the configured service and requires no local model weights.

| Agent 路由 / Agent route | 行为与边界 / Behavior and boundary |
|---|---|
| `agent_current` | 使用当前具备图像能力的 Agent；无本地模型/VISTA/OCR 权重要求。当前 Agent 不具备所需视觉能力时为 unknown/unsupported 并停止该视觉路径，不静默转调本地模型或 API。 / Uses the current image-capable agent; no local model/VISTA/OCR weights. Unknown or unsupported capability stops this route; no silent local/API fallback. |
| `agent_delegate` | 仅由客户端按显式配置/profile 选择和调用视觉子 Agent，例如 Astra 主 Agent 显式委派给 Luna；宿主不继承 API/key，也不自动创建或切换子 Agent。 / The client explicitly selects/invokes a delegate (e.g. Astra planner to Luna vision); no host credential inheritance or automatic model switching. |
| `read_text` on Agent routes | 返回当前原图供 Agent 阅读，不运行本地 OCR。 / Returns the current original image for the Agent; does not run local OCR. |
| resumable batch | grounding 等待通过 pending/status/resume 继续原命令，保留已完成项并禁止自动重放。 / Pending grounding suspends and resumes the same command without replaying completed fields. |
| `external_api` | 按配置端点和模型定位，再由公共执行器处理；无自动重试或切换服务。截图会发送给该服务，准确率及任意服务商兼容性不作保证。 / Grounds through the configured endpoint/model and shared executor; no automatic retry or provider fallback. Screenshots are sent to that service; accuracy and universal provider compatibility are not guaranteed. |

Historical test.8 and candidate01 results are recorded in their versioned acceptance documents; they do not count as v0.1.0 verification. / test.8 与 candidate01 的历史结果保存在各自验收文档中，不计作 v0.1.0 验收结果。

### 外部视觉 API / External vision API

此路线不需要本地 VISTA 模型或模型权重。每次定位会把当前截图发送给配置的服务，并把返回候选交给现有公共执行器；`read_text` 仍返回原图，由调用方阅读。请求错误会明确停止，不自动重试，也不回退到本地模型或其他服务。请勿发送包含私人页面、凭证或账户信息的截图。

This route needs no local VISTA model or weights. Each grounding request sends the current screenshot to the configured service and passes its candidate through the shared executor. `read_text` still returns the original image to the caller. Errors stop clearly without retry or fallback to a local model or another provider. Do not send screenshots containing private pages, credentials or account information.

将下例保存为 `D:\AgentReviewConfig\vision-api.json`，按服务商替换完整请求端点和视觉模型 ID。密钥只通过运行 MCP 的进程环境提供；不要把密钥写入配置文件。

Save the following profile as `D:\AgentReviewConfig\vision-api.json` and replace the full request endpoint and vision model ID for your provider. Supply the key only through the MCP process environment; never put it in the profile.

```json
{
  "protocol": "chat_completions_json",
  "endpoint": "https://YOUR_PROVIDER/v1/chat/completions",
  "model": "YOUR_VISION_MODEL_ID",
  "api_key_env": "AGENT_REVIEW_VISION_API_KEY"
}
```

在程序目录运行以下命令。它会安装无本地模型的轻量执行依赖并生成 MCP 配置；连接所用进程必须能读取上述环境变量。管理员宿主也必须在其自身环境中取得密钥。

Run this from the application directory. It installs the lightweight execution dependencies without local model weights and creates the MCP configuration. The process connecting to MCP must inherit the named environment variable; an elevated host must receive it in its own environment.

```powershell
.\scripts\setup_instant.ps1 -RecognitionSource external_api -ApiProfile "D:\AgentReviewConfig\vision-api.json" -DataDirectory "D:\AgentReviewInstantData"
```

配置示例不会发送请求，也不证明服务商连通性。接入格式不等于对任意服务商兼容、识别准确率、速度或费用的承诺；详见[API 接入说明](docs/development/EXTERNAL_VISION_API.md)。 / Creating a profile sends no request and proves no provider connectivity. Protocol support does not guarantee compatibility, accuracy, speed or cost for any provider; see the API guide.

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

The published test.7 and test.8 acceptance records preserve results for those exact historical packages. Current v0.1.1 progress belongs in the [v0.1.1 acceptance record](docs/verification/V011_RELEASE_ACCEPTANCE.md); do not infer universal website/widget support.

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
| `app/execution/` | Eight maintained execution modules; legacy imports alias the same objects / 八个维护执行模块，旧导入为同对象别名 |
| `app/desktop_review/` | Coordinator and app preparation; compatible execution imports / 协调器、应用准备与执行兼容导入 |
| `app/core/`, `app/agent/` | Capture, Win32/UIA, input, target identity |
| `app/vision/`, `modules/ocr/` | Model service/worker and OCR contracts |
| `app/api/`, `app/application_profiles/` | Maintained action handlers and shared dependencies |
| `tests/`, `docs/verification/` | Regression and acceptance evidence |

v0.1.1 收拢八个既有执行模块，沿用原 owner、公共动作 API、七个 MCP 工具及全部视觉路线；不增加执行器。可选 `OptionalJudgment` 与 `ModelUsage` 仅为共享合同，未生产接线，默认不调用判断模型；未知用量保持 null，不代表全量 Agent 用量。见 [模块边界](docs/EXECUTION_MODULE_BOUNDARIES.md) 与 [判断／用量合同](docs/OPTIONAL_JUDGMENT_AND_MODEL_USAGE.md)。 / v0.1.1 consolidates eight existing execution modules while retaining the original owner, action API, seven MCP tools and all vision routes. Optional judgment and usage are unwired shared contracts: no default judgment-model invocation; unknown usage stays null and does not represent total Agent usage.

稳定 v0.1.1 源码中部分历史命名模块仍为执行模式共用依赖，不能因目录名含 `learn` 就删除。该稳定源码包不配送学习启动入口；已经发布的学习预览由上方独立安装器提供。

Historically named modules remain shared execution dependencies in stable v0.1.1, whose source bundle excludes learning startup entrypoints. The published learning preview is provided by the separate installer above.

## 4. 模型与环境 / Models and environment

- 所有路线都需要 Windows x64、**Python 3.11** 和本机执行框架。**外部 API / Agent 路线安装轻量执行依赖，不需要 VISTA 权重、CUDA 或用于本地识图的 GPU**；服务或 Agent 自身的要求由其提供方决定。
- **以下模型、CUDA、显存和磁盘规划只适用于 `local` 路线，不是 API / Agent 使用门槛。** 本地路线使用仓库 `uv.lock`，不随意替换依赖版本。
- 本地视觉定位使用官方 [inclusionAI/VISTA-4B](https://huggingface.co/inclusionAI/VISTA-4B)，走 Transformers 格式，不是 GGUF；保留配置、分词器、处理器、模板与全部权重。
- OCR 是另一个本地组件，UIA 是 Windows 可访问性接口，决策大模型由外部 Agent 提供。因此“只下载一个 VISTA 目录”不等于只有一个算法，**也无需额外部署三套大模型**。
- 锁定 GPU 路径使用 CUDA 13.0 PyTorch；CPU／AMD／所有 NVIDIA 驱动组合尚未认证。本机最近生命周期测试使用 RTX 4070 SUPER 12 GB，不代表该显存满足所有截图与并行负载。
- 模型约 9.1 GB；Python、依赖、缓存和截图另外占空间。可按 32 GB RAM、16 GB VRAM、35–45 GB 空闲磁盘做试用规划，**不是已验证最低配置**。

All routes require Windows x64, Python 3.11 and the local execution runtime. API/Agent routes use lightweight dependencies without VISTA weights, CUDA or a GPU for local grounding. The model, GPU and disk estimates above apply only to `local`; they are not API/Agent requirements or certified minima. The local route uses locked dependencies. See [full setup guidance](FRIEND_SETUP.md).

## 5. 安装与配置 / Install and configure

安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，解压到例如 `D:\AgentReviewInstant`。路径均为示例，请按本机修改。/ Install uv, extract the source and adjust paths.

**按所选识图方式执行其中一组命令，不需要全部安装。** / **Choose one setup route; you do not need to install every option.**

### A. 使用外部视觉 API，不下载本地模型 / External vision API, no local weights

先按上方“外部视觉 API”说明准备 JSON 配置和密钥环境变量，然后运行： / Prepare the API profile and secret environment variable described above, then run:

```powershell
Set-Location "D:\AgentReviewInstant"
.\scripts\setup_instant.ps1 -RecognitionSource external_api -ApiProfile "D:\AgentReviewConfig\vision-api.json" -DataDirectory "D:\AgentReviewInstantData"
```

这一路线不传 `-ModelDirectory` 或 `-DownloadModel`，无需执行下方本地模型下载步骤。 / Do not pass `-ModelDirectory` or `-DownloadModel`; skip the local-model download steps below.

### B. 使用当前 Agent 或视觉子 Agent，不下载本地模型 / Current or delegated agent, no local weights

当前 Agent 确实支持图像时使用： / When the current agent supports images:

```powershell
.\scripts\setup_instant.ps1 -RecognitionSource agent_current -DataDirectory "D:\AgentReviewInstantData"
```

客户端已配置视觉委派时，可改用 `-RecognitionSource agent_delegate -DelegateProfile "vision-luna"`；`vision-luna` 是示例配置名。 / For a client-configured delegate, use `-RecognitionSource agent_delegate -DelegateProfile "vision-luna"`; the profile name is an example.

### C. 使用本地 VISTA 模型 / Local VISTA model

**只有选择本地识图才需要以下模型安装与下载。** / **These model installation/download steps are required only for local grounding.**

```powershell
Set-Location "D:\AgentReviewInstant"
.\scripts\setup_instant.ps1 -RecognitionSource local -ModelDirectory "D:\AgentReviewModels\VISTA-4B" -DataDirectory "D:\AgentReviewInstantData" -DownloadModel -WhatIf
.\scripts\setup_instant.ps1 -RecognitionSource local -ModelDirectory "D:\AgentReviewModels\VISTA-4B" -DataDirectory "D:\AgentReviewInstantData" -DownloadModel
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
3. 仅本地模型路线在需要识别时调用 `prepare_models`，同一会话保持驻留；API / Agent 路线无需加载本地模型。
4. `instant_run` 执行一项动作或一个支持的 `input_sequence`。
5. 根据回执与后图判断 success / failure / uncertain，再决定下一步。
6. 正常关闭本轮创建的测试窗口 → `instant_stop` → `cleanup_verified=true` 且宿主退出，再断连。

Start/reattach, inspect the target, prepare models only for local recognition, then execute and inspect each result. API/Agent routes do not load local models. Keep one connection and one desktop controller. Finish with verified owned-window and resource cleanup.

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

v0.1.1 源码与隔离候选各 2086 项（覆盖重叠，不相加）；294 个项目模块来自独立包目录，739 项冻结清单摘要一致，STDIO 七工具通过。双方同冻结候选连续使用与清理及原始证据审计通过。外部 API 的真实输入使用本机回环测试服务，不等于真实供应商连通性或识别准确率验证。[v0.1.0 验收](docs/verification/V010_RELEASE_ACCEPTANCE.md) 另行保留为历史证据。 / v0.1.1 source and isolated candidate each passed 2086 overlapping checks; 294 project modules resolved inside the bundle, 739 manifest hashes matched and seven-tool STDIO passed. Main-agent and independent same-candidate continuous journeys, cleanup and original-evidence audit passed. Real API input used a loopback fixture, not a live-provider connectivity or accuracy benchmark; v0.1.0 acceptance remains separate historical evidence.


Published test.7 and test.8 results, failures and scope remain in their versioned acceptance records as historical evidence. See the [v0.1.1 acceptance record](docs/verification/V011_RELEASE_ACCEPTANCE.md) and [form contract](docs/verification/EXECUTION_FORM_FILL.md) for this patch's progress and limits; [v0.1.0 acceptance](docs/verification/V010_RELEASE_ACCEPTANCE.md) remains historical.

## 9. 可选学习模式 / Optional learning mode

**学习工作台 0.1.0-preview.1 已发布为测试版，独立安装，不要求额外学习模型。 / Learning Workbench 0.1.0-preview.1 is a published preview, independently installed without an extra learning model requirement.**

Agent 操作可形成可复用工作流草稿，用户在学习工作台审核、修改并保存确切版本。独立界面、流程图和任务步骤分别管理；流程图引用固定界面版本，加入成员不自动增加跳转。编辑后仍需审核，旧确切版本不被新修改静默改变。 / Agent teaching can synthesize reusable workflow drafts for human review, editing and pinned saves. Standalone interfaces, graphs and task steps remain distinct; graphs pin interface versions without implicit edges. Edits require review and do not silently change existing pinned versions.

用户可以修改目标规则、参数、步骤关系及结果核验；有判别证据的跳转默认提议本地图像核验。图像明确匹配时可确认结果，不匹配或不确定时由 Agent 审核原请求；可人工修改稳定区域和阈值，也可关闭图像选项后保存重开。 / Users can edit target rules, parameters, step relationships and result checks. Distinguishable transitions propose local image verification; clear matches can verify results and inconclusive evidence retains the original request for Agent review. Regions/thresholds are editable and disablement persists.

学习工作台可离线管理库；真实采集与试运行显式连接兼容执行组件，复用现有执行器。支持简体中文与 English，数据根保存在安装目录外。 / The workbench edits libraries offline and explicitly attaches to compatible execution for teaching/trials, using the existing executor. Simplified Chinese and English are supported; keep data outside installation roots.

[下载测试版 / Download preview](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/learning-v0.1.0-preview.1) · [使用说明 / Quickstart](https://github.com/Desolate-Jix/agent-gui-runtime/blob/3cd9b989c11592595ae5e63bd6dd183d33554068/docs/LEARNING_PREVIEW_QUICKSTART.md) · [验收及未验证范围 / Acceptance and limits](https://github.com/Desolate-Jix/agent-gui-runtime/blob/3cd9b989c11592595ae5e63bd6dd183d33554068/docs/verification/LEARNING_PREVIEW_RELEASE_ACCEPTANCE_20261007.md)

本次只证明验收报告中的受控新数据流程。旧便携候选未知退出仍为历史未解决项，不承诺任意应用稳定性或通用收益。后续继续扩大真实应用覆盖、变化与恢复测试及准确/速度收益评估。 / Evidence is limited to the controlled fresh-data journeys in the report. The excluded old portable exit remains unexplained; universal reliability and benefits are not established. Future work expands application coverage, change/recovery testing and accuracy/speed evaluation.

## License / 许可证

[ISC License](LICENSE). Dependencies and model weights retain their own licenses and are obtained from official sources.
