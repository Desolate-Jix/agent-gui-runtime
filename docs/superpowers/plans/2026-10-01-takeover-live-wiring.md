> **2026-10-01 当前顺序已调整 / Current priority supersedes earlier sequencing:** [学习主线重排计划](2026-10-01-learning-mainline-refocus.md) 为当前执行入口。先完整流程与六对诊断试采，再限定恢复、扩大实测。原目标、技术合同、未完成完整验收及首次失败保留；旧“待确认”和“下一步”只代表当时状态。本轮仅改计划，开发继续暂停。 / Follow the refocused plan; retain original targets and evidence. Historical pending approvals are not current blockers, and implementation remains paused.

# 原宿主现场接管接线 / Maintained live takeover wiring

沿已授权 R3 主线继续；learning 不发布、不改版本，正式 v0.1.1 保持独立。上一批接管基础相关回归 466 passed，不代表完整 GUI 验收。/ Continue approved R3 development without publishing learning or changing stable v0.1.1.

## 接口与事务 / Interface and transaction

1. 原 learning_workflow 增加 takeover_preview，输入 admission_request_id、source_run_id；外层原命令 ID 是持久预览 ID。原宿主通过既有 owner/只读观察器采集新界面，不接受客户端 observation/envelope。返回不可变预览 hash、来源、规则结果、拟导入账本及后续等待，失败/不确定不授予接管。/ The maintained host collects the observation and returns an immutable preview rather than accepting client evidence.
2. takeover_commit 输入 preview_request_id、preview_sha256、mode 及原可选 vision_capabilities。首次提交重新现场采集并比较预览中的业务范围、对象身份与结果；不比较光标等无关窗口像素。源及效果不符就拒绝。原 claim/Trial/Runner 导入暂停，不执行旧输入；明确原 continue 才生成后续新 EID。/ Reobserve semantic scope and effect before paused import; downstream dispatch stays explicit.
3. 原 queued 控制请求本身尚无 response。session_input_terminal 只允许确切当前 takeover 控制（原 ID/命令 SHA/受支持 action）作为只读处理中事实，其余 pending 仍拒绝。新输入指纹只排除同预览事务确切的控制及回执，不宽泛忽略所有 learning_workflow。普通准备与门控不变。/ A narrowly bound current control is distinct from unresolved input; unrelated pending commands still block.
4. 持久预览和首次提交记录固定逻辑请求、配置与真实新观察；失败后沿原记录恢复，不替换观察或重放原输入。ready 同逻辑请求回读原运行及新增 history；外层重试控制不得成为第二次消费。/ Durable logical retries reuse the transaction and never replay the source command.
5. 失败历史核验回读原 runtime 失败回执和 request digest；多 epoch 来源链另以原 claim/admission/历史前缀递归核验。缺原凭据、未知或冲突保持拒绝。/ Verify runtime failure and repeated-epoch provenance from original evidence without inventing facts.

## 检查与剩余范围 / Verification and remaining scope

- 有效 RED→GREEN：当前控制精确例外、队列竞争、来源/窗口/对象/值漂移、中文、短库锁外观察、持久故障及同逻辑请求重试。/ Contract checks cover exact control identity, drift and durable retries.
- 真实 original host/MCP/GUI 连续任务仍须单项→同应用状态累积/弹窗/中断/恢复/完整任务/清理；修复复测后再交同冻结候选独立验收。离线模拟不计实机通过。/ Complete fresh live continuity before independent acceptance.
- 新窗口实例与动态业务对象需要明确新绑定；人工 C、匹配 R4 收益、实测 R5 优化及 R6 迁移仍未完成。/ Rebinding and the benefit/transfer stages remain open.
