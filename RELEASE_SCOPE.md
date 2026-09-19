# test.2 候选范围 / Candidate scope

此目录从 `instant-v0.1.0-test.1` 建立，合入 13 个经核对的源码文件，以及双语说明和无输入回归子集；未复制主开发工作树的其他学习/UI 改动、用户数据或模型。版本为 `0.1.0-test.2`，是否公开以 GitHub Release 为准。

Based on `instant-v0.1.0-test.1`, with 13 reviewed source files, bilingual documentation and a no-input regression subset. No unrelated learning/UI changes, user data or weights are included. Version is `0.1.0-test.2`; publication is determined by its GitHub Release.

## 功能增量 / Changes

- 15 种编辑键、显式文本替换；保持原输入后端，不隐式提交。 / Fifteen editing keys and explicit text replacement, using the existing backend without implicit submission.
- 请求字段/状态错误结构化；参数校验不加载 Windows COM。 / Structured field/state errors and COM-free parameter validation.
- 明确目标标签用于候选身份匹配，返回候选失败诊断。 / Explicit target labels guide candidate identity, with actionable selection diagnostics.
- 事后截图异常保留固定原因；结果未知不等于未输入。 / Post-action capture errors preserve typed reasons; unknown outcomes do not mean no input.

## 当前证据 / Current evidence

- 隔离候选 550 项相关回归通过；独立编辑键审查 118 项通过（有重叠，不相加）。 / 550 isolated-candidate checks pass; independent key review passes 118 overlapping checks, not additive.
- 全新本机表单连续 10 轮、220 次输入通过；440 个前后图摘要及 220 个返回图摘要一致，宿主清理通过。 / Ten sequential local-form rounds and 220 inputs pass, with 440 frame-pair and 220 returned-image digests verified and host cleanup confirmed.
- 首轮 23 次输入有一次已输入但后图失败；后续补图确认，未重放。另一次重复测试在第六轮被验收记录器的并发写入错误中断；记录器已加锁/原子替换并以失败回归验证。 / Initial 23-input run lost one after-frame after dispatch, then recovered by separate observation without replay. Another repetition campaign stopped in round six due to a test-recorder write race; locking/atomic replacement now has regression coverage.
- 原始缺帧尚未确定具体原因；十轮未复现不等于已修复。 / The original missing-frame cause remains uncertain; no recurrence is not proof of a fix.

## 候选复验与边界 / Candidate checks and limits

隔离真实入口、MCP stdio 生命周期及一轮 22 次输入通过，截图摘要与清理通过。辅助测试扩展运行中的 48 项失败分类见 FIXES.md；不是全仓通过。归档使用精确清单与 SHA-256；不会改变外部 Agent 配置。 / Isolated functional imports, real MCP lifecycle and one 22-input round pass, including image hashes and cleanup. See FIXES.md for the 48 auxiliary failures; this is not an all-suite pass. Distribution uses an exact manifest and SHA-256 without changing external Agent configurations.
