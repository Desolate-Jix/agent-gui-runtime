# 定义审核与运行证据 / Definition review and run evidence

2026-10-01：本说明补齐学习收益验收的证据边界；不改变普通试运行许可、执行授权或审核状态。

This note clarifies evidence required for learning-benefit acceptance without changing normal trial admission, action authorization or review state.

验收图像需及时独立归档。默认每目录保留最新 40 张；相邻 benchmarks 清单中的确切引用可受保护，普通回执 image_path 不自动保护。归档映射记录原路径、保存路径、SHA256 与 run/step/EID，逐字节核对且不修改旧回执。原文件缺失与归档字节已核验分别显示；没有字节不能取得完整资格。 / Default rolling retention keeps 40 captures per directory. Exact adjacent benchmark references may protect images; ordinary receipt paths do not. Verify scoped archived bytes and distinguish absent originals from available archives without rewriting receipts.

2026-10-01 普通编辑 QA 使用 reviewed 标记检查失效合同并记录 human_review_claim=false；真实运行完成不会把测试标记变成人工审核的 C 资格。 / Completed physical execution cannot convert QA review markers into human-review or formal C evidence.

## 三个独立事实 / Three independent facts

1. **已保存定义审核**：固定 workflow_id/program_id/content_sha256/project_snapshot_id，读取各步骤 review_status。执行成功不能将 pending 自动改为 reviewed；语义修改及依赖变化按既有保存规则重新待审。 / Pin the saved definition and its review state; execution success is not definition review.
2. **定义中存在规则**：目标引用和结果规则表示可尝试复用的能力。read_spec=agent_read、verification=agent_judgment 仍需要 Agent；目录名称、learned 策略或规则数量不证明实际省模型。 / A rule definition is a potential capability, not proof of actual deterministic coverage or model savings.
3. **本轮运行的实际行为**：目标解析必须从原回执和报告核实 matched/miss/ambiguous/unsupported；结果从原 history 的 judged_by 与 verification 核实 rule/agent/runtime。输入派发、运行结算和规则通过不能混算。 / Resolve actual matching and verification sources from this run's original receipts and reports.

工作台可以提供定义的只读概览；它不能替代本轮运行页、原始证据或逐调用计量。未保存修改应明确标注，不能提前作为已保存审核结果显示。 / A read-only workbench overview must distinguish unsaved edits and cannot replace run evidence or call telemetry.

## R4 采集合同 / R4 collection contract

每类案例可添加 c_workflow，绑定 workflow_id/program_id/content_sha256/project_snapshot_id/start_step_id/artifact_path/target_memory_steps/rule_verification_steps。artifact 必须是清单内相同 path/version 的 workflow 文件。冻结核对内容摘要、入口及全部可达分支，所声明的目标/规则步骤集合必须与定义相同；可达待审步骤拒绝作为此类 C 候选，不自动修改审核状态。

The optional descriptor pins the saved program, entry and exact declared target/rule sets to a listed artifact. Frozen binding validation checks hashes and every reachable branch, rejecting pending definitions as a bound C candidate without changing their review state.

绑定后的 B/C 必须先通过原 learning_workflow.read 读取同一确切版本，原回执与冻结 artifact 内容相同才允许 start；B 仍为 steps_only，C 为 learned。原入口、输入、trial 身份和票据均保持绑定。prepare 生成的输入只能使用原 ID 和完全相同命令，run/continue 继续沿用原宿主；Agent 识图解析、续接和记账仅归属当前工作流的原请求。

Bound B/C starts require an original read receipt for the same pinned program. Strategies remain steps_only/learned; entry, inputs, trial and original execution tickets cannot drift. Original runtime continuation and receipt-bound telemetry retain their scoped identities.

完成时按实际 history、原命令/响应及报告保存逐步覆盖，缺证据为 unknown，未执行为 not_executed，Agent 消歧或判断必须如实计入。覆盖不足或定义待审不能作为“全部规则已审核并生效”的证据；失败尝试仍留在记录中，不能通过筛除失败提高评分。完整模型调用与 token 的覆盖还须独立证明。

Archive actual per-step coverage; missing evidence stays unknown and Agent work remains visible. Keep unsuccessful attempts. Definition eligibility, actual coverage and complete usage are separate requirements.

原定义回执和运行 history 与 commands/responses/agent-commands、核验 JSON 和当前会话内图像字节一起保存为快照。离线比较核对字节摘要、命令/版本/运行关联并重算规则，不能靠修改 coverage 字段取得资格；图片或文件缺失保持局部证据，资格为 false。源文件摘要必须与冻结计分依赖相同，使用旧记录复算应加载其对应候选，不改旧 manifest 绕过。

Archived snapshots bind definition receipts, history, commands, terminal results, observation JSON and in-session image bytes. Replay verifies identities/hashes and recomputes rules; missing evidence cannot qualify a full-rule run. Re-score historical records with their corresponding pinned implementation.

workflow_provenance 报告每次 C 尝试的定义与覆盖；c_route_contract 只描述本集合已记录的正向 scored、非恢复尝试，不能代替三类配额、完整调用/学习成本或最终验收。全部失败、重试和负向记录仍保留。非读取动作还有 Agent 判断，或目标回退、未执行、缺图时，完整规则资格为 false；Agent 读取允许但成本不能省略。

Collection provenance covers recorded positive scored non-recovery attempts, separately from quotas, complete model telemetry and acceptance. Keep failures/retries/negative cases. Remaining action judgment, target fallback, missing input or image evidence cannot establish full-rule qualification; Agent reads remain visible work.

旧清单无 c_workflow 时仍可诊断采集，但标为 unbound。普通待审学习试运行保持原行为。本合同的单元/合成证据检查不证明实机变化、恢复或真实收益，empirical_acceptance 继续 false。 / Unbound history remains diagnostic and ordinary pending trials stay compatible; source verification does not establish physical acceptance or empirical benefit.
