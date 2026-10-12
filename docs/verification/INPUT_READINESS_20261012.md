# 输入前改为点击点可用审核 / Input readiness at the executed click

2026-10-12。源码未发布，安装器未更新。 / Source-only correction; no release or installer update.

## 故障与修复 / Incident and repair

1. **故障 / Failure.** 先前只简化了输入后文字核验，漏掉输入前的视觉焦点要求和 500ms 补图。上批两次真实尝试在空搜索框返回 evidence_insufficient，未输入 java；这些失败仍保留于[前批记录](STARTUP_CAPTURE_SETTLEMENT_20261012.md)。 / The prior change simplified value checks but retained pre-input focus evidence and a 500ms follow-up capture. Both previous attempts stopped before java input; their failures remain recorded.
2. **共享合同 / Invariant.** 普通执行把实际点击点渲染到当前图，交 Decision 判断是否为目标输入框、是否可输入；不要求可见光标、焦点样式或连续焦点。输入后只核对要求的文字。 / Review input usability at the executed click, without caret, focus styling or continuity evidence; compare requested text after typing.
3. **修复位置 / Shared fix.** visual_field_proof、input_sequence、input_review_options 不再生成或调用焦点补图；openai_decisions、choice_contract、field_content_choice 使用独立的简短 Choice 问题。配置增加明确的新条件，旧冻结回执不重新解释。 / Runtime producers remove the extra capture; the production provider uses dedicated readiness/content Choice questions under new conditions, preserving frozen historical semantics.
4. **通用性 / Generality.** 没有 Google 特判。空输入框直接输入；非空且允许替换时，先全选并核对文本选区，不要求焦点样式。内部兼容字段名 focus/after_click 不等于仍要求光标。显式原生/UIA与学习路线保留各自合同。 / No site-specific rule was added. Empty fields skip selection; allowed replacements verify text selection without visual focus. Compatibility field names do not impose caret evidence. Explicit native and learned routes retain their contracts.
5. **回归 / Regression.** 新 provider 用例修复前7项失败、修复后通过；运行时新用例修复前5项失败。Main最终20个相关模块479 passed、0 failed、0 errors；覆盖 provider HTTP边界、标注绑定、拒绝/证据不足时不派发键盘、空框跳过全选及残留旧等待参数不重新启用补图。 / New tests reproduced the defects before repair. Main passed479 integrated checks covering provider transport, bindings, keyboard refusal, empty-field strategy and removal of the legacy wait.
6. **动作约束 / Safety impact.** 删除重复视觉焦点要求；窗口/进程/前台身份、实际点击回执、截图来源、坐标、认证、取消、期限和不自动重放保持。目标错误、遮挡、禁用、只读或证据不足仍交Main。 / Identity, foreground ownership, click/source/coordinate bindings, cancellation, deadlines and no-replay remain. Wrong, obstructed, disabled, read-only or uncertain targets still require Main.

## 实际条件与问题 / Actual condition and question

`The marked click is inside the intended visible text input and the field is usable for typing now.`

> At the cyan recorded-click marker, is this the intended input described by action.field.field_goal and can text be entered there now? Check the marked target for mismatch, obstruction, disabled, read-only or masked input.

空/非空判断在同一次请求中，只上传一张点击标注整图；原图本地保留认证，不增加模型往返。可输入审核不发送期望未来文字。 / Content classification shares the request and its single annotated image; originals remain local for authentication. Expected future text is excluded from readiness review.

## 真实流程 / Live flow

| 步骤 / Step | 结果 / Result | 输入证据 / Input evidence |
| --- | --- | --- |
| 输入Google网址并打开 / Enter and open Google URL | success，Decision确认 / Decision confirmed | 一张点击后图；非空地址栏替换 / One after-click frame; replace nonempty address bar |
| 输入java并搜索 / Search java | success，Decision确认 / Decision confirmed | verified_empty，effective_clear_existing=false，无after_selection / Empty field, direct input, no selection review |
| 打开首个普通链接 / Open first ordinary result | success，Decision确认 / Decision confirmed | Java · Oracle；截图地址 https://www.java.com/zh-CN/ |

原始目录 / Run: `D:/AgentReviewAcceptance/native-focus-geometry-20261012-input-ready-05`。

- `flow-result.json`：completed，successful_steps=3，settled_steps=3，原输入全部completed，无Main接管。 / Completed3/3 with all original inputs settled and no Main takeover.
- `final-summary.json`：原命令、条件、单帧、实际输入策略及截图路径。 / Command, input and screenshot evidence.
- `host-cleanup.json`：cleanup_verified=true；`isolated-browser-cleanup.json`：window_closed=true、profile_preserved=true、force_termination=false。 / Normal owned-window and host cleanup verified.
- 原保留资料目录 / Retained profile: `D:/AgentReviewAcceptance/current-step-decision-20261012-1791764425288/edge-profile`。未删除、重置或清理缓存，不修改日常浏览器资料。 / No cache/profile deletion or reset; daily browser data untouched.

离线证据 / Offline evidence: `.superpowers/sdd/2026-10-12-input-readiness/main-regression.xml`。实际使用项目Python执行 `-B -X utf8 -m pytest -q`；20个模块为 visual_input_readiness_decision、visual_input_ready_runtime、visual_text_value_decision、field_content_choice、openai_decisions、decision_choice、native_focus_evidence、native_value_evidence、decision_candidate_annotation_integration、executed_click_integration、executed_click_annotation、visual_field_proof、visual_input_no_uia、visual_empty_input、visual_empty_partial、input_sequence_visual_focus_partial、agent_command_action_review、execution_startup、pre_capture_failure_settlement、visual_focus_pair 对应的 test_*.py。

## 限制与下一步 / Limits and next step

阈值未改；新宿主已加载新条件，自定义旧profile需明确加入条件并重连，运行中的旧宿主不会自动更新。本轮一个完整流程通过，不能证明连续稳定、长期准确率或量化提速。先前失败不改记成功；更广的连续使用、异常恢复和独立验收仍是发布前工作，本轮不发布。 / Thresholds are unchanged. The fresh host loaded new conditions; custom profiles require explicit updates and reconnecting. One complete trial establishes neither continuous reliability nor measured speedup. Previous failures remain failures; broader continuous/recovery and independent acceptance remain before release.
