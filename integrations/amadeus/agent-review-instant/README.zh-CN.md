# Amadeus Windows GUI Runtime 扩展 0.0.4

[English](README.md)

通过**原生 Streamable HTTP MCP** 和随包执行 Skill，将 Pi 连接到操作员独立启动的 Windows GUI Runtime。Runtime **0.1.6** 与扩展 **0.0.4** 由同一 `instant-v0.1.6` Release 交付。公开分发与独立商店审核是两件事，本页不宣称商店审核通过。

## 下载

- [Runtime 0.1.6 Windows 安装包](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.6/AgentGUIRuntimeExecution-Setup.exe)
- [Amadeus 扩展 0.0.4 wheel](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.6/amadeus_agent_gui_runtime-0.0.4-py3-none-any.whl)
- [扩展源码 ZIP](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.6/extension-source-0.0.4.zip)

先独立安装 Runtime，再向 Amadeus 导入 wheel；wheel 不是 Runtime 安装器。详见 [Runtime 安装说明](../../../README.zh-CN.md)。历史 0.0.2 仍是独立的 stdio 启动器版本。

## 各组件做什么

| 组件 | 职责 |
| --- | --- |
| Amadeus / Pi | 规划任务、管理自身批准界面，通过原生 HTTP MCP 客户端调用工具。 |
| 扩展 0.0.4 | 仅含 HTTP 连接声明和 Skill；不含启动器、可执行程序选择、模型权重或依赖。 |
| 本机 Runtime | 提供带鉴权的本机 MCP 服务，负责视觉／Decision 配置、输入授权、回执和收尾。 |

Host 使用 Python 3.12。Runtime 0.1.6 的 API 路线为新环境默认准备 Python 3.12，**不需要本地 GPU 或下载模型权重**，并保留既有受支持的 Python 3.11 环境。可选本地模型安装仍沿用原 Python 3.11 合同。统一 Python 小版本**不等于共用虚拟环境**，各组件保留自己的锁定依赖。冻结的 0.1.5 安装包没有 HTTP MCP 入口；请使用 0.1.6 并核对实际运行版本。

## 启动本机 Runtime

先安装 Runtime；若 setup 提示缺少 `uv`，先按 Runtime 安装说明安装它，再执行下方 API setup。将 `configs/vision-api-openai-luna.example.json` 和 `configs/decision-profile.visual-execution.example.json` 复制为私有配置文件，按 Runtime 说明配置 endpoint、模型和任务条件，明确保留 Decision 阈值及普通复核策略。模型请求交给选定的远程服务，可能产生费用。各 profile 的 `api_key_env` 变量只设置在 Runtime 进程环境中；示例使用 `OPENAI_API_KEY`，不能填入扩展。

生成至少 32 字符的强随机**本机连接密钥**并私下保存；它与所有模型 API Key 不同。用不回显的提示输入，再在独立控制台启动服务：

```powershell
$RuntimeRoot = 'C:\Path\To\Runtime'
$RuntimeData = 'C:\Path\To\GuiRuntimeData'
$VisionProfile = 'C:\Path\To\Config\vision-api.json'
$DecisionProfile = 'C:\Path\To\Config\decision.json'
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'Provider API key' -AsSecureString)).Password
$env:AGENT_GUI_MCP_TOKEN = [System.Net.NetworkCredential]::new('', (Read-Host 'Local MCP connection token' -AsSecureString)).Password
Set-Location -LiteralPath $RuntimeRoot
& '.\scripts\setup_instant.ps1' -RecognitionSource external_api -ApiProfile $VisionProfile -DataDirectory $RuntimeData
& '.\.venv-agent\Scripts\python.exe' -I -B -X utf8 scripts/start_instant_mcp_http.py `
  --data-dir $RuntimeData --port 17665 --recognition-source external_api `
  --api-profile $VisionProfile --decision-profile $DecisionProfile
```

setup 运行一次即可，可能下载锁定依赖；它生成的独立 stdio MCP 配置不需要再导入本扩展。省略 `-PythonVersion` 可沿用既有受支持的 API 环境；明确选择其他小版本时，需另建环境，不能原地覆盖。

