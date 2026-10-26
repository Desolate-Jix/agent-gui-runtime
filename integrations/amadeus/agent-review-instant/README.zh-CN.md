# Amadeus Windows GUI Runtime 连接器 0.0.5

[English](https://github.com/Desolate-Jix/agent-gui-runtime/blob/amadeus-extension-v0.0.5/integrations/amadeus/agent-review-instant/README.md)

本作者发行的连接器通过原生 Streamable HTTP MCP，将 Pi 连接到**用户独立安装并启动的 Windows 本机 GUI Runtime**。它只含连接声明与执行 Skill，不含 Runtime。**独立商店审核待完成；作者发布不等于商店批准。**

## 下载与兼容性

- [连接器 0.0.5 发布页](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/amadeus-extension-v0.0.5)
- [连接器 wheel：amadeus_agent_gui_runtime-0.0.5-py3-none-any.whl](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/amadeus-extension-v0.0.5/amadeus_agent_gui_runtime-0.0.5-py3-none-any.whl)
- [连接器源码：extension-source-0.0.5.zip](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/amadeus-extension-v0.0.5/extension-source-0.0.5.zip)
- [作者预检：preflight.json](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/amadeus-extension-v0.0.5/preflight.json)
- [推荐的 Runtime 0.1.8 Windows 安装包](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.8/AgentGUIRuntimeExecution-Setup.exe)与 [Runtime 发布页／校验值](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.8)

请先在运行 Amadeus 的 Windows 电脑上自行安装 Runtime，再导入连接器 wheel。详见 [Runtime 安装指南](https://github.com/Desolate-Jix/agent-gui-runtime/blob/instant-v0.1.8/README.zh-CN.md#快速开始)。连接器与 Runtime 使用独立版本号和发布 tag；连接器 0.0.5 不会更新 Runtime 0.1.8。

| 组合或能力 | 支持范围与证据 |
| --- | --- |
| Runtime 0.1.8 ＋连接器 0.0.5 | 推荐的已发布 Runtime 与本连接器。这个确切组合的新安装态 GUI 验收及独立商店审核仍待完成。 |
| Runtime 0.1.6 ＋连接器 0.0.4 | 历史受控安装态 Pi 证据覆盖四步目录导航、显式 TEST 双拒、Main 审核／继续及收尾。它不是 0.0.5／0.1.8 的新测试。 |
| 最低 Runtime 合同 | 0.1.6 引入本连接路线所需的带鉴权 HTTP MCP 入口及输入前候选审核；运行中的服务还必须提供文字结果审核／继续合同。 |
| Runtime 0.1.5 及更早版本 | 不能用于本 HTTP 连接器：0.1.5 没有 HTTP MCP 入口，尽管当时已有文字结果审核。 |
| Runtime 0.1.7 current-Agent 模式 | 本连接器没有通过 Amadeus 核验该模式；本 Skill 仅支持原有的 **external API 路线**。 |
| 后续 Runtime 或 Amadeus 版本 | 不默认兼容。维护者须人工核对实际版本、原生 HTTP／Skill 支持、必要工具和命令 schema、鉴权及清理／审核合同。本包不提供自动兼容探测。 |

已记录的 Amadeus 基线为上游 `9547f39`／`0.17.1-alpha.1`，原生 Pi 1.2.0。[历史证据及其边界](https://github.com/Desolate-Jix/agent-gui-runtime/blob/instant-v0.1.6/docs/verification/MAIN_PRE_ACTION_REVIEW_20261023.md)与 [0.0.5 作者验证记录](https://github.com/Desolate-Jix/agent-gui-runtime/blob/amadeus-extension-v0.0.5/docs/verification/AMADEUS_CONNECTOR_005_20261026.md)、独立商店审核分别记录。版本号或预检通过不能证明已执行桌面任务。

## 各组件做什么

| 组件 | 职责 |
| --- | --- |
| Amadeus／Pi | 规划任务，管理自身批准界面，并使用原生 HTTP MCP 客户端。 |
| 连接器 0.0.5 | 仅含连接声明与 Skill；不含启动器、可执行程序选择、模型权重或 Runtime 依赖。 |
| 本机 Runtime | 提供带鉴权的本机服务、视觉／Decision 配置、输入门禁、回执与宿主清理；由用户独立安装并启动。 |

Host 使用 Python 3.12。Runtime API setup 为新环境默认准备 Python 3.12，保留既有受支持的 Python 3.11 环境，**不需要本地 GPU 或下载模型权重**。可选本地模型安装有单独的 Python 3.11 合同，不在本连接器支持路线内。相同 Python 小版本不等于共用虚拟环境，各组件保留自己的锁定依赖。

## 启动本机 Runtime

先安装 Runtime；若 setup 提示需要 `uv`，先安装它。将 `configs/vision-api-openai-luna.example.json` 和 `configs/decision-profile.visual-execution.example.json` 复制为私有 profile，按 Runtime 指南配置 endpoint、模型和任务条件，明确保留 Decision 阈值及普通复核策略。识别／审核使用的截图和任务信息会发送给选定的模型服务；服务可能按调用收费，本 wheel 不含模型服务或 API 额度。各 profile 的 `api_key_env` 只设置在 Runtime 进程环境中；示例使用 `OPENAI_API_KEY`，不能放入连接器设置。

生成并私下保存 32–256 字符、强随机且 URL-safe 的**本机连接密钥**，例如在可信 Python 环境中使用 `secrets.token_urlsafe(32)`。它与所有模型服务 API Key 不同。用不回显的提示输入密钥，再在独立控制台启动服务：

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

setup 运行一次即可，可能下载锁定依赖；它生成的独立 stdio MCP 配置不需要再导入本连接器。省略 `-PythonVersion` 可沿用既有受支持的 API 环境；明确选择其他小版本时，需另建环境，不能原地覆盖。Amadeus 使用服务期间，保持该控制台运行。

输入默认禁用。仅在明确授权桌面任务后，在最后的启动命令加入原有 `--allow-local-input` 参数。**这个选项也会关闭自动风险拦截。** 连接密钥用于认证，不代表允许任意点击、提交、付款或修改无关文件。服务仅绑定 `127.0.0.1`，在处理 MCP 前验证 Host 并拒绝浏览器 Origin 请求头。不要通过公网绑定、隧道或反向代理暴露服务。

## 安装与连接

1. 使用支持原生 Streamable HTTP MCP 和 Skill 的 Amadeus 构建，将实际安装版本与上方已记录基线核对。
2. 下载并在 Settings → Extensions 安装 **0.0.5 wheel**，检查身份和披露；安装后初始禁用。
3. 将 `runtime_url` 填为 `http://127.0.0.1:17665/mcp` 或所选端口，只使用可信的本机 Runtime。secret `connection_token` 填入启动 Runtime 控制台使用的同一本机密钥，不能填模型 API Key。
4. MCP 和 Skill 均绑定 Pi，明确启用并应用 backend restart，再开新 Work。保存配置不证明它已加载。
5. 查看 MCP 初始化报告的版本和实际发现的工具，再在申请输入前读取 `instant_status`。必要工具为 `instant_start`、`instant_status`、`instant_run`、`instant_result`、`instant_image`、`instant_stop`；其 schema 须支持随包 Skill 描述的 task-plan、原命令状态及审核／继续操作。实际进入审核状态时核对服务返回的真实 recipe。这是人工核对，不是自动兼容认证。

连接器不能启动、安装、升级或重新配置外部 Runtime，也不接收模型服务 API Key。`network: ["*"]` 披露可配置 HTTP 访问，不是 OS 沙箱或桌面操作授权。

## 一个最小可复现任务

使用合成临时目录，不打开个人文件。请自行安装 7-Zip。连接 Pi 前，手动在新的临时根目录下准备两个空目录，例如：

```powershell
$FixtureRoot = Join-Path $env:TEMP ('amadeus-gui-demo-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $FixtureRoot 'Documents\Reports'), (Join-Path $FixtureRoot 'Documents\Receipts')
$FixtureRoot
```

手动打开一个新的 7-Zip File Manager 窗口，定位到这个确切根目录，记下实际路径，再让 Pi 选择已观察到的该窗口。预备窗口属于操作员；选择窗口不会使它变成本任务自有窗口。明确启用本机输入后，仅授权以下任务：

> 在已准备好、位于 `<实际 FixtureRoot>` 的 7-Zip 窗口内，仅做目录导航：打开 Documents，打开 Reports，向上一次，再打开 Receipts。核对显示路径为 `<实际 FixtureRoot>\Documents\Receipts`。不得创建、改名、删除、编辑、压缩、解压、输入凭证、打开其他位置或关闭操作员预备的窗口。输入状态不明或审核没有有效票据时，停止并报告。任务后结算原回执，并核实 Runtime 宿主清理。

验收要求为原四步导航全部成功、绑定图像证明最终路径、目录树未变及宿主清理通过。报告任何 Main 审核或人工协助。启动确认、待定回执或未查看的截图均不算成功。本任务不授权写入外部数据，测试目录由操作员事先手动建立；示例只覆盖目录导航，不覆盖压缩／解压，也不是性能基准。

## 任务、审核与收尾

使用随包 [Skill](https://github.com/Desolate-Jix/agent-gui-runtime/blob/amadeus-extension-v0.0.5/integrations/amadeus/agent-review-instant/src/amadeus_agent_gui/skills/gui-execution/SKILL.md) 和[参考](https://github.com/Desolate-Jix/agent-gui-runtime/blob/amadeus-extension-v0.0.5/integrations/amadeus/agent-review-instant/src/amadeus_agent_gui/skills/gui-execution/references/runtime.md)。完整 Work 保持同一个 MCP 连接及一个输入所有者。待定、未知或中断的输入保留原 request／run／command ID，不能为了延长等待而换 ID 重放。

遇到真实 `pre_action_review_packet.v1` 时，用新的状态请求读取原 job，查看该状态请求绑定的 **before 图像**，复制返回的 review recipe，再使用单独返回的 continue recipe。审核本身不点击；继续保留原 job／候选，派发一次前仍须通过新截图的目标区域核对及现有输入门禁。遇到 `field_review_packet.v1` 时，查看已输入文字的绑定 **after 图像**，继续不会重输。文字审核不批准输入前候选，也不证明后续提交成功。没有真实可续票据或证据已过期时，停止并报告原状态。

历史 Pi 证据使用原生缩放后的完整绑定帧，不能声称收到原 PNG 的相同字节。受控、带协助的 0.0.4／0.1.6 实测只证明所述恢复范围，不证明无人准确率、速度或新组合验收。

仅按返回的窗口身份关闭本任务启动的窗口，并核对 `window_closed`；上例操作员预备的窗口应保留。随后调用 `instant_stop` 并查询至 `host_alive=false`、`pending_ids=[]`、`cleanup_verified=true`。之后才能释放 HTTP MCP 所有者，使其他 Work 连接。断线不等于取消或清理。禁用／移除连接器改变 Host 侧连接配置，后端变更遵循 Host 的重启要求；不会停止或卸载外部 Runtime，也不删除它的数据。先完成清理再禁用／移除；如需停用独立服务，再明确关闭它。

## 错误排查与恢复

| 症状 | 核对与处理 |
| --- | --- |
| 拒绝连接、超时或没有工具 | 确认 Runtime 控制台仍在运行、setup 成功，`runtime_url` 使用实际本机端口及 `/mcp`。从未启动服务时，按上方命令启动；其他所有者／输入未结算时，不另起第二份服务。 |
| HTTP 401／`authentication_required` | 两处本机密钥必须相同。secret `connection_token` 填本机密钥，不能填模型 API Key；不要把密钥粘进日志。必须更换 daemon 密钥时，先结算旧任务并完成清理，再明确重启并连接。 |
| HTTP 404、421 或 403 | 通过 Amadeus 原生 MCP 客户端直连 `http://127.0.0.1:<port>/mcp`，核对 endpoint／端口，移除代理或浏览器路线；服务拒绝无效 Host 或浏览器 Origin 请求头。 |
| 缺少 HTTP、工具、schema 或审核／继续 recipe | 人工核对安装版本、MCP 报告的 Runtime 版本及实际 schema。0.1.5 无法提供本连接器服务。合同不受支持时，在新输入前停止；结算旧所有者后，单独安装／配置推荐 Runtime 并重新核对。不伪造票据，不默认后续版本兼容。 |
| 输入禁用或模型／profile 错误 | 在 Runtime 控制台核对私有 API／Decision profile 及其环境变量名。仅为授权任务启用 `--allow-local-input`，并记住它会关闭自动风险拦截。不改阈值／提示词以强行通过；更改启动配置前先结算当前任务。 |
| 输入期间取消请求、超时或断线 | 保留原 ID，检查原状态／结果；取消必须确认到终态才算完成。原活动连接仍可用时，按真实 cancel／status recipe 等待结算，再清理。连接已丢失时，保留诊断并停止，交操作员恢复；新 Work 不是旧 MCP 所有者。未知输入绝不重放。 |
| `input_owner_conflict`、`runtime_cleanup_required` 或旧 owner 未释放 | 回到原活动 Work，结算待定回执、关闭其自有窗口、调用 `instant_stop`、核实全部清理条件后释放原生会话。读取 `cleanup_pending` 诊断，解除具体阻塞后仅重试清理。原 owner 已不可用时，保留证据并请求 Runtime 维护帮助；不得抢占所有权、删除队列／锁／会话记录或反复重连／重启绕过门禁。 |

作者侧源码 0.1.8 检查观察到：同一 HTTP 服务连续两轮启动／停止／释放会话后，两个宿主均已退出，但其中已停止会话的维护登记未立即核销。更新器会另行验证原始结算证据并可核销已结算登记；本轮未复现更新受阻。宿主清理和维护就绪分别记录。维护被拒时应保留原会话证据并联系 Runtime 维护者，不要删除锁或登记。见[验证范围](https://github.com/Desolate-Jix/agent-gui-runtime/blob/amadeus-extension-v0.0.5/docs/verification/AMADEUS_CONNECTOR_005_20261026.md)。

## 版本变化与商店状态

0.0.5 只修改文档／披露及包元数据，不改变连接配置、权限、输入执行或 Runtime 代码。既有 0.0.3／0.0.4 的 `runtime_url`、`connection_token` 无需迁移。历史 0.0.2 stdio 启动器及不可变 0.0.4 产物保持原样。从 0.0.2 迁移时，Runtime 路径、profile、模型密钥与本机输入选项改在独立服务配置，并明确填写两个连接器配置；不能把旧模型密钥当作连接密钥。

作者发布、wheel／预检、协议检查、安装态 GUI 执行、独立商店批准分别记录。本作者发行的 0.0.5 仍**待独立商店审核**，不含作者自批或虚构审核人。请按链接结果的确切范围阅读，未运行层继续保留待定。

连接器代码采用 ISC；Runtime 与第三方许可证分别保留。wheel 不含用户数据、真实 profile、密钥、模型权重或 Runtime 载荷。
