# 朋友试用：安装、模型下载与 Agent 连接 / Friend trial setup

适用范围：Windows x64 即时模式源码预览包。它不是双击即用安装器；包内不含 Python 环境和模型。先完成下面的连接检查，再由人在场监督真实操作。本说明中的 `D:` 路径都只是示例，可换成你自己的磁盘；不要照搬别人电脑生成的 `mcp-config.local.json`。

This guide is for the Windows x64 instant-mode source preview, not a standalone installer. Install dependencies for the chosen route (weights only for local vision), verify the connection, then supervise real input. All `D:` paths are examples. Generate your own configuration instead of copying another machine's local MCP paths.

## test.8：不装本地模型 / Model-free Agent setup

**以下适用于 test.8 或更新；test.7 不含这些新路由。** `agent_current` 将视觉任务交给当前确实支持图像的 Agent；`agent_delegate` 仅由客户端按显式 profile 选择视觉子 Agent（例如 Astra 主 Agent 显式委派给 Luna）。委派名只是客户端配置标识，不会让宿主继承 API/key、自动创建子 Agent 或切换模型。unknown/unsupported 会停止所选视觉路径，不会偷偷回退到本地 VISTA/OCR 或外部 API。Agent 路线 `read_text` 回传当前原图供 Agent 阅读，不加载本地 OCR。独立 API 仅保留 adapter/config/mock 协议检查，宿主执行路由禁用，不读取或要求 key，也不要求 live-provider 验收；详见[预留接口](docs/development/EXTERNAL_VISION_API.md)。

**Requires test.8 or later; test.7 does not include these routes.** `agent_current` uses the current agent only when it actually supports images. `agent_delegate` asks the client to select a vision delegate by an explicit profile (for example, an Astra planner explicitly delegates to Luna). A profile is just client configuration: it grants no host API/key access and creates or switches no model automatically. Unknown/unsupported capability stops the selected route; there is no silent fallback to local VISTA/OCR or external API. Agent-route `read_text` returns the current original image for the Agent and does not load local OCR. The external API is limited to reserved adapter/config/mock-protocol checks; host execution is disabled, no key is read or required, and no live-provider acceptance is required. See the [reserved adapter](docs/development/EXTERNAL_VISION_API.md).

```powershell
# 当前 Agent 读图，不安装 VISTA 或本地 OCR。
.\scripts\setup_instant.ps1 -RecognitionSource agent_current -DataDirectory "D:\AgentReviewInstantData"

# 或：客户端已配置视觉委派时使用（vision-luna 是示例配置名）。
.\scripts\setup_instant.ps1 -RecognitionSource agent_delegate -DelegateProfile "vision-luna" -DataDirectory "D:\AgentReviewInstantData"
```

安装在独立 `.venv-agent`，不覆盖 `.venv` 本地模型环境；Python 和下载缓存保存在程序目录，不创建全局 Python 命令或注册 Python。直接依赖版本固定，传递依赖仍由安装时解析，并非完整锁定。第一次安装必须联网。Agent 路线不传 `-ModelDirectory` 或 `-DownloadModel`，不运行下文的 `uv sync`，不需要本地识别 GPU 或模型权重。Agent 自身的运行成本和图像权限由它的客户端负责。

Setup uses `.venv-agent` without modifying `.venv`, keeps Python/cache under the application directory, and skips global Python command/registry registration. Direct dependencies are pinned; transitives are resolved during installation, not fully locked. No local recognition GPU/weights are required; the Agent's own compute and image permissions remain client responsibilities. Do not use local-model flags or the `uv sync` instructions below for this route.

只重建配置 / Regenerate configuration only:

```powershell
.\scripts\configure_instant.ps1 -RecognitionSource agent_current -DataDirectory "D:\AgentReviewInstantData"
```

生成的默认快捷配置仍为管理员入口和真实输入，连接时需要用户处理 UAC；脚本不会自动修改已注册 MCP。先用普通权限做零输入连接自检（不是视觉或点击验收） / The quick config remains elevated real input, requiring UAC on connection, without changing registered MCP entries. First run the non-elevated, no-input connectivity check, which does not validate vision or clicks:

