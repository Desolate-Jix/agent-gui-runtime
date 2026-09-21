> **test.4 发布状态 / Release status (2026-09-21):** 本文契约实现已随冻结候选 10 交付。下文较早的“仅源码/待测试/test.3 未更新”描述保留为当时记录，不代表当前 test.4 状态。最新限定实测和未覆盖范围以 [FIXES.md](../../CHANGELOG.md) 为准。 / Implementation ships in test.4; earlier source-only/pending notes below are historical. Consult FIXES.md for current coverage and limits.

# 输入结果与窗口观察恢复 / Input outcome and window observation recovery

## 进程退出诊断修正 / Process-exit diagnostic correction (2026-09-20)

新记事本“不保存”窄复验已正常退出，但恢复探针把目标 `NoSuchProcess` 与普通探针故障一起报告为 `recovery_observation_failed`。根因是公共恢复器的宽泛异常归类；不是点击失败。 / The fresh Don't Save run exited normally, but the shared recovery probe classified target disappearance as a probe failure.

现仅在读取目标进程身份时将 `NoSuchProcess` 返回为 `recovery.status=process_not_running`、`source=process_identity`；旧图仍不可用，协调器改给 `error_code=target_process_not_running`、`next_action=review_task_effect_without_replaying_input`。枚举其他窗口时的异常、权限不足及 PID 身份变化仍如实报告，不能推断目标退出。 / Only target identity reads establish process absence; other probe failures and identity changes remain distinct.

这不证明正常关闭（进程也可能崩溃），不将任务效果置为成功、不生成后图、不自动重放、不新增安全策略。输入原始成功/失败/未知结果均保留。适用于所有应用退出后的观察，不含记事本特判。 / Absence does not prove graceful closure or task success. Dispatch outcomes and agent judgment remain separate, with no synthetic image, replay, or new policy.

验证：先复现 3 项失败；补全成功/失败/未知路由后 **151 项相关检查通过**。另启动并等待一个真实无界面的 Python 子进程退出，再调用生产恢复器，返回 `process_not_running`，不使用 mock、不操作桌面。随后 continuous18 新记事本“不保存”真实退出返回 process_not_running，独立关窗复核通过；旧实机原件不改写。证据：`process-exit-red.xml`、`process-exit-final.xml`、`process-exit-real-probe.json`，位于 `reports/execution-cross-site-20260920`。 / Three red cases precede the repair; 151 scoped checks and a real headless child-process exit probe pass. A subsequent fresh continuous18 GUI exit also reports process_not_running with independently checked closure.

2026-09-20，源码修复，未打包或发布。公开 `instant-v0.1.0-test.3`、冻结候选 `execution-20260920-07` 未修改。 / Source-only; frozen/public packages unchanged.

## 故障复盘 / Failure review

1. **Failure：** 保存提示上的 Enter 已派发且打开另存为，旧提示窗口消失。原协调器把截图异常覆盖为 `phase=result_unknown`，MCP 因而返回 `operation_succeeded=false`，还提示读取并不存在的 after 图。 / A disappearing modal erased the distinction between successful input dispatch and missing post-action evidence.
2. **Root invariant：** 输入派发、观察可用性、任务效果是三种不同事实；观察失败不能抹掉已知路由结果，也不能证明目标成功。 / Dispatch, observation availability and task effect must remain separate.
3. **Fix location：** `local_direct_step.py` 保留路由结果；`post_action_recovery.py` 只读枚举同一进程可见窗口；`instant_mcp.py` 返回范围说明与恢复提示。 / Repairs live in the shared coordinator, passive recovery helper and MCP response adapter.
4. **Why not app-only：** 没有硬编码记事本、保存标签或后继 HWND。关闭菜单、模态提示、另存为等窗口切换共用此语义；候选只代表同进程窗口，不自动推断唯一后继。 / No app, label or HWND is hardcoded; candidates are not assumed to be successors.
5. **Regression：** 初始 7 failed / 109 passed；修复后相关回归 143 passed。补充进程对象缓存与缺失/非布尔成功标记的负控（3 failed / 1 passed），修复后扩大相关集合为 **162 passed**。 / Red/green tests cover outcome separation, no replay, identity rechecks, errors, timing, keyboard and close behavior.
6. **Safety impact：** 没有新增审批或安全策略；没有自动聚焦、选窗、补按、保存或丢弃。重查进程创建时间/路径仅保证窗口线索属于原进程；Agent 仍明确选择并查看新窗口。 / No new approval policy or automatic input; process checks preserve evidence identity.

