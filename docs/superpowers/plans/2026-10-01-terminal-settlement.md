# 原终态结算切片 / Original terminal settlement slice

范围：继续已批准的 R3 计划，只处理死宿主已保存的异步 worker 真终态。正式版 v0.1.1 已在独立正式树发布；本学习开发树不发布、不改版本。/ Continue the approved R3 plan for saved asynchronous worker terminal evidence only. Stable v0.1.1 was released from the separate formal tree; this learning slice remains unreleased and unchanged in version.

1. 先写失败契约，绑定原 run、program、step、EID、command/acceptance/worker 原字节 SHA、完整 trial 状态摘要及 pointer/report 进程身份。拒绝未知派发、身份漂移、非终态和不一致的最后一次 dispatch 回执。/ Test exact original bindings first, including byte hashes, complete trial state and persisted process identity. Reject unresolved dispatch, drift, nonterminal state and inconsistent last-dispatch evidence.
2. 专用客户端结算接口以记忆库独占锁及原 runner 锁完成单个 trial 原子写入；保留 pending、history、outputs 和原 runner/命令文件。累计 True 不降级；业务结果保持未知。原 Runner drive 和 Trial review 不可推进已结算的恢复暂停。/ A dedicated client transaction holds the existing workspace and runner locks and commits one trial snapshot. Preserve the original ticket and files; do not downgrade known True, infer task success or advance a branch.
3. 普通面板先核对再显式结算，失败保留原 preview/request ID。刷新、重开和原 result 仍只读，控制按钮保持禁用。/ The ordinary panel previews then explicitly settles, retaining the original recovery identity on failure. Reads and reopening remain read-only, with input controls disabled.
4. Main 运行相关源码回归，再在实际子进程原子提交前后硬终止、原 ID 重读/重试、Qt 重开和完整进程清理。合成 receipt、效果替身及离屏面板不能冒充真实桌面输入验收。/ Main runs source regressions, then actual process termination around commit, original-ID retries, Qt reopening and owned-process cleanup. Synthetic receipts, effect doubles and offscreen panels are not live desktop acceptance.

后续：新鲜自建窗口中的真实单项/连续中断测试 → 独立资源清理证明与新宿主 epoch 接管 → 原票据的弹窗窗口范围和双身份观察 → 同候选完整 R3 验收 → R4 真实匹配收益实验。未知输入绝不重放；未完成项明确保留，不把本切片称为完整恢复或省模型证明。/ Follow with fresh owned-window input and continuous interruption tests, separate cleanup/readiness proof, explicit new-host takeover, dialog scope and dual observation identity, complete R3 and then matched R4 benefits. Never replay uncertain input or call this slice complete recovery or empirical model savings.

## 2026-10-01 新鲜实机检查点 / Fresh live checkpoint

Main 已在全新原会话验证实际教学、原事件/截图 review、同源 synthesis、不可变 program 保存及正常规则复用。第三次输入的原 worker 完成后硬杀实际宿主；正常面板 preview/settle、同 ID 幂等、不同 ID 冲突拒绝和刷新/重开通过。原三份字节、runner/report/pointer、history/outputs 保持，仅 Trial 增加结算。Main 245 passed，实机后 608 个冻结 Python 文件哈希不变。/ Main verifies fresh live teaching, event review, synthesis, immutable saves and rule reuse, then host termination after the original third input. Ordinary settlement and reopening preserve the original evidence, with 245 source checks and an unchanged 608-file source freeze.

首次客户端身份错误及外部 AnyIO lifecycle 已修并复测；候选引用、能力字段层级、launcher 自动退出后的 NoSuchProcess 和离屏字体失败保持原记录。后者修正只用于外部只读重开渲染，未改变产品字体或输入。窗口及已登记进程已退出，正常 cleanup 仍失败，新 epoch 未就绪。不能记作完整 R3 或独立实机通过。/ Preserve original client, lifecycle, caller, kill-adapter and font failures. External rendering repair changes no product/input behavior. Observed process exits do not satisfy normal cleanup or new-epoch readiness.

下一切片先补独立清理证据/admission 与明确新宿主接管，再补活动弹窗和完整连续验收；未知输入不重放，已知 True 不降级，正式人工 C 和 R4 收益保持待项。/ Next add separate cleanup/admission and explicit takeover, then active-dialog scope and complete continuity; reviewed C and R4 benefits remain open.

证据 / Evidence：D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-terminal-live-01/main-final-live-audit.json、main-fixed-contracts.xml、session-02/recovery-proof/summary.json、session-02/cleanup.json。