```powershell
.\.venv-agent\Scripts\python.exe scripts\smoke_instant_mcp.py --recognition-source agent_current --data-dir "D:\AgentReviewInstantSmoke" --report "D:\AgentReviewInstant\smoke-report.json"
```

委派检查加 `--recognition-source agent_delegate --delegate-profile vision-luna`，它只检查宿主协议，不会实际调用委派模型。Agent 组合命令会在 grounding 等待时暂停；客户端回传后继续原命令，保留已完成字段且不自动重放。test.8 源码和冻结候选均 2010 项全套测试通过；Codex 已完成两轮真实 Luna 委派混合填写与清理。首个 `CaptureVisibilityError` 保留，并通过明确的新截图和重新选择恢复；两轮耗时 139.013s / 126.147s，含 Agent 等待，不是性能基准；24 张原图摘要已核验。AionUi 同一冻结候选独立验收已派发，任务 `test8-independent-20260927-01`，待返回结果，因此不把 test.8 称作发布版或独立验收通过。**Agent 路线 `read_text` 返回原图给 Agent 阅读，不加载本地 OCR；桌面审核 UI 不包含在轻量依赖中**。见 [接入协议](docs/development/AGENT_BATCH_PROTOCOL.md) 和 [test.8 验收记录](docs/verification/TEST8_CANDIDATE_ACCEPTANCE.md)。

For delegate startup use its source/profile flags; this smoke does not invoke the delegate. Grounding waits suspend and resume the original Agent command, preserving completed fields without replay. Source and frozen candidate suites each pass 2010 checks; Codex completed two real Luna-delegated mixed-form runs and cleanup on the frozen candidate. The first `CaptureVisibilityError` is retained; recovery used explicit fresh capture and reselection. Per-run wall times (139.013s / 126.147s) include Agent waits and are not performance benchmarks; 24 original-image hashes were checked. AionUi acceptance of the same candidate has been dispatched (`test8-independent-20260927-01`), with result pending, so test.8 is not called released or independently accepted. **Agent read_text returns the original image without local OCR; the desktop review UI is excluded**. See the [batch protocol](docs/development/AGENT_BATCH_PROTOCOL.md) and [test.8 acceptance record](docs/verification/TEST8_CANDIDATE_ACCEPTANCE.md).

## 本次测试版快捷入口 / Quick setup for this test edition

本次要求的运行方式是 **管理员 MCP + 自动安全拦截关闭**。下列脚本按这个方式生成配置，不给整个 Agent 软件提权。操作必须有人监督。Windows 的 UAC 和窗口／坐标完整性检查不会删除。

This edition's quick script configures **administrator MCP with automatic safety interception disabled**. It does not elevate the entire Agent application. Supervise real operations; UAC and window/coordinate integrity checks remain.

先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，进入解压后的程序目录。下面将安装较大依赖并下载约 9.1 GB 模型（全部磁盘空间规划见下一节）：

```powershell
.\scripts\setup_instant.ps1 -ModelDirectory "D:\AgentReviewModels\VISTA-4B" -DataDirectory "D:\AgentReviewInstantData" -DownloadModel
```

已有完整环境和模型，只生成配置：

```powershell
.\scripts\configure_instant.ps1 -ModelDirectory "D:\AgentReviewModels\VISTA-4B" -DataDirectory "D:\AgentReviewInstantData"
```

前者将 uv 缓存及管理的 Python 放在解压目录的 `.setup-cache`、`.python`，避免默认占用系统盘；不覆盖已有模型，不打包虚拟环境。任一步失败即停止。两个脚本都支持 `-WhatIf` 先查看将执行什么。如果系统阻止脚本，先审阅文件并按组织政策处理，不需要修改全局执行策略；也可按下文逐条命令操作。生成后按第 4 节合并同名 MCP 配置；UAC 弹出时由用户确认。

The setup script installs locked dependencies and optionally downloads official weights. The configuration-only script reuses your environment/model. Setup keeps uv cache/managed Python on the extracted program's drive and stops on failure. Use `-WhatIf` to preview. If PowerShell policy blocks scripts, review the files and follow your organization's policy or use the manual commands below; no global policy change is required. Merge the resulting MCP entry and confirm UAC when connecting.

下文保留逐步／普通权限配置作为排错参考；**本次管理员测试版用上面的快捷脚本**。连接等待设置建议至少 180 秒，但连接器不能替你自动确认或取消 UAC。

