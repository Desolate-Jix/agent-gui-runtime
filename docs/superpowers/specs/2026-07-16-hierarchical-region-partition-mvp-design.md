# 混合式分层区域划分 MVP 设计

## 目标

验证现有多源候选能否由单次整屏 8B 调用组织成两级区域树，并产生可用于后续 ROI 的真实 crop。实验是只读 shadow evaluation，不替换 `bar_detection_v1`。

## 数据流

`固定截图 -> screen_inventory/layout_graph -> 匿名候选 C* -> 单次 8B 组织 -> 程序 union bbox -> 独立 validator -> overlay/crops/comparison report`

模型只返回 candidate ID、父子关系、摘要、可选角色和 candidate gaps。程序拥有所有坐标、bbox union、校验、绘图和裁剪职责。

## 坐标契约

- 候选进入实验前统一为原始截图坐标 `{x,y,w,h}`。
- 每个候选记录 `coordinate_space=original_image` 和原图尺寸。
- 模型不得返回 bbox；最终 bbox 只能由 `source_candidate_ids` 的 bbox union 得到。
- overlay 与 crop 直接使用原图坐标，不经过 inference-image 反向缩放。

## 独立组件

- `app/learn/experiments/hierarchical_region_partition.py`：schema 解析、匿名候选构造、bbox union、validator、frame-local 查询、overlay/crop。
- `scripts/eval_hierarchical_region_partition_mvp.py`：固定输入 CLI、单次模型调用、old-v1 对照、证据落盘。
- `tests/test_hierarchical_region_partition_mvp.py`：纯离线结构与几何回归。

## 安全与隔离

- 不修改 `app/learn/recognition/two_stage.py`、Execute、PathGraph、Gate 或面板。
- 不执行点击、输入或窗口操作。
- 不允许 repair 结果覆盖主结果。
- 输出只写入 `logs/region_partition_mvp/<run_id>/`。
- 任何缺失引用、越界、循环、严重同级重叠、断裂 union 或不可裁剪都保留为明确失败。

## 可行性判断

逐样本报告 root/child 数、覆盖率、重叠、未分配率、gap、断裂 union、crop 成功率和 reviewer notes。只有至少改善两个旧方案问题、没有污染正常样本、crop 可用且无应用专用规则时，结论才是“值得继续”。

