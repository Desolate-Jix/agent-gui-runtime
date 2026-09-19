# Agent Review Instant

**v0.1.0-test.2 · 执行模式第二批测试版 / Execution-mode test release 2**

让支持 MCP 的 Agent 通过同一套 Windows 框架识别界面、点击、填写、编辑按键和滚动，并读取原始截图判断结果。

A Windows automation runtime for MCP-compatible agents: recognize controls, click, type, use editing keys, scroll, and inspect original screenshots to judge results.

> **仅用于有人看护的低风险测试，不是正式稳定版。快捷配置使用管理员宿主并关闭框架自动风险拦截，会真实操作鼠标和键盘。不要用于付款、发送、删除、最终提交等不可逆操作。**
>
> **Supervised low-risk testing only, not a stable release. Quick setup uses an administrator host with automatic risk interception disabled and real mouse/keyboard input. Do not use for payments, sending, deletion or final submissions.**

## 下载 / Download

- [下载测试包 / Download ZIP](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.0-test.2/AgentReviewInstant-v0.1.0-test.2.zip)
- [发布页与 SHA-256 / Release and checksum](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.0-test.2)
- [安装、模型下载与配置 / Setup, models and configuration](FRIEND_SETUP.md)
- [给 Agent 的操作说明 / Agent instructions](AGENT_GUIDE.md)
- [测试范围与限制 / Test scope and limitations](FIXES.md)

这是小型**源码包**，不含 Python 环境、模型权重、账号或用户数据，也不是双击即用的安装器。

This is a small **source bundle**, not a standalone installer. Python dependencies and model weights are installed separately. No accounts or user data are included.

## 能做什么 / Capabilities

| 功能 / Capability | 本版范围 / Scope |
| --- | --- |
| Agent 连接 / Connection | MCP stdio；六个工具 / Six tools |
| 窗口 / Windows | 发现、启动目录内应用、选择、前台切换、最大化 / Discover, catalog launch, select, focus, maximize |
| 识别点击 / Recognition click | 根据明确目标定位；保留原图、模型点与 OCR 证据 / Goal-based targeting with image/model/OCR evidence |
| 输入 / Input | 文本填写/替换、15 种编辑键、上下滚动 / Type/replace, 15 editing keys, vertical scroll |
| 结果判断 / Outcome | Agent 查看前后原图判断；框架不将像素变化冒充任务成功 / Agent judges original images; pixel change is not task success |
| 会话 / Sessions | 一次一个命令、同 ID 不重放、重连取回执、停止清理 / Serial commands, no ID replay, reconnect receipts, cleanup |

**不包含**学习模式、流程记忆复用、完整审核工作台、任意快捷键或无人值守任务。不要将这些开发主线能力当成本次测试包的交付承诺。

**Not included:** learning mode, workflow-memory reuse, the full review workbench, arbitrary hotkeys or unattended tasks.

## 快速开始 / Quick start

