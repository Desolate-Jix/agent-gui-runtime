# Agent Review Instant

**v0.1.0-test.4 · 执行模式测试版 / Execution-mode test release**

本分支以已发布 test.4 为基线，包含尚未打包的输入框聚焦修复；下方下载仍是原 test.4，不含本修复。它不是正式稳定版。/ This branch is based on published test.4 with an unreleased input-focus fix. The download below remains the original test.4 and does not contain this fix. It is not production-stable.

源码修复与实测边界见 [输入框聚焦回归 / Input-focus regression](EXECUTION_INPUT_FOCUS.md)。/ See the linked report for source changes and live-test limits.

**已做有限实测的源码新增，未发布 / Source additions with bounded live verification, unreleased:** `input_sequence` 组合填写、核对与可选回车；`instant_run` 一次返回精简回执和原图；同帧 UIA 父链去重；新增可选 `observation_condition`，等待明确标志出现后返回，不改变默认等待。836 项测试通过；本轮同一真实 Google 窗口连续完成 9 次搜索、1 次已有标志负控，原图与清理均复核。条件命中的“回车＋后图”0.76–1.50秒，对照固定等待2.17–2.31秒；这是有限组件测量，不是总体性能或准确率保证。旧 test.4 不包含这些新增。 / 836 tests passed. Nine real same-session searches and one pre-existing-marker control completed, with image and cleanup verification. Successful conditional Enter-plus-observation took 0.76–1.50s versus fixed 2.17–2.31s; bounded component measurements are not overall performance or accuracy guarantees. Released test.4 does not include these additions.

**独立验收 / Independent acceptance:** AionUi 同源码最终一轮8次搜索＋1次负控通过；前4次客户端中止、条件未提前结束及跨宿主窗口归属问题如实保留。验收后的两处回执修复另做无输入复核，详见 [验收范围 / Acceptance](EXECUTION_AIONUI_ACCEPTANCE_20260921.md)。 / The final independent round passed; earlier failures and remaining limits are retained. Receipt-only follow-up is distinguished from live coverage.

见 [接口 / API](EXECUTION_INPUT_SEQUENCE.md)、[早期测试 / Earlier tests](EXECUTION_INPUT_SEQUENCE_TESTS.md)、[UIA 去重 / UIA deduplication](EXECUTION_UIA_SCAN_OPTIMIZATION.md) 与 [条件等待与稳定性 / Conditional wait and stability](EXECUTION_CONDITIONAL_WAIT.md)。

让支持 MCP 的 Agent 通过同一套 Windows 框架识别界面、点击、填写、编辑按键和滚动，并读取原始截图判断结果。

A Windows automation runtime for MCP-compatible agents: recognize controls, click, type, use editing keys, scroll, and inspect original screenshots to judge results.

> **仅用于有人看护的低风险测试，不是正式稳定版。快捷配置使用管理员宿主并关闭框架自动风险拦截，会真实操作鼠标和键盘。不要用于付款、发送、删除、最终提交等不可逆操作。**
>
> **Supervised low-risk testing only, not a stable release. Quick setup uses an administrator host with automatic risk interception disabled and real mouse/keyboard input. Do not use for payments, sending, deletion or final submissions.**

## 下载 / Download

- [下载测试包 / Download ZIP](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.0-test.4/AgentReviewInstant-v0.1.0-test.4.zip)
- [发布页与 SHA-256 / Release and checksum](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.0-test.4)
- [安装、模型下载与配置 / Setup, models and configuration](FRIEND_SETUP.md)
- [给 Agent 的操作说明 / Agent instructions](AGENT_GUIDE.md)
- [测试范围与限制 / Test scope and limitations](FIXES.md)

这是小型**源码包**，不含 Python 环境、模型权重、账号或用户数据，也不是双击即用的安装器。

This is a small **source bundle**, not a standalone installer. Python dependencies and model weights are installed separately. No accounts or user data are included.

## 能做什么 / Capabilities

| 功能 / Capability | 本版范围 / Scope |
| --- | --- |
| Agent 连接 / Connection | MCP stdio；六个工具 / Six tools |
| 窗口 / Windows | 发现、目录启动、选择、前台切换、最大化、正常关闭本会话启动的窗口 / Discover, catalog launch, select, focus, maximize, close session-launched windows |
| 识别点击 / Recognition click | 单击、右击、双击；字段、菜单项和单词定位，保留原图和几何来源 / Single/right/double click with field/menu/word targeting and original evidence |
| 输入 / Input | 文本填写/替换、23 种编辑键、上下滚动 / Type/replace, 23 editing keys, vertical scroll |
| 读取 / Reading | 每次从当前可见原图读取OCR文字及行框；不是全页或DOM提取 / Fresh visible-image OCR and line boxes, not full-page/DOM extraction |
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
5. 把 [AGENT_GUIDE.md](AGENT_GUIDE.md) 给 Agent，先验连接，再在专用低风险窗口测试。同一任务保持连接；结束前 `close_launched_window` 关闭本会话测试窗口，然后 `instant_stop` 并轮询 `instant_status` 至 `cleanup_verified=true`，最后断连。

