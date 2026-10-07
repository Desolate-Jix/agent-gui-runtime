# T16 忙碌拒绝恢复契约 / Busy-admission recovery contract

更新 / Updated: 2026-10-03。分支 / Branch: `codex/dev-workflow-editor`。稳定版 v0.1.1 和 UI v14 不变，未发布。 / Stable release and UI unchanged, unpublished.

## 失败 / Failure

T16 使用全新 7-Zip 内容教学四步并整理一次。普通离屏控件把第一步修改为 ensure_selected，保存三版、审核重开并公开读取同一确切版本。首步真实已满足，原 worker completed，action_executed=false、dispatch_attempts=[]；保留真实选择证明。第二步原 awaiting_grounding 尚未输入时正常 stop，原 ticket 保留，worker cancelled/false/空派发；公开 preview_recovery/settle_recovery 通过。 / Fresh teaching/editing/reopen precede real no-input selection reuse and a genuine interrupted second-step grounding wait. Original ticket, cancellation facts and public settlement are verified.

第一次 epoch preview 回 `session_input_admission_rejection_unproven`：先前竞争的 workflow.run 实际被生产者在派发前拒绝，却不在消费者的四种输入白名单内。原失败不改记通过。 / The first epoch preview rejects a genuine pre-dispatch workflow.run refusal because the consumer recognizes only four input kinds.

## 被破坏的共同契约 / Broken invariant

真实受忙碌门控的已知命令，其严格零派发拒绝必须可独立核验；这只能结算被拒请求，不能证明原动作效果、授权重试或结算另一个 worker。 / Every genuinely gated known command must have independently verifiable typed zero-dispatch rejection; no task effect, retry authority or other-worker settlement follows.

## 修复位置 / Fix location

新增 `app/execution/agent_command_admission.py` 的纯策略，由原 producer `scripts/run_local_step_session.py` 和 `app/execution/session_input_terminal.py` 共用。保持原控制命令放行范围；消费者仍要求原 command 相等、严格 typed result、匹配 ID/异常/原因、两项 false 和无同 ID worker。明确忙碌错误缺 typed proof 拒绝，不能掉入只读命令普通失败分支。 / Share the original pure gate policy while retaining exact command/result/error/no-worker checks and refusing untyped busy errors.

## 为什么不是应用特判 / Why shared

同样覆盖 workflow.run/prepare/read、capture、discover、select 和学习控制的真实忙碌拒绝，适用于所有运行时客户端；没有 7-Zip 名称或坐标特判。 / The contract covers busy rejections across runtime clients without application-specific names or coordinates.

## 回归 / Regression

Main RED：新 29 项中 8 failed、21 passed；其中 7 个真实 producer 范围正例失败，另一个旧字符串 workflow 忙碌错误被错误当作普通只读失败。修复后新旧忙碌检查 37 passed / 0.61s。Main 14 模块相关回归 373 passed / 36.14s（集合包含窄测，不相加）；JUnit 0 failure/error/skip。 / Preserve 8 actual RED failures, then 37 focused and 373 related passing checks without adding overlapping counts.

只读调用生产 `inspect_session_input_terminal` 复验原 S16：被拒请求 failed/false，原输入 cancelled/false，原结算再次核验；163 原文件逐字节 SHA 前后不变。不运行 GUI 输入、不补写历史。 / Production read-only replay revalidates independent rejection/cancellation/settlement facts with all 163 original-file hashes unchanged.

证据 / Evidence: [Main 相关 JUnit](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-recovery-16-grounding-stop/main-busy-related.xml)、[原记录复验](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-recovery-16-grounding-stop/main-original-terminal-replay.json)、[编辑审核](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-recovery-16-grounding-stop/editor-02/audit.json)。 / See original evidence.

## 安全与当前限制 / Safety and limitations

未放宽输入准入，没有重放原命令。已获准控制的伪造拒绝、未知 kind、同 ID worker、命令/事实漂移、旧字符串缺证据及原 worker 未终态均仍拒绝。 / Input admission and no-replay invariants remain; forgery, unknown kinds, worker presence, drift and unfinished original workers still block.

原 MCP 已缓存旧消费者，无受支持热加载入口；T16 原窗口/driver 尚未正常结束。该轮完整接管、剩余步骤、弹窗和清理均未通过。源码审阅发现 effect takeover 只接受当前效果成功，known-zero 未执行步骤没有显式继续路径；这仍是待实机验证/设计的缺口，未新增 retry API。T15 原生命周期限定通过和 T13 原失败/未清理窗口保留。 / The old MCP caches the old consumer without supported hot reload. T16 window/driver cleanup, full takeover, remaining steps and modal handling are unpassed. Source review finds no explicit continuation for a known-zero unfinished step; this gap remains unimplemented/unverified in a live effect takeover. Preserve prior T15 bounded evidence and T13 failures.

自动审批曾把首步“已满足选中状态”的 success 审核误判为伪造点击而拒绝；Main 只读调用原 `_receipt_state` 验证真实原生选择证明后，原请求获准。最终历史仍 action_executed=false、input_route_succeeded=false，未记点击。QA 首次 recipe.action 字段假设失败、旧 wait ID、竞争 run 的拒绝均保留；重跑不改计首次成功。 / Preserve the initial approval-review rejection, its read-only production-proof resolution, and caller/helper failures. Final selection history retains false input facts.