Manual/non-elevated configuration remains below for diagnostics; the quick scripts implement this administrator test edition. Allow at least 180 seconds in your MCP client, but the connector cannot approve or dismiss UAC for you.

## 1. 准备目录与设备 / Prepare folders and hardware

建议分开存放，更新程序时不会混入测试记录：

| 用途 / Purpose | 示例 / Example |
| --- | --- |
| 解压后的程序 / Extracted application | `D:\AgentReviewInstant` |
| VISTA 模型 / Model weights | `D:\AgentReviewModels\VISTA-4B` |
| 实测记录 / Trial data | `D:\AgentReviewInstantData` |
| 首次连接检查 / Initial smoke data | `D:\AgentReviewInstantSmoke` |

- 使用 Windows x64；锁定环境是 **Python 3.11**，不是 3.12 或更高版本。
- 当前依赖使用 CUDA 13.0 版 PyTorch；需要匹配的 NVIDIA GPU／驱动。CPU、AMD GPU、不同显卡容量及驱动组合尚未作为本预览包的兼容性承诺。
- 模型目录约 **9.1 GB**；其中官方 `model.safetensors` 页面标示 **9.08 GB**，约 **8.46 GiB**。这不是安装总空间：Python、PyTorch、下载缓存和截图记录还会占用额外空间。[官方模型文件](https://huggingface.co/inclusionAI/VISTA-4B/tree/main)
- 容量规划可先按 **32 GB 内存、16 GB 显存、目标磁盘 35–45 GB 空余空间**预留；这是保守的试用规划估算，**不是已验证最低配置，也不保证该配置必定可运行**。显存还受图片大小、并行程序与推理参数影响。

Use Windows x64 and Python 3.11. The lockfile selects CUDA 13.0 PyTorch; compatible NVIDIA hardware/drivers are required for that path. CPU/AMD and untested GPU configurations are not certified. Weights occupy about 9.1 GB, excluding runtime/cache/data. Planning for 32 GB RAM, 16 GB VRAM and 35–45 GB free disk is an estimate, not a tested minimum or a performance guarantee.

## 2. 安装环境 / Install the environment

先按 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/) 安装 uv。Windows 已有 WinGet 时，可在 PowerShell 执行：

```powershell
winget install --id=astral-sh.uv -e
```

安装后重新打开 PowerShell，执行以下命令。`Set-Location` 指向包含 `pyproject.toml` 和 `uv.lock` 的解压目录，而不是它的父目录：

```powershell
Set-Location "D:\AgentReviewInstant"
uv --version
uv python install 3.11
uv sync --frozen --group desktop --group vista
.\.venv\Scripts\python.exe --version
```

最后应显示 Python 3.11.x。安装会联网下载依赖；不要在报错后删除锁文件、改用随意版本或复制别人的 `.venv`。检查错误原因后再继续。依赖装好不代表模型已经下载。

Install uv from its official instructions, reopen PowerShell, enter the extracted project root and run the commands above. Dependency installation needs network access and does not download VISTA weights. Keep the lockfile; do not bypass failures by replacing versions or copying someone else's virtual environment.

## 3. 下载官方模型 / Download official weights

