# Amadeus 的 Windows GUI Runtime 扩展 0.0.2

[English](README.md)

此 wheel 贡献一个 stdio MCP 连接和一个原生 Pi Skill。仅用标准库的启动器调用明确配置的**外部执行 Runtime 安装和其 Python 3.11**。Runtime 本体与本适配共用同一份维护中的 Runtime 源码；适配器不实现 MCP 消息、另一套执行器、计划解析器或学习模式，包内不含 Runtime 载荷、模型、真实 profile 或凭据。适配器自身在 Amadeus 的 Python 3.12 环境运行。

**兼容范围：** 仅 execution Runtime **0.1.4 或 0.1.5**、Windows、Amadeus Host Python **3.12**，以及依赖已准备好的 Runtime Python **3.11** 环境。Main 审核续行应使用 0.1.5；接受 0.1.4 marker 不会给 0.1.4 增加该功能。本包通过本地 wheel 交付，不通过插件商店。

**冻结 wheel：** `amadeus_agent_gui_runtime-0.0.2-py3-none-any.whl`，SHA256 `32d27ed81eab33db05ae2780b98a808205da5057ee98bd71bdad8382e35a6588`。此相同 wheel 已构建、安装、配置 Pi、启用并在 backend restart 后加载。包内含 MCP 启动器、Skill、reference 和 ISC 许可证，不含 Runtime 载荷、用户数据、真实 profile 或 key。本独立 README 是当前交付指南，冻结 wheel 的内嵌描述保留早期构建时记录；此次文档更新不改变任何 wheel 字节。

**正常安装态使用：** 两项全新 synthetic Notepad 编辑 → File → Save 任务在同一 Amadeus 产品／Chat 内，经 Chat → Pi → 已安装扩展 0.0.2 → 已安装 Runtime 0.1.5 完成，各用独立 Pi Work 和 Runtime session。全部 **6 个 Runtime 步骤**、两份精确磁盘结果、自有窗口关闭及 Runtime 清理通过，每任务正文仅派发一次。首任务发生一次普通 Luna 复核，两任务均无 Main 语义 override；Host 逐次权限批准另计。第二 Pi Work 在 Runtime 派发前纠正了 shell 策略拒绝和缺 request_id 的 SDK 错误，不称为零错误首过。实际禁用／重启、移除／重启和默认保留数据也已通过。