输入默认禁用。仅在明确授权当前桌面任务后，加入原有 `--allow-local-input` 参数；它原有的含义包括关闭自动风险拦截。连接密钥用于认证，不代表允许任意点击、提交、付款或修改无关文件。服务仅绑定 `127.0.0.1`，在处理 MCP 前核对 Host／Origin；不要通过公网绑定、隧道或反向代理暴露服务。

## 安装与连接

1. 使用已核验、支持原生 HTTP MCP 和 Skill 的 Amadeus。当前开发检查针对上游 `9547f39`／`0.17.1-alpha.1`。
2. 下载并在 Settings → Extensions 安装 **0.0.4 wheel**，检查身份和权限披露；初始保持禁用。
3. 将 `runtime_url` 填为 `http://127.0.0.1:17665/mcp`（或实际端口），只使用可信的本机 Runtime 地址。secret `connection_token` 填入启动 Runtime 时使用的同一连接密钥。
4. MCP 和 Skill 均绑定 Pi，明确启用并应用 backend restart，再开新 Work。保存配置不等于已加载。
5. 先发现实际工具并查看 `instant_status`，再申请输入。核对 Runtime 版本与原回执，不把刚修改的源码视为已运行版本。

扩展不会启动、安装或升级外部 Runtime，也不接收模型服务 API Key。`network: ["*"]` 如实披露可配置的 HTTP 访问，不是 OS 沙箱，也不是额外桌面操作授权。

## 任务与连接收尾

使用随包 [Skill](src/amadeus_agent_gui/skills/gui-execution/SKILL.md) 和[参考](src/amadeus_agent_gui/skills/gui-execution/references/runtime.md)。完整任务保持同一个 MCP 连接和一个输入所有者。待定／未知输入保留原 request／run ID，不换 ID 重放。

0.0.4 的 Skill 说明文字结果审核和新增的点击前 Main 审核合同。遇到真实 `pre_action_review_packet.v1` 时，用新的状态请求读取原 job，查看其绑定的 **before 图像**，再使用返回的 review 和单独的 continue 请求。审核本身不点击；继续后保留原 job 和候选，先核对新截图中的目标区域及输入门禁，再派发一次。原有 `field_review_packet.v1` 使用 **after 图像**审核已输入文字，两种作用域不能互换。candidate05 已通过本体五步及原生 Pi 四步安装态流程，覆盖显式 TEST 双拒后的续行，阈值未改。见[验收结果与边界](../../../docs/verification/MAIN_PRE_ACTION_REVIEW_20261023.md)。Pi 可能先原生缩放完整绑定帧再交给模型，因此不能声称模型收到原 PNG 字节。受控、带兜底实测不是无人 benchmark，也不证明通用准确率或速度；Release／版本号不能证明商店批准或当前服务已加载该合同。

只关闭本轮自有窗口，然后调用 `instant_stop` 并查询至 `host_alive=false`、`pending_ids=[]`、`cleanup_verified=true`。断开传输不等于取消或清理；只有前一个所有者满足服务的明确释放条件后，新 Work 才能连接。禁用／移除扩展不会停止独立启动的 Runtime 服务，也不会删除其数据；先确认收尾，再明确关闭服务。

## 迁移与入驻审核

0.0.3 更改了配置：`runtime_root`、`runtime_python`、profile、`api_key`、`allow_local_input` 不再由扩展保存，改在 Runtime 服务配置。两个新连接配置需明确填写，不能把原模型 API Key 当作连接密钥。历史 0.0.2 文件及其验收证据不被本候选替换。

不可变的 0.0.4 wheel／源码 ZIP 保留构建时文档，其中的旧 pending 标签是构建时快照；当前安装说明和验收文档记录后续结果，不替换原产物字节。

首批精选策略不允许配置项选择可执行程序／模块。HTTP 使用现有原生合同，不能靠另一层启动器绕过审核。wheel 检查、固定作者预检、原生协议调用、桌面执行与独立商店审核分别记录，实际覆盖见验收文档，未测层不得记为通过。材料不包含作者自批或虚构审核人。

本扩展代码采用 ISC；Runtime 与第三方组件许可证分别保留。wheel 不含用户数据、真实 profile、密钥、模型或 Runtime 载荷。
