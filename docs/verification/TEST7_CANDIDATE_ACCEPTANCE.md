# test.7 最终验收 / Final acceptance

2026-09-24 · 有人看护的执行模式测试版；学习模式不发布。/ Supervised execution preview; no learning release.

## 冻结身份 / Frozen identity

- Candidate03 MANIFEST SHA-256: `9e25f9d8d6c48c518391185a85f4ccbb28b11e535b1e012ca8893bc44a036fed`; 687 entries, 14,177,605 bytes, no dependencies/models/user data.
- Source: 1759 passed / 36.27 s. Isolated candidate: 1759 passed / 36.72 s. These overlapping checks are not added together.
- Real MCP smoke: seven tools, structured invalid-command recovery, request receipt identity, reconnect readback and cleanup. No-input smoke is separate from live acceptance.
- Final release documentation can differ; runtime, configuration and tests must remain byte-identical to the independently tested candidate.

## 连续实机 / Continuous real GUI

All input used the candidate framework against the real Selenium web form in a fresh external Edge window; synthetic values and a text attachment only. No final Submit, personal résumé or mock replacement. Independent agent task: `test7-candidate03-independent-20260924`.

| 场景 / Case | Codex | AionUi |
|---|---|---|
| Two four-field rounds: text, textarea, select, date | 61.439 / 53.021 s; all readbacks matched | 64.123 / 55.881 s; all readbacks and independent UIA checks matched |
| Original choose-file goal | Opened actual native dialog | Opened actual native dialog |
| Absolute synthetic file path and original unquoted Open(O) goal | Two confirmations passed | Two confirmations passed, 8.565 / 8.429 s |
| Reopen → Cancel → reopen → choose again | Passed, values and filename preserved | Passed, values and filename preserved |
| Owned-window close, host stop and driver exit | Cleanup verified, pending empty | Cleanup verified, pending empty |

Codex inspected the final original screenshot: round-two text/textarea, Three, date and attachment filename remained on the form, which was not submitted. Final independent screenshot SHA-256: `4d34e6d848979c9f526370c68c879c2f74458862a43cf9a0e3e774c6ce36f2c6`.

## 首失败与限制 / Retained failures and limits

- Candidate01 independent native Open(O) recognition failed; Enter recovery did not pass that route. Candidate02 reopened file buttons failed twice before input. Shared mnemonic parsing and accessible-name/control-pixel fixes preceded candidate03 retests; no first-pass success claim. See [mnemonic repair](NATIVE_MNEMONIC_TARGET.md) and [bound-button repair](BOUND_BUTTON_LOCALIZATION.md).
- Independent caller first used an unsupported date `label` instead of `field_goal`: structured rejection before queue/input, then corrected explicitly.
- After a successful Open closed the dialog, a capture against its stale binding returned raw `ValueError: Window handle is not valid`. Rebinding the original browser restored capture. Error guidance remains imperfect; do not interpret it as failed click or replay automatically.
- Prior candidate01 real eight-field rounds, Tab batches and invalid-option recovery remain historical coverage below, not new candidate03 full-suite live coverage. Candidate03 independently retested the changed paths and four-field continuous journey.
- Fewer agent round trips are implemented, but 53–64-second mixed batches remain slow. Cold/warm samples are not a controlled speedup benchmark. No universal form, full 32-field live, visual multi-select, automatic option scrolling, server-upload or unattended guarantee.
- Operator mode was explicitly enabled. Both independent Open(O) receipts recorded `bypass_applied=true` / `automatic_rejection_bypassed`; correct observed clicks do not prove the automatic policy would accept them. The tester report wording “no rejection” was too broad. / 本轮为操作员模式，两次打开均记录自动判定被旁路；正确点击不等于自动策略通过，测试者“未遇拒绝”措辞过宽。
- Final effect judgment remains with the agent; tests do not validate automatic safety-policy mode, new hardware or every MCP client.

---

## Historical candidate01 record / candidate01 原始记录

# test.7 candidate01 验收 / Acceptance

