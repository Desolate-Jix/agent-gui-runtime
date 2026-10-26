# 确认后更新 Runtime

**0.1.8 任务计划结算：** 若已完成清理但 `settle` 仍报
`runtime_task_ledger_session_unsettled`，请按 [0.1.9 恢复流程](RUNTIME_018_SETTLEMENT_RECOVERY.md)
处理。不要删除登记或任务证据；活动任务和未知输入仍会阻止维护。

Runtime **0.1.8** 开始提供更新器。0.1.7 及更早版本需先关闭并核实所有旧 Runtime
入口，再手动安装 0.1.8；旧安装器没有更新器。[发布与下载](releases/EXECUTION_018_20261024.md)。

[English](RUNTIME_UPDATES.md)

## 两个产品分别升级

Runtime 只升级自己的执行文件。Amadeus 的 HTTP MCP＋Skill 扩展继续通过它的
插件商店独立检查、确认和管理版本。兼容的 Runtime 补丁不要求重新安装未变化的
扩展，双方不会静默安装对方。

Runtime 启动入口会用独立后台进程检查本项目 GitHub 稳定版，每天最多一次，支持
关闭检查。检查不预下载载荷、不调用视觉／Decision API、不取消任务，也不安装。
`instant_status` 只报告简短的缓存更新状态；离线或检查失败不影响执行。

## 本地维护入口

在安装目录打开 PowerShell。包装脚本使用安装中已准备好的 Python 环境，不安装依赖。

```powershell
.\scripts\update_runtime.ps1 -Action status
.\scripts\update_runtime.ps1 -Action check
.\scripts\update_runtime.ps1 -Action stage
.\scripts\update_runtime.ps1 -Action apply
```

`stage` 将选中的发行版下载到安装目录旁的暂存目录并核验，不改变已安装文件。
`apply` 展示确切目标的 SHA-256，需要输入该摘要确认后才安装。本地自动化也可在
操作员批准该确切目标后，为 Python CLI 提供 `--confirm-target <确切 SHA-256>`。
安装入口不对普通 MCP 工具开放。

应用前须关闭所有 Runtime 客户端、HTTP 服务和模型 worker。安装级内核锁阻止更新
与新任务启动发生竞争。原输入未结算、清理证据缺失或崩溃后留下的登记同样阻止更新：
进程退出不等于清理完成。更新器不会强制结束任务或删除原记录来制造空闲状态。
`-Action settle` 可重查原证据，仅清除已经证明结算的登记；未知或未完成输入仍被阻止。

```powershell
.\scripts\update_runtime.ps1 -Action disable-checks
.\scripts\update_runtime.ps1 -Action enable-checks
```

## 失败与回滚

更新前，将安装文件与已安装卸载器内嵌的冻结清单核对，并保留完整备份和持久事务
日志。新卸载器、文件所有权记录与新载荷一起切换，保持后续安装／卸载兼容；正常
安装的注册表展示版本也参与同一事务。

替换后运行固定的隔离导入／接口检查，不创建输入宿主、不调用模型 API。失败时
恢复旧的受管文件和注册版本。这是安装健康检查，不代表新版本的所有 GUI 流程均
已通过实测。

```powershell
.\scripts\update_runtime.ps1 -Action rollback
.\scripts\update_runtime.ps1 -Action recover
```

回滚需要确认本地保留的确切旧目标。更新中断或回滚失败时，保留备份并阻止启动新
任务。`status` 会给出运行外部事务备份中旧更新器的恢复命令，避免依赖已被部分
替换的安装代码。不要删除待恢复标记、日志或备份来绕过恢复；中断任务不会自动重放。

用户数据、模型、密钥和 Python 环境不属于版本载荷，不随代码回滚或清理。第一版
更新器遇到依赖锁、Python 合同、随包配置变化或跨 major/minor 发行线时，会要求
先核对兼容性并手动安装迁移；本地文件
被修改或与未知文件冲突时拒绝覆盖。备份会保留，尚未启用自动清理。

## 来源与信任边界

来源固定为 `Desolate-Jix/agent-gui-runtime` 的 GitHub 稳定版。拒绝预览／草稿、
任意地址或命令、不安全 ZIP 路径、暂存被修改、大小／摘要不符，以及已见版本被
换成另一份目标。下载有界，不向更新来源发送模型或 MCP 密钥。
当前信任依据是固定 GitHub HTTPS 来源、确切摘要和操作员确认。
**安装器仍未签名；摘要不是独立的发布者签名。尚未实现 TUF、Authenticode 或
发布证明的验证。**

发布时须提供相互匹配的 `runtime-update.json`、
`AgentGUIRuntimeExecution-update.zip` 和该不可变版本的安装器。
`scripts/build_runtime_update.py` 从已验证的安装器构建生成两份更新资产，不负责
发布。缺少这些资产的旧发行版不能通过此更新器应用。

Amadeus 上游实现及独立的验证／激活边界见
[Amadeus 更新实现记录](development/AMADEUS_UPDATE_IMPLEMENTATION.md)。