1. 使用 Windows x64；依赖锁定为 Python 3.11。先准备 [uv](https://docs.astral.sh/uv/getting-started/installation/)。设备、显存和磁盘规划见安装说明；不同设备仍需实测。
2. 下载 ZIP，解压到空间充足的目录。进入该目录，审阅脚本后执行：

```powershell
.\scripts\setup_instant.ps1 -ModelDirectory "D:\AgentReviewModels\VISTA-4B" -DataDirectory "D:\AgentReviewInstantData" -DownloadModel
```

3. 脚本安装依赖、下载 [VISTA-4B 官方模型](https://huggingface.co/inclusionAI/VISTA-4B)，生成本机 MCP 配置。模型约 9.1 GB，环境另占空间。不要复制别人的绝对路径配置。
4. 将生成的 `mcp-config.local.json` 中的服务器配置导入 Agent，重新连接。UAC 弹窗由本人确认；本包不自动确认 UAC。
5. 把 [AGENT_GUIDE.md](AGENT_GUIDE.md) 给 Agent，先验连接，再在专用低风险窗口测试。结束后 `instant_stop`，轮询 `instant_status`，直到 `cleanup_verified=true`。

Use Windows x64 and Python 3.11 with uv. Extract the ZIP, review and run the setup command above, then import the generated local MCP configuration into your Agent. Confirm UAC yourself. Follow AGENT_GUIDE.md, test a dedicated low-risk target, and poll cleanup after stopping. Setup does not alter global Agent configuration or download unrelated models.

已有环境与模型，仅重新生成连接配置 / Reuse an existing environment and model:

```powershell
.\scripts\configure_instant.ps1 -ModelDirectory "D:\AgentReviewModels\VISTA-4B" -DataDirectory "D:\AgentReviewInstantData"
```

## 已验证与边界 / Verification and limits

- 本批在首个公开测试版基础上增量更新：550 项相关回归、真实 MCP 无输入生命周期与隔离功能入口检查通过。源码实机表单连续 10 轮/220 次输入通过；隔离候选另跑 1 轮/22 次输入，截图摘要和清理均通过。这不是跨设备成功保证。
- 回归范围和未通过的辅助测试分类见 FIXES.md。曾出现已输入但后图失败，已补全原因诊断；具体原因尚未证实，后续未复现不代表已修复。首次安装、模型加载、管理员目标和其他设备仍需接收者实测。
- 小目标与不完整 OCR 仍可能定位不准；冷启动较慢。`verified=null` 表示待 Agent 判断，不代表成功或失败。
- Agent 主图与内部即时诊断帧分别标记，不能混用其差分。等待后图不保证页面已渲染完成；缺图时不自动重放。
- 一个桌面同时只让一个 Agent 操作；程序、模型和数据目录分开。提供源码清单与 SHA-256，升级不要覆盖模型或历史。

Incremental release on test.1: 550 targeted regressions, real no-input MCP lifecycle and isolated functional imports pass. Ten source-form rounds (220 inputs) and one isolated-candidate round (22 inputs) pass with image hashes and cleanup checked. A previous missing after-frame remains unexplained; improved diagnostics and no recurrence are not a proven fix. See FIXES.md for scope and auxiliary-test failures. This is not a cross-device, elevated-target or small-target guarantee. Null verification means unassessed; inspect images instead of replaying input.

## 维护者检查 / Maintainer checks

包内带有编辑键、文本输入和 MCP 的无输入回归子集。安装开发依赖后执行 `python -m pytest tests -q`；它不等于完整开发仓库的 550 项相关验收。真实连接检查可运行 `scripts/smoke_instant_mcp.py`（参数见安装说明）。不要把单元测试通过当作已执行桌面动作。

The bundle includes a no-input regression subset for editing keys, text input and MCP. After installing dev dependencies, run `python -m pytest tests -q`. This subset is not the full 550-check development validation. The stdio smoke script separately checks connectivity; neither substitutes for real desktop testing.

## 反馈 / Feedback

[提交 Issue / File an issue](https://github.com/Desolate-Jix/agent-gui-runtime/issues)：提供版本、Windows/GPU、目标软件、复现步骤、脱敏回执、是否发生真实输入及清理结果。截图和日志可能含个人信息，请自行脱敏，**不要上传账号、令牌、完整私人会话或模型权重**。

Include version, Windows/GPU, target application, reproduction steps, redacted receipts, actual-input status and cleanup results. Remove personal data from screenshots/logs; never upload credentials, private conversations or weights.

## 源码分支与许可 / Source branch and license

`codex/release-instant-test-2`：用于第二批执行模式测试版的可复现源码快照；不替代完整桌面产品开发分支。 / A clean source snapshot for this instant-mode test release, separate from full-product development.

[ISC License](LICENSE)。依赖与模型受各自许可证约束，模型从官方来源另行下载。 / Dependencies and models retain their respective licenses and are downloaded separately.
