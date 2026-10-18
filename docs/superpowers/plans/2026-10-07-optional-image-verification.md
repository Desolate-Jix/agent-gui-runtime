# 可选图像跳转核验 / Optional image verification

> **For agentic workers:** Use the existing implementation loop and bounded Sol workers. Preserve unrelated work; no commit, push, packaging or native Computer Use.

**Goal:** 已知结果用本地图像核验，问题留给 Agent。 / Verify known states locally and retain Agent review when inconclusive.

**Architecture:** 在现有 `agent_judgment` 规则中加入可选 `image_check`，复用原截图、Trial、Runner 与审核入口。 / Extend the existing rule and reuse capture, Trial, Runner and review.

**Tech Stack:** Python, OpenCV, Pillow, PySide6, existing project capture API.

**Spec:** 本对话已批准的学习→人工修改→复用方案及“可选，问题仍可 Agent 审核”的补充。 / User-approved design and optional Agent-review requirement in this conversation.

## Constraints / 约束

- 用户补充：新学习默认优先图像匹配，用户仍可关闭；缺少有效规则沿用 Agent，普通保存和重开不自动补回关闭的规则。 / New learning defaults to image matching; users may disable it. Missing rules retain Agent review; save/reopen never reenables a disabled rule.
- 配置固定原图 SHA、尺寸、模板区域、搜索区域和阈值；旧程序版本不变。 / Pin image digest, dimensions, template/search regions and threshold; preserve old revisions.
- 第一批只支持没有输出及读取规则的非读取步骤；不能从旧图生成当次数据。 / First slice excludes read steps and dynamic outputs.
- 匹配失败、歧义、缺图或几何变化保留原 pending，交 Agent 审核；不重放点击。 / Inconclusive checks preserve the original pending ticket without replay.
- 桌面只用项目维护接口；测试先离线，再新数据真实单项及连续路径。 / Use maintained interfaces, offline checks before fresh live single/continuous acceptance.

## Tasks / 任务

- [x] Backend: validate configuration, verify hash/geometry, match within ROI, bound read-only polling, and record success through the public verifier. Tests demonstrate matching, mismatch, ambiguity, invalid evidence, and unchanged pending on fallback. Final Trial consumption rereads original images and recomputes matching.
- [x] Sources and learning: expose successful after images from the pinned target state; default to a pending local rule only when its localized after feature distinguishes the before state; advertise annotations, reject unrelated reference images, preserve explicit disablement and immutable versions.
- [x] UI: configurable image control, original-image preview, editable stable/search regions and threshold; preserve disabled and unavailable configurations across save/reopen; Chinese and English labels. A generated valid rule is enabled by default.
- [x] Main: inspect actual diffs and run focused contract/runtime/UI checks. Fresh owned-window captures match three successive changed-data states and reject a wrong state; the window closes normally. Offline Trial/Runner coverage verifies Agent review with the original pending ticket. Initial failures and reruns are retained.
- [x] Sync affected public/local documentation and report source versus installed status; do not claim measured speed or accuracy improvements without evidence.
- [ ] Future installed acceptance: a fresh real click-to-verification continuous workflow, interruption/recovery and real Agent takeover in a frozen candidate. This source slice does not replace installation/release acceptance.

## Evidence / 验证范围

证据保存在 `.superpowers/sdd/2026-10-07-optional-image-verification`。真实窗口探针仅使用项目截图接口，没有派发键鼠；完整真实动作闭环和安装包验收未跑。试验中约 12–16 毫秒的局部核验不是端到端收益 benchmark。 / Evidence is retained in that directory. The owned-window probe uses maintained capture without keyboard/mouse dispatch. Full real-action and installer acceptance were not run. Its approximately 12–16 ms checks are not an end-to-end benefit benchmark.

## Review focus / 审查重点

- Repeated or low-texture visual features must not automatically pass.
- Stale capture, changed window, missing reference or incompatible dimensions must wait for review.
- Toggling off must retain the original Agent path; fallback must not consume the ticket.
- Editing a rule must create a pending new revision without changing published or running programs.
- Dynamic text and outputs must still come from the current run.
