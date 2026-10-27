# Runtime 0.1.8/0.1.9 task-plan settlement / 任务计划结算

## English

Runtime 0.1.8 can finish a task plan and clean up its processes, yet reject
`update_runtime.py settle` with `runtime_task_ledger_session_unsettled`.
Its input-terminal classifier does not cover task-plan commands. Runtime 0.1.9
validates the original frozen plan, runner, command and input receipts before
settling those registrations. Runtime 0.1.10 also validates successful read-only
observation records and original pre-dispatch refusal proofs. It does not
re-evaluate model answers, repeat
input, revive a workflow or classify an input-bearing plan as read-only.

The old updater uses the old classifier. Re-running it or launching the old
installer does not repair a retained task-plan registration. **Do not delete
the registration, lock, task directory or evidence to install an update.**

### Use the repaired verifier without replacing the old installation

1. Finish or cancel the original task using its original IDs. Stop the Runtime
   host normally, confirm its cleanup, and close the HTTP/stdio service and
   other Runtime clients. An active task, unknown input or incomplete cleanup
   still blocks maintenance.
2. From the [0.1.10 release](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.10),
   download `AgentGUIRuntimeExecution-update.zip`, `runtime-update.json` and
   `SHA256SUMS.txt`. Verify their published SHA-256 values and each extracted
   file's path, size and SHA-256 against `runtime-update.json`. Extract into a
   **new, separate directory**, never over the existing installation. Use only
   this project's release; a hash is not an independent publisher signature.
3. Run the **new directory's** maintenance script with an existing compatible
   Runtime Python environment and the **old installation** as `--root`:

   ```powershell
   & '<runtime-python>\python.exe' -I -B -X utf8 '<verified-0.1.10>\scripts\update_runtime.py' --root '<old-installation>' settle
   ```

   This imports the new verifier and takes the old installation's exclusive
   maintenance lock. It clears only registrations whose original resource and
   input proofs pass. It neither replaces program files nor changes credentials,
   user data or task evidence. If it refuses, retain the error and evidence;
   do not force removal or repeat a task to manufacture a settled state.
4. After successful settlement, use the old installation's normal `stage` and
   `apply` commands, inspect the exact target and explicitly confirm its digest.
   Alternatively install the verified new installer after the same settlement.
   A new task cannot run while the exclusive maintenance lock is held.

Older refused requests may lack the original proof required by 0.1.10. A failure
message or absence of a dispatch record cannot replace it; these sessions remain
blocked. Do not backfill receipts, edit original evidence, remove registrations
or repeat a task to force a pass. Recovery of every affected session is not
guaranteed. Advanced `recover`/`resume_pre_dispatch` task-plan controls remain
unqualified for settlement.

The release's acceptance report records the exact tested versions and route.
This procedure addresses proven task-plan settlement; it does not certify
unknown legacy sessions, arbitrary version migrations or physical power loss.
Published SHA-256 values identify the tested assets; they do not mean GitHub
enforces immutable releases. Verify every extracted file before running code:

```powershell
$target = Get-Content -LiteralPath '<download>\runtime-update.json' -Raw | ConvertFrom-Json
$verified = '<separate-extraction>'
foreach ($item in $target.files) {
    $file = Join-Path $verified $item.path
    if ((Get-Item -LiteralPath $file).Length -ne $item.size -or
        (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.sha256) {
        throw 'Runtime payload verification failed'
    }
}
```

This file-list check follows the official HTTPS download, archive hash and safe
path validation in step 2. It is not a safe extractor for an untrusted archive.

## 简体中文

Runtime 0.1.8 可能已完成任务计划并清理进程，但官方
`update_runtime.py settle` 仍报 `runtime_task_ledger_session_unsettled`。
原因是输入终态分类未覆盖任务计划命令。0.1.9 会核验原冻结计划、runner、
命令和输入回执，再结算对应登记；不重新判断模型答案，不重复输入，不恢复
旧流程，也不把有输入的计划当作只读。0.1.10 另核验成功只读观察的原记录及原始
派发前拒绝证明。

旧更新器仍使用旧分类器，重复运行或直接启动旧安装器不能修复这类残留登记。
**不要为安装更新而删除登记、锁、任务目录或证据。**

### 不替换旧安装，先使用修复后的核验器

1. 使用原 ID 正常完成或取消原任务，正常停止宿主并确认清理，再关闭
   HTTP／stdio 服务及其他 Runtime 客户端。活动任务、未知输入或未完成的
   清理仍会阻止维护。
2. 从 [0.1.10 发布页](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.10)
   下载 `AgentGUIRuntimeExecution-update.zip`、`runtime-update.json` 和
   `SHA256SUMS.txt`。核对发布的 SHA-256，并按 `runtime-update.json` 核对
   解包后的逐文件路径、大小和摘要。解压到**全新的独立目录**，不要覆盖旧安装。
   只使用本项目发行来源；摘要不等于独立的发布者签名。
3. 用已有的兼容 Runtime Python 环境执行**新目录里的**维护脚本，
   `--root` 指向**旧安装目录**：

   ```powershell
   & '<Runtime Python目录>\python.exe' -I -B -X utf8 '<已核验0.1.10目录>\scripts\update_runtime.py' --root '<旧安装目录>' settle
   ```

   该命令加载新版核验逻辑，持有旧安装的排他维护锁，只清理原资源与输入证明
   全部通过的登记。不替换程序，不改密钥、用户数据或任务证据。若拒绝，保留
   错误和证据；不要强制删除，也不要重做任务来制造结算成功。
4. 结算成功后，在旧安装使用正常 `stage`／`apply`，检查确切目标并明确确认
   摘要；也可在同样完成结算后使用核验过的新安装器。排他维护锁持有期间
   不能启动新任务。

旧拒绝请求可能缺少 0.1.10 所要求的原始证明。错误文字或派发记录缺失不能替代
证明，这类会话仍会阻断维护。不要补造回执、修改原证据、删除登记或重做任务来
制造通过；不保证所有受影响会话均可恢复。高级 `recover`／`resume_pre_dispatch`
任务计划控制仍未通过结算认证。

确切测试版本与升级路径见发布附件中的验收报告。本流程只处理证据完整的
任务计划结算，不代表未知旧会话、任意版本迁移或物理断电均已通过验收。
发布摘要标识已测资产，不代表 GitHub 已强制发行不可变。执行代码前，按上方
PowerShell 示例逐项核验解包文件大小与 SHA-256。该检查应在第 2 步官方 HTTPS
下载、压缩包摘要及安全路径检查之后进行，不能用作不可信压缩包的安全解包器。
