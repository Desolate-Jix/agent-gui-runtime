# v0.1.0-test.2 · 更新与验收范围 / Changes and verification scope

2026-09-19 · 执行模式增量测试版，不是稳定版。 / Incremental execution-mode test release, not a stable release.

## 新增与修复 / Changes

1. 支持 15 种编辑键及显式文本替换；复用现有输入后端，按键不偷偷点击或重新聚焦。 / Fifteen editing keys and explicit replacement reuse the input backend; key dispatch never implicitly clicks or refocuses.
2. MCP 请求字段和宿主状态错误结构化，非法请求不入队；纯参数校验不再导入 Windows COM。 / Structured field/state rejection before queuing; pure validation no longer imports Windows COM.
3. 明确标签提取与候选排序、控件身份判断共用同一规则；避免把指令上下文中的 Search 当目标标签。模糊候选返回诊断，不新建另一个点击后端。 / Shared explicit-label extraction for ranking and identity; command context does not become the target label. Ambiguous candidates return diagnostics.
4. 事后采集失败保留固定错误码和单独补图指引；已输入不等于目标成功，也不允许把未知结果当未输入。 / Post-capture failure retains typed diagnostics and an observation-only recovery hint; dispatch is not task success.
5. 没有新增自动风险拦截、审批步骤或学习功能，也未进行模型速度优化。 / No new automatic risk policy, approval steps, learning feature or model-speed optimization.

## 实际验证 / Checks performed

- 隔离候选 23 个相关模块共 **550 项通过**，2 个第三方弃用警告。覆盖字段校验、COM 隔离、目标标签、识别候选、编辑键、输入派发及后图诊断。 / **550 checks pass** across 23 targeted modules in the isolated candidate, with two dependency deprecation warnings.
- 真实 MCP stdio：版本 test.2、六工具、非法请求恢复、同连接同宿主、同 ID 不重放、重连回执、关闭清理通过；不将其称为实机输入测试。 / Real stdio lifecycle passes version/tool/error/reconnect/cleanup checks; this is distinct from real input.
- 维护源码用全新本机 Edge 表单连续 **10 轮、220 次输入**，耗时 **187.613 秒**；440 个前后图摘要与 220 个返回图片摘要一致。 / Ten fresh local-form rounds, 220 inputs, 187.613 seconds; 440 before/after and 220 returned-image digests checked.
- 隔离候选另以全新会话复跑 **1 轮、22 次输入**，**17.691 秒**，44 个前后图和 22 个返回图摘要一致，清理通过。涵盖全部 15 种按键和文本替换。 / Isolated candidate: one fresh 22-input round in 17.691 seconds, all 15 keys/replacement, 66 digest checks and cleanup pass.
- 上述表单测试不加载视觉模型，耗时不能代表识别点击速度；同一台设备不代表跨设备稳定性。 / Form runs do not load vision models; timings are not recognition-click performance or cross-device guarantees.

## 保留的问题 / Known limitations

- 初次 23 次输入测试曾有一次已输入但事后采集失败。独立补图确认输入生效、没有重放；原始具体原因仍未知。后续十轮和候选一轮未复现，不声称修复了缺帧根因。 / One initial after-frame failure followed real dispatch. Separate capture confirmed the effect without replay. Its original cause remains unproven despite no recurrence.
- 一次重复测试在第六轮因测试记录器并发写文件而中断；记录器的锁和原子替换已有失败前/修复后回归。这不是一次完整通过的产品测试。 / A separate repetition attempt stopped in round six due to a recorder write race, now regression-tested with lock/atomic replacement; that campaign is not counted as a full pass.
- 意外收集测试辅助模块的扩展运行出现 48 失败、1232 通过、1 跳过；其中 20 项缺未交付的原生审核测试 fixture，24 项用旧 tag 的同一测试独立复现（含 18 项学习导航等价判断），其余 4 项在旧版通过、在候选隔离重跑也通过（对应两模块共 6 项通过）。后者提示运行顺序/共享状态问题，具体污染源尚未证明。不宣称全仓测试通过，也不把学习导航旧失败当作已修复；这些能力不在即时包交付范围。 / Overbroad helper collection: 48 failures, 1232 passes, one skip. Twenty lacked a native-review fixture; 24 reproduced against test.1 with identical tests, including 18 learned-navigation equivalence cases. Four passed on baseline and on an isolated candidate rerun (six checks across their two modules). Order/shared-state interference is suspected, not proven. This is not an all-suite pass or a fix for the excluded learning/navigation baseline failures.
- 小目标、不完整 OCR、动态页面、其他应用/设备、管理员目标的本批增量仍需测试；首次安装依赖和模型下载没有在新电脑上重验。 / Small targets, partial OCR, dynamic pages, other apps/devices, elevated-target increments and first installation on a fresh machine remain unverified.

主执行语义保持：verified=null，由 Agent 读取前后原图判断；不自动重放。不含旧学习内容、截图、用户日志或模型权重。 / Outcome judgement remains with the Agent using original frames; no automatic replay. No learned content, screenshots, user logs or weights are distributed.

分发目录复核：包内无输入回归子集 110 项通过，实际 MCP stdio 再验通过；其运行源码与实机候选逐文件一致。 / Distribution recheck: 110 shipped no-input checks and real MCP stdio smoke pass; runtime source matches the live-tested candidate byte for byte.
