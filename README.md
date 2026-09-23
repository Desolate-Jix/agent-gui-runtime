# Agent Review Instant

**Windows GUI execution runtime for MCP agents / 面向 MCP Agent 的 Windows 图形界面执行框架**

Agent 负责理解任务、决定下一步和判断结果；框架负责观察真实界面、定位目标、派发操作、返回证据与管理本地资源。它不是另一个自主决策 Agent，也不是网页管理面板。

The connected agent plans and judges outcomes. This runtime observes real Windows interfaces, grounds targets, dispatches actions and returns evidence. It is an execution layer, not an autonomous planner or web management console.

> **当前版本：v0.1.0-test.7 · 执行模式测试版。**
> **Current version: v0.1.0-test.7 · execution-mode test release.**
>
> **本次只更新执行模式，学习模式不发布。** 文末介绍是后续方向，不代表下载包已支持。
> **Execution only. Learning is not shipped.** The roadmap below is not an available feature list.
>
> 测试版，不是生产稳定版。快捷配置启用管理员宿主、真实键鼠输入，关闭自动风险拦截。请有人看护，不用于付款、发送、删除或最终提交；UAC、窗口身份与坐标有效性检查仍存在。
> Supervised test software. Quick setup enables elevated real input with automatic risk interception disabled. Do not use it for payment, sending, deletion or final submission. UAC and window/coordinate integrity checks remain.

## 1. 下载与文档 / Downloads and documentation

