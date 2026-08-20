# 学习模式结构识别三联审核设计

## 目标

学习模式对 Apple Music、Python.org 和 Windows 设置三个回归界面输出可审查的结构识别结果，并把修复固化为不含应用名、网站名或固定坐标的通用工作流。

## 验收口径

- 每次识别必须保存同一 `capture_id` 与截图校验和对应的原图、仅 Stage1 栏识别图、最终融合图。
- `structure_region_match_rate` 以人工标注的结构栏为分母；目标为 `>= 0.95`。
- `normalized_boundary_error` 分别计算 `x/y/w/h` 的绝对误差除以截图宽高；每条边目标为 `<= 0.10`。
- 区域类别、存在性和边界均需通过；流程完成、产物存在或 PathGraph 可渲染不能替代识别质量。
- 当前三个界面可作为 fixture 与 golden annotation，但生产规则禁止引用界面名、进程名、网站名、专用文本或专用坐标。

## 通用结构证据规则

1. `unknown-only` 不能通过 Stage1。缺少可识别的主结构族时，状态必须为 `needs_structure_review`，并阻止 Stage2。
2. 侧栏必须有明确容器证据，或至少两个语义一致、沿同一轴排列并覆盖有效距离的子元素。单个 OCR 文本或单个靠边图标不能创建整条侧栏。
3. 右侧卡片列只有在存在独立面板边界、不同于主网格的布局连续性或明确容器语义时才能成为右栏。主网格中的末列仍属于主区域。
4. OCR/UIA 降级观察可以提供候选，但不能单独把不完整结构提升为通过。
5. 浏览器 chrome 与原生应用工具栏必须依据 URL/地址栏/标签页等证据区分。原生工具栏中的可见控件必须进入最终融合图。
6. Stage1 栏通过后才运行 Stage2；最终融合图必须保留所有未被证据规则抑制的 Stage2 子项。

## 三联图审核工作流

`capture -> Stage1 structure -> Stage1-only overlay -> structure gate -> Stage2 numbering -> fusion overlay -> triad contact sheet -> metric report -> protected regression`

每个 case 的报告必须包含：原图路径、Stage1 图路径、融合图路径、截图校验和、结构栏 expected/actual、缺失栏、伪造栏、边界误差、匹配率和人工审核状态。

## 安全边界

全部流程只读；不点击、不填写、不提交，不生成 Execute 授权，不提升 Runtime PathGraph。

