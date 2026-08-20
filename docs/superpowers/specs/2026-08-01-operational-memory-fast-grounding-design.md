# 已学习控件快速重定位实验设计

## 目标

验证已审核的 Agent 操作证据能否减少重复视觉定位开销，同时保持当前截图、当前控件、Gate 和动作后验证不变。

## 实验路径

基线继续执行：当前截图 -> UIA 候选 -> VISTA ROI 定位 -> rerank -> pre-click Gate。

实验路径仅在显式开关开启且满足全部条件时执行：

1. 学习资产要求当前重定位，禁止复用历史坐标；
2. 当前 UIA 中只有一个控件与学习目标和当前 goal 一致；
3. 当前控件可见、可用、bbox 合法且动作属于低风险操作；
4. 当前页面 OCR 已通过学习资产的 surface anchor 检查；
5. 当前控件点位仍需通过本地 OCR 关联、pre-click Gate 和动作后验证。

满足条件时，使用当前 UIA bbox 的中心点作为当前坐标证据并跳过 VISTA。出现零命中、多命中、禁用控件、危险动作、页面不匹配或本地 OCR 冲突时，继续使用原有 VISTA 路径或安全停止。

## 安全边界

- 不复用学习资产中的历史 click point。
- 不绕过 `pre_click_decision_v1`、Gate、当前 surface 校验和 post-click verification。
- 不允许 final submit、send、confirm、payment 等动作进入快速路径。
- 默认关闭，只通过实验 metadata 开启。
- 真实测试只执行低风险动作；其他样本只做 dry-run。

## 真实截图验收

至少使用两个真实窗口重新截图：Notepad 和外部浏览器。逐样本比较：

- 当前 screenshot 路径和 checksum；
- baseline / fast-path 总耗时与分层耗时；
- 是否调用 VISTA；
- baseline / fast-path 选择的当前 bbox 和点位；
- Gate 结果和本地 OCR 结果；
- 是否发生回退；
- 若执行低风险点击，记录 post-click verification 和 Trace。

结果不得表述为准确率或通用稳定性，只回答该优化在这些真实截图上是否可行。