- [GitHub Releases / 已发布版本](https://github.com/Desolate-Jix/agent-gui-runtime/releases)
- [test.7 ZIP / 当前源码包](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.0-test.7/AgentReviewInstant-v0.1.0-test.7.zip)
- [安装、模型下载与配置 / Setup and models](FRIEND_SETUP.md)
- [Agent 使用指南 / Agent guide](AGENT_GUIDE.md)
- [发布范围 / Release scope](RELEASE_SCOPE.md) · [变更记录 / Changelog](CHANGELOG.md)
- [历史网页与学习工作台归档 / Historical workbench archive](https://github.com/Desolate-Jix/agent-gui-runtime/tree/codex/archive-learning-workbench)

这是小型源码包，不是独立 EXE 安装器。不包含模型权重、Python 环境、用户截图、账号或本机 MCP 配置。程序、模型、数据分开存放；升级不要覆盖未清理的运行会话。

This is a source bundle, not a standalone installer. Prepare dependencies, weights and configuration locally. Keep application, model and data directories separate and preserve unresolved sessions.

## 2. 功能 / Capabilities

> **test.7：** 最多 32 项组合填写、可选具名文本 Tab 连续输入、日期、真实标签关联、原生文件选择与取消恢复。源码和隔离包各 **1759 项回归通过**（不相加）；Codex 连续实测及 AionUi 同包复验已完成。四字段两轮约 53–64 秒；组合动作减少 Agent 往返，并不等于所有表格已高速通用。/ Up to 32 ordered fields, optional named-text Tab input, dates, label binding and native-file recovery. **1759 checks each** in source and isolated bundle; Codex continuous use and AionUi same-bundle retesting completed. Four-field batches took about 53–64 seconds; fewer agent round trips do not imply universal fast forms. [实测、首失败与限制 / Evidence and limits](docs/verification/TEST7_CANDIDATE_ACCEPTANCE.md).

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

### test.6 新增 / New in test.6

**以下功能随 test.6 配送。 / Included in test.6.**

- 自动发现开始菜单／桌面快捷方式及 Windows App Paths；按名称、发现 ID 或本地 `.exe/.lnk` 路径启动。同名返回候选，默认复用唯一现有窗口。
- `desktop_capture` / `desktop_click` 无需调用方预先绑定；运行时自动确认桌面图标宿主，沿用现有识别执行链。
- 模型启动错误包含阶段、错误码和日志位置；清理错误包含进程身份、Job、PID 文件与采样证据。
- 关闭失败进入 `cleanup_pending`，保留原 owner，允许显式重试清理；旧会话未解决时返回结构化启动拒绝。
- 修正模型下载参数及跨机器配置说明。
- test.6 的 `form_fill` 支持一次声明 1–12 项文本、下拉、单选与复选状态，返回部分结果，不自动提交。test.7 的扩展范围见上方 test.7 说明与[表单协议 / Form contract](docs/verification/EXECUTION_FORM_FILL.md)。 / Shipped test.6 supports 1–12 text/dropdown/radio/checkbox fields, partial results and no automatic final submission. test.7 extensions are identified above.

真实 W3C 表单的连续填写、重复设置、中断恢复，以及 Google→Maps 两地点查询已通过 Codex 同包实测和 AionUi 独立复测。独立地图测试首次发生模型点偏左 5px、零输入拒绝；Agent 核对后明确重试成功，不能算首轮全通过。

Real W3C forms and Google-to-Maps two-place queries passed same-package Codex checks and independent AionUi retesting. The independent Maps first attempt was refused without input after a 5px model mislocalization; an explicit agent-reviewed retry succeeded. This is not first-attempt perfection or universal widget support.

The release adds installed-app name/ID/path launch, desktop commands without caller-side binding, model diagnostics, cleanup-only recovery and corrected download instructions. UWP-only links, cross-executable launchers and ambiguous windows are not universally supported.

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
    |-- VISTA model worker / 视觉目标定位
    |-- Existing action API / 点击、输入、按键、滚动
    |-- After observation / 操作后截图与诊断
    v
Receipts + original images + cleanup evidence / 回执、原图、清理证据
    +---------------------> Agent judges success / failure / uncertain
```

### 各层职责 / Responsibilities

1. **MCP 层**验证参数、管理请求 ID、落盘与查询回执。管理员入口通过 stdio 中继连接提权宿主，UAC 由用户确认，不给整个 Agent 提权。
2. **会话／执行层**串行处理命令，维护目标窗口和进程身份。专用线程维持原生资源生命周期；不要求每次点击都关闭、重载模型。
3. **观察／定位层**以截图提供当前像素，OCR 提供文字与框，UIA 提供可用控件和焦点，VISTA 根据图像和目标生成定位。它们是不同来源，不把模型点或合成搜索框当独立验证。
4. **动作层**复用现有窗口与输入实现，不为每个网站另写点击引擎。输入已派发、后图有变化、任务成功分别表达。
5. **证据／资源层**持久化命令、回执、原图和清理记录。`verified=null` / `awaiting_agent_review` 把任务判定交给 Agent；进程资源清理则按自身证据验证。

The adapter validates/persists requests; the serial coordinator owns native resources; capture, OCR, UIA and VISTA supply distinct observations; existing handlers dispatch input. Dispatch, observed change, task success and cleanup success are separate concepts. Elevation applies to the host, not the whole client.

| 代码位置 / Location | 职责 / Role |
|---|---|
| `app/instant_mcp.py`, `app/instant_receipt.py` | MCP tools, admission, compact/full receipts |
| `scripts/start_instant_mcp.py`, `scripts/start_instant_mcp_admin.py` | Normal/elevated entrypoints |
| `scripts/run_local_step_session.py` | Session loop and evidence |
| `app/desktop_review/` | Coordinator, ownership, app preparation, input sequences, recovery |
| `app/core/`, `app/agent/` | Capture, Win32/UIA, input, target identity |
| `app/vision/`, `modules/ocr/` | Model service/worker and OCR contracts |
| `app/api/`, `app/application_profiles/` | Maintained action handlers and shared dependencies |
| `tests/`, `docs/verification/` | Regression and acceptance evidence |

部分历史命名模块仍为执行模式的共用依赖，不能因目录名含 `learn` 就删除。它们不代表学习产品已启用；本包不配送学习启动入口，MCP 只暴露执行工具。

Historically named modules may remain shared dependencies. Their presence does not enable learning; the bundle excludes learning startup entrypoints and exposes execution tools only.

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

- 源码与隔离冻结包各 **1759 项通过**（重叠集合，不相加）；另有隔离入口及真实 MCP stdio 检查。
- Codex 先完成单项、连续表单填写与原生文件选择/取消/重开；AionUi 在同一候选独立复验。两轮四字段均正确保留值，原始 `打开(O)` 目标两次确认文件，不使用回车代替。
- 四字段：Codex **61.439 / 53.021 s**，AionUi **64.123 / 55.881 s**。此前具名三文本 Tab 组合约9–22秒，但并非同条件的提速A/B测量。
- 保留早期 Open(O) 标签错误和文件按钮重开拒绝；修复后复验通过，不改记首次成功。
- 本轮是操作员模式，两次独立 Open(O) 的自动判定被旁路；不宣称自动拦截策略通过。关闭对话框后直接截图仍会返回失效窗口 ValueError，需显式重新选择原浏览器。
- 不保证任意表单、视觉多选、自定义日期部件、自动选项滚动、32项整批实机覆盖、跨设备稳定或无人值守。附件名显示不证明服务器收到文件，本轮未最终提交。

Source and isolated bundle each passed 1759 overlapping checks. Independent AionUi testing followed Codex single/continuous runs on the same frozen runtime. Two four-field rounds and native choose/cancel/reopen/reselect passed, with original failures retained. Measured mixed batches remain roughly 53–64 seconds, not a universal speed or accuracy claim. Operator-mode bypass was active; automatic policy acceptance was not demonstrated. A capture against a closed picker still needs explicit browser rebinding.

详细范围与证据见 [test.7 验收](docs/verification/TEST7_CANDIDATE_ACCEPTANCE.md) 和 [表单契约](docs/verification/EXECUTION_FORM_FILL.md)。/ See acceptance and contract for exact coverage and known limitations.

## 9. 后续轻量学习模式 / Future lightweight learning

**独立开发中，本次不发布，不要求额外学习模型，不承诺完成时间。 / Separate development, not shipped and no extra learning models required.**

核心：**Agent 决策，框架提供可编辑、可复用的界面与流程记忆，继续使用同一个执行器。** 不再建一套点击引擎，也不每步重复读取完整历史。

The agent remains the decision-maker. Learning adds editable interface/process memory above the same executor, with scoped retrieval rather than full-history replay.

1. **学习段**：Agent 正常操作时记录前后界面、目标、动作和真实跳转。
2. **界面与流程分开**：单页面学习产生独立界面；连续学习按实际跳转成图。输入值作为变量，不因换搜索词重复造页面。
3. **人工修改**：在原图上修改控件框、标签、含义；已有界面可加入／移出流程，持续保存编辑，不强制定稿。
4. **轻量复用**：按需读取节点、目标控件、下一跳与变量，使用明确版本引用；仍核对当前界面，不照搬旧坐标。
5. **局部截图定位**：固定样式按钮保存局部模板，在当前图里比较定位。重复匹配、缺失、缩放／布局变化要明确返回，不伪装成命中。
6. **反馈与版本**：可人工修正或交 Agent 重学，保留来源和修订，避免新修改静默污染旧流程。

Planned experience: action-linked learning segments, standalone interfaces, real transition graphs, editable regions/semantics, parameterized reuse, local screenshot-template matching and explicit revisions/relearning. Templates assist localization; they do not prove old coordinates remain valid.

先把执行模式稳定性、操作覆盖和跨 Agent 使用打磨好，再把学习接到稳定执行链上。历史网页／工作台仅供参考，不把旧截图和旧流程当成新版验收数据。

Execution stability and coverage come first. Learning requires separate acceptance with fresh content; the historical workbench is not the current product download.

## License / 许可证

[ISC License](LICENSE). Dependencies and model weights retain their own licenses and are obtained from official sources.