## 当前契约 / Current contract

对于 `local_direct_step_v1`：

| 字段 / Field | 含义 / Meaning |
|---|---|
| `phase=returned_observation_unavailable` | 输入路由明确成功，但事后观察不可用 / Route succeeded, post-action evidence unavailable |
| `operation_success_scope=input_route_only` | `operation_succeeded` 不表示任务效果 / Success is scoped to the input route |
| `input_route_succeeded` | 原路由的布尔结果；缺失或非法类型为 null / Original boolean result, or null if unknown |
| `observation_status` | `captured`、`unavailable` 或 `not_requested` |
| `agent_review.status=evidence_incomplete` | 不假称完整证据；`verified=null` / Evidence remains incomplete |
| `agent_review.recovery.candidates` | 只读同进程当前可见窗口；可能多个 / Passive current-window hints, potentially ambiguous |

旧 `result_unknown` 回执不被重写成成功。输入失败/结果未知也不会因找到新窗口被升级为成功。`automatic_retry_allowed=false` 保持不变。 / Old unknown outcomes and failed input are not retroactively promoted by finding a window.

**恢复顺序 / Recovery：** 保留原请求回执 → 查看 candidates 与任务上下文 → 使用新请求明确 `select` 目标 → `instant_image` 查看所选窗口 → Agent 判断效果。候选为空/不可用时可 `discover`，不能把它解释为目标必然已关闭。新图属于新请求，不能替代旧请求的 after 摘要。 / Explicitly select and inspect the intended current window under a new request; never overwrite the original evidence pair or replay input automatically.

## 实机验收 / Live acceptance

新建真实记事本，同一 MCP 会话，全部输入经框架，正文为本轮新生成内容。 / Fresh real Notepad, one MCP connection, all input through the framework.

| 动作 / Action | 结果 / Result | 命令耗时 / ms |
|---|---|---:|
| Escape 取消保存提示 / Cancel save prompt | 已派发；旧图不可用；回执给出原记事本 HWND；重新选择后正文原图摘要与取消前一致 | 297.023 |
| Enter 选择保存 / Choose Save | 已派发；回执给出另存为与原主窗口两个候选；Agent 选择另存为并查看原图 | 1048.640 |
| Enter 保存新文件并退出 / Save and exit | 已派发；进程退出导致恢复线索 `NoSuchProcess`；独立核对保存文件及正常关窗 | 1041.076 |

两次 Enter 含显式 1000 ms 观察等待；Escape 含 250 ms，不能当成纯输入时延。本轮没有优化等待或模型速度。 / Timing includes explicit observation waits, not just input latency.

- `instant_image(view=after)` 对缺失旧帧返回 `image_frame_unavailable`；紧接着查询同一 `instant_result` 与原回执完全一致，没有重放。 / Missing-frame negative control and unchanged receipt polling verified.
- 15 条操作命令、另有 1 条宿主退出命令；7 份取图的 SHA-256 与对应原始帧核验一致。 / Fifteen commands plus one host-close command; seven image-to-source bindings verified.
- 最终文本 `Owned transition recovery 2026-09-20` 字节一致，框架确认 `window_closed` 后才退出宿主，`cleanup_verified=true`。 / Exact saved text and graceful closure precede host cleanup.
- 最终源码对原始实机回执再次只读复核，并核验新建进程对象的两次真实身份读取；这一复核没有重新派发输入。 / Final source re-read the real receipts and exercised fresh process identity reads without new input.
- 证据约 0.643 MiB。索引 `reports/execution-cross-site-20260920/transition-recovery-reviewed.json`，脚本 `review_transition_recovery.py`，测试记录 `transition-recovery-regression.xml`。 / Evidence index, reproducible audit and test results retained.

## 边界 / Limits

同进程其他窗口不一定是后继；跨进程弹窗不会包含在此候选列表，需 Agent 另行发现。暂不自动获得新窗口截图，也不把 `NoSuchProcess` 本身当作正常保存或关窗证明。只证明本轮真实连续流程，不代表全平台稳定；同文撤销、历史焦点来源、滚动偶发缺帧及更广泛验收仍待处理。 / Cross-process transitions require discovery; no automatic successor capture or general stability claim. Remaining state and coverage work is unchanged.
