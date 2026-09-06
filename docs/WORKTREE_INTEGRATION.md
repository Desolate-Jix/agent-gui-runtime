# 工作树收拢与主目录流程

更新：2026-09-06。本页记录本地合并，不代表全项目或生产发布验收完成。

## 当前目录职责

| 目录/分支 | 职责与状态 |
|---|---|
| `D:/agent-gui-runtime` / `codex/replay-v2` | 日常统一入口；已从 `5510e78c` 快进到 `1cb1291e`，包含 310 个既有依赖提交与 1 个实验接入提交 |
| `D:/agent-gui-runtime/.worktrees/omni-guiactor-learning` | 已合入的实验快照；保留原 105 条真实推理、框图和审核证据，不再继续平行修改同一功能 |
| `D:/agent-gui-runtime/.worktrees/simple-provider-protocol-v1` | 提交已被上面来源分支包含，无需再单独合并；验收仍引用其部分输入，暂不删除 |

没有 push、删除工作树/分支、切换生产模型默认或放松动作门禁。工作树内 Git 状态干净不代表 ignored 证据可以删除。

## 同名文件取舍

主目录四个未跟踪原件已通过 SHA-256 核对后，原样移动到 `D:/agent-gui-runtime/artifacts/worktree-merge/20260906/archived-originals/`；此前的 `target-before/` 字节级备份也保留。记录在同级 `before.json` 和 `20260906-mainline/merge.json`。

- 两份 `2026-09-05-omni-guiactor-integration-supplement.md` 计划/设计：采用来源分支的更新状态，原件保留。
- `scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py` 与配套 runner 测试：采用来源分支实现。旧生产接口全部通过 `RunnerProductionBlocked` 阻断，不是已运行的生产能力；不把旧注入接口重新拼进新版。
- `tests/test_agent_runtime_actual_adapter_portfolio_v1.py` 是主目录独有的未跟踪测试，原文件逐字节保留，未纳入本次提交。

### benchmark 独有逻辑核对

| 旧约束 | 新版落点与处理 |
|---|---|
| 可注入 runtime port | `BenchmarkV2ProductionRuntimePort` 与公开 factory；测试在 factory 接缝注入，不恢复旧 `run_cli(runtime=..., clock=...)` |
| 派发前重新校验 | `attest_benchmark_provider_dispatch` 在各 provider 真正 I/O 边界核验窗口、运行时与操作身份，持久化事务后才返回；不是仅每组校验一次 |
| server journal / in-flight 才允许 probe | `read_server_journal` 联接已提交派发证据，`trigger_probe` 再核对当前运行时确实观察过的同一请求；provider 顺序运行 |
| 已初始化 attempt 的恢复清理 | `_open_attempts`、`_finish_attempt` 与生产 runtime 消费持久化父证据、验证清理、追加账本，不仅凭内存状态 |
| accepted-run 不得覆盖旧 attempt | `_write_pretty_json_create_or_identical` 允许相同字节幂等重放，不同字节拒绝覆盖；无需恢复旧通用写文件 helper |

### 明确保留的恢复限制

旧测试表达过“没有 manifest、attempt 目录还没创建，也能只靠 opened ledger 自动清理”的意图，但旧生产路径没有实现。新版 cleanup CLI 仍要求 manifest；生产 runtime 在内部 attempt journal 缺失时拒绝恢复。

因此，**runner ledger 已登记 opened，但内部 runtime journal 尚未建立时的崩溃窗口，目前不能自动证明清理完成**。不能把它宣传成已恢复，也不能仅凭文件缺失或全局资源数为零制造 stable-zero receipt。未来需要共用 runtime/lifecycle 的持久化预约身份，或明确的 indeterminate 分类；本次不扩展该协议，也不重封旧 benchmark release。

## 合并验证

验证记录、精确命令和日志位于 `D:/agent-gui-runtime/artifacts/worktree-merge/20260906-mainline/`。

- 来源 runner 合并前：173 项通过。
- 主目录学习固定离线集合：253 Python + 28 JavaScript 通过。
- 主目录独有未跟踪测试：合并前后均在 `/runtime/agent/session/start` 返回 503 / `agent_runtime_recovery_required`，是已复现的既存失败，不是本次全仓报绿或修复声明。
- 并行验证最初共享了同一个临时 WorkflowStore，触发正确的独占锁拒绝。已修正本轮日志脚本：离线测试用受支持的内存模式，实际验证使用独立路径；不删除锁、不修改用户原工作流存储、不放松生产所有权。
- benchmark 首轮 186 passed / 2 failed，发现主目录原有 gate v2 工作副本仍是 CRLF，而 HEAD/来源分支及既有属性要求 LF。确认 JSON 完全相等、唯一差异是换行后，保留原字节并恢复精确 HEAD 字节，没有修改 gate 参数或批准身份。
- gate 修复后两个原失败用例均通过；随后完整重跑同一 benchmark 集合，**188 项全部通过**。这是 173 项 runner 与补充派发/探针边界用例，不是全仓测试。
- 主目录 `actual-r1` 已实际运行公开固定 web-01 样例：Omni 成功产出 56 个候选，普通 provider receipt 为 `clean`，记录的 owned PID 已按创建时间复验为不存在。但更严格的 process-scope observation 是 `indeterminate`（无 process-scope acquisition），不能提升为完整进程域清理证明。随后 GUIActor 在显存准入阶段停止，子进程未启动，VISTA 未启动，没有生成可审核 trial。三次后续设备抽样空闲显存为 9896 / 9904 / 9927 MiB，均低于固定 10240 MiB 下限；这些是失败后的抽样，不冒充失败瞬间读数。
- 因资源条件未满足，本次**主目录的真实三模型→审核→保存→新进程重载闭环尚未完成**。已通过的 253 + 28 离线测试及来源工作树旧真实闭环不能替代它。没有降低显存门槛、关闭其他应用、改变模型组合或重写失败；待资源满足后使用新输出目录重跑同一固定样例。

主目录实际重试命令（无需重做选型、不执行 GUI 动作）：

```powershell
$env:AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH='D:/agent-gui-runtime/artifacts/worktree-merge/20260906-mainline/actual-r2-workflow-store.json'
D:/agent-gui-runtime/.venv/Scripts/python.exe scripts/run_learning_selection_actual.py --case-json artifacts/worktree-merge/20260906-mainline/inputs/case.json --manifest artifacts/worktree-merge/20260906-mainline/inputs/manifest.json --out artifacts/worktree-merge/20260906-mainline/actual-r2 --refinement-mode always
```

该 `always` 只为一次接线验证覆盖 VISTA，不修改生产或实验默认策略。得到新的 selected trial 后，再执行 `scripts/verify_learning_selection_review.py` 的模拟审核保存重载；必须保持 `user_confirmed=false`，不把人工修订回填成模型分数。

## 后续固定开发流程

1. 主目录作为已集成代码的日常入口，开始任务前检查分支和未提交文件。
2. 会修改代码且需要隔离的任务建立一个短期工作树，不在多个目录继续修改同一功能。
3. 按可运行的小切片实施、窄测试、检查输出；获授权时只提交明确范围文件。
4. 合并前检查依赖、同名未跟踪文件和必要协议边界；不能用强制覆盖代替取舍。
5. 合入主目录后再运行相关离线回归和必要真实 no-action 冒烟；不把模型选型与每次集成混成一件事。
6. 将来源明确的原始证据独立归档，核查截图/模型/配置的路径引用已解除后，才另行安全移除工作树。

当前不新增 CI/任务平台，不重做模型选型，不开展新留出集，不删除历史失败证据。