> **后续状态 / Follow-up:** candidate02 的两轮四字段与原始 Open(O) 通过，但选入文件后重开两次均框外拒绝，零点击；未交独立验收。共享 UIA 名称/可见文案区分和唯一绑定按钮裁图修复后，源码 1759 项通过，真实连续重开/取消/重选通过。详见 [关联标签定位修复 / Bound-button repair](BOUND_BUTTON_LOCALIZATION.md)。以下 candidate01 数据保留原始口径，不代表新候选已获独立通过。

未发布；学习模式不包含。/ Unreleased; learning is not included.

## 候选身份 / Candidate identity

- Version `0.1.0-test.7`; 682 manifest entries, 14,153,232 bytes excluding dependencies and weights.
- `MANIFEST.json` SHA-256: `85eba75ba01f0cd6670b3b1f177601fb1a4494dc1ee786b4514951dfbe850af5`.
- 源码1727 passed / 33.26 s；独立包1727 passed / 34.75 s，集合重合不能相加。/ Source and isolated bundle each passed 1727 overlapping checks.
- 隔离依赖预检及真实 stdio smoke通过：7工具、参数拒绝后同宿主恢复、相同ID回执、重连读回与清理；不等同于输入验收。/ Isolated imports/contracts and real stdio smoke passed; these alone do not prove real input.

## 同包真实连续实测 / Same-bundle live journey

所有输入经本包MCP，只使用新开的真实浏览器窗口、虚构内容与测试附件，不创建替代网页、不最终提交。每批核对字段读回与框架原图。/ All input used the candidate MCP against fresh real browser windows. Synthetic values/files only; no substitute page or final submission. Readbacks and images were reviewed.

| 场景 / Case | 结果 / Result | Tool wall time |
|---|---|---|
| httpbin 三文本Tab / named text | 连续两轮替换成功 / Two rounds passed | 21.800 / 9.653 s |
| Selenium 混合八项 / mixed fields | 文本、textarea、datalist、日期、下拉、两复选、单选；两轮全匹配 / All eight matched both rounds | 107.936 / 109.916 s |
| 不存在选项 / missing option | 返回选项并停在索引0，后项未填写 / Choices returned; later text unchanged | 11.892 s |
| 展开下拉恢复 / dropdown recovery | 明确新命令选One / Explicit request selected One | 12.167 s |
| 原生文件名 / native filename | 两个对话框读回路径，中间取消重开 / Both readbacks passed, cancel/reopen between | 10.947 / 10.966 s |
| 确认文件 / choose file | 原表单显示synthetic-attachment.txt；未提交 / Filename visible, not submitted | 10.953 s |

三文本首轮与第二轮不是冷热一致的A/B对照，不据此宣称55%提速；整表耗时仍高。/ These are not controlled speedup measurements; whole-form latency remains substantial.

两个本轮窗口均经框架按确切HWND/PID关闭，宿主stopped、pending为空、cleanup_verified=true，驱动正常退出。/ Both owned windows closed through the framework; host stopped, pending empty and cleanup verified.

## 仍未完成 / Remaining

- AionUi已完成：两轮三文本20.452/8.964秒、两轮八项101.228/103.870秒通过，异常恢复/宿主清理通过；原生Open(O)识别点击失败，Enter替代不能覆盖该失败。共享解析修复源码1753项通过，新候选实机及独立复验尚未完成。/ Independent batches and cleanup passed, but native Open(O) recognition failed. Enter recovery is not proof of that route. The shared parsing fix passes 1753 source checks; repaired live and independent retests remain pending.
- 不宣称任意表格通用、32项全长度实机覆盖、视觉多选可靠、服务器已收到文件或无人值守稳定。/ No universal-form, full-length 32-field live, visual multi-select, server-upload or unattended-stability claim.
- 发布前核对非文档文件与本候选摘要一致；独立失败需修复并重做相关单项及连续复验。/ Non-document hashes must match this candidate before release; independent failures require repaired single/continuous retests.
