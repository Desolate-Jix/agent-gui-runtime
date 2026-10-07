# Explicit unexecuted-step takeover / 明确继续未执行步骤

更新 / Updated: 2026-10-03。分支 / Branch: `codex/dev-workflow-editor`。这是源码与离线合同结果，不是正式版、普通恢复选择 UI 或完整实机验收。 / Source and offline contracts only; not release, ordinary recovery-choice UI or complete live acceptance.

## Incident / 故障闭合

1. Failure / 可见失败：T16 第二步在真实 awaiting_grounding 时正常停止；原 worker cancelled、action=false、dispatch_attempts=[]，原 ticket 和终态结算保留。共同忙碌拒绝修复后，源码另缺“确定未输入后明确继续”路径；旧接管只消费已成功效果。
2. Root invariant / 共同合同：取消零输入不能被重评分为成功，也不能自动重试。新运行必须保留未完成步骤、上游原证明和固定程序；处置、来源及调度进度不可因空前缀或历史长度变化而失去核验。
3. Fix / 位置：共同学习恢复 import/history/runner、public takeover preview/control，加纯 resolution 合同；修两个遗漏资源指纹的相关离线夹具，不放宽生产校验。 / Shared recovery and public controls plus strict resolution; test-only resource-fingerprint repair.
4. Why shared / 不是应用补丁：规则依原命令、准入、结算、窗口身份和保存的观察合同，不依赖 7-Zip 行名或坐标。 / No app-specific row names or coordinates.
5. Regression / 回归：全新隔离 0/1 上游、原 prepare/settle/admission，公开双观察、commit 零派发、fresh ID 继续、真正新回执审核与历史重建；来源/当前状态/runner seen/伪增长历史/终态遗留 wait 的拒绝。所有动作回执为明确的离线夹具，不算实机。 / Offline receipt fixtures only.
6. Safety / 安全影响：未放宽门控或最终提交限制。原 cancelled/false 来源不变；有过派发、未知动作、失败终态或不确定观察都拒绝本处置，公开 commit 不输入，明确 continue 才走现有 fresh-capture/gated 路径。 / No gate or final-submission relaxation.

## Contract / 合同

- Preview optional `resolution`: omitted or `adopt_success` preserves v1; explicit `resume_unexecuted` produces exact v2 with the choice. Commit inherits the preview hash and rejects overrides. / 缺省 v1 保持兼容，明确继续才使用严格 v2；提交继承预览哈希。
- Require original settlement/worker cancelled with false recursive action facts, explicitly false dispatch-in-progress, empty attempts, no last execution or grounding, exact original SHA/catalog and pinned program. / 原零输入事实须由原字节证明。
- Complete new native observation must bind the same window and return `failure/observed_value_conflict`; success stays the existing adoption path and uncertainty stays paused. / 成功和未知不得冒充未执行继续。
- Import only verified upstream history/outputs; keep the original interrupted step current with no pending ticket and no invented success. An empty consumed prefix is allowed only by v2. / 仅导入上游，原中断步骤不消费。
- Source-only claim identity stays identical across choices. Ready retries are read-only; commit pauses at takeover_ready. Before ticket-free continuation, reconstruct source and real new history, bind runner seen/count, compare the initial trial exactly when no new history exists, and reject terminal states retaining a wait. / 独占、幂等、初始与后续来源核验均闭合。

## Actual checks / 实际检查

Evidence root / 证据目录: `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-recovery-16-grounding-stop`.

| Check / 检查 | Actual result / 实际结果 |
|---|---|
| Public resolution/marker first RED / 参数与记录首次失败 | 5 failed / 15 passed, `resolution-red.xml/txt`; first minimal GREEN 20 passed |
| Fresh core fixture first failure / 新夹具首次失败 | Missing original command before settlement, 31 failed / 1 passed; corrected only before settlement/admission, original log retained |
| Core implementation RED / 核心实现前失败 | 28 failed / 4 passed, `unexecuted-red.xml/txt` |
| Related first Main run / 首次相关回归 | 5 failed / 358 passed, `unexecuted-main-first.xml/txt` |
| Exact before-six-module isolated baseline / 修改前六模块基线 | Same 5 failed / 11 passed; no worktree rollback or live MCP reload, `unexecuted-old-contract-baseline.xml/txt` |
| Resource-fingerprint fixture repair / 资源指纹夹具修正 | 16 passed; includes report.json and session-resources.json, no production relaxation |
| Runner seen drift and unproven history / 调度 seen 与伪历史 | Each RED 2 failed, retained; source/receipt progress reconstruction fixes them |
| Larger Main regression / 较大 Main 回归 | 374 passed, `unexecuted-main-verified.xml/txt`, before the final terminal-wait repair |
| Terminal-with-wait RED / 终态遗留等待失败 | 2 failed, `unexecuted-terminal-wait-red.xml/txt` |
| Final direct regression / 最后直接回归 | 125 passed, `unexecuted-terminal-final.xml/txt`; includes all 65 new checks and directly affected runner/runtime/control/cancel contracts; do not add to 374 |
| Original T16 zero-input replay / 原真实票据只读复验 | Pass, original 163 files unchanged; no current effect observation/input/live takeover, `unexecuted-original-zero-proof.json` |

Exact command lists are in `unexecuted-main-verified-command.json` and `unexecuted-terminal-final-command.json`. Main inspected actual source differences; bounded Sol source reviews found and helped close concrete guard gaps, but are not independent live acceptance. / 命令、首次失败与复测均分别保留；源码审阅不代替独立现场验收。

## Remaining / 剩余

Final identity inspection observes T16's original window/PID absent. Its original supported finish path confirms cleanup_verified=true and driver exit 0; supported normal reconnect is still pending. No hot reload or original ledger rewrite occurred. Next wire ordinary recovery choices, then validate fresh actual pending-ticket takeover, fresh-ID unfinished/remaining steps, dialogs and full cleanup, followed by independent same-freeze live acceptance. Native desktop pixels/human use, delivery and benefits remain pending. Stable v0.1.1/UI v14 are unchanged without packaging, version bump, commit or publication. / 原窗口/PID 已退出，旧连接正常清理并 exit 0；支持的重连、普通恢复选择、完整原票据续跑/弹窗/清理、同冻结独立实机、桌面/真人与交付仍待；收益后置，正式版和 v14 不变。


Lifecycle update / 生命周期更新：原窗口/PID 已退出；原支持结束请求已签名发送一次，原 helper 不产生该请求 reply，短轮询 timeout 保留，随后 cleanup_verified=true、driver exit 0。只读核验原 host/PID/创建时间和 runner 原创建时间已结束；104732 已复用，首次 PID-only 断言失败及修正诊断分别保存，未触碰其它进程。原 pending 票据仍 cancelled/action=false，不把清理改记为任务完成。证据 / Evidence: `unexecuted-original-cleanup.json`, `unexecuted-cleanup-audit-pid-first-failure.json`, `live/identity-absent.json`, `live/cleanup.json`, `live/driver-exit.json`. The original connection now closes normally without hot reload or rewriting task success; the reused runner PID belongs to a different creation time. Full live takeover remains unverified.
