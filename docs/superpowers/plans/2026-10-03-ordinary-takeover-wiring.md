# 普通恢复入口接线 / Ordinary takeover wiring

当前状态 / Current status (2026-10-03): 来源读取、普通选择/预览/暂停提交和原请求回读已接入源码，最近 154 项合并离线检查通过；尚待回执契约收尾、真实队列联调及完整实机。当前子任务归[有限试用计划 S2](2026-10-03-learning-trial-closeout.md)；下方保留接线合同，不扩展为更多恢复类型。本次只更新计划。 / Source wiring and 154 offline checks exist; receipt integration and live acceptance remain open. This is S2 of the linked closeout plan; retain the contract below without adding recovery categories.

范围 / Scope: 沿用 v14，将既有公开接管合同接入普通运行页；不会创建新执行器或隐式修改输入权限。Epoch 继续由已授权 Agent 入口生成，UI 连接其返回的新会话。 / Keep v14 and wire existing public takeover controls into the ordinary run page; preserve existing executor and authority. The authorized Agent creates the epoch and the UI attaches its returned session.

完成检查 / Checks:
1. 只读发现严格绑定的 ready admission、原 fixed program 与中断步骤；未知/非零输入不开放 resume_unexecuted。 / Discover pinned ready sources read-only; expose unexecuted continuation only for strict original zero-input evidence.
2. 人选择原任务及处置，原 host 做 fresh preview；提交绑定原 ID/hash/choice，仅暂停接管。 / Explicit selection and fresh public preview; commit binds the original preview and pauses.
3. 原 UI 请求未知、失败、重开时只回读原 ID，不自动重派、commit 或 continue；多个事务不猜选。 / Reopen and unknown outcomes read original IDs; no implicit retries or execution.
4. “继续原运行”复用既有 wait_id 路径，产生新 eid；源码/普通 Qt/队列验证不冒充实机。 / Continue uses the existing wait path and fresh execution identity; offline checks are reported separately from live acceptance.
5. Main 集成并亲跑相关合同、普通控件回归、看图，更新状态；再做全新实机连续恢复与收尾及同冻结独立验收。 / Main integrates, verifies ordinary controls and artifacts, and synchronizes docs before fresh continuous live recovery and independent same-freeze acceptance.

所有未跑实机、桌面像素、真人、交付与收益仍按现有主线保留。 / Retain all pending live, native-pixel, human, delivery and benefit gates.