Use Windows x64 and Python 3.11 with uv. Extract the ZIP, review and run the setup command above, then import the generated local MCP configuration into your Agent. Confirm UAC yourself. Follow AGENT_GUIDE.md, test a dedicated low-risk target, and poll cleanup after stopping. Setup does not alter global Agent configuration or download unrelated models.

已有环境与模型，仅重新生成连接配置 / Reuse an existing environment and model:

```powershell
.\scripts\configure_instant.ps1 -ModelDirectory "D:\AgentReviewModels\VISTA-4B" -DataDirectory "D:\AgentReviewInstantData"
```

## 已验证与边界 / Verification and limits

- test.4 冻结候选已通过 743 项源码回归与 743 项隔离包回归（集合有重叠，不相加），另有 7 项构建检查和 241 项运行时导入检查；未发现原工作树泄漏。/ The test.4 frozen candidate passes 743 source checks and 743 isolated-bundle checks (overlapping, not additive), plus 7 build checks and 241 runtime-import checks with no worktree leakage.
- Codex 已在同一冻结候选完成原生连续流程与浏览器连续流程；AionUi 随后完成四个有界验收组。AionUi 的首轮并非全通过，期间修复了 5 个 tester-client 问题后，四组复测均通过。/ Codex completed native and browser continuous journeys on the same frozen candidate. AionUi then passed four bounded groups after five tester-client fixes; the first attempt was not all-pass.
- 原生覆盖记事本替换、键盘 Undo、菜单 Undo 与 Don't Save 关闭；浏览器覆盖 Python 文档 Quick search → 精确文章 → Back，并重复两次后关闭/停止清理。归档哈希 562 项、图片引用 23 项、冻结文件 595 项均已复核。/ Native coverage includes Notepad replace, keyboard Undo, menu Undo and Don't Save close; browser coverage is Python docs Quick search → exact article → Back, repeated twice, then close/stop cleanup. 562 archive hashes, 23 image references and 595 frozen files were verified.
- 这是有人看护的 operator-mode 测试包；本批未验证自动策略，也不作通用准确率或性能承诺。Back 实测约 19.95–22.58 秒，链接约 7.85–8.37 秒，均为观测值而非保证。/ This remains an operator-mode test package; automatic-policy validation was not performed, and no general accuracy or performance claim is made. Observed Back latency was about 19.95–22.58s and link latency about 7.85–8.37s; these are observations, not guarantees.
- 候选 09 的独立实机失败记录保留为历史，不代表 test.4 结果。首次安装、管理员目标和跨设备验收本批未重复；不自动重放、不承诺任意网站或长期稳定。/ Candidate09's independent live-acceptance failure is retained as history and does not describe test.4. Fresh install, elevated targets and cross-device acceptance were not repeated; no automatic replay, universal-site or long-term stability claim is made.

The earlier candidate09 failure remains historical context; the test.4 evidence above is the current release evidence. Counts overlap and are not additive.

**依赖不要混用 / Keep the interpreter consistent:** 本包锁定 Python 3.11 与 `rapidocr-onnxruntime==1.4.4`。MCP服务与辅助OCR脚本都使用安装脚本生成的 `.venv\Scripts\python.exe`，不要随手用PATH里的 `python`。实测旧版1.2.3不返回词级几何，出现 `OCR word output is missing character metadata` 时先核对解释器和依赖，不要跳过校验或把整行框伪装成词框。 / Use the package venv for both MCP and OCR helpers. Version 1.2.3 lacks the required word metadata; check interpreter/dependencies rather than fabricating word boxes.

## 维护者检查 / Maintainer checks

包内带有编辑键、MCP、读文、鼠标序列、菜单和词框的无输入回归子集。安装开发依赖后执行 `python -m pytest tests -q`；它不等于完整开发仓库验收。真实连接检查可运行 `scripts/smoke_instant_mcp.py`（参数见安装说明）。不要把单元测试通过当作已执行桌面动作。

The shipped no-input subset covers keys, MCP, reading, mouse sequences, menus and word geometry. Run `python -m pytest tests -q` after installing dev dependencies. This is not full-repository validation; the separate stdio smoke also does not substitute for live input.

## 反馈 / Feedback

[提交 Issue / File an issue](https://github.com/Desolate-Jix/agent-gui-runtime/issues)：提供版本、Windows/GPU、目标软件、复现步骤、脱敏回执、是否发生真实输入及清理结果。截图和日志可能含个人信息，请自行脱敏，**不要上传账号、令牌、完整私人会话或模型权重**。

Include version, Windows/GPU, target application, reproduction steps, redacted receipts, actual-input status and cleanup results. Remove personal data from screenshots/logs; never upload credentials, private conversations or weights.

## 源码分支与许可 / Source branch and license

`codex/release-instant-test-4`：用于第四批执行模式测试版的可复现源码快照；不替代完整桌面产品开发分支。 / A clean source snapshot for this instant-mode test release, separate from full-product development.

[ISC License](LICENSE)。依赖与模型受各自许可证约束，模型从官方来源另行下载。 / Dependencies and models retain their respective licenses and are downloaded separately.
