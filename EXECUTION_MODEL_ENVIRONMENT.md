> **test.4 发布状态 / Release status (2026-09-21):** 本文契约实现已随冻结候选 10 交付。下文较早的“仅源码/待测试/test.3 未更新”描述保留为当时记录，不代表当前 test.4 状态。最新限定实测和未覆盖范围以 [FIXES.md](FIXES.md) 为准。 / Implementation ships in test.4; earlier source-only/pending notes below are historical. Consult FIXES.md for current coverage and limits.

# 模型子进程环境 / Model worker environment

## 故障 / Failure

source24 在最小环境的 MCP 宿主中，识别点击前的模型准备失败，未派发输入。同一配置从普通终端启动成功。无输入对照确定两处必要环境缺失：没有 `PATHEXT` 时 PowerShell 把绝对路径的 `python.exe` 当文档激活，启动脚本提前返回；补齐后又发现缺少账户环境，使 Torch 的 `getpass.getuser()` 在 Windows 错误尝试导入 `pwd`。 / Model preparation failed before input under a minimal MCP host environment, while the same configuration worked from a normal terminal. Controls isolated missing executable-extension classification and account identity: PowerShell treated Python as a document, then Torch's username lookup attempted Unix `pwd` on Windows.

## 通用修复 / Shared fix

- `app/vision/model_environment.py` 只为模型子进程创建环境副本，不更改宿主、系统变量、用户配置、权限或模型权重。 / Create a worker-only copy, without changing parent/global settings, permissions or weights.
- 仅 Windows 且 `PATHEXT` 缺失或空时补 `.EXE`；保留已有扩展名配置。 / Supply `.EXE` only when Windows PATHEXT is absent or empty; preserve explicit existing values.
- 仅 `LOGNAME`、`USER`、`LNAME`、`USERNAME` 均无值时，从操作系统取得当前账户并设置子进程 `USERNAME`；不从目录名猜测。读取失败明确报错，不使用伪造账户。 / When all standard account variables are absent, obtain the current account from the OS; never infer it from a path or invent a fallback.
- 同一准备、进程所有权、日志、取消与清理链保持不变。不是模型协议错误后的备用模型，也不自动重放桌面输入。 / Preserve preparation, ownership, logging, cancellation and cleanup; no alternate model or automatic input replay.

## 验证与边界 / Evidence and limits

8 项新回归通过；模型相关集合 125 项通过。原先失败的最小环境下，正式准备入口返回 `ready`，原 Job 清理通过；随后 source25 在真实新记事本中完成右键、首行选区/替换、菜单撤销与“不保存”，并确认窗口和宿主清理。 / Eight new tests and 125 related checks pass. The original minimal environment now prepares and cleans up the real model; source25 also passes the scoped native edit/menu/discard journey.

这不证明任意缺失环境都可恢复，也不代表跨设备或最新冻结包已通过。浏览器后退完整复验仍等待用户处理首次使用/隐私设置；未经同包独立验收不发布。 / Not a claim that arbitrary stripped environments, other devices or a new frozen bundle are validated. Browser acceptance and independent same-package testing remain required before publication.