**恢复与限制：** 较早未发布载荷通过 live04 **显式 TEST 双拒绝**路径：原 Pi 看到绑定 PNG 后审核并继续原命令，不重输，完成三步保存及清理；8 项验收检查和 19 项只读审计通过。只读审计不是另一轮桌面执行，也不属于自然模型误拒、准确率、性能或新的 0.1.5 Main override 实测。Host 的 `succeeded/partial/review_ready` 是待用户审核口径，与 Runtime 完成分开。此前取消的 normal05 和被排除的受干扰样本继续保留历史失败，不改记新成功。本次不证明 wallpaper、声学／ASR、通用兼容、强制终止或完整取消／重连覆盖。详见[验收记录与限制](https://github.com/Desolate-Jix/agent-gui-runtime/blob/main/docs/verification/AMADEUS_PI_MAIN_REVIEW_20261015.md)。

## 安装本地扩展包

1. 使用包含 Pi、原生 MCP/Skill 贡献和本地插件管理器的兼容 Amadeus。本适配实测使用 Host 基线 [a9a488ae](https://github.com/Code-Amadeus/Amadeus/commit/a9a488ae)，并应用 [PR #225](https://github.com/Code-Amadeus/Amadeus/pull/225) 与 [PR #226](https://github.com/Code-Amadeus/Amadeus/pull/226)。核验时两个 PR 均已 ready for review、尚未合并；不保证所有已发布 Amadeus 版本兼容。[Host profile](https://github.com/Code-Amadeus/Amadeus/blob/main/docs/extension_host_profile_v0.1.md) 仍是实验子集；本包无需、也不提供插件商店安装。
2. 从 [Runtime Releases](https://github.com/Desolate-Jix/agent-gui-runtime/releases) 获取**执行 Runtime** 安装器。需要 Main 审核续行时选择 **0.1.5**。填写真正的安装根目录，其中应有 `execution-installation.json`（`schema=execution_installation.v1`、`component=execution`、`version=0.1.5`）及 `scripts/start_instant_mcp.py`；不要填安装器 EXE、快捷方式或学习工作台目录。
3. 从该 Runtime 根目录复制 `configs/vision-api-openai-luna.example.json` 和 `configs/decision-profile.visual-execution.example.json` 到自己的配置目录，不把 key 写入其中。按原维护 setup 准备 Runtime 依赖；下列示例路径应替换为自己的既有安装路径和选定配置／数据路径：

```powershell
$RuntimeRoot = 'C:\Path\To\Runtime'
$VisionProfile = 'C:\Path\To\Config\vision-api.json'
$SetupData = 'C:\Path\To\GuiSetupData'
Set-Location -LiteralPath $RuntimeRoot
.\scripts\setup_instant.ps1 -RecognitionSource external_api -ApiProfile $VisionProfile -DataDirectory $SetupData
$RuntimePython = Join-Path $RuntimeRoot '.venv-agent\Scripts\python.exe'
Test-Path -LiteralPath $RuntimePython -PathType Leaf
& $RuntimePython -I -B -c "import sys; print(sys.executable); print(sys.version); assert sys.version_info[:2] == (3, 11)"
```

该路径来自 `setup_instant.ps1`：external API setup 创建 `<RuntimeRoot>/.venv-agent/Scripts/python.exe`。只有 setup 成功且实际路径／版本检查通过后才继续。安装器**不自带该环境**；实机验收复用了已经准备好的 Python 3.11 环境，全新机器首次依赖 setup 尚未验收。setup 需要已有 [uv](https://docs.astral.sh/uv/getting-started/installation/) 和网络。此扩展路线**不要再合并 setup 生成的独立手动 MCP 配置**，连接由已安装扩展提供。详细 setup 见 [Runtime 安装指南](https://github.com/Desolate-Jix/agent-gui-runtime/blob/main/docs/EXECUTION_GUIDE.md)。
4. 下载 `amadeus_agent_gui_runtime-0.0.2-py3-none-any.whl`，核对上方 SHA256。在 **Settings → General → Manage plugins** 选择本地 wheel，查看身份、许可证、命令及 OS 权限披露；安装初始禁用。填写下方六项配置，将 MCP 和 Skill 均绑定 **Pi**，明确启用并应用 backend restart，核对 applied 版本／revision 后再开新 Work。保存配置不等于已加载；安装扩展无需手工运行 pip、另加手动 MCP 项或复制全局 Skill。

## 配置与授权

原生管理器负责安装、secret 保存与启用；确认前应查看完整权限披露。安装初始禁用，保存配置不等于 backend 已重载。包不会在 MCP 启动时运行 Setup、pip、uv、模型下载或安装器。移除扩展不会卸载外部 Runtime；除非用户明确选择删除，Host 默认保留扩展数据。

| 配置项 | 所需值 |
|---|---|
| `runtime_root` | 既有 execution 0.1.4 或 0.1.5 安装根目录的绝对路径，含 `execution-installation.json` 和原 `scripts/start_instant_mcp.py`。 |
| `runtime_python` | 既有 Runtime **Python 3.11** 可执行文件的绝对路径，不回退到 PATH；可位于安装根目录之外。 |
| `api_profile` | 已批准、不含秘密的视觉 JSON profile 绝对路径。 |
| `decision_profile` | 已批准、不含秘密的 Decision JSON profile 绝对路径。 |
| `api_key` | Amadeus **secret** 配置，仅通过子进程环境 `OPENAI_API_KEY` 传递；不放进命令、profile、包文件或说明。 |
| `allow_local_input` | 布尔值，默认 **false**；仅在操作员明确授权当前任务后设为 true。 |

此包只绑定一份共用 key：视觉 `api_key_env`、Decision 实际生效的 `api_key_env`、普通复核实际生效的 `ordinary_review_api_key_env` 都须为 `OPENAI_API_KEY`。Decision 未填主字段时默认该名称；普通复核字段未填/null 时按现有 Runtime 合同继承主字段。明确配置其他环境变量名会在 Runtime 启动前清楚拒绝，既不静默重写，也不继承无关 provider key。Runtime 本身仍支持各服务使用独立 key；共用 key 只是本包限制。endpoint、model、预算、阈值和审核策略均保留在操作员既有 profile 中，由原 Runtime 完整验证 schema。

`allow_local_input=true` 添加原有 `--allow-local-input` 参数，其在两个兼容 Runtime 版本中的含义均包括**关闭自动风险拦截**。启用扩展或 Skill 不代表获准操作任意窗口、提交/发送、确认、付款或修改无关数据。只执行当前明确授权的任务，同一时间一个输入所有者，保留 Runtime/Amadeus 门禁和具体动作确认。

manifest 如实披露 `network:["*"]`、`process:["*"]` 和文件系统 `* / read_write`：外部 profile 决定获准服务 endpoint，Runtime 可操作获准应用和文件。这些是**能力披露，不是额外授权，也不是 OS 沙箱**。`permissions.host` 为空。不得声称流量仅限某个服务商，或启动器隔离了桌面访问。操作员必须信任选定的 Runtime 安装、Python 和 profile；版本 marker 检查仅为兼容性元数据，不是独立文件认证。

## 进程与会话行为

适配器检查绝对路径、execution marker schema／组件及明确的 0.1.4／0.1.5 版本集合、共用 key 绑定、严格布尔输入设置和解释器实际 Python 版本。无效配置以固定诊断码退出 2，不回显配置值；进程启动失败退出 3。原脚本收到 `-I -B -X utf8`、`--data-dir <扩展 data>/runtime`、`--recognition-source external_api` 和两个 profile 路径，仅明确 true 才附输入参数。key 不进入 argv。子进程仅收到共用 key、UTF-8 设置及一小组 Windows OS 环境变量，不转发无关 provider 变量或 `PYTHONPATH`。

原 Runtime 直接继承 stdin/stdout/stderr，适配器不读取 MCP 字节、不输出 stdout 横幅、不做代理协议或重试，并传播子进程正常退出码。fixture 测试证明实时字节传输、EOF 和子进程退出传播。上述正常安装态任务核实了明确 owned close 和 Runtime stop 后的清理，不证明 Pi 断连、强制终止或所有取消位置均自动清理 Runtime；不能用断开连接替代 Runtime 生命周期。

使用随包 [Skill](https://github.com/Desolate-Jix/agent-gui-runtime/blob/main/integrations/amadeus/agent-review-instant/src/amadeus_agent_gui/skills/gui-execution/SKILL.md) 和[参考](https://github.com/Desolate-Jix/agent-gui-runtime/blob/main/integrations/amadeus/agent-review-instant/src/amadeus_agent_gui/skills/gui-execution/references/runtime.md)；Host 向 Pi 提供实际安装路径，不复制到全局目录。一次完整 Work 任务保持同一 MCP 连接，保存 Pi 对话不会跨 Work run 保持 MCP 常驻。实际发现工具名，不猜 Pi 哈希名；保留原 request/run/command ID 和绑定原图。pending 或未知输入只查询，不换新 ID 重放。

Runtime 0.1.5 可在双模型真实非通过并认证后，将原活跃输入 job 保持在 `field_review_packet.v1` 等待。原 Agent 读取绑定 after 原图，复制确切 `caller_controls.review.request` 并补实际 verdict/reason，再单独调用返回的 `caller_controls.continue.request`。review 只记录，明确 continue 才恢复原线程且不重输。该审核只确认已经输入的文字；若原请求还有 submit 后缀，仍须经过既有 fresh-target／输入门禁与结果核验。本包不实现该 Runtime 修复。

Main 视觉审核要求 **Pi 执行模型支持 image 输入**，且 adapter 保留 MCP image 内容；仅有文本回执不能证明审核者看到了绑定 after 原图。实测 Host 的最终 session-scoped 公共 hook 修正 PR #225 经 **17 项实际 SDK 检查**，不替换 Provider、改写用户配置或第三方源码。独立的取消收尾 PR #226 经 **28 项相关检查**。核验时两个 PR 均 ready for review、尚未合并，其他 Host 构建必须具备等价行为，不能假定兼容。较早 live04 Pi 在提交绑定审核前收到原 PNG，但不代表捕获了 provider 原始 HTTP payload 或证明通用视觉准确率。

原执行未终态时，先用**新的外层 request** 提交 `agent_command_status`，其中 `command_id=packet.execution_request_id`，再用该 status request ID 调 `instant_image` 取原图，不直接对未完成的原执行取图。**已发布 0.1.4 基线限制**仍然保留：部分 `field_review` 失败没有恢复票据。当前宿主未返回实际 review/continue recipe 时停报，不猜票据、不重启重放、不改记成功；仅版本 marker 相同不能证明具备新能力。

输入结算后，只关闭本轮自有窗口，确认 `window_closed`，然后 `instant_stop` 并查询到 `host_alive=false`、`pending_ids=[]`、`cleanup_verified=true`。保存提示只在该选择已获授权时处理。`capture` 仅为 `{"kind":"capture"}`，不带 handle/process_id；`close_launched_window` 使用 launch 回执的 `kind/handle/process_id`，无需虚构 `request.ownership`。任务结果和收尾分别报告；保留浏览器数据及独立测试 profile。

## 离线开发

需要已具备的 Python 3.12、setuptools >=77、Python 3.11、已安装的 `uv` 构建工具和 Amadeus 源码。下列命令不安装依赖，只运行合成子进程及静态 Host 检查：

```powershell
$env:AGENT_GUI_TEST_PYTHON311 = 'C:/explicit/python311/python.exe'
$env:AGENT_GUI_TEST_HOST_ROOT = 'C:/explicit/amadeus'
& 'C:/explicit/python312/python.exe' -I -B -X utf8 -m unittest discover -s tests -v
```

测试覆盖标准流/EOF 和非零子进程退出、中文空格路径、明确参数、缺失/畸形配置、错误 Python/版本 marker、共用秘密绑定，以及 canonical Host manifest/Skill 加载和原生 MCP 投影。合成凭据仅为 fixture，不是真实 key。若缺少明确指定的前置环境，相应边界测试会跳过；跳过不能计验收。

选定兼容候选后，可在不下载依赖的情况下构建并检查：

```powershell
uv build --wheel --python 'C:/explicit/python312/python.exe' --no-build-isolation --no-index --offline --no-python-downloads --no-sources --no-config --no-create-gitignore --out-dir 'C:/explicit/evidence/dist' .
& 'C:/explicit/python312/python.exe' -I -B 'C:/explicit/amadeus/tools/extension_package.py' inspect-wheel 'C:/explicit/evidence/dist/amadeus_agent_gui_runtime-0.0.2-py3-none-any.whl'
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:/explicit/evidence/dist/amadeus_agent_gui_runtime-0.0.2-py3-none-any.whl'
```

`uv build` 只构建 wheel，不安装项目依赖，本包也未声明此类依赖。明确参数禁止索引访问、网络/Python 下载及创建隔离依赖环境，无需另装 pip。原生安装前检查真实 wheel 资源和 entry point。离线测试、wheel 检查、MCP 握手与真实输入/生命周期验收分别报告。这些测试不进行提交、安装、桌面/模型调用或发布。

开发检查、历史 fault-proxy 测试、真实任务结果与只读审计应分开；数量不相加，前置缺失而跳过不算验收通过。[验证文档](https://github.com/Desolate-Jix/agent-gui-runtime/blob/main/docs/verification/AMADEUS_PI_MAIN_REVIEW_20261015.md) 保留首次失败、历史注入范围和当前安装态使用边界。

壁纸补充（2026-10-16）：Lively 2.2.1.0 的空显示器名称报告缺陷已通过原版／修正副本真实对照确认，修正副本上的两轮 Amadeus 生命周期通过。随后本机已备份原DLL并应用修正；这是第三方本机修复，非官方升级，不包含在本wheel或Runtime安装器中。Amadeus的不确定挂载恢复修复见 [PR #228](https://github.com/Code-Amadeus/Amadeus/pull/228)。其他用户须单独处理受影响的Lively安装，安装本扩展不等于壁纸兼容已验收；正常启动路径最终结果见Runtime发布说明。
