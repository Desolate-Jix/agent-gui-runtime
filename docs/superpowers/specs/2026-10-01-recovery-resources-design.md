# 异常退出资源清单与明确接管 / Crash resource inventory and explicit takeover

2026-10-01 当前实现：Task 4b 资源与原输入证明、明确新会话准入和发布后原结算只读核对已完成；Main 482 项及原宿主/STDIO 无输入恢复通过。Task 4c 内部当前效果/provenance/唯一 claim/暂停导入已实现，本阶段相关回归 466 passed / 21.45s（main-final-contracts.xml，含最终边界 race 11）。公开采集/接管与完整 GUI 工作流恢复仍待，旧阶段证据与首次失败保留。详见 [准入证据](../../verification/LEARNING_EPOCH_ADMISSION.md)。/ Task 4b admission and archived checks are implemented. Task 4c internal effect, provenance, unique-claim and paused-import primitives pass 466 phase checks including eleven final-boundary races; public collection/takeover and complete live GUI recovery remain open, with earlier evidence and first failures preserved.

沿已批准的 R3 主线开发，learning 未发布、不改版本；stable v0.1.1 正式树保持独立不动。原问题是硬杀绕过 finally、缺少持久资源拥有权；现已补维护清单与独立恢复证明，仍不补造旧正常 cleanup。恢复必须完成完整任务并收尾，不能仅证明新进程能启动。/ Continue the approved R3 work without publishing learning or changing its version; stable v0.1.1 remains unchanged. Durable ownership and separate recovery proof address the original crash gap without inventing normal cleanup. Complete task recovery remains the final acceptance requirement.

## 合同 / Contract

- 已结算 Trial 的 cancel/resume/admit 不得改写原票据或重派输入；业务效果仍未知，True 不降级。/ Settled controls cannot rewrite tickets or replay input.
- 原 runner 启动时固定原 session、来源、launcher PID/created、实际 runner PID/create_time_ns；资源清单只记录本宿主与 FormalModelService 拥有权边界。目标应用窗口和外部服务不是可任意杀除的资源。/ Bind the original epoch and runtime-owned model boundaries, separately from applications and external services.
- 同一个 SessionResourceJournal 在原模型注册、Job 创建前、挂起子进程恢复前、ready、原模型请求及关闭边界原子保存。登记失败不得继续启动子进程。scope、PID 文件和已见身份不可变；模型 owned 不降为 external；原成员累计保留。/ Persist atomic boundaries before launch/resume. Failure blocks launch; ownership and observed identities stay pinned.
- 恢复只观察旧 runner/launcher 与每个原 owned Job、retained identities、专用 PID 文件，不调用 terminate 或 unlink。缺失/损坏/漂移、未登记启动、访问失败保持不确定，不补正常 report/finished_at。/ Recovery observes without termination or deletion; missing or uncertain evidence is not success.
- 清单固定原四字段 Job policy；独立 cleanup_member_identities 累积新成员，closed_from_phase 保留关闭前的阶段。关闭事实不填补 scope_starting/launch_starting 身份缺口。原 pending owned 请求在全部本地进程退出后只可证明资源清理，不被清除；external pending 保持不确定。/ Preserve native policy, cumulative cleanup identities and pre-close phase; local cleanup never clears an input/request ticket.
- observe_session_resource_cleanup 使用同一份原字节解码和哈希，并在前后核对原进程 incarnation、文件和三次零资源样本；预算 0 < timeout_seconds <= 10。返回独立资源证明，input_terminal_settlement_verified/new_epoch_ready 固定 False。/ Bind decoding and hashes to one snapshot and keep resource proof separate from settlement and admission.
- 原正常 cleanup、recovered runtime resources、原执行结算和新 epoch ready 是不同事实。明确接管固定旧 session/run/step/EID/program/字节 hash 与新宿主身份，先重新绑定当前窗口及新图核验原效果，再消费原票据、生成后续新 EID；永不扫描旧队列。/ Keep cleanup, input settlement and new readiness separate. Takeover verifies current effect before consuming the old ticket and generating a new downstream command.

Windows Job 的创建、无 breakaway 与挂起登记复用维护 helper；销毁语义依据 [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。/ Reuse existing Windows scope helpers and the primary Job lifecycle contract.

## Task 4c 当前内部合同 / Current internal takeover contract

- verify_current_effect 以 workflow_current_effect.v1 和新观察核验当前效果，固定原 run/step/EID、receipt/settlement/program SHA 与新 session/capture/window；保留原 source_action_executed，包括 False/null，不制造新执行回执。/ Verify current effect with separately bound provenance and fresh observation while preserving original action facts.
- workflow_recovery_history.v1 回读原 trial/program、逐步 command/receipt/terminal、Agent 请求提交或 rule envelope/PNG，重算有效上游 outputs；Agent 审核来源不代表独立准确率，runtime/recovery_import 来源及缺失原提交的旧历史明确拒绝。/ Verify original history provenance and upstream values without treating Agent review as independent accuracy or inventing unsupported history.
- workflow-takeovers 唯一 claim 的来源键跨 admission/新 epoch 稳定；固定请求与新 run，先持久预占，再 importing→新 Trial→原 Runner 暂停导入→ready。旧目录字节不变、原 EID 不入新队列，ready 同 ID 只读；普通明确继续后才生成下游新 EID。/ A source-stable claim prevents repeated consumption across epochs and imports a paused successor ledger without replaying the old command.
- prepare 固定新输入目录和 effect envelope/PNG 原字节；commit、原 queue 与 admit 使用共同锁。来源/新目录漂移或竞争写入拒绝；partial claim 即使还未写 Trial/Runner 也不能放行竞争输入。/ Pin effect and input evidence, serialize commit with maintained queue admission, and block competing input throughout partial import.

本阶段只支持原回执与新现场相同窗口 incarnation；测试为离线持久集成，OS/launcher 边界模拟。证据目录 D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-takeover-01；466 项阶段结果不证明真实 GUI 接管、收益或完整连续恢复。/ This phase supports only the same window incarnation and is verified through offline persistent integration with simulated OS/launcher boundaries; phase checks do not establish live takeover, benefits or full recovery.

未完成：public MCP 与原 live collector；语义业务对象/窗口新实例绑定；runtime 与重复 epoch/import 历史来源；全新同应用连续任务、活动弹窗、异常恢复和最终清理→同冻结独立实机验收；R4/R5/R6。/ Open work: public MCP and maintained live collection; semantic business-object/new-window binding; runtime and repeated-epoch/import provenance; fresh complete live continuity, dialogs, recovery and cleanup followed by independent frozen-candidate acceptance; R4/R5/R6.

## 实现范围与验收 / Implementation and acceptance

先锁住结算控制合同，再接持久清单及启动前模型登记；随后实现只观察的恢复证据、新 epoch admission 与明确工作流接管。前置项按窄红/绿回归和真实无输入宿主中断验证，之后新鲜实机任务覆盖输入后未核验中断、当前窗口核验、后续步骤与最终清理。完整 Main 单项/连续通过后才交同冻结候选独立实机验收。/ Implement the prerequisites and observation/admission/takeover in order, ending with real complete continuity before independent acceptance.

不将本切片称为完整 R3；活动工作流弹窗、正式人工 C、公平 R4、实测 R5 与 R6 迁移仍属于完整目标。codegraph 对当前树未初始化，本切片采用确切 UTF-8 文件与 rg 追踪。/ Full R3 and later evaluation requirements remain open; use exact source reads because this tree is not indexed.