当前即时识别使用 [inclusionAI/VISTA-4B](https://huggingface.co/inclusionAI/VISTA-4B)。按 Hugging Face 官方 [CLI 下载说明](https://huggingface.co/docs/huggingface_hub/guides/cli#download-to-a-local-folder)，在同一个程序目录执行：

```powershell
.\.venv\Scripts\hf.exe download inclusionAI/VISTA-4B --local-dir "D:\AgentReviewModels\VISTA-4B" --include "*.json" --include "*.safetensors" --include "*.jinja"
```

- 下载的是 Transformers 格式。保留配置、分词器、处理器和模板文件，不能只下载一个权重文件；不需要下载训练用的 `training_args.bin`。
- 每个筛选模式都要重复 `--include`；空格后直接追加模式会被当前锁定的 CLI 解析为明确文件名，并忽略筛选条件。
- 官方仓库目前使用单个 `model.safetensors`。本包也支持既有的合法分片目录（索引加全部分片），**不需要手工把官方权重拆分**。GGUF／量化模型不能直接替换此路径。
- 下载中断可以重复同一下载命令继续检查缺失文件；**这不等于允许重复发送 GUI 动作**。
- 为便于复现，保存下载时官方页面的提交版本；需要固定版本时可为下载命令增加 `--revision <完整提交SHA>`，替换成真实 SHA，不要原样复制占位符。
- 不需要额外下载 Qwen、OmniParser 等学习模式候选模型。OCR 运行依赖由锁定环境安装；真实模型准备能否成功仍要在你的设备上验证。

Download the official Transformers assets, not GGUF. Keep the configuration, tokenizer, processor and chat template alongside the weights. A single official `model.safetensors` and complete indexed shards are supported; no manual sharding is needed. Record the repository commit for reproducibility, or pin a real full commit with `--revision`. Other learning-mode candidate models are unnecessary for this trial.

Repeat `--include` for each pattern. With the locked CLI, additional bare patterns become explicit filenames and override the include filters.

## 4. 生成本机连接配置 / Generate local MCP configuration

先生成**未开启本地输入**的配置：

```powershell
.\.venv\Scripts\python.exe scripts\configure_instant_mcp.py --model-directory "D:\AgentReviewModels\VISTA-4B" --data-dir "D:\AgentReviewInstantData"
```

这只在程序目录生成 `mcp-config.local.json` 和 `mcp-config.local.toml`，不会自动修改 Agent 软件的全局设置。未启用输入的配置不用于真实操作；完成下一节检查并确认愿意授权后，再按第 6 节重新生成。

Generate local JSON/TOML snippets without input permission first. The generator does not modify any agent application's global settings. Real input requires the explicit opt-in in section 6.

### 如何加入 Agent / Add it to your agent

1. 找到 Agent 软件的 MCP／工具服务器设置，选择本地 **stdio** 服务器。
2. JSON 客户端：将 `mcpServers` 内的 **`agent-review-instant` 单个条目**合并进现有配置，保留其他服务器；已经有同名条目就更新，**不要新增重复项或覆盖整个配置文件**。
3. TOML 客户端：使用生成的 `mcp-config.local.toml` 对应段落；不要把 JSON 粘进 TOML。
4. 如果设置界面要求分别填写命令、参数、环境变量，分别使用生成配置中的 `command`、`args`、`env`；不要把全部参数拼进 executable 字段。
5. 保存并重新连接服务器。若当前对话没有工具，按该 Agent 软件的机制新开对话。应出现 `instant_start / instant_status / instant_submit / instant_result / instant_image / instant_stop / instant_run` 七个工具。

Merge only the named server into the existing configuration, or update it in place. Preserve other servers. Use the generated TOML section only for TOML clients. Reconnect; some clients need a new conversation to expose tools. If the folder is moved later, regenerate the snippets because paths are absolute.

## 5. 先做不输入的检查 / Run the no-input smoke first

在没有其他 Agent 操作桌面、没有运行中的本包会话时执行：

```powershell
.\.venv\Scripts\python.exe scripts\smoke_instant_mcp.py --model-directory "D:\AgentReviewModels\VISTA-4B" --data-dir "D:\AgentReviewInstantSmoke" --report "D:\AgentReviewInstant\smoke-report.json"
```

该脚本只验证 MCP 握手、七个工具、宿主启动、窗口发现、同 ID 回执及清理，**不发送键鼠、不截图、不进行模型推理**。注意：脚本为了覆盖实际配置通道，会在它自己隔离的宿主中启用本地输入能力，但脚本不提交输入命令；它不会修改你给 Agent 的配置。完成后应看到 `cleanup_verified=true`。

这个结果只代表连接正常。入口依赖检查可另执行：

```powershell
.\.venv\Scripts\python.exe scripts\check_instant_entrypoints.py --report "D:\AgentReviewInstant\entrypoint-report.json"
```

不要把两项检查通过写成“真实点击、显卡模型或完整任务通过”。新机依赖安装和硬件兼容性仍以该机实际结果为准。

The smoke sends no GUI input, takes no screenshots and performs no inference. It enables input capability only in its own test host to exercise that configuration; it submits no input commands and does not alter the agent configuration. Expect verified cleanup. The separate entrypoint check validates imports, not GUI behavior. Neither check certifies model/hardware compatibility or end-to-end task success.

## 6. 确认授权后再开启真实操作 / Explicitly enable supervised input

**只有你愿意让 Agent 实际控制键盘鼠标时才执行下面命令。** 该预览通道的自动风险拦截关闭，也没有逐动作人工审批；目标窗口、坐标和请求完整性等检查仍在。不能用于无人值守、发送、支付、删除或最终提交。一次只让一个 Agent 操作桌面。

```powershell
.\.venv\Scripts\python.exe scripts\configure_instant_mcp.py --model-directory "D:\AgentReviewModels\VISTA-4B" --data-dir "D:\AgentReviewInstantData" --enable-local-input
```

重新合并生成的同名服务器配置并重连，不要重复注册。`--enable-local-input` 会把 `--allow-local-input` 加入服务器启动参数。仅修改磁盘上的配置不会改变已经启动的宿主。

Only run this opt-in command when you consent to real keyboard/mouse input. It disables automatic risk interception and does not require per-action human approval; target/coordinate/integrity checks remain. Supervise low-risk tasks only. Merge the updated server entry and reconnect; an already-running host does not reload an edited file.

### 管理员目标（可选） / Elevated targets (optional)

如果目标软件以管理员运行，可由本机操作者再加 `--administrator`，例如：

```powershell
.\.venv\Scripts\python.exe scripts\configure_instant_mcp.py --model-directory "D:\AgentReviewModels\VISTA-4B" --data-dir "D:\AgentReviewInstantData" --enable-local-input --administrator
```

合并的是同一服务器条目，入口变为 `start_instant_mcp_admin.py`。它保留 MCP 的 stdio 通信，经 UAC 启动管理员子服务；请确认 UAC。客户端启动超时建议至少 180 秒。拒绝／超时会报错，不自动降级或反复提权。运行后核对 `instant_status.host_is_admin=true`。这不是给其他服务器或整个 Agent 软件提权；但该服务器收到的已开放操作具有管理员权限，务必监督。普通软件优先用非管理员入口。

Append `--administrator` only when needed, update the same entry and confirm UAC. The stdio relay launches an elevated MCP child, not an elevated copy of your entire Agent application. Allow at least 180 seconds for startup. Cancellation/timeout fails explicitly. Verify `instant_status.host_is_admin`; supervise this more powerful connection. Normal targets should use the non-elevated entrypoint.

测试开关关闭后，OCR／窄搜索和风险判断只记录、不自动否决当前候选；无候选、坐标越界、窗口身份变化仍不能执行。它不是修复模型准确率的捷径。访问拒绝会保留 Win32 错误与函数；错误 5 本身并不证明目标已经提权。

With test interception disabled, OCR/narrow-search/risk judgments are recorded rather than enforced. Missing candidates, invalid coordinates or changed windows still fail. This does not improve model accuracy. Win32 access-denied details are retained; error 5 alone does not prove elevation.

把包内 `AGENT_GUIDE.md` 交给 Agent，并要求按下列顺序测试：

1. 启动并等 `ready`，发现并确认目标窗口；启动失败时查看具体回执，不把“命令返回了”当作成功。
2. 截图，通过 `instant_image` 看原图，确认目标页面。聊天显示可能缩小，坐标必须使用原始截图像素。
3. `prepare_models`，确认模型准备结果；首次加载时间单独记录。
4. 每次只执行一个低风险动作：例如 Google 搜索 Google Maps、进入地图、在空搜索框输入地点并回车、查看结果、滚动详情。
5. 每步查询原请求 ID 并检查后图。超时／结果未知时不要换 ID 重发点击；先核对当前画面与旧回执。
6. 先用 `close_launched_window` 正常关闭本会话 `launch` 返回的确切 handle/process_id；有保存弹窗时先观察并处理本轮测试内容。再 `instant_stop`，查询至 `cleanup_verified=true` 且宿主退出，再结束连接。不要为了清理本测试而终止所有同名浏览器进程。

Give `AGENT_GUIDE.md` to the agent. Verify the target and original image, prepare models, perform one low-risk action at a time, then inspect its receipt and after-image. Poll original IDs; never blindly replay unknown outcomes. First use close_launched_window for the exact handle/process_id launched by this session and resolve only its test-content dialogs. Then stop and verify cleanup and host exit rather than killing every browser process. Keep the MCP connection alive during a task.

## 7. 本预览版边界与反馈 / Limits and useful feedback

**test.6 起的模型清理诊断 / Model cleanup diagnostics since test.6:** 清理失败时请保留回执 `diagnostics`、会话 `report.json`，以及诊断 `evidence_path` 指向的 `cleanup-evidence.json`（先脱敏），无需发整个目录。里面区分进程身份、Job 成员、连续零观测与 PID 文件删除结果。显存下降不等于全部清理通过；10 秒是观察预算，不是朋友故障已经解决的证明。`cleanup_pending` 解除阻塞后可再调用 `instant_stop` 只重试清理；不得删除历史指针来强开新会话。

For cleanup failures, share redacted receipt diagnostics, session report and the cleanup-evidence file referenced by `evidence_path`, not the entire data directory. VRAM release alone is insufficient. The new observation budget is not proof of a friend-machine fix. Resolve the blocker before explicitly retrying cleanup with `instant_stop`; preserve session records. [验证记录 / Verification](docs/verification/V5_MODEL_CLEANUP_FIXES.md).

**test.6 起的通用启动 / Generic launch since test.6:** 应用“未发现”不等于 MCP 未注册。可使用 launch.name、发现的 app_id 或本地 .exe/.lnk 绝对路径；同名候选必须消歧，UWP 专用启动不保证。test.6 及本次 test.7包含，旧 test.5 包不包含，详见 AGENT_GUIDE.md。

An undiscovered app is not an unregistered MCP server. Name, discovered ID and local executable/shortcut launch are included since test.6 and in test.7, not in older test.5 bundles.

模型准备错误新增 `diagnostics`：`phase`（preflight/launch/readiness）、`error_code`、`cause_type`，以及可取得的退出码、日志目录/路径、errno/winerror。提供脱敏错误、对应日志末尾、GPU/显存、模型目录及包名；不要发 token 或整个数据目录。模型加载完成前可能还未监听端口，单凭“拒绝连接”不能认定防火墙，也不能认定已修复。

Model errors now expose startup phase/code/type and available exit/log/OS details. Share minimal redacted logs and hardware information. Connection refusal alone does not diagnose the firewall or prove a fix: the worker may not listen until weights load.

- 填写支持 `clear_existing=true` 显式替换已有内容；不会自动回车。
- 自 test.5 起支持 23 种编辑键，完整列表见 AGENT_GUIDE.md。按键作用于当前焦点，x/y 不会点击；不是任意快捷键工具。
- `read_text` 从当前可见原图返回 OCR 文字与行框，不是 DOM 或整篇结构化内容提取；需要 Agent 看图核验错字和截断。
- 支持识别单击、右击和双击；不包含学习、自动流程记忆、拖拽或任意应用可靠性的保证。
- `verified=null` / `awaiting_agent_review` 表示还需要 Agent 检查实际效果；不能只凭 `returned`／成功标志判断业务目标完成。
- 截图可能遮罩被遮挡区域，这不是分辨率下降。不要点击遮罩内无法确认的目标。
- 日志可能包含填写的原文，原图会进入连接的 Agent 上下文并可能发送给其模型服务。请用无敏感内容的专用测试窗口；向开发者反馈时只提供脱敏必要片段，不转发整个数据目录、账号信息或模型访问令牌。

Since test.5, the runtime supports text replacement, 23 current-focus editing keys, single/right/double clicks and visible-image OCR. Arbitrary hotkeys, DOM/full-document extraction, learning and drag remain outside the supported surface. Inspect actual effects; receipts are not task proof. Occlusion masks are not downsampling. Logs may contain entered text and screenshots may reach the connected agent's model provider; share only minimal redacted diagnostics.

遇到问题请记录：包版本、Windows／GPU／驱动、失败命令类型和请求 ID、错误原文、每步 `command_wall_ms`、是否已经产生实际动作，以及清理结果。**不必为了收集报告而反复执行失败输入。**

Report the bundle version, OS/GPU/driver, operation and request ID, exact error, timing, observed effect and cleanup result. Do not repeat failed input just to collect a report.
