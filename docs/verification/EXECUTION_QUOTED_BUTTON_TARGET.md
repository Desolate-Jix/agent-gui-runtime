> **test.4 发布状态 / Release status (2026-09-21):** 本文契约实现已随冻结候选 10 交付。下文较早的“仅源码/待测试/test.3 未更新”描述保留为当时记录，不代表当前 test.4 状态。最新限定实测和未覆盖范围以 [FIXES.md](../../CHANGELOG.md) 为准。 / Implementation ships in test.4; earlier source-only/pending notes below are historical. Consult FIXES.md for current coverage and limits.

# 引号按钮目标修复 / Quoted button target repair

2026-09-20：源码窄实机复验通过；候选 08 未修改、未发布，公开仍为 test.3。 / Narrow source live validation passes; frozen candidate 08 and public test.3 remain unchanged.

## 故障与通用修复 / Failure and shared repair

1. **Failure:** AionUi 候选 08 测试要求点击 `Click the '不保存' (Don't save) button in the save-changes dialog`，却点到保存或控件间隙。 / Candidate 08 hit Save or the inter-button gap instead of Don't Save.
2. **Root invariant:** 显式标签和目标角色必须保留，同帧真实控件身份必须约束模型定位。原解析仅支持 `labelled` 等标记，漏掉直接引号标签；只修提示词后真实模型仍返回保存按钮内的 `(140,84)`，因此提示词不是完整修复。 / Preserve explicit labels and roles and bind model geometry to current control identity. Direct quoted labels were missed; prompt-only real inference still hit Save.
3. **Fix location:** 公共 `text_match` / `control_target` 支持直接引号标签、英文撇号、角色前后缀，并排除明确备选表达。公共视觉主路径在同帧完整 UIA 树存在唯一、可见、启用且精确标签匹配的 Button 时，从真实控件 ROI 开始模型定位，按真实框判断落点，不拿合成框自证。没有关闭模型或失败后改点中心的回退。 / Shared parsing retains identity; unique exact current UIA buttons seed the first model ROI. Real bounds constrain the point; no synthetic proof or post-failure center fallback.
4. **Why not app-only:** 未硬编码记事本、“不保存”或坐标。通用于相邻按钮、中文否定标签和单字母快捷键后缀；同名链接/输入框不能误入按钮路径。重复、禁用、不完整树及词级目标不强走此路径。 / No app, label or coordinate special case. Covers adjacent/opposite captions and accelerators while preserving role and ambiguity boundaries.
5. **Regression:** 新增 27 项检查；累计相关源码 878 项通过，构建检查 7 项通过（集合非独立累计统计）。包含原错误模型点、同名角色、备选目标、重复/截断/禁用树。独立代码复核揭示的角色丢失与备选后缀问题先复现，再修复。 / 27 new cases; 878 scoped source and 7 build checks pass. Role and alternative-target regressions were independently found, reproduced and repaired.
6. **Safety impact:** 修的是识别身份和几何，不增加安全策略或恢复自动拦截；仍由 Agent 判断效果，不自动重放，不宣称框架已经验证业务成功。 / Recognition repair, not a new safety feature or interception change. Agent judgment and no automatic replay remain.

## 已检查 / Checks performed

- 原失败图真实模型：`(191,81)` 位于“不保存”真实框 `(169,70,90,25)` 内，938 ms 为识别耗时，不含冷启动；未派发输入。 / Real inference on the retained failure image hits the proper box; no input.
- 全新真实记事本、全新会话：框架启动 → 写测试文字 → 正常关闭触发保存提示 → 选择弹窗 → 同原失败目标识别点击 → 核对窗口关闭。点击 `(191,77)` 命中“不保存(N)”真实框。点击命令 2165.096 ms，模型准备 8446.710 ms。 / Fresh real Notepad journey reaches normal Don't Save closure; timings separate click from cold preparation.
- 框架回执与独立 `IsWindow` 双重核对父窗口、弹窗均消失；宿主停止、pending 空、cleanup_verified=true。3 份读回原图摘要及执行前图 SHA-256 核对通过。本轮实机证据 854,423 字节。 / Window disappearance and host cleanup independently checked; image hashes agree, evidence under 1 MiB.
- 关闭后的目标已不存在，因此事后截图不可用，回执保留 `post_action_observation_failed` / `NoSuchProcess`，没有虚构后图或重放点击。此轮成功判定来自目标身份、真实派发及窗口消失，不来自该错误字段或 API 成功标记。 / No after image exists once the target closes; success is independently judged, not inferred from API flags.

本地原件 / Local evidence: `reports/execution-cross-site-20260920/quoted-dialog-live01-reviewed.json`、`quoted-button-final-regression.xml`、`quoted-bundle-tests.xml`、`quoted-dialog-model-primary/report.json`。不上传原始截图/私人回执。 / Do not publish raw screenshots or private receipts.

## 剩余 / Remaining

这是单条修复路径通过，不是整体准确率或发布证书。仍需补齐候选验收中缺少的连续操作，再冻结新候选交 AionUi 独立复测；不重发已结束的 `AION-CANDIDATE08-20260920-17`，不修改候选 08。跨宿主清理恢复及窗口消失后的诊断清晰度保留为已知边界。 / Complete missing continuous operations, freeze a new candidate and independently retest; do not mutate candidate 08 or resend completed task 17. Cross-host close recovery and vanished-window diagnostics remain limitations.
