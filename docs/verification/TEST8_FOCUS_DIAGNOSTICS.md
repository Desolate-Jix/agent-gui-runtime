# test.8 字段定位与错误回执 / Field targeting and failure receipts

2026-09-27. 修订候选尚未发布，以下结论区分原始失败与离线复验。 / The revised candidate is unpublished; original failures and offline verification are distinct.

## Failure / 失败

AionUi 对 candidate01 的独立验收为 PARTIAL。`b7-fill-r1` 首字段已完成，第二字段聚焦被拒绝；`b13-fill-r2` 和 `b14-fill-r2b` 未执行输入。完整原始回执均有 `local_recognition_invalid`，但精简表单响应丢失底层步骤的错误和耗时，只显示 `focus_input_not_confirmed`。

Independent candidate01 acceptance was PARTIAL. The first field completed before b7's second-field focus was rejected; b13/b14 dispatched no input. Full receipts preserved the underlying error, while compact form projections omitted it.

## Root invariant / 公共契约

结构化文本字段的精确 `label` 与自然语言 `field_goal` 不同。此次请求只提供裸中文 field_goal，走一般模型定位；VISTA 分别指向相邻输入框或左侧文字标签，与同帧 UIA 目标框冲突。拒绝冲突是正确行为，不可放宽或在失败后静默换点。错误回执必须保留中断步骤的原因、是否输入及耗时，且不能把整批部分输入误报为零输入。

Exact accessible labels and natural-language goals are distinct contracts. These requests omitted label, so visual localization was used. VISTA points disagreed with the current UIA target boxes. Rejection remains correct; no relaxed checks or post-failure coordinate substitution are introduced. Compact failures must preserve step-level cause, dispatch state and timing without erasing prior completed input.

## Fix location / 修改位置

`app/instant_receipt.py` 只修精简投影：中断字段保留必要步骤摘要，复用 input_sequence 投影规则；不附带原始识别计划。已知精确字段名时，调用方同时传 `label`，启用既有唯一、完整、当前 UIA 文本框主定位。生产识别、输入守卫和模型冲突拒绝规则未更改。

The shared compact-receipt projector now retains bounded interrupted-step summaries without raw recognition plans. Callers supply label when the exact field name is known, using the existing current unique UIA primary path. Recognition and dispatch guards are unchanged.

## Why shared / 通用性

此投影修复适用于所有本地与 Agent 表单，包括部分完成、嵌套 Agent 命令及失败后恢复。精确字段名的调用约束适用于原生应用和网页，不含 Google 专用判断。

The projection fix covers local and Agent forms, partial progress, nested Agent commands and recovery. Exact-label guidance applies to native apps and websites without site-specific logic.

## Regression / 回归

- 新诊断测试先失败（两项缺 steps），修复后相关 56 项通过。
- 原始三份失败回执只读重放：底层错误、零输入步骤、耗时与已完成索引均保留，原件哈希未改。
- 原始两框 UIA 形态离线验证第二框与再次定位第一框，错误页面标题绑定不覆盖 Name；同名歧义不进入唯一主定位。
- 当前源码全套：2015 passed in 41.91s。这不是新候选实机或独立验收结论。

New diagnostics failed before the fix; 56 related checks then passed. Three original failures replay without modifying their sources. Offline geometry/name/ambiguity regressions pass. The source suite passed 2015 tests in 41.91s; revised frozen-package live and independent acceptance remain separate gates.

本地证据 / Local evidence: `D:\AgentReviewAcceptance\20260927-test8-recovery-01`；原始独立报告 / Original report: `D:\AgentReviewAcceptance\20260927-test8-aionui-01\REPORT-test8-independent-20260927-01.md`。日志和截图不进入发布包。 / Logs and screenshots are not shipped.

## Safety impact / 安全影响

未增加执行权限、未关闭模型/UIA 冲突检查、未自动重放、未提交表单。当前改动不修饰首次失败。原始截图新鲜度、窗口身份与几何检查仍有效。

No added authority, disabled conflict checks, automatic replay or form submission. First failures remain recorded; capture freshness, window identity and geometry checks remain intact.
