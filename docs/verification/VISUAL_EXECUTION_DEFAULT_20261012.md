# 默认视觉执行验收 / Default visual execution acceptance

2026-10-12，未发布源码；本轮实测仍在进行，不能按连续通过交付。 / Unreleased source; live acceptance is in progress, not a continuous-pass claim.

## 范围 / Scope

- 新普通组合输入默认视觉闭环；UIA/OCR 字段读取不再是必经依赖。显式原生、学习和旧冻结计划/回执保留原合同。 / New ordinary sequences default to visual evidence, preserving explicit native, learning and frozen contracts.
- 新公开入口补确定性审核上下文，保留原 kind/request_id；重复 ID 只读回执。无 Decision 在输入组合前明确拒绝，不隐式降级为 UIA 或盲输。 / Admission preserves identity and idempotency; unavailable Decision stops before input.
- 纯视觉值核验保留新图和完整输入回执，`actual_text/value_reading=null`，回执为 `verified/decision_visual`。 / Visual verification does not invent an extracted value.
- 所有配置阈值保持不变。pass/fail 为 0.90/0.10，动作前和动作后通过阈值均 0.80，动作后转 Main 阈值 0.70。 / Existing thresholds are unchanged.
- [设计与流程图 / Design](../development/VISUAL_EXECUTION_INPUT.md)。无安装包、发布或提交。 / No package, publication or commit.

## 离线记录 / Offline record

证据根 / Evidence root: `.superpowers/sdd/2026-10-12-native-focus-geometry/`。

| 批次 / Batch | 结果 / Result | 证据 / Evidence |
|---|---|---|
| 首次整合 / Initial integration | 628 passed, 3 failed | `main-integrated.xml` |
| 修正无服务回执及原生夹具 / Corrected integration | 730 passed, 42.06s | `main-integrated-fixed.xml` |
| 公开采纳最终回归 / Admission follow-up | 173 passed, 8.64s | `main-admission-final.xml` |
| 两帧提示与字段细节兼容 / Provider follow-up | 137 passed, 1.47s | `focus-pair-provider-green.xml` |
| 双帧完整整合 / Paired integration | 774 passed, 41.67s | `main-paired-integrated.xml` |
| 移除补图整框否决 / No duplicate mask veto | 165 passed, 4.88s | `focus-paired-final.xml` |
| 只读焦点失败取消 / Focus-only failure settlement | 226 passed, 13.56s | `visual-partial-final.xml` |

这些批次有重叠，不能相加成唯一测试数。视觉焦点拒绝后的部分终态回归待补。 / Batches overlap; do not add them into a unique test count. Visual partial-terminal regression remains pending.

## 真实首败保留 / Preserved live failures

所有尝试使用同一个独立 Edge 资料目录与窗口（HWND 5441892、PID 30752），未删除、重置或复制资料。 / All attempts retain the same isolated Edge profile and owned window.

资料目录 / Profile: `D:/AgentReviewAcceptance/current-step-decision-20261012-1791764425288/edge-profile`。

本轮证据 / Run: `D:/AgentReviewAcceptance/native-focus-geometry-20261012-1791765386452`。

| 尝试 / Attempt | 实际结果 / Outcome | 定位 / Finding |
|---|---|---|
| `visual-loop-round-1` | 0/3；地址栏点击和 Ctrl+A 完成，未粘贴或 Enter | selection 0.09。远端 field 混入未来 expected_text；已剔除，原本地绑定保留。 |
| `visual-fixed-round-1` | 1/3；自动输入网址并打开 Google，空搜索框 Ctrl+A 后停止，未粘贴 java | selection 0.26；前后图仅差 `(330,473,331,490)` 的细竖线，符合光标闪烁。 |
| `visual-final-round-1` | 1/3；自动打开 Google，点击搜索框后停止，未 Ctrl+A/粘贴/Enter | 初始单图焦点 0.05；单帧未获得足够可见焦点证据。 |
| `visual-paired-round-1` | 0/3；点击地址栏后停止，未 Ctrl+A/粘贴/Enter | 两帧显示选中文字，但焦点判断 0.14；只读简化问题诊断 0.77，仍未到原阈值。 |
| `visual-continuous-round-1` | 1/3；Google 已自动打开，搜索框 focus 1.00，全选核验 0.65，未输入 java | 发现 completed selection / text not_started 仍被归为未知；补齐同类已知前缀的失败结算。 |

同图只读诊断：地址栏删除未来文字后 0.22，加入完整原图的同帧无标记字段裁剪后 0.99；空字段改写说明后 0.02，补光标闪烁连续性说明后 0.91。它们是限定样本，不是准确率统计或完整任务通过。 / Same-frame diagnostics are scoped examples, not accuracy rates or task acceptance.

字段裁剪直接来自同帧 PNG，保留源摘要、坐标与完整原图，不缩放、不画框、不增加 API 次数。空值特例要求前后均明确为空；非空仍要求原全文相同且选中。专用问题只用于精确声明的 selection 条件。 / Crops preserve original pixels and provenance. Empty-field and nonempty-selection cases retain distinct requirements and exact condition routing.

截至上述五次尝试，账本记录 33 次 Decision 发送（含 5 次同图诊断），阈值未变；五个宿主均正常结束并返回 `cleanup_verified=true`。第四次取消暴露视觉只读焦点拒绝仍被记成未知，正在补齐新原回执的已知失败结算；旧失败不改写。浏览器仍保留，最终连续复测及收尾待补。 / Five attempts record 33 Decision dispatches including five diagnostics. Hosts closed cleanly. Visual focus-only failure settlement is being completed without rewriting historical failures; continuous acceptance remains pending.

## 限制 / Limits

默认路线切换不证明旧 `text_field_geometry_changed` 的原生根因已修复。单图/同图分数提升不证明模型在其他界面稳定；必须按最终冻结源码记录连续测试结果。没有性能基线对照，不声明加速倍率或通用准确率。 / The route change does not repair the unexplained native geometry defect or establish general reliability/performance.
