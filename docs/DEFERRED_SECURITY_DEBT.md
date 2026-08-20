# Deferred Security Debt

日期：2026-08-15

本文件记录本阶段明确保留、但没有借助文档措辞掩盖的两项安全债务。它们不改变当前的 Gate、Operation、Execute 或 final-submit/no-submit 边界。

## 1. 受管 artifacts 的本地写权限与证据引用/路径替换边界

### 问题

reviewed workflow 的证据 materialization 可能在本地受管目录中复制或替换 screenshot、overlay 及其引用路径，并产生 materialization digest。当前 revision 修复已经要求用服务端已落盘 bytes、registry provenance、资产字节哈希和审核证据建立可信 revision；但“本地写权限下哪些路径可被替换、谁拥有替换权、替换后哪些引用仍然是同一证据”的正式存储边界仍未完成。不能把文件名、报告文字、客户端 hash 或路径存在本身当作证据。

### 当前补偿（fail closed）

- 只读 projection 不接受客户端 `reviewed_revision_hash`、标签或布尔值来构造可信 revision。
- 缺失、无效、陈旧或 provenance 不完整的 revision 继续得到 `needs_human_review`；navigation replay 在预筛阶段将其标为 invalid case，不进入 Agent context、Gate 或 Operation。
- source path、内容、语义、控件、动作或 evidence provenance 发生无法证明的变化时，不复活旧批准。
- `artifact_is_authorization=false`、`execute_binding_enabled=false`、`final_submit_forbidden=true` 保持不变；当前公开行为只到 Quick Apply `open_apply_flow` 与 no-submit safe-stop。

### 何时修

在任何要把受管 artifact 用作跨进程/跨 worker 的 Agent operational memory，或要扩大到 live safe-fill、ATS E2E、执行绑定之前修复。修复应采用内容寻址/不可变证据对象或等价的显式 allow-list + owner/provenance 机制，并补充跨路径 materialization、同路径内容篡改、overlay 复制、重放和重启后的 bytes/SHA-256 回归；在此之前不扩大公开范围。

## 2. 单 API owner 模型下 registry 并发 stale save

### 问题

当前 durable workflow store 明确是单 API owner；重叠 API worker 会因 owner 冲突 fail closed，共享多 worker 协调尚未实现。registry review save、后台 projection/rebuild 或 reload 若在未来并发，仍需要服务端 compare-and-swap/owner epoch 约束，防止较旧的 workflow bytes、registry provenance 或 review revision 覆盖较新的人工保存。当前不应把单 owner 约束误写成已经解决了并发 stale save。

### 当前补偿（fail closed）

- 在单 owner 运行约束下拒绝重叠 owner；不支持共享多 worker deployment。
- 保存事务从同一事务内已落盘的服务端 workflow bytes 与 registry provenance 构造 revision map；缺 map、无效 hash 或旧 revision 继续落为 `needs_human_review`。
- replay 要求每个资产携带与资产字节、审核证据和 `interface_id` 绑定的 persisted revision；缺失/陈旧即 invalid case。
- projection、Gate、Operation、Execute 与 final-submit/no-submit 仍不授权 stale save 产生动作；Quick Apply 只到入口观察，终端提交永远 safe-stop。

### 何时修

在启用多 API worker、多进程共享 store、异步 review rebuild，或任何需要并发保存/发布前修复。应为 registry 写入增加单调 revision/owner epoch 和 CAS（或等价的锁/序列化协议），让旧版本保存明确返回 stale conflict，并补并发 save/reload/replay negative controls；在完成并验证前保持单 owner 与 fail-closed。

## 当前验证范围

本阶段完整离线验证为：`uv run pytest tests -q` → `2762 passed, 1 skipped` in `149.42s`；full JavaScript 为 `128 passed, 0 failed`。一次被忽略但必需的 Python.org screenshot fixture 已从 `logs` 下已有的 SHA-256 完全相同副本恢复；这是测试证据恢复，不是代码变更或提交产物。focused 下位证据为：form `286 passed`、learning `412 passed`、navigation/SEEK offline `443 passed`、JavaScript `104 passed`。这些结果不代表真实 SEEK、live Demo、live safe-fill、ATS E2E 或推送完成。